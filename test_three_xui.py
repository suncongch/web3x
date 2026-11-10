import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import unquote
from uuid import UUID

from three_xui import DuplicateClientError, PanelError, PanelRequestError, ThreeXUI


class PanelHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, obj=None, success=True):
        body = json.dumps({'success': success, 'obj': obj}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', 'session=example; Path=/')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/prefix/csrf-token':
            return self.respond('csrf-token')
        if self.headers.get('Cookie') != 'session=example':
            return self.respond(success=False)
        if self.path == '/prefix/panel/api/inbounds/list':
            return self.respond(self.server.inbounds)
        if self.path == '/prefix/panel/api/clients/list':
            return self.respond(self.server.clients)
        if self.path.startswith('/prefix/panel/api/clients/traffic/'):
            email = unquote(self.path.rsplit('/', 1)[-1])
            return self.respond(self.server.traffic.get(email))
        if self.path.startswith('/prefix/panel/api/clients/get/subId/'):
            sub_id = unquote(self.path.rsplit('/', 1)[-1])
            return self.respond([{'client': client} for client in self.server.clients
                                 if client.get('subId') == sub_id])
        if self.path.startswith('/prefix/panel/api/clients/get/'):
            email = unquote(self.path.rsplit('/', 1)[-1])
            client = next((item for item in self.server.clients if item['email'] == email), None)
            return self.respond({'client': client}, success=client is not None)
        self.send_error(404)

    def do_POST(self):
        if (self.headers.get('Cookie') != 'session=example'
                or self.headers.get('X-CSRF-Token') != 'csrf-token'):
            return self.respond(success=False)
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/prefix/login':
            return self.respond(success=payload == {'username': 'admin', 'password': 'secret'})
        if self.path == '/prefix/panel/api/clients/add':
            self.server.payloads.append(payload)
            inbound_id = payload['inboundIds'][0]
            success = self.server.allow_add and inbound_id not in self.server.failed_ids
            if success or inbound_id in self.server.persist_on_failure:
                client = payload['client']
                existing = next((item for item in self.server.clients
                                 if item['email'] == client['email']), None)
                if existing is None:
                    existing = {'email': client['email'], 'comment': client['comment'],
                                'subId': client['subId'], 'inboundIds': []}
                    self.server.clients.append(existing)
                existing['inboundIds'].append(inbound_id)
            return self.respond(success=success)
        self.send_error(404)


class ThreeXUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), PanelHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def setUp(self):
        self.server.clients = []
        self.server.traffic = {}
        self.server.payloads = []
        self.server.inbounds = [{'id': 2, 'enable': True}]
        self.server.failed_ids = set()
        self.server.persist_on_failure = set()
        self.server.allow_add = True
        self.environ = patch.dict(os.environ, {
            'XUI_BASE_URL': f'http://127.0.0.1:{self.server.server_port}/prefix',
            'XUI_USERNAME': 'admin',
            'XUI_PASSWORD': 'secret',
        })
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def test_creates_vmess_client_with_comment_and_limits(self):
        before = time.time()
        email = ThreeXUI().create_client('测试用户', 'user@example.com')
        after = time.time()
        payload = self.server.payloads[0]
        self.assertEqual(payload['inboundIds'], [2])
        client = payload['client']
        self.assertEqual(client['comment'], '测试用户')
        self.assertEqual(client['email'], email)
        self.assertEqual(email, 'user@example.com')
        self.assertEqual(str(UUID(client['id'])), client['id'])
        self.assertTrue(client['enable'])
        self.assertEqual(client['totalGB'], 25 * 1024 ** 3)
        self.assertLessEqual(int((before + 30 * 86400) * 1000), client['expiryTime'])
        self.assertLessEqual(client['expiryTime'], (after + 30 * 86400) * 1000)

    def test_duplicate_comment_across_panel_prevents_creation(self):
        self.server.clients = [{'email': 'different', 'comment': 'alice', 'inboundIds': [9]}]
        with self.assertRaises(DuplicateClientError):
            ThreeXUI().create_client('alice', 'alice@example.com')
        self.assertEqual(self.server.payloads, [])

    def test_rejects_missing_enabled_inbounds_and_invalid_client_list(self):
        self.server.inbounds = [{'id': 2, 'enable': False}]
        with self.assertRaises(PanelError):
            ThreeXUI().create_client('alice', 'alice@example.com')
        self.server.inbounds = [{'id': 2, 'enable': True}]
        self.server.clients = [{'email': 'missing-comment'}]
        with self.assertRaises(PanelRequestError):
            ThreeXUI().create_client('alice', 'alice@example.com')
        self.assertEqual(self.server.payloads, [])

    def test_rejected_panel_create_is_not_success(self):
        self.server.allow_add = False
        with self.assertRaises(PanelError):
            ThreeXUI().create_client('alice', 'alice@example.com')

    def test_adds_to_each_enabled_inbound_and_skips_disabled(self):
        self.server.inbounds = [
            {'id': 1, 'enable': True, 'protocol': 'vmess'},
            {'id': 2, 'enable': False, 'protocol': 'vless'},
            {'id': 3, 'enable': True, 'protocol': 'vless'},
        ]
        panel = ThreeXUI()
        panel.create_client('alice', 'alice@example.com')
        self.assertEqual([p['inboundIds'] for p in self.server.payloads], [[1], [3]])
        self.assertEqual(self.server.payloads[0]['client'], self.server.payloads[1]['client'])
        self.assertEqual(panel.failed_inbounds, [])

    def test_partial_failure_is_reported_and_other_inbounds_are_added(self):
        self.server.inbounds = [{'id': n, 'enable': True} for n in (1, 2, 3)]
        self.server.failed_ids = {2}
        panel = ThreeXUI()
        panel.create_client('alice', 'alice@example.com')
        self.assertEqual(panel.failed_inbounds, [2])
        self.assertEqual(self.server.clients[0]['inboundIds'], [1, 3])

    def test_failed_response_can_be_reconciled_with_panel(self):
        self.server.failed_ids = {2}
        self.server.persist_on_failure = {2}
        panel = ThreeXUI()
        panel.create_client('alice', 'alice@example.com')
        self.assertEqual(panel.failed_inbounds, [])
        self.assertEqual(self.server.clients[0]['inboundIds'], [2])

    def test_rejects_malformed_or_duplicate_inbounds(self):
        for inbounds in ([{'id': 2}], [{'id': 2, 'enable': True}] * 2):
            self.server.inbounds = inbounds
            with self.assertRaises(PanelError):
                ThreeXUI().create_client('alice', 'alice@example.com')
            self.assertEqual(self.server.payloads, [])

    def test_duplicate_email_rejected_case_insensitively(self):
        self.server.clients = [{'email': 'Alice@example.com', 'comment': 'other'}]
        with self.assertRaisesRegex(DuplicateClientError, '邮箱已存在'):
            ThreeXUI().create_client('alice', 'alice@example.com')
        self.assertEqual(self.server.payloads, [])

    def test_generated_identifier_is_used_as_email(self):
        email = ThreeXUI().create_client('alice', 'A1b2C3d4', True)
        self.assertEqual(email, 'A1b2C3d4')
        self.assertEqual(self.server.payloads[0]['client']['email'], 'A1b2C3d4')

    def test_duplicate_generated_identifier_does_not_create_client(self):
        self.server.clients = [{'email': 'a1B2c3D4', 'comment': 'other'}]
        with self.assertRaisesRegex(DuplicateClientError, '重新注册'):
            ThreeXUI().create_client('alice', 'A1b2C3d4', True)
        self.assertEqual(self.server.payloads, [])

    def test_requires_safe_config(self):
        os.environ['XUI_BASE_URL'] = 'http://remote.example/panel'
        with self.assertRaises(PanelError):
            ThreeXUI()

    def test_get_client_rejects_shared_or_missing_subscription_id(self):
        self.server.clients = [{'email': 'alice@example.com', 'comment': 'alice', 'subId': 'shared'},
                               {'email': 'bob@example.com', 'comment': 'bob', 'subId': 'shared'}]
        with self.assertRaises(PanelRequestError):
            ThreeXUI().get_client('alice@example.com')
        self.server.clients.pop()
        self.assertEqual(ThreeXUI().get_client('alice@example.com')['client']['subId'], 'shared')
        del self.server.clients[0]['subId']
        with self.assertRaises(PanelRequestError):
            ThreeXUI().get_client('alice@example.com')

    def test_client_traffic_validates_identity_and_counters(self):
        panel = ThreeXUI()
        panel.login()
        self.server.traffic['alice@example.com'] = {'email': 'alice@example.com', 'up': 23, 'down': 47}
        self.assertEqual(panel.get_client_traffic('alice@example.com')['down'], 47)
        for value in (None, {'email': 'bob@example.com', 'up': 0, 'down': 0},
                      {'email': 'alice@example.com', 'up': -1, 'down': 0},
                      {'email': 'alice@example.com', 'up': True, 'down': 0}):
            self.server.traffic['alice@example.com'] = value
            with self.assertRaises(PanelRequestError):
                panel.get_client_traffic('alice@example.com')


if __name__ == '__main__':
    unittest.main()
