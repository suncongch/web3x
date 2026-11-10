import gzip
import unittest
from unittest.mock import patch

from flask import Flask

from app import AppSetting, SubscriptionToken, User, app, db
from subscription import SubscriptionResult


class SubscriptionResponseTest(unittest.TestCase):
    def setUp(self):
        self.test_app = Flask(__name__)
        self.test_app.config.update(
            TESTING=True,
            SECRET_KEY='test-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        )
        db.init_app(self.test_app)
        for rule in app.url_map.iter_rules():
            if rule.endpoint != 'static':
                self.test_app.add_url_rule(
                    rule.rule,
                    endpoint=rule.endpoint,
                    view_func=app.view_functions[rule.endpoint],
                    methods=rule.methods - {'HEAD', 'OPTIONS'},
                )
        self.context = self.test_app.app_context()
        self.context.push()
        db.create_all()
        user = User(username='alice', email='alice@example.com', password='test-hash')
        db.session.add(user)
        db.session.flush()
        self.user_id = user.id
        db.session.add(SubscriptionToken(user_id=user.id, token='test-sub-token'))
        db.session.commit()
        self.client = self.test_app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_subscription_responses_negotiate_gzip(self):
        body = 'proxies:\n  - name: 香港节点\n' + '# test\n' * 1000
        path = '/subscription/clash/test-sub-token'
        with patch('app.build_subscription',
                   return_value=SubscriptionResult(body, 0, 0, 0, 0)) as build_subscription, \
                patch('app.ThreeXUI'):
            compressed = self.client.get(path, headers={'Accept-Encoding': 'gzip'})
            self.assertEqual(compressed.headers['Content-Encoding'], 'gzip')
            self.assertEqual(gzip.decompress(compressed.data), body.encode('utf-8'))
            self.assertEqual(compressed.headers['Vary'], 'Accept-Encoding')

            uncompressed = self.client.get(path, headers={'Accept-Encoding': 'gzip;q=0'})
            self.assertNotIn('Content-Encoding', uncompressed.headers)
            self.assertEqual(uncompressed.data, body.encode('utf-8'))
            self.assertEqual(uncompressed.headers['Vary'], 'Accept-Encoding')
            self.assertEqual(build_subscription.call_args.kwargs['include_external_nodes'], False)
            self.assertIn('日本', build_subscription.call_args.kwargs['include_pattern'].pattern)

        user = db.session.get(User, self.user_id)
        user.can_use_external_nodes = True
        db.session.add(AppSetting(key='node_include_pattern', value='香港'))
        db.session.commit()
        with patch('app.build_subscription',
                   return_value=SubscriptionResult('vmess://node', 0, 0, 0, 0)) as build_subscription, \
                patch('app.ThreeXUI'):
            shadowrocket = self.client.get(
                '/subscription/shadowrocket/test-sub-token',
                headers={'Accept-Encoding': 'gzip'},
            )
        self.assertEqual(shadowrocket.headers['Content-Encoding'], 'gzip')
        self.assertEqual(gzip.decompress(shadowrocket.data), b'vmess://node')
        self.assertTrue(build_subscription.call_args.kwargs['include_external_nodes'])
        self.assertEqual(build_subscription.call_args.kwargs['include_pattern'].pattern, '香港')


if __name__ == '__main__':
    unittest.main()
