import os
import re
import time
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from app import Order, User, app, db, protect_admin_responses


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
        self.assertNotIn('private-password-hash', html)
        orders = self.client.get(f'/admin/users/{self.user_id}/orders')
        html = orders.get_data(as_text=True)
        self.assertIn('plan-a', html)
        self.assertNotIn('plan-b', html)
        self.assertNotIn('private-password-hash', html)
        self.assertEqual(self.client.get('/admin/users/9999/orders').status_code, 404)
        self.assertEqual(self.client.get('/admin?page=0').status_code, 400)
        self.assertEqual(self.client.get(f'/admin/users/{self.user_id}/orders?page=bad').status_code, 400)

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


if __name__ == '__main__':
    unittest.main()
