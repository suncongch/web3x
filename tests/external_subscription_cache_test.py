import base64
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from subscription import (EXTRA_SUB_CACHE_TTL, SubscriptionError,
                          _read_rule_cache, _write_rule_cache, build_subscription,
                          cached_extra_subscription)


CLASH_SOURCE = '''proxies:
  - {name: 香港节点, type: ss, server: node.example, port: 443, cipher: aes-128-gcm, password: secret}
proxy-groups:
  - {name: Select, type: select, proxies: [香港节点]}
rules: ["MATCH,Select"]
'''


class ExternalSubscriptionCacheTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache_path = Path(directory.name) / 'extra-cache.json'
        self.cache_patch = patch('subscription.extra_subscription_cache_path',
                                 return_value=self.cache_path)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_clash_cache_stores_only_nodes_and_reuses_fresh_data(self):
        with patch('subscription.fetch_subscription', return_value=CLASH_SOURCE) as fetch, \
                patch('subscription.time.time', return_value=1000):
            first = cached_extra_subscription('https://feed.example/sub', 'clash', 'clash-agent')
        stored = json.loads(self.cache_path.read_text(encoding='utf-8'))
        self.assertEqual(set(stored), {'updated', 'nodes'})
        self.assertEqual(len(stored['nodes']), 1)
        self.assertEqual(stored['nodes'][0]['name'], '香港节点')
        self.assertNotIn('proxy-groups', self.cache_path.read_text(encoding='utf-8'))
        self.assertNotIn('rules', self.cache_path.read_text(encoding='utf-8'))
        self.assertIn('\n  "nodes": [\n', self.cache_path.read_text(encoding='utf-8'))
        self.assertTrue(self.cache_path.read_text(encoding='utf-8').endswith('\n'))
        self.assertEqual(stat.S_IMODE(self.cache_path.stat().st_mode), 0o600)

        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('offline')) as fetch, \
                patch('subscription.time.time', return_value=1001):
            second = cached_extra_subscription('https://feed.example/sub', 'clash', 'clash-agent')
        self.assertEqual(first, second)
        fetch.assert_not_called()

    def test_expired_cache_is_used_when_refresh_fails(self):
        with patch('subscription.fetch_subscription', return_value=CLASH_SOURCE), \
                patch('subscription.time.time', return_value=1000):
            first = cached_extra_subscription('https://feed.example/sub', 'clash', 'clash-agent')

        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('offline')), \
                patch('subscription.time.time', return_value=1000 + EXTRA_SUB_CACHE_TTL), \
                self.assertLogs('subscription', level='WARNING') as logs:
            stale = cached_extra_subscription('https://feed.example/sub', 'clash', 'clash-agent')
        self.assertEqual(first, stale)
        self.assertIn('继续使用已有节点缓存', '\n'.join(logs.output))

    def test_shadowrocket_cache_stores_decoded_node_links(self):
        encoded = base64.b64encode(b'vmess://first\nvless://second').decode('ascii')
        with patch('subscription.fetch_subscription', return_value=encoded):
            links = cached_extra_subscription('https://feed.example/sub', 'shadowrocket', 'shadow-agent')
        stored = json.loads(self.cache_path.read_text(encoding='utf-8'))
        self.assertEqual(stored['nodes'], ['vmess://first', 'vless://second'])
        self.assertEqual(links, 'vmess://first\nvless://second')

    def test_refresh_failure_without_cache_is_reported(self):
        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('offline')):
            with self.assertRaisesRegex(SubscriptionError, 'offline'):
                cached_extra_subscription('https://feed.example/sub', 'clash', 'clash-agent')

    def test_rule_cache_is_pretty_printed(self):
        path = self.cache_path
        config = ('custom_proxy_group=Select`select`[]DIRECT`.*\n'
                  'ruleset=Select,https://rules.example/list\n'
                  'ruleset=Select,[]FINAL\n')
        rules = {'https://rules.example/list': 'DOMAIN,example.com\n'}
        cache = {'identity': 'test', 'updated': 1000, 'config': config, 'rules': rules}
        _write_rule_cache(path, cache)
        formatted = path.read_text(encoding='utf-8')
        self.assertIn('\n  "config": ', formatted)
        self.assertTrue(formatted.endswith('\n'))
        stored = json.loads(formatted)
        self.assertEqual(stored['config'], config.split('\n'))
        self.assertEqual(stored['rules'], {
            'https://rules.example/list': ['DOMAIN,example.com', ''],
        })
        self.assertEqual(_read_rule_cache(path, 'test')['config'], config)
        self.assertEqual(_read_rule_cache(path, 'test')['rules'], rules)

        path.write_text(json.dumps(cache), encoding='utf-8')
        self.assertEqual(_read_rule_cache(path, 'test')['config'], config)
        self.assertEqual(_read_rule_cache(path, 'test')['rules'], rules)

    def test_build_subscription_caches_only_extra_source(self):
        panel = Mock()
        panel.get_client.return_value = {
            'client': {'email': 'alice@example.com', 'comment': 'alice', 'subId': 'client-id',
                       'enable': True, 'expiryTime': 0, 'totalGB': 100},
            'usedTraffic': 1,
        }
        primary_url = 'https://panel.example/sub/client-id'
        extra_url = 'https://feed.example/sub'
        extra_content = base64.b64encode(b'vless://extra').decode('ascii')

        def fetch(url, _agent):
            return 'vmess://primary' if url == primary_url else extra_content

        with patch.dict(os.environ, {
            'XUI_SUB_BASE_URL': 'https://panel.example/sub',
            'EXTRA_SUB_URLS': json.dumps([extra_url]),
        }), patch('subscription.extra_subscription_cache_path',
                  return_value=self.cache_path), \
                patch('subscription.fetch_subscription', side_effect=fetch) as network:
            results = [
                build_subscription(panel, 'alice@example.com', 'alice', 'shadowrocket')
                for _ in range(2)
            ]

        self.assertEqual(
            [base64.b64decode(result.content).decode() for result in results],
            ['vmess://primary\nvless://extra'] * 2,
        )
        self.assertEqual([call.args[0] for call in network.call_args_list],
                         [primary_url, extra_url, primary_url])
        self.assertEqual(json.loads(self.cache_path.read_text(encoding='utf-8'))['nodes'],
                         ['vless://extra'])


if __name__ == '__main__':
    unittest.main()
