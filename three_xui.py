import http.cookiejar
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)


class PanelError(Exception):
    pass


class DuplicateClientError(PanelError):
    pass


class PanelRequestError(PanelError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request_label(path):
    fixed_paths = {
        '/csrf-token': 'csrf_token',
        '/login': 'login',
        '/panel/api/inbounds/list': 'inbounds_list',
        '/panel/api/clients/list': 'clients_list',
        '/panel/api/clients/add': 'clients_add',
    }
    if path in fixed_paths:
        return fixed_paths[path]
    if path.startswith('/panel/api/clients/get/subId/'):
        return 'client_by_sub_id'
    if path.startswith('/panel/api/clients/get/'):
        return 'client_by_email'
    if path.startswith('/panel/api/clients/traffic/'):
        return 'client_traffic'
    return 'other'


class ThreeXUI:
    def __init__(self):
        self.base_url = os.environ.get('XUI_BASE_URL', '').rstrip('/')
        self.username = os.environ.get('XUI_USERNAME', '')
        self.password = os.environ.get('XUI_PASSWORD', '')
        parts = urlsplit(self.base_url)
        if (not self.username or not self.password or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or (parts.scheme != 'https' and not (
                    parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')
                ))):
            raise PanelError('3x-ui 配置缺失或地址不安全，请检查服务器配置')
        self.origin = f'{parts.scheme}://{parts.netloc}'
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            NoRedirect(),
        )
        self.csrf = ''
        self.failed_inbounds = []

    def request(self, path, payload=None):
        started = time.perf_counter()
        outcome = 'error'
        try:
            headers = {'Accept': 'application/json', 'Origin': self.origin}
            data = None
            if payload is not None:
                data = json.dumps(payload).encode('utf-8')
                headers.update({'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf})
            request = urllib.request.Request(self.base_url + path, data=data, headers=headers)
            try:
                with self.opener.open(request, timeout=10) as response:
                    body = json.load(response)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                raise PanelRequestError('无法连接 3x-ui 面板或面板响应无效') from exc
            if not isinstance(body, dict) or body.get('success') is not True:
                raise PanelRequestError('3x-ui 面板拒绝请求')
            outcome = 'ok'
            return body.get('obj')
        finally:
            logger.info('3xui_request_timing endpoint=%s elapsed_ms=%.1f outcome=%s',
                        _request_label(path), (time.perf_counter() - started) * 1000, outcome)

    def login(self):
        token = self.request('/csrf-token')
        if not isinstance(token, str) or not token:
            raise PanelRequestError('3x-ui 面板未返回有效的 CSRF 令牌')
        self.csrf = token
        self.request('/login', {'username': self.username, 'password': self.password})
        token = self.request('/csrf-token')
        if not isinstance(token, str) or not token:
            raise PanelRequestError('3x-ui 面板未返回有效的 CSRF 令牌')
        self.csrf = token

    def create_client(self, username, email, generated_email=False, *, expiry_time=None, total_gb=None):
        self.login()
        inbounds = self.request('/panel/api/inbounds/list')
        if not isinstance(inbounds, list) or any(
            not isinstance(inbound, dict)
            or type(inbound.get('id')) is not int or inbound['id'] <= 0
            or not isinstance(inbound.get('enable'), bool)
            for inbound in inbounds
        ):
            raise PanelRequestError('3x-ui 入站列表格式无效')
        inbound_ids = [inbound['id'] for inbound in inbounds if inbound['enable']]
        if not inbound_ids or len(inbound_ids) != len(set(inbound_ids)):
            raise PanelError('3x-ui 没有可用入站，或入站列表包含重复 ID')
        clients = self.request('/panel/api/clients/list')
        if not isinstance(clients, list) or any(
            not isinstance(client, dict) or not isinstance(client.get('comment'), str)
            or not isinstance(client.get('email'), str)
            for client in clients
        ):
            raise PanelRequestError('3x-ui 客户端列表格式无效')
        if any(client['comment'] == username for client in clients):
            raise DuplicateClientError('3x-ui 已存在同名客户端，无法注册')
        if any(client['email'].casefold() == email.casefold() for client in clients):
            if generated_email:
                raise DuplicateClientError('生成的客户端邮箱已存在，请重新注册')
            raise DuplicateClientError('3x-ui 客户端邮箱已存在，无法注册')
        client_id = str(uuid.uuid4())
        sub_id = str(uuid.uuid4())
        client = {
            'id': client_id,
            'subId': sub_id,
            'email': email,
            'comment': username,
            'enable': True,
            'security': 'auto',
            'totalGB': 25 * 1024 ** 3 if total_gb is None else total_gb,
            'expiryTime': int((time.time() + 30 * 24 * 60 * 60) * 1000) if expiry_time is None else expiry_time,
        }
        successful = 0
        for inbound_id in inbound_ids:
            try:
                self.request('/panel/api/clients/add', {
                    'client': client, 'inboundIds': [inbound_id],
                })
                successful += 1
            except PanelRequestError:
                logger.exception('3x-ui 入站 %s 创建客户端失败，正在核实结果', inbound_id)
                clients = self.request('/panel/api/clients/list')
                if not isinstance(clients, list) or any(
                    not isinstance(item, dict) or not isinstance(item.get('email'), str)
                    for item in clients
                ):
                    raise PanelRequestError('无法核实 3x-ui 客户端创建结果')
                matches = [item for item in clients if item['email'].casefold() == email.casefold()]
                if matches:
                    if (len(matches) != 1 or matches[0].get('subId') != sub_id
                            or not isinstance(matches[0].get('inboundIds'), list)
                            or any(type(value) is not int for value in matches[0]['inboundIds'])):
                        raise PanelRequestError('无法核实 3x-ui 客户端归属或入站')
                    if inbound_id in matches[0]['inboundIds']:
                        successful += 1
                        continue
                self.failed_inbounds.append(inbound_id)
        if not successful:
            raise PanelError('所有已启用的入站均添加失败')
        return email

    def delete_client(self, email):
        self.request('/panel/api/clients/del/' + quote(email, safe=''), {})

    def get_client(self, email):
        self.login()
        result = self.request('/panel/api/clients/get/' + quote(email, safe=''))
        if not isinstance(result, dict) or not isinstance(result.get('client'), dict):
            raise PanelRequestError('3x-ui 客户端信息格式无效')
        if result['client'].get('email') != email:
            raise PanelRequestError('3x-ui 客户端信息不匹配')
        sub_id = result['client'].get('subId')
        if not isinstance(sub_id, str) or not sub_id:
            raise PanelRequestError('3x-ui 客户端订阅 ID 无效')
        owners = self.request('/panel/api/clients/get/subId/' + quote(sub_id, safe=''))
        if (not isinstance(owners, list) or len(owners) != 1
                or not isinstance(owners[0], dict)
                or not isinstance(owners[0].get('client'), dict)
                or owners[0]['client'].get('email') != email
                or owners[0]['client'].get('subId') != sub_id):
            raise PanelRequestError('3x-ui 订阅 ID 不属于唯一客户端')
        return result

    def get_client_traffic(self, email):
        result = self.request('/panel/api/clients/traffic/' + quote(email, safe=''))
        if (not isinstance(result, dict) or result.get('email') != email
                or any(type(result.get(key)) is not int or result[key] < 0
                       for key in ('up', 'down'))):
            raise PanelRequestError('3x-ui 客户端流量信息无效')
        return result
