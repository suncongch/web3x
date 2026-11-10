import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

UNSUPPORTED_RULE_TYPES = {
    "URL-REGEX",
    "URL",
    "USER-AGENT",
}

RULESET_CACHE_DIR = Path("data") / "rulesets"
RULESET_CACHE_TTL = 7 * 24 * 60 * 60
_ruleset_locks: dict[str, threading.Lock] = {}
_ruleset_locks_guard = threading.Lock()


def _ruleset_cache_paths(url: str) -> tuple[Path, Path]:
    """Return cache paths named after the remote ruleset's list filename."""
    filename = Path(unquote(urlparse(url).path)).name
    if not filename:
        # A URL without a path cannot provide a meaningful list name.
        filename = hashlib.sha256(url.encode("utf-8")).hexdigest()
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    if not filename.lower().endswith(".list"):
        filename += ".list"
    cache_file = RULESET_CACHE_DIR / filename
    return (
        cache_file,
        cache_file.with_suffix(".json"),
    )


def _ruleset_lock(url: str) -> threading.Lock:
    with _ruleset_locks_guard:
        return _ruleset_locks.setdefault(url, threading.Lock())


def _read_cached_ruleset(cache_file: Path) -> str | None:
    try:
        return cache_file.read_text(encoding="utf-8")
    except OSError:
        return None


def _cache_is_fresh(meta_file: Path) -> bool:
    try:
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        saved_at = float(metadata["saved_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return time.time() - saved_at < RULESET_CACHE_TTL


def _write_ruleset_cache(url: str, content: str, cache_file: Path, meta_file: Path) -> None:
    RULESET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_tmp = cache_file.with_suffix(".list.tmp")
    meta_tmp = meta_file.with_suffix(".json.tmp")
    cache_tmp.write_text(content, encoding="utf-8")
    meta_tmp.write_text(
        json.dumps({"url": url, "saved_at": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(cache_tmp, cache_file)
    os.replace(meta_tmp, meta_file)


def get_ruleset_content(url: str, force: bool = False) -> str:
    """Read a cached ruleset, downloading it when its seven-day TTL expires or force is set."""
    cache_file, meta_file = _ruleset_cache_paths(url)

    with _ruleset_lock(url):
        cached = _read_cached_ruleset(cache_file)
        if not force and cached is not None and _cache_is_fresh(meta_file):
            return cached

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            _write_ruleset_cache(url, response.text, cache_file, meta_file)
            return response.text
        except requests.RequestException:
            # An expired cache is still preferable to dropping all its rules when
            # the upstream provider is temporarily unavailable.
            if cached is not None:
                return cached
            raise

def parse_acl4ssr_config(text: str):
    cfg = {
        "proxy_groups": [],
        "rulesets": [],
        "rename": [],
        "emoji": []
    }

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue

        if line.startswith("custom_proxy_group="):
            cfg["proxy_groups"].append(parse_proxy_group(line))
        elif line.startswith("ruleset="):
            cfg["rulesets"].append(parse_ruleset(line))
        elif line.startswith("rename_node="):
            cfg["rename"].append(parse_rename(line))
        elif line.startswith("emoji="):
            cfg["emoji"].append(parse_emoji(line))

    return cfg

def parse_rename(line):
    _, expr = line.split("=", 1)
    pattern, repl = expr.split("@", 1)
    return pattern, repl

def apply_rename(name, rules):
    for pattern, repl in rules:
        try:
            name = re.sub(pattern, repl, name)
        except re.error:
            pass
    return name

def parse_emoji(line):
    _, expr = line.split("=", 1)
    pattern, emoji = expr.split(",", 1)
    return pattern.strip("()"), emoji

def apply_emoji(name, emoji_rules):
    for pattern, emoji in emoji_rules:
        if re.search(pattern, name) and not name.startswith(emoji):
            return f"{emoji} {name}"
    return name

def name_rank(name,group):

    # 优先级规则
    if "ai" in group.lower() and "节点选择" in name.lower():
        return 0
    if "ai" in group.lower() and "vultr" in name.lower():
        return 1
    if "日本" in name:
        return 3
    if "狮城" in name:
        return 2
    if "美国" in name:
        return 4

    return (99)

    

def parse_proxy_group(line):
    _, expr = line.split("=", 1)
    parts = expr.split("`")

    name = parts[0]
    group_type = parts[1]
    options = []
    regex = None

    for p in parts[2:]:
        if p.startswith("[]"):
            options.append(p[2:])
        else:
            regex = p

    return {
        "name": name,
        "type": group_type,
        "options": options,
        "regex": regex
    }

def build_proxy_groups(cfg, proxies):

    names = [p["name"] for p in proxies]
    groups = []

    for g in cfg["proxy_groups"]:
        members = []

        if g["regex"]:
            members.extend([n for n in names if re.search(g["regex"], n)])

        members.extend(g["options"])

        # ⭐ 1. 去重（保序）
        members = list(dict.fromkeys(members))

        # ⭐ 2. 排序（插入点就在这里）
        members = sorted(
            members,
            key=lambda x: name_rank(x,g["name"])
        )

        groups.append({
            "name": g["name"],
            "type": g["type"],
            "proxies": members
        })

    return groups

def load_ruleset(url: str | None, group: str, rule_type=None, value=None, force: bool = False):
    rules = []

    # ① 内置 GEOIP
    if rule_type == "GEOIP":
        rules.append(f"GEOIP,{value},{group}")
        return rules

    # ② FINAL
    if rule_type == "FINAL":
        rules.append(f"FINAL,{group}")
        return rules

    # ③ 远程 ruleset
    if not url:
        return []

    for line in get_ruleset_content(url, force).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rules.append(f"{line},{group}")

    return rules


def load_rulesets(rulesets: list[dict], force: bool = False) -> list[list[str]]:
    """Load remote rulesets concurrently while retaining config-file order."""
    if not rulesets:
        return []

    def load(spec: dict) -> list[str]:
        return load_ruleset(
            spec.get("url"),
            spec["group"],
            spec.get("type"),
            spec.get("value"),
            force,
        )

    worker_count = min(8, len(rulesets))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ruleset") as executor:
        return list(executor.map(load, rulesets))

def build_clash_config(proxies, proxy_groups, rules):
    return {
        "proxies": proxies,
        "proxy-groups": proxy_groups,
        "rules": rules
    }

def parse_ruleset(line: str):
    # ruleset=🎯 全球直连,[]GEOIP,CN
    # ruleset=🐟 漏网之鱼,[]FINAL
    # ruleset=🚀 节点选择,https://xxx.list

    _, body = line.split("=", 1)
    group, value = body.split(",", 1)

    value = value.strip()

    if value.startswith("[]GEOIP"):
        _, geo = value.split(",", 1)
        return {
            "group": group,
            "type": "GEOIP",
            "value": geo,
            "url": None,
        }

    if value == "[]FINAL":
        return {
            "group": group,
            "type": "FINAL",
            "url": None,
        }

    return {
        "group": group,
        "type": "REMOTE",
        "url": value,
    }

def filter_clash_rule(rule: str) -> str | None:
    rule = rule.strip()
    if not rule:
        return None

    rule_type = rule.split(",", 1)[0].upper()
    if rule_type in UNSUPPORTED_RULE_TYPES:
        return None  # 直接丢弃

    return rule

def normalize_rule(rule: str):
    rule = rule.strip()

    # 1️⃣ FINAL → MATCH
    if rule.startswith("FINAL,"):
        rule = "MATCH," + rule[len("FINAL,"):]

    parts = [p.strip() for p in rule.split(",")]

    if "no-resolve" in parts and parts[-1] != "no-resolve":
        parts.remove("no-resolve")
        parts.append("no-resolve")

    return ",".join(parts)
