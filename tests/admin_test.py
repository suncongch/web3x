import os
import re
import time
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from app import AppSetting, Order, Ticket, User, app, db, protect_admin_responses


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'ADMIN_USERNAME': 'admin',
            'ADMIN_PASSWORD_HASH': generate_password_hash('admin-password', method='pbkdf2:sha256'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = Flask(__name__, template_folder=os.path.join(app.root_path, 'templates'))
        self.app.config.update(TESTING=True, SECRET_KEY='test-secret',
                               SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        db.init_app(self.app)
        for rule in app.url_map.iter_rules():
            if rule.endpoint != 'static':
                self.app.add_url_rule(rule.rule, endpoint=rule.endpoint,
                                      view_func=app.view_functions[rule.endpoint],
                                      methods=rule.methods - {'HEAD', 'OPTIONS'})
        self.app.after_request(protect_admin_responses)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        user = User(username='<alice>', email='alice@example.com', password='private-password-hash')
        other = User(username='bob', email='bob@example.com', password='another-private-hash')
        db.session.add_all([user, other])
        db.session.flush()
        self.user_id = user.id
        self.other_id = other.id
        db.session.add(Order(user_id=user.id, product_name='plan-a', price=99, status='completed'))
        db.session.add(Order(user_id=other.id, product_name='plan-b', price=42, status='completed'))
        db.session.add(Ticket(user_id=user.id, subject='订阅故障', category='技术问题',
                              content='无法导入订阅链接'))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def csrf(self, response):
        return re.search(r'name="csrf_token" value="([^"]+)"',
                         response.get_data(as_text=True)).group(1)

    def login(self, password='admin-password'):
        token = self.csrf(self.client.get('/admin/login'))
        return self.client.post('/admin/login', data={
            'csrf_token': token, 'username': 'admin', 'password': password,
        })

    def test_requires_configured_credentials_and_secret(self):
        with patch.dict(os.environ, {'ADMIN_PASSWORD_HASH': 'invalid'}):
            self.assertEqual(self.client.get('/admin/login').status_code, 503)
        with self.app.test_request_context():
            self.app.config['SECRET_KEY'] = 'your-secret-key-change-this'
            try:
                self.assertEqual(self.client.get('/admin').status_code, 503)
            finally:
                self.app.config['SECRET_KEY'] = 'test-secret'

    def test_authentication_and_csrf(self):
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.get(f'/admin/users/{self.user_id}/orders').status_code, 302)
        self.assertEqual(self.client.post('/admin/login', data={
            'username': 'admin', 'password': 'admin-password',
        }).status_code, 400)
        self.assertEqual(self.login('wrong').status_code, 401)
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.client.post('/admin/logout').status_code, 400)
        page = self.client.get('/admin')
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.post('/admin/logout', data={
            'csrf_token': self.csrf(page),
        }).status_code, 302)
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_user_and_order_data_are_scoped_and_escaped(self):
        self.login()
        page = self.client.get('/admin')
        html = page.get_data(as_text=True)
        self.assertIn('&lt;alice&gt;', html)
        self.assertIn('alice@example.com', html)
        self.assertIn('name="enabled" value="true"', html)
        self.assertNotIn('checked>', html)
        self.assertNotIn('private-password-hash', html)
        orders = self.client.get(f'/admin/users/{self.user_id}/orders')
        html = orders.get_data(as_text=True)
        self.assertIn('plan-a', html)
        self.assertNotIn('plan-b', html)
        self.assertNotIn('private-password-hash', html)
        self.assertEqual(self.client.get('/admin/users/9999/orders').status_code, 404)
        self.assertEqual(self.client.get('/admin?page=0').status_code, 400)
        self.assertEqual(self.client.get(f'/admin/users/{self.user_id}/orders?page=bad').status_code, 400)

    def test_admin_can_toggle_external_node_access_with_csrf(self):
        user = db.session.get(User, self.user_id)
        self.assertFalse(user.can_use_external_nodes)
        path = f'/admin/users/{self.user_id}/external-nodes'
        self.assertEqual(self.client.post(path, data={'enabled': 'true'}).status_code, 302)
        self.login()
        page = self.client.get('/admin')
        csrf_token = self.csrf(page)
        self.assertEqual(self.client.post(path, data={
            'csrf_token': csrf_token, 'enabled': 'invalid',
        }).status_code, 400)
        enabled = self.client.post(path, data={
            'csrf_token': csrf_token, 'enabled': 'true',
        })
        self.assertEqual(enabled.status_code, 302)
        self.assertTrue(db.session.get(User, self.user_id).can_use_external_nodes)
        self.assertIn('checked>', self.client.get('/admin').get_data(as_text=True))
        disabled = self.client.post(path, data={'csrf_token': csrf_token})
        self.assertEqual(disabled.status_code, 302)
        self.assertFalse(db.session.get(User, self.user_id).can_use_external_nodes)

    def test_admin_can_edit_node_filter_and_invalid_regex_is_rejected(self):
        self.login()
        page = self.client.get('/admin')
        self.assertIn('日本(?!\\s*3\\b)', page.get_data(as_text=True))
        path = '/admin/node-filter'
        self.assertEqual(self.client.post(path, data={
            'csrf_token': self.csrf(page), 'include_pattern': '香港',
        }).status_code, 302)
        self.assertEqual(db.session.get(AppSetting, 'node_include_pattern').value, '香港')
        self.assertIn('香港', self.client.get('/admin').get_data(as_text=True))

        page = self.client.get('/admin')
        invalid = self.client.post(path, data={
            'csrf_token': self.csrf(page), 'include_pattern': '(',
        })
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('正则表达式无效', invalid.get_data(as_text=True))
        self.assertEqual(db.session.get(AppSetting, 'node_include_pattern').value, '香港')

    def test_expiry_and_credential_rotation_revoke_session(self):
        self.login()
        with self.client.session_transaction() as state:
            state['admin_expires'] = time.time() - 1
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.login()
        with patch.dict(os.environ, {'ADMIN_USERNAME': 'new-admin'}):
            self.assertEqual(self.client.get('/admin').status_code, 302)
        with patch.dict(os.environ, {
            'ADMIN_PASSWORD_HASH': generate_password_hash('new-password', method='pbkdf2:sha256'),
        }):
            self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_admin_and_user_logins_replace_each_other(self):
        user = db.session.get(User, self.user_id)
        user.set_password('user-password')
        db.session.commit()
        with self.client.session_transaction() as state:
            state['user_id'] = self.user_id
            state['username'] = user.username
        self.login()
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id', state)
            self.assertIn('admin_fingerprint', state)
        response = self.client.post('/login', data={
            'username': user.username, 'password': 'user-password',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/admin').status_code, 302)
        with self.client.session_transaction() as state:
            self.assertEqual(state['user_id'], self.user_id)
            self.assertNotIn('admin_fingerprint', state)

    def test_pagination(self):
        for number in range(25):
            db.session.add(User(username=f'user-{number}', email=f'u{number}@example.com', password='hash'))
            db.session.add(Order(user_id=self.user_id, product_name=f'item-{number}',
                                 price=1, status='completed'))
        db.session.commit()
        self.login()
        self.assertIn('下一页', self.client.get('/admin').get_data(as_text=True))
        self.assertIn('上一页', self.client.get('/admin?page=2').get_data(as_text=True))
        orders_url = f'/admin/users/{self.user_id}/orders'
        self.assertIn('下一页', self.client.get(orders_url).get_data(as_text=True))
        self.assertIn('上一页', self.client.get(orders_url + '?page=2').get_data(as_text=True))

    def test_refresh_rules_requires_admin_and_csrf_and_reports_result(self):
        with patch('app.cached_rule_config') as refresh:
            self.assertEqual(self.client.post('/admin/refresh-rules').status_code, 302)
            refresh.assert_not_called()
            self.login()
            self.assertEqual(self.client.post('/admin/refresh-rules').status_code, 400)
            refresh.assert_not_called()
            token = self.csrf(self.client.get('/admin'))
            response = self.client.post('/admin/refresh-rules',
                                        data={'csrf_token': token}, follow_redirects=True)
            refresh.assert_called_once_with(force=True)
            self.assertIn('分流规则缓存刷新成功', response.get_data(as_text=True))
            from subscription import SubscriptionError
            refresh.side_effect = SubscriptionError('offline')
            response = self.client.post('/admin/refresh-rules',
                                        data={'csrf_token': token}, follow_redirects=True)
            self.assertIn('分流规则缓存刷新失败', response.get_data(as_text=True))

    def test_admin_can_manage_tickets(self):
        ticket = Ticket.query.one()
        self.assertEqual(self.client.get('/admin/tickets').status_code, 302)
        self.login()
        page = self.client.get('/admin/tickets')
        html = page.get_data(as_text=True)
        self.assertIn('订阅故障', html)
        self.assertIn('&lt;alice&gt;', html)
        token = self.csrf(page)
        invalid = self.client.post(f'/admin/tickets/{ticket.id}', data={
            'csrf_token': token, 'status': 'bad-status', 'admin_reply': '',
        })
        self.assertEqual(invalid.status_code, 400)
        updated = self.client.post(f'/admin/tickets/{ticket.id}', data={
            'csrf_token': token,
            'status': 'resolved',
            'admin_reply': '已修复，请重新获取订阅链接',
        }, follow_redirects=True)
        self.assertIn('已更新为“已解决”', updated.get_data(as_text=True))
        ticket = db.session.get(Ticket, ticket.id)
        self.assertEqual(ticket.status, 'resolved')
        self.assertEqual(ticket.admin_reply, '已修复，请重新获取订阅链接')
        self.assertIsNotNone(ticket.closed_at)


if __name__ == '__main__':
    unittest.main()
