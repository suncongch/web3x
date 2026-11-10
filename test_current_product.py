import base64
import os
import threading
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import yaml
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from app import Order, User, app, db
from subscription import SubscriptionResult
from three_xui import DuplicateClientError, PanelRequestError, ThreeXUI
from test_three_xui import PanelHandler


class CurrentProductTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name) / 'base.yaml'
        base.write_text('mixed-port: 7890\nmode: rule\n', encoding='utf-8')
        environment = patch.dict(os.environ, {'CLASH_BASE_CONFIG': str(base)})
        environment.start()
        self.addCleanup(environment.stop)
        self.panel_patch = patch('app.ThreeXUI')
        self.panel = self.panel_patch.start().return_value
        self.panel.create_client.return_value = 'test-client'
        self.panel.failed_inbounds = []
        self.addCleanup(self.panel_patch.stop)
        self.app = Flask(
            __name__, template_folder=os.path.join(app.root_path, 'templates')
        )
        self.app.config.update(
            TESTING=True,
            SECRET_KEY='test-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        )
        db.init_app(self.app)
        for rule in app.url_map.iter_rules():
            if rule.endpoint != 'static':
                self.app.add_url_rule(
                    rule.rule,
                    endpoint=rule.endpoint,
                    view_func=app.view_functions[rule.endpoint],
                    methods=rule.methods - {'HEAD', 'OPTIONS'},
                )
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def register_and_login(self, username):
        response = self.client.post('/register', data={
            'username': username,
            'email': username + '@example.com',
            'password': 'password123',
            'confirm_password': 'password123',
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post('/login', data={
            'username': username, 'password': 'password123'
        })
        self.assertEqual(response.status_code, 302)

    def buy(self, name, price):
        response = self.client.post('/api/purchase', json={
            'product_name': name, 'price': price
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        return response.get_json()['order_id']

    def assert_current(self, name=None):
        for path in ('/home', '/dashboard'):
            html = self.client.get(path).get_data(as_text=True)
            if name is None:
                self.assertIn('您还没有购买产品', html)
                self.assertIn('>0</div>', html)
            else:
                self.assertIn('<strong>' + name + '</strong>', html)
                self.assertIn('>1</div>', html)

    def test_purchase_replaces_current_product_and_preserves_history(self):
        self.register_and_login('alice')
        self.assert_current()
        first_id = self.buy('Web3 入门套件', 99)
        self.assert_current('Web3 入门套件')
        second_id = self.buy('高级开发套件', 299)
        self.assertGreater(second_id, first_id)
        self.assert_current('高级开发套件')
        for path in ('/home', '/dashboard'):
            self.assertNotIn('Web3 入门套件', self.client.get(path).get_data(as_text=True))
        self.buy('高级开发套件', 299)
        self.assert_current('高级开发套件')
        self.assertEqual(Order.query.count(), 3)

    def test_users_are_isolated_and_incomplete_orders_are_ignored(self):
        self.register_and_login('alice')
        self.buy('Web3 入门套件', 99)
        alice = User.query.filter_by(username='alice').one()
        db.session.add(Order(user_id=alice.id, product_name='未完成', price=1,
                             status='pending'))
        db.session.commit()
        self.assert_current('Web3 入门套件')
        self.client.get('/logout')
        self.register_and_login('bob')
        self.assert_current()
        self.buy('企业方案', 999)
        self.assert_current('企业方案')
        self.client.get('/logout')
        self.client.post('/login', data={'username': 'alice', 'password': 'password123'})
        self.assert_current('Web3 入门套件')

    def test_unsuccessful_purchase_does_not_replace_current_product(self):
        response = self.client.post('/api/purchase', json={
            'product_name': '企业方案', 'price': 999
        })
        self.assertEqual(response.status_code, 401)
        self.register_and_login('alice')
        self.buy('Web3 入门套件', 99)
        response = self.client.post('/api/purchase', json={'product_name': '企业方案'})
        self.assertEqual(response.status_code, 400)
        self.assert_current('Web3 入门套件')

    def test_home_displays_subscription_management(self):
        self.register_and_login('alice')
        for purchased in (False, True):
            if purchased:
                self.buy('Web3 入门套件', 99)
            html = self.client.get('/home').get_data(as_text=True)
            self.assertIn('订阅管理', html)
            self.assertNotIn('data-client=', html)
            self.assertIn('id="shadowrocket-import"', html)
            self.assertIn('id="view-subscription"', html)
            self.assertIn('id="subscription-links" hidden', html)
            self.assertIn('id="clash-link"', html)
            self.assertIn('id="shadowrocket-link"', html)
            for action in ('续订', '取消订阅'):
                self.assertIn('data-subscription-action="' + action + '"', html)
            self.assertIn('id="subscription-message"', html)

    def test_subscription_links_are_stable_private_and_user_specific(self):
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'https://web.example',
                                     'XUI_SUB_BASE_URL': 'https://panel.example/sub',
                                     'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
                                     'EXTRA_SUB_URLS': '["https://example.com/sub"]'}), \
                patch('app.build_subscription', return_value=SubscriptionResult('proxies: []', 0, 0, 0, 0)) as build:
            self.assertEqual(self.client.post('/api/subscription-links').status_code, 401)
            self.register_and_login('alice')
            first = self.client.post('/api/subscription-links')
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.headers['Cache-Control'], 'no-store')
            links = first.get_json()
            self.assertEqual(links, self.client.post('/api/subscription-links').get_json())
            self.assertTrue(links['shadowrocket_import'].startswith('shadowrocket://add/'))
            path = urlsplit(links['clash']).path
            self.client.get('/logout')
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), 'proxies: []')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(build.call_args.args[1:], ('alice@example.com', 'alice', 'clash'))
            self.assertEqual(self.client.get('/subscription/clash/invalid').status_code, 404)
            self.register_and_login('bob')
            self.assertNotEqual(links['clash'], self.client.post('/api/subscription-links').get_json()['clash'])

    def test_subscription_links_use_configured_http_public_address(self):
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'http://192.168.2.17:8000/',
                                     'XUI_SUB_BASE_URL': 'https://panel.example/sub',
                                     'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
                                     'EXTRA_SUB_URLS': '[]'}):
            self.register_and_login('alice')
            response = self.client.post('/api/subscription-links')
            self.assertEqual(response.status_code, 200)
            links = response.get_json()
            self.assertTrue(links['clash'].startswith('http://192.168.2.17:8000/subscription/clash/'))
            self.assertTrue(links['shadowrocket'].startswith('http://192.168.2.17:8000/subscription/shadowrocket/'))
            self.assertIn('http%3A%2F%2F192.168.2.17%3A8000%2Fsubscription%2Fshadowrocket%2F',
                          links['shadowrocket_import'])

    def test_subscription_errors_are_not_success_responses(self):
        from subscription import SubscriptionError
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'https://web.example',
                                     'XUI_SUB_BASE_URL': 'https://panel.example/sub',
                                     'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
                                     'EXTRA_SUB_URLS': '["https://example.com/sub"]'}):
            self.register_and_login('alice')
            path = urlsplit(self.client.post('/api/subscription-links').get_json()['clash']).path
            with patch('app.build_subscription', side_effect=SubscriptionError('failed')):
                response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertIn('订阅生成失败'.encode(), response.data)

    def test_clash_response_matches_yaml_response_headers_and_utf8(self):
        body = 'proxies:\n  - name: 香港节点\n' + '# 测试\n' * 2000
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'https://web.example',
                                     'XUI_SUB_BASE_URL': 'https://panel.example/sub',
                                     'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
                                     'CLASH_ATTACHMENT_FILENAME': 'Web3X_Clash.yaml',
                                     'EXTRA_SUB_URLS': '[]'}):
            self.register_and_login('alice')
            links = self.client.post('/api/subscription-links').get_json()
            with patch('app.build_subscription', return_value=SubscriptionResult(body, 2000000000123, 23, 47, 100)):
                clash = self.client.get(urlsplit(links['clash']).path)
            self.assertEqual(clash.status_code, 200)
            self.assertEqual(clash.data, body.encode('utf-8'))
            self.assertEqual(clash.headers['Content-Type'], 'text/plain; charset=utf-8')
            self.assertEqual(clash.headers['Content-Disposition'],
                             "attachment; filename*=UTF-8''Web3X_Clash.yaml")
            self.assertRegex(clash.headers['subscription-userinfo'],
                             r'^upload=23; download=47; total=100; update=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}; expire=2000000000$')
            self.assertEqual(clash.headers['Cache-Control'], 'no-store')
            self.assertEqual(clash.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(clash.headers['Referrer-Policy'], 'no-referrer')
            with patch('app.build_subscription', return_value=SubscriptionResult(body, 0, 23, 47, 0)):
                unlimited = self.client.get(urlsplit(links['clash']).path)
            self.assertRegex(unlimited.headers['subscription-userinfo'],
                             r'^upload=23; download=47; total=0; update=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
            with patch('app.build_subscription', return_value=SubscriptionResult('dm1lc3M6Ly90ZXN0', 2000000000123, 0, 0, 0)):
                shadow = self.client.get(urlsplit(links['shadowrocket']).path)
            self.assertEqual(shadow.data, b'dm1lc3M6Ly90ZXN0')
            self.assertNotIn('Content-Disposition', shadow.headers)
            self.assertNotIn('subscription-userinfo', shadow.headers)

    def test_clash_attachment_filename_is_configurable_and_validated(self):
        self.register_and_login('alice')
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'https://web.example',
                                     'XUI_SUB_BASE_URL': 'https://panel.example/sub',
                                     'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
                                     'EXTRA_SUB_URLS': '[]'}):
            links = self.client.post('/api/subscription-links').get_json()
            path = urlsplit(links['clash']).path
            with patch('app.build_subscription', return_value=SubscriptionResult('proxies: []', 0, 0, 0, 0)) as build:
                with patch.dict(os.environ, {'CLASH_ATTACHMENT_FILENAME': '订阅 名称;1.yaml'}):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers['Content-Disposition'],
                                     "attachment; filename*=UTF-8''%E8%AE%A2%E9%98%85%20"
                                     "%E5%90%8D%E7%A7%B0%3B1.yaml")
                for name in ('', ' ', '../bad.yaml', 'bad\\name.yaml', 'bad\r\nX: y'):
                    with self.subTest(name=name), patch.dict(os.environ, {'CLASH_ATTACHMENT_FILENAME': name}):
                        build.reset_mock()
                        response = self.client.get(path)
                        self.assertEqual(response.status_code, 503)
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        build.assert_not_called()
                with patch.dict(os.environ):
                    os.environ.pop('CLASH_ATTACHMENT_FILENAME', None)
                    response = self.client.get(path)
                    self.assertEqual(response.headers['Content-Disposition'],
                                     "attachment; filename*=UTF-8''Web3X_Clash.yaml")

    def test_subscription_fetches_panel_and_optional_sources_over_http(self):
        class SubscriptionHandler(PanelHandler):
            def do_GET(self):
                if self.path == '/prefix/panel/api/clients/get/alice%40example.com':
                    return self.respond({'client': self.server.clients[0], 'usedTraffic': 10})
                if self.path in ('/clash/client-id', '/sub/client-id', '/extra', '/config.ini', '/rules.list'):
                    agent = self.headers.get('User-Agent')
                    self.server.agents.append((self.path, agent))
                    if self.path == '/config.ini':
                        body = ('custom_proxy_group=Select`select`[]DIRECT`.*\n'
                                f'ruleset=Select,http://127.0.0.1:{self.server.server_port}/rules.list\n'
                                'ruleset=Select,[]FINAL\nrename_node=香港@香港测试\n')
                    elif self.path == '/rules.list':
                        body = 'DOMAIN,example.com\n'
                    elif agent.startswith('clash'):
                        body = ('proxies:\n  - {name: 香港 main, type: ss, server: example, '
                                'port: 443, cipher: aes-128-gcm, password: test}\n'
                                'proxy-groups:\n  - {name: Select, type: select, proxies: [香港 main]}\n'
                                'rules: ["MATCH,Select"]\n')
                    else:
                        body = 'vmess://primary' if self.path.startswith('/sub/') else 'vless://extra'
                    data = body.encode()
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(data)
                    return
                super().do_GET()

        server = ThreadingHTTPServer(('127.0.0.1', 0), SubscriptionHandler)
        server.clients = [{'email': 'alice@example.com', 'comment': 'alice', 'subId': 'client-id',
                           'enable': True, 'expiryTime': 4102444800123, 'totalGB': 100}]
        server.traffic = {'alice@example.com': {'email': 'alice@example.com', 'up': 3, 'down': 7}}
        server.agents = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with patch.dict(os.environ, {
                'XUI_BASE_URL': base + '/prefix',
                'XUI_USERNAME': 'admin',
                'XUI_PASSWORD': 'secret',
                'PUBLIC_BASE_URL': 'https://web.example',
                'XUI_SUB_BASE_URL': base + '/sub',
                'XUI_CLASH_BASE_URL': base + '/clash',
                'CLASH_CONFIG': base + '/config.ini',
                'EXTRA_SUB_URLS': f'["{base}/extra"]',
            }), patch('app.ThreeXUI', ThreeXUI):
                user = User(username='alice', email='alice@example.com')
                user.set_password('password123')
                db.session.add(user)
                db.session.commit()
                self.client.post('/login', data={'username': 'alice', 'password': 'password123'})
                links = self.client.post('/api/subscription-links').get_json()
                clash = self.client.get(urlsplit(links['clash']).path)
                self.assertEqual(clash.status_code, 200)
                self.assertIn('expire=4102444800', clash.headers['subscription-userinfo'])
                self.assertIn('upload=3; download=7; total=100;', clash.headers['subscription-userinfo'])
                config = yaml.safe_load(clash.data)
                self.assertEqual([proxy['name'] for proxy in config['proxies']], ['🇭🇰 香港测试 main', '🇭🇰 香港测试 main (2)'])
                self.assertEqual(config['rules'], ['DOMAIN,example.com,Select', 'MATCH,Select'])
                shadow = self.client.get(urlsplit(links['shadowrocket']).path)
                self.assertEqual(shadow.status_code, 200)
                self.assertEqual(base64.b64decode(shadow.data).decode(), 'vmess://primary\nvless://extra')
                self.assertEqual(server.agents, [
                    ('/clash/client-id', 'clash-verge/v2.3.1'),
                    ('/extra', 'clash-verge/v2.3.1'),
                    ('/config.ini', 'clash-verge/v2.3.1'),
                    ('/rules.list', 'clash-verge/v2.3.1'),
                    ('/sub/client-id', 'Shadowrocket'),
                    ('/extra', 'Shadowrocket'),
                ])
                server.clients[0]['expiryTime'] = 4102531200000
                server.traffic['alice@example.com'].update(up=11, down=22)
                updated = self.client.get(urlsplit(links['clash']).path)
                self.assertEqual(updated.status_code, 200)
                self.assertIn('expire=4102531200', updated.headers['subscription-userinfo'])
                self.assertIn('upload=11; download=22; total=100;', updated.headers['subscription-userinfo'])
                server.agents.clear()
                with patch.dict(os.environ, {'EXTRA_SUB_URLS': ''}):
                    clash = self.client.get(urlsplit(links['clash']).path)
                    shadow = self.client.get(urlsplit(links['shadowrocket']).path)
                    self.assertEqual(clash.status_code, 200)
                    self.assertEqual([proxy['name'] for proxy in yaml.safe_load(clash.data)['proxies']], ['🇭🇰 香港测试 main'])
                    self.assertEqual(shadow.status_code, 200)
                    self.assertEqual(base64.b64decode(shadow.data).decode(), 'vmess://primary')
                    self.assertEqual([path for path, _ in server.agents],
                                     ['/clash/client-id', '/config.ini', '/rules.list', '/sub/client-id'])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_default_session_secret_cannot_issue_subscription_links(self):
        self.app.config['SECRET_KEY'] = 'your-secret-key-change-this'
        self.register_and_login('alice')
        with patch.dict(os.environ, {'PUBLIC_BASE_URL': 'https://web.example'}):
            response = self.client.post('/api/subscription-links')
        self.assertEqual(response.status_code, 503)

    def test_registration_rejects_duplicate_panel_remark(self):
        self.panel.create_client.side_effect = DuplicateClientError('3x-ui 已存在同名客户端，无法注册')
        response = self.client.post('/register', data={
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'password123', 'confirm_password': 'password123',
        })
        self.assertIn('3x-ui 已存在同名客户端'.encode(), response.data)
        self.assertIsNone(User.query.filter_by(username='alice').first())

    def test_registration_fails_when_panel_fails(self):
        self.panel.create_client.side_effect = PanelRequestError('unavailable')
        response = self.client.post('/register', data={
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'password123', 'confirm_password': 'password123',
        })
        self.assertIn('客户端创建失败'.encode(), response.data)
        self.assertIsNone(User.query.filter_by(username='alice').first())

    def test_registration_passes_entered_email_to_panel(self):
        response = self.client.post('/register', data={
            'username': 'alice', 'email': ' alice@example.com ',
            'password': 'password123', 'confirm_password': 'password123',
        })
        self.assertEqual(response.status_code, 302)
        self.panel.create_client.assert_called_once_with('alice', 'alice@example.com', False)
        self.assertEqual(User.query.filter_by(username='alice').one().email, 'alice@example.com')

    def test_registration_automatically_logs_in(self):
        self.assertEqual(self.client.get('/').location, '/login')
        response = self.client.post('/register', data={
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'password123', 'confirm_password': 'password123',
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request.path, '/dashboard')
        self.assertIn('欢迎，alice'.encode(), response.data)
        with self.client.session_transaction() as saved_session:
            self.assertEqual(saved_session['user_id'], User.query.filter_by(username='alice').one().id)
            self.assertEqual(saved_session['username'], 'alice')
        self.assertEqual(self.client.get('/home').status_code, 200)
        self.assertEqual(self.client.get('/purchase').status_code, 200)
        self.assertEqual(self.client.get('/').location, '/dashboard')

    def test_registration_without_email_generates_random_client_identifier(self):
        response = self.client.post('/register', data={
            'username': 'alice', 'password': 'password123',
            'confirm_password': 'password123',
        })
        self.assertEqual(response.status_code, 302)
        email = User.query.filter_by(username='alice').one().email
        self.assertRegex(email, r'^[A-Za-z0-9]{8}$')
        self.panel.create_client.assert_called_once_with('alice', email, True)

    def test_generated_local_collision_retries(self):
        db.session.add(User(username='other', email='aaaaaaaa', password='hash'))
        db.session.commit()
        with patch('app.random_client_email', side_effect=['aaaaaaaa', 'BBBBBBBB']):
            response = self.client.post('/register', data={
                'username': 'alice', 'email': '',
                'password': 'password123', 'confirm_password': 'password123',
            })
        self.assertEqual(response.status_code, 302)
        self.panel.create_client.assert_called_once_with('alice', 'BBBBBBBB', True)

    def test_invalid_email_rejected_before_panel_call(self):
        response = self.client.post('/register', data={
            'username': 'alice', 'email': 'invalid',
            'password': 'password123', 'confirm_password': 'password123',
        })
        self.assertIn('请输入有效的邮箱地址'.encode(), response.data)
        self.panel.create_client.assert_not_called()
        self.assertIsNone(User.query.filter_by(username='alice').first())

    def test_registration_sends_entered_and_generated_emails_to_panel(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), PanelHandler)
        server.clients = []
        server.payloads = []
        server.inbounds = [{'id': 2, 'enable': True}, {'id': 3, 'enable': True},
                           {'id': 4, 'enable': False}]
        server.failed_ids = {3}
        server.persist_on_failure = set()
        server.allow_add = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {
                'XUI_BASE_URL': f'http://127.0.0.1:{server.server_port}/prefix',
                'XUI_USERNAME': 'admin',
                'XUI_PASSWORD': 'secret',
            }), patch('app.ThreeXUI', ThreeXUI):
                for username, email in (('alice', 'alice@example.com'), ('bob', '')):
                    response = self.client.post('/register', data={
                        'username': username, 'email': email,
                        'password': 'password123', 'confirm_password': 'password123',
                    })
                    self.assertEqual(response.status_code, 302)
                    stored_email = User.query.filter_by(username=username).one().email
                    payload = server.payloads[-2]['client']
                    self.assertEqual(payload['email'], stored_email)
                    self.assertEqual(payload['comment'], username)
                    self.assertEqual(server.payloads[-2]['inboundIds'], [2])
                    self.assertEqual(server.payloads[-1]['inboundIds'], [3])
                    dashboard = self.client.get('/dashboard').get_data(as_text=True)
                    self.assertIn('部分入站未能分配', dashboard)
                    if email:
                        self.assertEqual(stored_email, email)
                    else:
                        self.assertRegex(stored_email, r'^[A-Za-z0-9]{8}$')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_registration_rolls_back_when_panel_fails(self):
        self.panel.create_client.side_effect = PanelRequestError('unavailable')
        response = self.client.post('/register', data={
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'password123', 'confirm_password': 'password123',
        })
        self.assertIn('客户端创建失败'.encode(), response.data)
        self.assertIsNone(User.query.filter_by(username='alice').first())
        with self.client.session_transaction() as saved_session:
            self.assertNotIn('user_id', saved_session)
        self.assertEqual(self.client.get('/dashboard').status_code, 302)

    def test_partial_inbound_registration_warns_user(self):
        self.panel.failed_inbounds = [3]
        response = self.client.post('/register', data={
            'username': 'alice', 'email': 'alice@example.com',
            'password': 'password123', 'confirm_password': 'password123',
        }, follow_redirects=True)
        self.assertEqual(response.request.path, '/dashboard')
        self.assertIn('部分入站未能分配'.encode(), response.data)
        self.assertIsNotNone(User.query.filter_by(username='alice').first())

    def test_local_commit_failure_deletes_created_client(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('commit failed')):
            response = self.client.post('/register', data={
                'username': 'alice', 'email': 'alice@example.com',
                'password': 'password123', 'confirm_password': 'password123',
            })
        self.assertIn('注册保存失败'.encode(), response.data)
        self.panel.delete_client.assert_called_once_with('test-client')
        self.assertIsNone(User.query.filter_by(username='alice').first())
        with self.client.session_transaction() as saved_session:
            self.assertNotIn('user_id', saved_session)


if __name__ == '__main__':
    unittest.main()
