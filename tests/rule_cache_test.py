import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from subscription import (RULE_CACHE_RETRY, RULE_CACHE_TTL, SubscriptionError,
                          _rule_cache_retry, build_clash, build_subscription, cached_rule_config)


INI_URL = 'https://config.example/config.ini'
RULE_URL = 'https://rules.example/list'
INI = ('custom_proxy_group=Select`select`[]DIRECT`.*\n'
       f'ruleset=Select,{RULE_URL}\n'
       'ruleset=Select,[]FINAL\n')
PRIMARY = 'proxies:\n  - {name: 香港 main, type: ss, server: example.com, port: 443}\n'


class RuleCacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name)
        (path / 'base.yaml').write_text('mixed-port: 7890\n', encoding='utf-8')
        self.cache = path / 'cache.json'
        environment = patch.dict(os.environ, {
            'CLASH_CONFIG': INI_URL, 'CLASH_BASE_CONFIG': str(path / 'base.yaml'),
        })
        environment.start()
        self.addCleanup(environment.stop)
        cache_path = patch('subscription.rule_cache_path', return_value=self.cache)
        cache_path.start()
        self.addCleanup(cache_path.stop)
        _rule_cache_retry.clear()
        self.addCleanup(_rule_cache_retry.clear)

    def fetch(self, url, agent):
        self.assertEqual(agent, 'clash-verge/v2.3.1')
        return {INI_URL: INI, RULE_URL: 'DOMAIN,example.com\n'}[url]

    def test_initial_cache_reuse_and_expiry(self):
        with patch('subscription.fetch_subscription', side_effect=self.fetch) as fetch, \
                patch('subscription.time.time', return_value=1000) as clock:
            first = build_clash(PRIMARY, [])
            self.assertIn('DOMAIN,example.com,Select', first)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(first, build_clash(PRIMARY, []))
            self.assertEqual(fetch.call_count, 2)
            clock.return_value += RULE_CACHE_TTL
            build_clash(PRIMARY, [])
            self.assertEqual(fetch.call_count, 4)

    def test_stale_cache_fallback_and_retry_delay(self):
        with patch('subscription.fetch_subscription', side_effect=self.fetch), \
                patch('subscription.time.time', return_value=1000):
            cached_rule_config()
        original = self.cache.read_bytes()
        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('offline')) as fetch, \
                patch('subscription.time.time', return_value=1000 + RULE_CACHE_TTL) as clock:
            with self.assertLogs('subscription', level='WARNING'):
                self.assertIn('DOMAIN,example.com,Select', build_clash(PRIMARY, []))
            self.assertEqual(fetch.call_count, 1)
            build_clash(PRIMARY, [])
            self.assertEqual(fetch.call_count, 1)
            clock.return_value += RULE_CACHE_RETRY
            with self.assertLogs('subscription', level='WARNING'):
                build_clash(PRIMARY, [])
            self.assertEqual(fetch.call_count, 2)
            with self.assertRaises(SubscriptionError):
                cached_rule_config(force=True)
            self.assertEqual(original, self.cache.read_bytes())

    def test_force_refresh_is_atomic_and_validated(self):
        with patch('subscription.fetch_subscription', side_effect=self.fetch):
            cached_rule_config()
        original = self.cache.read_bytes()
        with patch('subscription.fetch_subscription', side_effect=[INI, 'INVALID']):
            with self.assertRaises(SubscriptionError):
                cached_rule_config(force=True)
        self.assertEqual(original, self.cache.read_bytes())
        invalid_ini = INI.replace('`.*', '`[')
        with patch('subscription.fetch_subscription', side_effect=[invalid_ini, 'DOMAIN,example.com']):
            with self.assertRaises(SubscriptionError):
                cached_rule_config(force=True)
        self.assertEqual(original, self.cache.read_bytes())
        with patch('subscription.fetch_subscription', side_effect=[INI, 'DOMAIN,updated.example']):
            cached_rule_config(force=True)
        self.assertEqual(json.loads(self.cache.read_text(encoding='utf-8'))['rules'][RULE_URL],
                         'DOMAIN,updated.example')

    def test_incomplete_cache_is_refetched(self):
        with patch('subscription.fetch_subscription', side_effect=self.fetch):
            cached_rule_config()
        data = json.loads(self.cache.read_text(encoding='utf-8'))
        data['rules'] = {}
        self.cache.write_text(json.dumps(data), encoding='utf-8')
        with patch('subscription.fetch_subscription', side_effect=self.fetch) as fetch, \
                self.assertLogs('subscription', level='WARNING'):
            self.assertIn('DOMAIN,example.com,Select', build_clash(PRIMARY, []))
            self.assertEqual(fetch.call_count, 2)

    def test_missing_cache_fails_and_changed_source_never_uses_old_cache(self):
        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('offline')):
            with self.assertRaises(SubscriptionError):
                cached_rule_config()
        with patch('subscription.fetch_subscription', side_effect=self.fetch):
            cached_rule_config()
        with patch.dict(os.environ, {'CLASH_CONFIG': 'https://other.example/config.ini'}), \
                patch('subscription.fetch_subscription', side_effect=SubscriptionError('offline')):
            with self.assertRaises(SubscriptionError):
                cached_rule_config()

    def test_concurrent_requests_share_initial_refresh(self):
        with patch('subscription.fetch_subscription', side_effect=self.fetch) as fetch:
            errors = []

            def read_cache():
                try:
                    cached_rule_config()
                except SubscriptionError as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=read_cache) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(fetch.call_count, 2)

    def test_nodes_still_refresh_on_every_subscription(self):
        panel = Mock()
        panel.get_client.return_value = {
            'client': {'email': 'alice@example.com', 'comment': 'alice', 'subId': 'id',
                       'enable': True, 'expiryTime': 0, 'totalGB': 100},
            'usedTraffic': 1,
        }
        panel.get_client_traffic.return_value = {'up': 1, 'down': 2}
        panel_url = 'https://panel.example/clash/id'

        def fetch(url, agent):
            if url == panel_url:
                return PRIMARY
            return self.fetch(url, agent)

        with patch.dict(os.environ, {'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
                                     'EXTRA_SUB_URLS': '[]'}), \
                patch('subscription.fetch_subscription', side_effect=fetch) as network:
            for _ in range(2):
                result = build_subscription(panel, 'alice@example.com', 'alice', 'clash')
                self.assertIn('DOMAIN,example.com,Select', result.content)
            self.assertEqual([call.args[0] for call in network.call_args_list],
                             [panel_url, INI_URL, RULE_URL, panel_url])


if __name__ == '__main__':
    unittest.main()
