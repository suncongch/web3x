import base64
import binascii
import hashlib
import json
import logging
import re
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import yaml

from clash_config import (ClashConfigError, INCLUDE_PATTERN, build_groups, build_rules,
                          load_config, parse_config, rename_proxy)
from three_xui import NoRedirect, PanelError


class SubscriptionError(Exception):
    pass


RULE_CACHE_TTL = 7 * 24 * 60 * 60
RULE_CACHE_RETRY = 5 * 60
EXTRA_SUB_CACHE_TTL = 7 * 24 * 60 * 60
_rule_cache_lock = threading.RLock()
_rule_cache_retry = {}
_extra_sub_cache_lock = threading.RLock()
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubscriptionResult:
    content: str
    expiry_ms: int
    upload: int
    download: int
    total: int


def safe_url(value, *, allow_query=False, allow_http=False):
    try:
        parts = urlsplit(value)
        if (not parts.hostname or parts.username or parts.password or parts.fragment
                or (parts.query and not allow_query)
                or (parts.scheme != 'https' and not (
                    parts.scheme == 'http' and
                    (allow_http or parts.hostname in ('localhost', '127.0.0.1', '::1'))
                ))):
            raise ValueError
        parts.port
    except ValueError as exc:
        raise SubscriptionError('订阅地址配置无效或不安全') from exc
    return value.rstrip('/') if not allow_query else value


def public_url():
    return safe_url(os.environ.get('PUBLIC_BASE_URL', ''), allow_http=True)


def fetch_subscription(url, user_agent):
    request = urllib.request.Request(url, headers={
        'User-Agent': user_agent, 'Accept-Encoding': 'identity',
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = response.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise SubscriptionError('订阅内容过大')
        return data.decode('utf-8-sig')
    except (urllib.error.URLError, OSError, UnicodeError, ValueError) as exc:
        raise SubscriptionError('无法获取订阅内容') from exc


def _timed(stage, operation, *args, **kwargs):
    started = time.perf_counter()
    outcome = 'ok'
    try:
        return operation(*args, **kwargs)
    except Exception:
        outcome = 'error'
        raise
    finally:
        _logger.info('subscription_timing stage=%s elapsed_ms=%.1f outcome=%s',
                     stage, (time.perf_counter() - started) * 1000, outcome)


def extra_urls():
    value = os.environ.get('EXTRA_SUB_URLS', '').strip()
    if not value:
        return []
    try:
        urls = json.loads(value)
    except ValueError:
        # 兼容未加引号的写法：[https://a, https://b] 或逗号/换行分隔
        urls = [item for item in re.split(r'[\s,]+', value.strip('[]')) if item]
        if not urls or any('://' not in item for item in urls):
            raise SubscriptionError('外部订阅配置无效') from None
    if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
        raise SubscriptionError('外部订阅配置必须是地址数组')
    return [safe_url(url.strip(), allow_query=True) for url in urls if url.strip()]


def extra_subscription_cache_path(kind, url):
    identity = hashlib.sha256(f'{kind}\0{url}'.encode('utf-8')).hexdigest()
    return Path(__file__).resolve().parent / 'instance' / f'extra-sub-{identity}.json'


def _read_extra_subscription_cache(path, kind):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as exc:
        _logger.warning('读取外部订阅节点缓存失败，将重新获取：%s', exc)
        return None
    nodes = data.get('nodes') if isinstance(data, dict) else None
    updated = data.get('updated') if isinstance(data, dict) else None
    if type(updated) not in (int, float) or not isinstance(nodes, list):
        _logger.warning('外部订阅节点缓存格式无效，将重新获取')
        return None
    if kind == 'clash':
        valid = all(isinstance(node, dict) and isinstance(node.get('name'), str)
                    and node['name'] for node in nodes)
    else:
        valid = all(isinstance(node, str) and '://' in node
                    and not any(char.isspace() for char in node) for node in nodes)
    if not valid:
        _logger.warning('外部订阅节点缓存内容无效，将重新获取')
        return None
    return {'updated': updated, 'nodes': nodes}


def _write_extra_subscription_cache(path, data):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.replace(temporary, path)
    except OSError as exc:
        _logger.warning('无法保存外部订阅节点缓存：%s', exc)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def cached_extra_subscription(url, kind, user_agent):
    path = extra_subscription_cache_path(kind, url)
    with _extra_sub_cache_lock:
        cached = _read_extra_subscription_cache(path, kind)
    now = time.time()
    if cached and 0 <= now - cached['updated'] < EXTRA_SUB_CACHE_TTL:
        _logger.info('subscription_cache type=extra_nodes kind=%s state=hit', kind)
        nodes = cached['nodes']
    else:
        _logger.info('subscription_cache type=extra_nodes kind=%s state=refresh', kind)
        try:
            text = _timed('extra_source_fetch', fetch_subscription, url, user_agent)
            if kind == 'clash':
                nodes = clash_config(text)['proxies']
            else:
                nodes = parse_links(text)
        except SubscriptionError:
            if not cached:
                raise
            _logger.warning('外部订阅刷新失败，继续使用已有节点缓存')
            nodes = cached['nodes']
        else:
            with _extra_sub_cache_lock:
                _write_extra_subscription_cache(
                    path, {'updated': time.time(), 'nodes': nodes},
                )
    if kind == 'clash':
        return yaml.safe_dump({'proxies': nodes}, allow_unicode=True, sort_keys=False)
    return '\n'.join(nodes)


def panel_subscription_base(kind):
    key = 'XUI_CLASH_BASE_URL' if kind == 'clash' else 'XUI_SUB_BASE_URL'
    try:
        return safe_url(os.environ.get(key, ''))
    except SubscriptionError as exc:
        raise SubscriptionError(f'3x-ui 订阅地址配置无效：{key}') from exc


def clash_attachment_filename():
    filename = os.environ.get('CLASH_ATTACHMENT_FILENAME', 'Web3X_Clash.yaml')
    if (not filename.strip() or filename in ('.', '..')
            or any(ord(char) < 32 or ord(char) == 127 or char in '/\\' for char in filename)):
        raise SubscriptionError('CLASH_ATTACHMENT_FILENAME 必须是有效的文件名')
    return filename


def clash_config(text):
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SubscriptionError('订阅不是有效的 Clash YAML') from exc
    if (not isinstance(config, dict) or not isinstance(config.get('proxies'), list)
            or any(not isinstance(proxy, dict) or not isinstance(proxy.get('name'), str)
                   or not proxy['name'] for proxy in config['proxies'])):
        raise SubscriptionError('Clash 订阅节点格式无效')
    return config


def clash_base_config():
    location = os.environ.get('CLASH_BASE_CONFIG', 'clash_base.yaml').strip()
    if not location or '://' in location:
        raise SubscriptionError('CLASH_BASE_CONFIG 必须是本地 YAML 文件路径')
    path = Path(location).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    try:
        config = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SubscriptionError('无法读取或解析 Clash 基础配置文件') from exc
    if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
        raise SubscriptionError('Clash 基础配置必须是 YAML 对象')
    if {'proxies', 'proxy-groups', 'rules'} & config.keys():
        raise SubscriptionError('Clash 基础配置不能包含 proxies、proxy-groups 或 rules')
    return config


def rule_cache_path():
    return Path(__file__).resolve().parent / 'instance' / 'clash-rule-cache.json'


def _rule_sources():
    location = os.environ.get('CLASH_CONFIG', '').strip()
    if not location:
        raise ClashConfigError('未配置 CLASH_CONFIG')
    remote = location.startswith(('https://', 'http://'))
    text = None if remote else load_config(location, None)
    node_rules = load_config('clash_node_rules.ini', None)
    identity = json.dumps([location, text, node_rules], ensure_ascii=False).encode('utf-8')
    return location, text, node_rules, hashlib.sha256(identity).hexdigest()


def _read_rule_cache(path, identity):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as exc:
        _logger.warning('读取分流规则缓存失败，将重新获取：%s', exc)
        return None
    if (not isinstance(data, dict) or data.get('identity') != identity
            or not isinstance(data.get('updated'), (int, float)) or isinstance(data['updated'], bool)
            or not isinstance(data.get('rules'), dict)
            or any(not isinstance(key, str) for key in data['rules'])):
        _logger.warning('分流规则缓存无效或配置已更改，将重新获取')
        return None
    config = data.get('config')
    rules = data['rules']
    if isinstance(config, list) and all(isinstance(line, str) for line in config):
        config = '\n'.join(config)
    if isinstance(config, str):
        config = config.split('\n')
    if not isinstance(config, list) or any(not isinstance(line, str) for line in config):
        _logger.warning('分流规则缓存无效或配置已更改，将重新获取')
        return None
    normalized_rules = {}
    for url, content in rules.items():
        if isinstance(content, str):
            content = content.split('\n')
        if not isinstance(content, list) or any(not isinstance(line, str) for line in content):
            _logger.warning('分流规则缓存无效或配置已更改，将重新获取')
            return None
        normalized_rules[url] = '\n'.join(content)
    data = {**data, 'config': '\n'.join(config), 'rules': normalized_rules}
    try:
        _validate_rule_snapshot(data['config'], data['rules'])
    except ClashConfigError as exc:
        _logger.warning('分流规则缓存内容无效，将重新获取：%s', exc)
        return None
    return data


def _validate_rule_snapshot(config, rules):
    parsed = parse_config(config)
    try:
        for pattern, _ in parsed['rename'] + parsed['emoji']:
            re.compile(pattern)
        for group in parsed['groups']:
            health_url_seen = False
            for item in group[2:]:
                if item.startswith('[]'):
                    continue
                if item.startswith(('https://', 'http://')):
                    health_url_seen = True
                elif not health_url_seen:
                    re.compile(item)
    except re.error as exc:
        raise ClashConfigError('分流配置正则表达式无效') from exc

    def rule_content(url):
        try:
            return rules[url]
        except KeyError as exc:
            raise ClashConfigError('分流规则缓存不完整') from exc

    build_rules(parsed, rule_content)


def _write_rule_cache(path, data):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as file:
            temporary = Path(file.name)
            formatted = {
                **data,
                'config': data['config'].split('\n'),
                'rules': {url: content.split('\n') for url, content in data['rules'].items()},
            }
            json.dump(formatted, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.replace(temporary, path)
    except OSError as exc:
        raise SubscriptionError('无法保存分流规则缓存') from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def cached_rule_config(force=False):
    with _rule_cache_lock:
        try:
            location, text, node_rules, identity = _rule_sources()
            path = rule_cache_path()
            cached = _read_rule_cache(path, identity)
            now = time.time()
            if not force and cached:
                if now - cached['updated'] < RULE_CACHE_TTL:
                    _logger.info('subscription_cache type=clash_rules state=hit')
                    return cached
                if now < _rule_cache_retry.get(identity, 0):
                    _logger.info('subscription_cache type=clash_rules state=stale')
                    return cached

            _logger.info('subscription_cache type=clash_rules state=refresh')

            def fetch(url):
                return _timed('clash_rule_source', fetch_subscription,
                              safe_url(url, allow_query=True), 'clash-verge/v2.3.1')

            try:
                if text is None:
                    text = load_config(location, fetch)
                combined = text + '\n' + node_rules
                parsed = parse_config(combined)
                rules = {}

                def fetch_rule(url):
                    if url not in rules:
                        rules[url] = fetch(url)
                    return rules[url]

                build_rules(parsed, fetch_rule)
                _validate_rule_snapshot(combined, rules)
                result = {'identity': identity, 'updated': time.time(),
                          'config': combined, 'rules': rules}
                _write_rule_cache(path, result)
            except (SubscriptionError, ClashConfigError) as exc:
                if force or cached is None:
                    raise
                _rule_cache_retry[identity] = time.time() + RULE_CACHE_RETRY
                _logger.warning('刷新分流规则缓存失败，继续使用旧缓存：%s', exc)
                return cached
            _rule_cache_retry.pop(identity, None)
            return result
        except ClashConfigError as exc:
            raise SubscriptionError(str(exc)) from exc


def build_clash(primary, extras):
    all_proxies = list(clash_config(primary)['proxies'])
    for text in extras:
        all_proxies.extend(clash_config(text)['proxies'])
    config = clash_base_config()
    try:
        cached = _timed('clash_rule_config', cached_rule_config)
        parsed = parse_config(cached['config'])
        proxies, names = [], set()
        for proxy in all_proxies:
            if not INCLUDE_PATTERN.search(proxy['name']):
                continue
            name = rename_proxy(proxy['name'], parsed)
            unique = name
            suffix = 2
            while unique in names:
                unique = f'{name} ({suffix})'
                suffix += 1
            names.add(unique)
            proxy['name'] = unique
            proxies.append(proxy)
        if not proxies:
            raise ClashConfigError('没有节点符合 sample 的筛选条件')
        config['proxies'] = proxies
        config['proxy-groups'] = build_groups(parsed, [proxy['name'] for proxy in proxies])
        def cached_rule(url):
            try:
                return cached['rules'][url]
            except KeyError as exc:
                raise ClashConfigError('分流规则缓存不完整，请刷新缓存') from exc

        config['rules'] = build_rules(parsed, cached_rule)
    except ClashConfigError as exc:
        raise SubscriptionError(str(exc)) from exc
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def parse_links(text):
    text = text.strip()
    if not text:
        raise SubscriptionError('节点订阅为空')
    if '://' not in text:
        try:
            data = base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)
            text = data.decode('utf-8')
        except (binascii.Error, UnicodeError, ValueError) as exc:
            raise SubscriptionError('节点订阅格式无效') from exc
    links = [line.strip() for line in text.splitlines() if line.strip()]
    if not links or any('://' not in link or any(c.isspace() for c in link) for link in links):
        raise SubscriptionError('节点订阅格式无效')
    return links


def validate_client(panel, email, username):
    try:
        payload = panel.get_client(email)
    except PanelError as exc:
        raise SubscriptionError(f'无法获取当前用户的客户端：{exc}') from exc
    client = payload['client']
    sub_id = client.get('subId')
    if (client.get('email') != email or client.get('comment') != username
            or not isinstance(client.get('enable'), bool)
            or not isinstance(sub_id, str) or not sub_id):
        raise SubscriptionError('当前用户的客户端信息无效')
    expiry, total, used = client.get('expiryTime'), client.get('totalGB'), payload.get('usedTraffic')
    if any(type(value) is not int for value in (expiry, total, used)):
        raise SubscriptionError('客户端流量或到期信息无效')
    if total < 0 or used < 0:
        raise SubscriptionError('客户端流量信息无效')
    if not client['enable'] or (expiry > 0 and expiry <= int(time.time() * 1000)) or (total > 0 and used >= total):
        raise SubscriptionError('客户端已停用、过期或流量已用完')
    return sub_id, expiry, total


def panel_subscription(panel, email, username, kind):
    base = panel_subscription_base(kind)
    sub_id, expiry, total = _timed('panel_client_validation', validate_client,
                                   panel, email, username)
    upload, download = 0, 0
    if kind == 'clash':
        try:
            traffic = _timed('panel_traffic', panel.get_client_traffic, email)
        except PanelError as exc:
            raise SubscriptionError(f'无法获取当前用户的客户端流量：{exc}') from exc
        upload, download = traffic['up'], traffic['down']
        if total > 0 and upload + download >= total:
            raise SubscriptionError('客户端已停用、过期或流量已用完')
    agent = 'clash-verge/v2.3.1' if kind == 'clash' else 'Shadowrocket'
    primary = _timed('primary_source', fetch_subscription,
                     base + '/' + quote(sub_id, safe=''), agent)
    if kind == 'clash':
        clash_config(primary)
    else:
        parse_links(primary)
    return primary, expiry, upload, download, total


def build_subscription(panel, email, username, kind):
    urls = extra_urls()
    primary, expiry, upload, download, total = panel_subscription(panel, email, username, kind)
    agent = 'clash-verge/v2.3.1' if kind == 'clash' else 'Shadowrocket'
    sources = [_timed(f'extra_source_{index}', cached_extra_subscription, url, kind, agent)
               for index, url in enumerate(urls, start=1)]
    if kind == 'clash':
        content = _timed('clash_render', build_clash, primary, sources)
        return SubscriptionResult(content, expiry, upload, download, total)
    links = parse_links(primary)
    for text in sources:
        links.extend(parse_links(text))
    return SubscriptionResult(base64.b64encode('\n'.join(links).encode('utf-8')).decode('ascii'),
                              expiry, upload, download, total)
