import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from subscription import SubscriptionError, build_clash, build_subscription, clash_base_config, extra_urls, parse_links, public_url, safe_url
from clash_config import load_config


PRIMARY = '''
mixed-port: 7890
proxies:
  - {name: 香港 main, type: vmess, server: node.example, port: 443, uuid: abc}
proxy-groups:
  - {name: Select, type: select, proxies: [香港 main]}
rules: ["MATCH,Select"]
'''
EXTRA = '''
proxies:
  - {name: 香港 main, type: ss, server: extra.example, port: 443, cipher: aes-128-gcm, password: test}
'''

INI = '''custom_proxy_group=Select`select`[]DIRECT`.*
ruleset=Select,[]FINAL
'''

class FakePanel:
    def get_client(self, email):
        return {'client': {'email': email, 'comment': 'alice', 'subId': 'client-id', 'enable': True,
                           'expiryTime': 0, 'totalGB': 100}, 'usedTraffic': 10}

    def get_client_traffic(self, email):
        return {'email': email, 'up': 3, 'down': 7}


class SubscriptionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name) / 'base.yaml'
        base.write_text('mixed-port: 7890\nmode: rule\n', encoding='utf-8')
        self.env = patch.dict(os.environ, {
            'XUI_SUB_BASE_URL': 'https://panel.example/sub',
            'XUI_CLASH_BASE_URL': 'https://panel.example/clash',
            'EXTRA_SUB_URLS': '["https://other.example/sub"]',
            'CLASH_CONFIG': 'test-config.ini',
            'CLASH_BASE_CONFIG': str(base),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        config_patch = patch('subscription.load_config', side_effect=lambda path, fetch:
                             INI if path == 'test-config.ini' else load_config(path, fetch))
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_public_url_allows_http_without_weakening_source_validation(self):
        for value in ('http://192.168.2.17:8000/', 'http://example.test', 'https://example.test'):
            with self.subTest(value=value), patch.dict(os.environ, {'PUBLIC_BASE_URL': value}):
                self.assertEqual(public_url(), value.rstrip('/'))
        for value in ('', 'ftp://example.test', 'http://example.test/?x=1',
                      'http://user:pass@example.test', 'http://example.test/#fragment'):
            with self.subTest(value=value), patch.dict(os.environ, {'PUBLIC_BASE_URL': value}):
                with self.assertRaises(SubscriptionError):
                    public_url()
        with self.assertRaises(SubscriptionError):
            safe_url('http://192.168.2.17:8000/sub')

    def test_clash_merges_proxies_and_preserves_rules(self):
        with patch('subscription.fetch_subscription', side_effect=[PRIMARY, EXTRA]) as fetch:
            config = yaml.safe_load(build_subscription(FakePanel(), 'alice@example.com', 'alice', 'clash').content)
        self.assertEqual([proxy['name'] for proxy in config['proxies']], ['🇭🇰 香港 main', '🇭🇰 香港 main (2)'])
        self.assertEqual(config['proxy-groups'][0]['proxies'], ['DIRECT', '🇭🇰 香港 main', '🇭🇰 香港 main (2)'])
        self.assertEqual(config['rules'], ['MATCH,Select'])
        self.assertEqual(fetch.call_args_list[0].args, ('https://panel.example/clash/client-id', 'clash-verge/v2.3.1'))
        self.assertEqual(fetch.call_args_list[1].args, ('https://other.example/sub', 'clash-verge/v2.3.1'))

    def test_base_file_controls_settings_and_precedes_generated_sections(self):
        primary = PRIMARY + '\nport: 1234\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'base.yaml'
            path.write_text('mixed-port: 7777\ndns:\n  enable: true\n', encoding='utf-8')
            with patch.dict(os.environ, {'CLASH_BASE_CONFIG': str(path)}):
                result = build_clash(primary, [EXTRA])
                parsed = yaml.safe_load(result)
                self.assertEqual(list(parsed), ['mixed-port', 'dns', 'proxies', 'proxy-groups', 'rules'])
                self.assertEqual(parsed['mixed-port'], 7777)
                self.assertTrue(parsed['dns']['enable'])
                self.assertNotIn('port', parsed)
                self.assertEqual(len(parsed['proxies']), 2)
                self.assertEqual(parsed['rules'], ['MATCH,Select'])
                path.write_text('mode: global\n', encoding='utf-8')
                updated = yaml.safe_load(build_clash(primary, []))
                self.assertEqual(list(updated), ['mode', 'proxies', 'proxy-groups', 'rules'])
                self.assertEqual(updated['mode'], 'global')

    def test_base_file_rejects_bad_sources_and_generated_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'base.yaml'
            for value in ('', 'https://example.com/base.yaml', str(path)):
                with self.subTest(path=value), patch.dict(os.environ, {'CLASH_BASE_CONFIG': value}):
                    with self.assertRaises(SubscriptionError):
                        clash_base_config()
            for text in ('[invalid', '- list', 'null', 'proxies: []', 'proxy-groups: []', 'rules: []'):
                path.write_text(text, encoding='utf-8')
                with self.subTest(text=text), patch.dict(os.environ, {'CLASH_BASE_CONFIG': str(path)}):
                    with self.assertRaises(SubscriptionError):
                        clash_base_config()

    def test_shadowrocket_merges_base64_and_plain_links(self):
        primary = base64.b64encode(b'vmess://first').decode()
        with patch('subscription.fetch_subscription', side_effect=[primary, 'vless://second']):
            result = build_subscription(FakePanel(), 'alice@example.com', 'alice', 'shadowrocket')
        self.assertEqual(base64.b64decode(result.content).decode(), 'vmess://first\nvless://second')

    def test_invalid_or_unavailable_sources_fail_closed(self):
        for value in ('not yaml', 'proxies: nope', 'proxies: [null]'):
            with self.assertRaises(SubscriptionError):
                build_clash(value, [])
        for value in ('', 'bad value', 'SGVsbG8='):
            with self.assertRaises(SubscriptionError):
                parse_links(value)
        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('unavailable')):
            with self.assertRaises(SubscriptionError):
                build_subscription(FakePanel(), 'alice@example.com', 'alice', 'clash')

    def test_disabled_expired_or_depleted_client_cannot_access_external_sources(self):
        panel = FakePanel()
        payload = panel.get_client('alice@example.com')
        for key, value in (('enable', False), ('expiryTime', 1), ('totalGB', 10)):
            changed = {'client': dict(payload['client']), 'usedTraffic': payload['usedTraffic']}
            changed['client'][key] = value
            with patch.object(panel, 'get_client', return_value=changed), \
                    patch('subscription.fetch_subscription') as fetch:
                with self.assertRaises(SubscriptionError):
                    build_subscription(panel, 'alice@example.com', 'alice', 'clash')
                fetch.assert_not_called()

    def test_client_remark_must_match_website_username(self):
        with patch('subscription.fetch_subscription') as fetch:
            with self.assertRaises(SubscriptionError):
                build_subscription(FakePanel(), 'alice@example.com', 'bob', 'clash')
            fetch.assert_not_called()

    def test_clash_returns_current_traffic_and_rejects_depleted_traffic(self):
        panel = FakePanel()
        with patch.dict(os.environ, {'EXTRA_SUB_URLS': ''}), \
                patch('subscription.fetch_subscription', return_value=PRIMARY):
            result = build_subscription(panel, 'alice@example.com', 'alice', 'clash')
        self.assertEqual((result.upload, result.download, result.total), (3, 7, 100))
        with patch.object(panel, 'get_client_traffic', return_value={'up': 40, 'down': 60}), \
                patch('subscription.fetch_subscription') as fetch:
            with self.assertRaisesRegex(SubscriptionError, '流量已用完'):
                build_subscription(panel, 'alice@example.com', 'alice', 'clash')
            fetch.assert_not_called()

    def test_missing_external_sources_uses_only_panel_subscription(self):
        for value in ('', '   ', '[]', '["", "  "]'):
            with self.subTest(value=value), patch.dict(os.environ, {'EXTRA_SUB_URLS': value}), \
                    patch('subscription.fetch_subscription', side_effect=[PRIMARY, 'vmess://first']) as fetch:
                config = yaml.safe_load(build_subscription(FakePanel(), 'alice@example.com', 'alice', 'clash').content)
                self.assertEqual([proxy['name'] for proxy in config['proxies']], ['🇭🇰 香港 main'])
                result = build_subscription(FakePanel(), 'alice@example.com', 'alice', 'shadowrocket')
                self.assertEqual(base64.b64decode(result.content).decode(), 'vmess://first')
                self.assertEqual([call.args[0] for call in fetch.call_args_list],
                                 ['https://panel.example/clash/client-id',
                                  'https://panel.example/sub/client-id'])

    def test_missing_panel_url_is_error(self):
        with patch.dict(os.environ, {'XUI_CLASH_BASE_URL': ''}), \
                patch('subscription.fetch_subscription') as fetch:
            with self.assertRaisesRegex(SubscriptionError, 'XUI_CLASH_BASE_URL'):
                build_subscription(FakePanel(), 'alice@example.com', 'alice', 'clash')
            fetch.assert_not_called()

    def test_blank_entries_are_ignored_and_invalid_config_still_fails(self):
        with patch.dict(os.environ, {'EXTRA_SUB_URLS': '["", " https://first.example/sub ", " "]'}):
            self.assertEqual(extra_urls(), ['https://first.example/sub'])
        with patch.dict(os.environ, {'EXTRA_SUB_URLS': '[https://a.example/x?t=1, https://b.example/y]'}):
            self.assertEqual(extra_urls(), ['https://a.example/x?t=1', 'https://b.example/y'])
        for value in ('invalid', '["not-a-url"]', '[null]'):
            with self.subTest(value=value), patch.dict(os.environ, {'EXTRA_SUB_URLS': value}):
                with self.assertRaises(SubscriptionError):
                    extra_urls()

    def test_sample_filter_rename_groups_and_online_rules(self):
        primary = '''
proxies:
  - {name: "新加坡 1", type: ss, server: sg.example, port: 443}
  - {name: "日本 3", type: ss, server: jp.example, port: 443}
  - {name: "香港 2", type: ss, server: hk.example, port: 443}
  - {name: "无关节点", type: ss, server: other.example, port: 443}
'''
        ini = r'''custom_proxy_group=Select`select`[]DIRECT`.*
custom_proxy_group=Auto`url-test`(狮城|香港)`https://example.com/check`300,,50
ruleset=Select,https://example.com/rules
ruleset=Select,[]GEOIP,CN
ruleset=Select,[]FINAL
rename_node=香港 (\d+)@香港-$1
'''
        with patch('subscription.load_config', side_effect=lambda path, fetch:
                   ini if path == 'test-config.ini' else load_config(path, fetch)), \
                patch('subscription.fetch_subscription', return_value=(
                    'DOMAIN,example.org\nIP-CIDR,1.2.3.0/24,no-resolve\n'
                    'URL-REGEX,^https://example.org\n')) as fetch:
            config = yaml.safe_load(build_clash(primary, []))
        self.assertEqual([p['name'] for p in config['proxies']], ['🇸🇬 狮城 1', '🇭🇰 香港-2'])
        self.assertEqual(config['proxy-groups'][1], {
            'name': 'Auto', 'type': 'url-test', 'proxies': ['🇸🇬 狮城 1', '🇭🇰 香港-2'],
            'url': 'https://example.com/check', 'interval': 300, 'tolerance': 50,
        })
        self.assertEqual(config['rules'], ['DOMAIN,example.org,Select',
                         'IP-CIDR,1.2.3.0/24,Select,no-resolve', 'GEOIP,CN,Select', 'MATCH,Select'])
        fetch.assert_called_once_with('https://example.com/rules', 'clash-verge/v2.3.1')

    def test_invalid_ini_and_filtered_out_nodes_fail(self):
        with patch('subscription.load_config', return_value='invalid'):
            with self.assertRaisesRegex(SubscriptionError, '策略组和规则集'):
                build_clash(PRIMARY, [])
        with self.assertRaisesRegex(SubscriptionError, '没有节点符合'):
            build_clash('proxies: [{name: 未知, type: ss}]', [])
        with patch('subscription.fetch_subscription', side_effect=SubscriptionError('unavailable')), \
                patch('subscription.load_config', side_effect=lambda path, fetch:
                      'custom_proxy_group=Select`select`.*\nruleset=Select,https://example.com/list'
                      if path == 'test-config.ini' else load_config(path, fetch)):
            with self.assertRaisesRegex(SubscriptionError, 'unavailable'):
                build_clash(PRIMARY, [])


if __name__ == '__main__':
    unittest.main()
