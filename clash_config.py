import re
from pathlib import Path


INCLUDE_PATTERN = re.compile(
    r'日本(?!\s*3\b).*|日本\s*1\s*\[\s*IPv6\s*\]|日本\s*2\s*\[\s*IPv6\s*\]|'
    r'香港|andy|新加坡(?!\s*3\b).*|新加坡\s*1\s*\[\s*IPv6\s*\]|'
    r'新加坡\s*2\s*\[\s*IPv6\s*\]|新加坡.*推荐|美国(?!.*海外).*|台湾(?!.*海外).*'
)


class ClashConfigError(ValueError):
    pass


def parse_config(text):
    result = {'rename': [], 'emoji': [], 'groups': [], 'rulesets': []}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((';', '#', '[')):
            continue
        key, separator, value = line.partition('=')
        if not separator:
            continue
        if key == 'rename_node':
            pattern, separator, replacement = value.partition('@')
            if not separator:
                raise ClashConfigError('重命名规则格式无效')
            result['rename'].append((pattern, replacement))
        elif key == 'emoji':
            pattern, separator, emoji = value.partition(',')
            if not separator or not emoji:
                raise ClashConfigError('节点图标规则格式无效')
            result['emoji'].append((pattern.strip(), emoji.strip()))
        elif key == 'custom_proxy_group':
            parts = value.split('`')
            if len(parts) < 3 or not parts[0] or parts[1] not in ('select', 'url-test', 'fallback', 'load-balance'):
                raise ClashConfigError('策略组配置格式无效')
            result['groups'].append(parts)
        elif key == 'ruleset':
            group, separator, spec = value.partition(',')
            if not separator or not group or not spec:
                raise ClashConfigError('规则集配置格式无效')
            result['rulesets'].append((group.strip(), spec.strip()))
    if not result['groups'] or not result['rulesets']:
        raise ClashConfigError('INI 配置必须包含策略组和规则集')
    names = [group[0] for group in result['groups']]
    if len(set(names)) != len(names):
        raise ClashConfigError('策略组名称重复')
    return result


def rename_proxy(name, config):
    try:
        for pattern, replacement in config['rename']:
            replacement = re.sub(r'\$(\d+)', r'\\g<\1>', replacement)
            name = re.sub(pattern, replacement, name)
        for pattern, emoji in config['emoji']:
            if re.search(pattern, name) and not name.startswith(emoji):
                name = f'{emoji} {name}'
                break
    except re.error as exc:
        raise ClashConfigError('节点重命名或图标正则表达式无效') from exc
    if not name.strip():
        raise ClashConfigError('重命名后的节点名称为空')
    return name


def build_groups(config, names):
    groups = []
    for parts in config['groups']:
        name, kind, *items = parts
        members, health_url, interval, tolerance = [], None, None, None
        for item in items:
            if item.startswith('[]'):
                members.append(item[2:])
            elif item.startswith(('https://', 'http://')):
                health_url = item
            elif health_url is not None:
                fields = item.split(',')
                try:
                    interval = int(fields[0])
                    if len(fields) > 2 and fields[2]:
                        tolerance = int(fields[2])
                except ValueError as exc:
                    raise ClashConfigError('策略组测速参数无效') from exc
            else:
                try:
                    members.extend(node for node in names if re.search(item, node))
                except re.error as exc:
                    raise ClashConfigError('策略组节点匹配表达式无效') from exc
        members = list(dict.fromkeys(members))
        def rank(member):
            if member == '♻️ 自动选择':
                return -1
            if 'ai' in name.lower() and '节点选择' in member:
                return 0
            if 'ai' in name.lower() and 'vultr' in member.lower():
                return 1
            if '狮城' in member:
                return 2
            if '日本' in member:
                return 3
            if '美国' in member:
                return 4
            return 99
        members.sort(key=rank)
        if not members:
            raise ClashConfigError('策略组没有可用节点或选项')
        group = {'name': name, 'type': kind, 'proxies': members}
        if kind != 'select':
            if not health_url or interval is None or interval <= 0:
                raise ClashConfigError('自动策略组缺少测速地址或间隔')
            group.update(url=health_url, interval=interval)
            if tolerance is not None and kind == 'url-test':
                group['tolerance'] = tolerance
        groups.append(group)
    group_names = [group['name'] for group in groups]
    if len(set(group_names)) != len(group_names) or set(group_names) & set(names):
        raise ClashConfigError('策略组或节点名称重复')
    available = set(names) | set(group_names) | {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS'}
    if any(member not in available for group in groups for member in group['proxies']):
        raise ClashConfigError('策略组引用了不存在的节点或策略组')
    return groups


def build_rules(config, fetch):
    def priority(item):
        group, spec = item
        if spec.startswith('[]'):
            return 2
        return 0 if spec.startswith('https://raw.githubusercontent.com/suncongch/') else 1

    rules = []
    available = {parts[0] for parts in config['groups']} | {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS'}
    for group, spec in sorted(config['rulesets'], key=priority):
        if group not in available:
            raise ClashConfigError(f'规则集引用了不存在的策略组：{group}')
        if spec == '[]FINAL':
            rules.append(f'MATCH,{group}')
        elif spec.startswith('[]GEOIP,'):
            rules.append(f'GEOIP,{spec[len("[]GEOIP,"):].strip()},{group}')
        elif spec.startswith('[]'):
            raise ClashConfigError('不支持的内置规则集')
        else:
            for line in fetch(spec).splitlines():
                line = line.strip()
                if not line or line.startswith(('#', ';')):
                    continue
                parts = [part.strip() for part in line.split(',')]
                if parts[0].upper() in {'URL-REGEX', 'URL', 'USER-AGENT'}:
                    continue
                if len(parts) < 2:
                    raise ClashConfigError('远程规则集格式无效')
                if 'no-resolve' in parts:
                    parts.remove('no-resolve')
                    parts.extend((group, 'no-resolve'))
                else:
                    parts.append(group)
                rules.append(','.join(parts))
    if not rules:
        raise ClashConfigError('INI 配置没有可用规则')
    return rules


def load_config(location, fetch):
    if not location:
        raise ClashConfigError('未配置 CLASH_CONFIG')
    if location.startswith(('https://', 'http://')):
        return fetch(location)
    path = Path(location).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    try:
        return path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        raise ClashConfigError('无法读取 Clash INI 配置文件') from exc
