import requests
import yaml
import re
import json
import base64
from urllib.parse import quote, urlencode
from ini import *
from pathlib import Path

includeCondition = (
    r'日本(?!\s*3\b).*|'
    r'日本\s*1\s*\[\s*IPv6\s*\]|'
    r'日本\s*2\s*\[\s*IPv6\s*\]|'
    r'香港|'
    r'andy|'
    r'新加坡(?!\s*3\b).*|'
    r'新加坡\s*1\s*\[\s*IPv6\s*\]|'
    r'新加坡\s*2\s*\[\s*IPv6\s*\]|'
    r'新加坡.*推荐|'
    r'美国(?!.*海外).*|'
    r'台湾(?!.*海外).*'
)
subscribe_url = "https://xhtoken.huyun.nl/api/xiongtoken/1002261321f54fe532237e5a59b84361"
config_url = "http://cloud.andysun.cool:9001/ini"

def fetch_config(url):
    if not url:
        return {}
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return yaml.safe_load(r.text)

def fetch_subscribe(url: str) -> str:
    headers = {
        "User-Agent": "clash-verge/v2.3.1",
        "Accept": "*/*",
        "Accept-Encoding": "identity"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    raw = resp.text 
    return resp.text

def filter_proxies(proxies: list[dict], include_regex: str) -> list[dict]:
    pattern = re.compile(include_regex)

    result = []
    for proxy in proxies:
        name = proxy.get("name", "")
        if pattern.search(name):
            result.append(proxy)

    return result

def build_clash_yaml(base: dict, proxies: list[dict]) -> str:
    output = {
        "mixed-port": 7890,
        "allow-lan": True,
        "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "PROXY",
                "type": "select",
                "proxies": [p["name"] for p in proxies]
            }
        ],
        "rules": [
            "MATCH,PROXY"
        ]
    }

    return yaml.dump(
        output,
        allow_unicode=True,
        sort_keys=False
    )

def merge_config(base, extra):
    """
    base: 你生成的 Clash 配置（含 proxies）
    extra: config.yaml
    """
    if not extra:
        return base

    merged = extra.copy()

    # proxies 永远用你自己的
    merged["proxies"] = base.get("proxies", [])

    # proxy-groups / rules / providers 等可以从 config 来
    for k in ("proxy-groups", "rules", "rule-providers", "dns"):
        if k in base:
            merged[k] = base[k]
        elif k not in merged:
            merged[k] = []

    return merged

def parse_clash_yaml(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Invalid clash yaml")
    data.setdefault("proxies", [])
    return data


def order_rulesets_by_priority(rulesets: list[dict]) -> list[dict]:
    """Keep ACL4SSR as the base ruleset source, with suncongch overrides first.

    Clash applies the first matching rule.  Moving suncongch rulesets ahead of
    the base rulesets makes their entries win whenever both sources match.
    GEOIP and FINAL rules retain their configured position at the end.
    """
    suncongch_rulesets = []
    base_rulesets = []
    terminal_rulesets = []

    for ruleset in rulesets:
        if ruleset.get("type") in {"GEOIP", "FINAL"}:
            terminal_rulesets.append(ruleset)
        elif (ruleset.get("url") or "").startswith(
            "https://raw.githubusercontent.com/suncongch/"
        ):
            suncongch_rulesets.append(ruleset)
        else:
            base_rulesets.append(ruleset)

    return suncongch_rulesets + base_rulesets + terminal_rulesets

def sub():
    raw = fetch_subscribe(subscribe_url)
    data = parse_clash_yaml(raw)

    proxies = data.get("proxies", [])

    if includeCondition:
        proxies = filter_proxies(proxies, includeCondition)

    yaml_text = build_clash_yaml(data, proxies)

    extra = fetch_config(config_url)

    final = merge_config(yaml_text, extra)

    return yaml_text


def _link_host(server: str) -> str:
    return f"[{server}]" if ":" in server and not server.startswith("[") else server


def _clash_stream_params(p: dict) -> dict | None:
    """Clash 传输/加密字段 -> 分享链接 query 参数；不支持的传输返回 None。"""
    network = p.get("network", "tcp")
    params = {}

    ws = p.get("ws-opts") or {}
    if network == "ws" and ws.get("v2ray-http-upgrade"):
        network = "httpupgrade"
    params["type"] = network

    if network in ("ws", "httpupgrade"):
        headers = ws.get("headers") or {}
        params["path"] = ws.get("path", "/")
        host = headers.get("Host") or headers.get("host")
        if host:
            params["host"] = host
    elif network == "grpc":
        params["serviceName"] = (p.get("grpc-opts") or {}).get("grpc-service-name", "")
    elif network != "tcp":
        return None

    if p.get("tls"):
        params["sni"] = p.get("servername") or p.get("sni") or p.get("server")
        params["fp"] = p.get("client-fingerprint") or "chrome"
        if p.get("reality-opts"):
            ro = p["reality-opts"]
            params["security"] = "reality"
            params["pbk"] = ro.get("public-key", "")
            params["sid"] = ro.get("short-id", "")
        else:
            params["security"] = "tls"
            if p.get("alpn"):
                params["alpn"] = ",".join(p["alpn"])
    else:
        params["security"] = "none"
    return params


def clash_proxy_to_link(p: dict) -> str | None:
    """Clash 节点 -> 分享链接（3x-ui 出站订阅格式）；不支持的返回 None。"""
    ptype = p.get("type")
    try:
        server, port = _link_host(p["server"]), int(p["port"])
        name = quote(p.get("name", "node"), safe="")

        if ptype == "vmess":
            params = _clash_stream_params(p)
            if params is None:
                return None
            obj = {
                "v": "2", "ps": p.get("name", "node"), "add": p["server"],
                "port": str(port), "id": p["uuid"],
                "aid": str(p.get("alterId", 0)), "scy": p.get("cipher", "auto"),
                "net": params["type"], "type": "none",
                "host": params.get("host", ""),
                "path": params.get("path", params.get("serviceName", "")),
                "tls": "tls" if params["security"] == "tls" else "",
                "sni": params.get("sni", ""), "fp": params.get("fp", ""),
                "alpn": params.get("alpn", ""),
            }
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            return "vmess://" + base64.b64encode(raw).decode()

        if ptype == "ss":
            userinfo = base64.urlsafe_b64encode(
                f"{p['cipher']}:{p['password']}".encode()
            ).decode().rstrip("=")
            return f"ss://{userinfo}@{server}:{port}#{name}"

        if ptype == "hysteria2":
            params = {"sni": p.get("sni") or p.get("servername") or p.get("server")}
            if p.get("alpn"):
                params["alpn"] = ",".join(p["alpn"])
            if p.get("obfs"):
                params["obfs"] = p["obfs"]
                params["obfs-password"] = p.get("obfs-password", "")
            query = urlencode(params)
            return (f"hysteria2://{quote(str(p['password']), safe='')}"
                    f"@{server}:{port}?{query}#{name}")

        params = _clash_stream_params(p)
        if params is None:
            return None
        if ptype == "vless":
            params["encryption"] = "none"
            if p.get("flow"):
                params["flow"] = p["flow"]
            userinfo = p["uuid"]
        elif ptype == "trojan":
            userinfo = quote(str(p["password"]), safe="")
        else:
            return None
        return f"{ptype}://{userinfo}@{server}:{port}?{urlencode(params)}#{name}"
    except (KeyError, TypeError, ValueError):
        return None


def build_3xui_outbound_subscription(proxies: list[dict]) -> str:
    """节点列表 -> 3x-ui 出站订阅内容：分享链接逐行排列后整体 Base64。"""
    links = [link for link in map(clash_proxy_to_link, proxies) if link]
    return base64.b64encode("\n".join(links).encode("utf-8")).decode()


AUTO_GROUP_NAME = "♻️ 自动选择"
AUTO_GROUP_REGIONS = ("狮城", "日本", "香港")


def add_auto_group(proxy_groups: list[dict], proxies: list[dict]) -> None:
    """Add a fallback group ordered 狮城 > 日本 > 香港 (first alive node wins)."""
    members = []
    for region in AUTO_GROUP_REGIONS:
        members.extend(p["name"] for p in proxies if region in p["name"])
    members = list(dict.fromkeys(members))
    if not members:
        return

    proxy_groups.insert(0, {
        "name": AUTO_GROUP_NAME,
        "type": "fallback",
        "proxies": members,
        "url": "https://cp.cloudflare.com/generate_204",
        "interval": 300,
    })
    for g in proxy_groups[1:]:
        if g["name"].endswith("节点选择"):
            g["proxies"].insert(0, AUTO_GROUP_NAME)


def build_from_config(config_url: str, sub_urls: list[str], auto_group: bool = False) -> dict:
    # 1️⃣ 拉 ACL4SSR config
    cfg_text = requests.get(config_url, timeout=15).text
    cfg = parse_acl4ssr_config(cfg_text)

    # 2️⃣ 拉取所有订阅并整合 proxies
    all_proxies = []
    for url in sub_urls:
        raw = fetch_subscribe(url)
        data = parse_clash_yaml(raw)

        if not data or "proxies" not in data:
            print(f"警告：订阅 {url} 不是合法 Clash YAML，已跳过")
            continue

        proxies = data["proxies"]

        if includeCondition:
            proxies = filter_proxies(proxies, includeCondition)

        all_proxies.extend(proxies)

    # 3️⃣ 节点处理：rename + emoji
    new_proxies = []
    for p in all_proxies:
        name = p.get("name", "")
        name = apply_rename(name, cfg["rename"])
        name = apply_emoji(name, cfg["emoji"])
        p["name"] = name
        new_proxies.append(p)

    # 4️⃣ proxy-groups
    proxy_groups = build_proxy_groups(cfg, new_proxies)
    if auto_group:
        add_auto_group(proxy_groups, new_proxies)

    # 5️⃣ rules（可选，先给空）
    rules = []
    for ruleset_rules in load_rulesets(order_rulesets_by_priority(cfg["rulesets"])):
        rules.extend(ruleset_rules)

    fixed_rules = []
    for r in rules:
        r = normalize_rule(r)
        r = filter_clash_rule(r)
        if r:
            fixed_rules.append(r)

    rules = fixed_rules
    # 6️⃣ 组装最终 Clash
    return {
        "mixed-port": 7890,
        "allow-lan": True,
        "bind-address": "*",
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "secret": "huyun_password",
        "tcp-concurrent": True,
        "ipv6": True,

        "clash-for-android": {
            "append-system-dns": False
        },

        "dns": {
            "enable": True,
            "ipv6": True,
            "default-nameserver": [
                "223.5.5.5",
                "119.29.29.29",
                "180.76.76.76",
                "223.6.6.6",
                "119.28.28.28"
            ],
            "fake-ip-range": "198.18.0.1/16",
            "use-hosts": True,
            "nameserver": [
                'https://dns.alidns.com/dns-query',
                'https://doh.pub/dns-query',
                'https://120.53.53.53/dns-query',
                'tls://dot.pub',
                'tls://120.53.53.53',
                'tls://dns.alidns.com',
                "223.5.5.5",
                "119.29.29.29",
                "180.76.76.76",
                "223.6.6.6",
                "119.28.28.28",
            ],
            "fallback": [
                'https://doh.dns.sb/dns-query',
                'https://dns.cloudflare.com/dns-query',
                'https://dns.twnic.tw/dns-query',
                'tls://8.8.4.4:853',
                'https://dns.alidns.com/dns-query',
                'https://doh.pub/dns-query',
                'https://120.53.53.53/dns-query',
                'tls://dot.pub',
                'tls://120.53.53.53',
                'tls://dns.alidns.com',
                "223.5.5.5",
                "119.29.29.29",
                "180.76.76.76",
                "223.6.6.6",
                "119.28.28.28",
            ],
            "fallback-filter": {
                "geo": [
                    "240.0.0.0/4",
                    "0.0.0.0/32",
                    "127.0.0.1/32",
                    "61.160.148.90/32",
                    "124.236.16.201/32",
                    "182.43.124.6/32",
                    "106.74.25.198/32",
                    "120.222.19.204/32",
                    "221.228.32.13/32",
                    "211.137.117.149/32",
                    "36.135.82.110/32",
                    "183.203.36.36/32",
                    "111.28.0.32/32",
                    "117.156.25.11/32",
                    "120.204.204.201/32",
                    "120.209.204.204/32",
                    "211.138.218.190/32",
                    "183.252.183.9/32",
                    "117.187.10.42/32",
                    "218.203.122.98/32",
                    "221.180.160.221/32",
                    "111.31.192.110/32",
                    "221.130.39.3/32",
                    "120.209.204.20/32",
                    "218.201.25.129/32",
                    "211.139.145.129/32",
                    "36.138.129.47/32",
                    "112.54.50.50/32",
                    "111.22.226.1/32",
                    "111.63.132.170/32",
                    "111.44.246.131/32",
                    "112.17.14.211/32",
                    "111.22.226.1/32",
                    "47.92.198.202/32"
                ]
            }
        },

        "proxies": new_proxies,
        "proxy-groups": proxy_groups,
        "rules": rules
    }

def yamlToStr(temYaml):
    return  yaml.safe_dump(
            temYaml,
            allow_unicode=True,   # 中文节点名必须
            sort_keys=False       # 保持 clash 结构顺序
        )

def save_yaml(data: dict, output_path: str):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,   # 中文节点名必须
            sort_keys=False       # 保持 clash 结构顺序
        )

    print(f"[OK] 已保存到 {path}")

#yamlFile = build_from_config(config_url,subscribe_url)

#ssave_yaml(yamlFile,"./test.yaml")
