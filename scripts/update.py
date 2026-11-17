from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources.yaml"
OUTPUT = ROOT / "output" / "clash.yaml"
STATUS = ROOT / "output" / "source-status.json"

MAX_NODES = int(os.getenv("MAX_NODES", "500"))
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "20"))
TEST_INTERVAL = int(os.getenv("TEST_INTERVAL", "300"))

TEST_URL = "http://www.gstatic.com/generate_204"

# 走 QUIC 的协议：带宽和抗丢包通常明显好于 vmess/ss，但延迟数字不占优，
# 放在统一的 url-test 里会被低延迟的 vmess 长期压制，永远选不到。
QUIC_TYPES = {"hysteria2"}


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "free-vpn-clash-aggregator/1.0"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        body = response.read()
    parsed = yaml.safe_load(body) or {}
    if not isinstance(parsed, dict):
        raise ValueError("top-level YAML value is not a mapping")
    return parsed


def fingerprint(proxy: dict) -> tuple:
    fields = ("type", "server", "port", "uuid", "password", "public-key", "private-key", "token")
    return tuple(str(proxy.get(field, "")) for field in fields)


def collect(entries: list) -> tuple[list[deque], list[dict]]:
    """按源分桶收集节点，跨源用指纹去重。单个源失败不影响其他源。"""
    buckets: list[deque] = []
    seen: set[tuple] = set()
    status: list[dict] = []

    for source in entries:
        name, url = source["name"], source["url"]
        bucket: deque = deque()
        try:
            document = fetch(url)
            candidates = document.get("proxies", [])
            if not isinstance(candidates, list):
                raise ValueError("proxies is not a list")
            for proxy in candidates:
                if not isinstance(proxy, dict) or not proxy.get("name") or not proxy.get("type"):
                    continue
                key = fingerprint(proxy)
                if key in seen:
                    continue
                seen.add(key)
                bucket.append(dict(proxy))
            buckets.append(bucket)
            status.append(
                {"name": name, "url": url, "ok": True, "received": len(candidates), "kept": len(bucket)}
            )
        except Exception as exc:  # 一个坏上游不能阻塞其他源
            buckets.append(deque())
            status.append({"name": name, "url": url, "ok": False, "error": str(exc)})

    return buckets, status


def interleave(buckets: list[deque], limit: int) -> list[dict]:
    """轮转取节点：每轮从每个源各取一个，直到凑满上限。

    这样节点数少的源能全量进入，节点多的大源均分剩余名额，
    而不是像原来那样按 sources.yaml 顺序切片、被头两个源吃满配额。
    """
    pool = [bucket for bucket in buckets if bucket]
    picked: list[dict] = []
    while len(picked) < limit and pool:
        for bucket in pool:
            if len(picked) >= limit:
                break
            if bucket:
                picked.append(bucket.popleft())
        if all(not bucket for bucket in pool):
            break
    return picked


def unique_names(proxies: list[dict]) -> list[str]:
    used: set[str] = set()
    for proxy in proxies:
        base = (str(proxy.get("name", "")).strip()[:80] or "node")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} #{suffix}"
            suffix += 1
        used.add(candidate)
        proxy["name"] = candidate
    return [proxy["name"] for proxy in proxies]


def split_by_protocol(proxies: list[dict], names: list[str]) -> tuple[list[str], list[str]]:
    """按协议把节点名分成 QUIC 组和普通组。"""
    quic: list[str] = []
    normal: list[str] = []
    for proxy, name in zip(proxies, names):
        (quic if proxy.get("type") in QUIC_TYPES else normal).append(name)
    return quic, normal


def build(proxies: list[dict], names: list[str]) -> dict:
    quic, normal = split_by_protocol(proxies, names)

    groups: list[dict] = [
        {
            "name": "AUTO",
            "type": "url-test",
            "url": TEST_URL,
            "interval": TEST_INTERVAL,
            "tolerance": 50,
            # 全是 QUIC 节点时 normal 为空，退回全量，避免空组
            "proxies": normal or names,
        }
    ]
    if quic:
        groups.append(
            {
                "name": "AUTO-HY2",
                "type": "url-test",
                "url": TEST_URL,
                "interval": TEST_INTERVAL,
                "tolerance": 50,
                "proxies": quic,
            }
        )
    groups.append({"name": "PROXY", "type": "select", "proxies": [g["name"] for g in groups] + ["DIRECT"] + names})

    return {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": groups,
        # 国内直连分流：局域网 -> 中国大陆 IP -> 其余走代理
        "rules": [
            "GEOIP,LAN,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,PROXY",
        ],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    config = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    entries = config.get("sources", [])

    buckets, status = collect(entries)
    proxies = interleave(buckets, MAX_NODES)

    if not proxies:
        raise RuntimeError("all upstream sources failed or returned no Clash proxies")

    names = unique_names(proxies)
    generated = build(proxies, names)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "# Generated by scripts/update.py; do not edit.\n" + yaml.safe_dump(generated, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    per_source = {item["name"]: item.get("kept", 0) for item in status if item.get("ok")}
    STATUS.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "proxy_count": len(proxies),
                "max_nodes": MAX_NODES,
                "mode": "interleave",
                "usable_sources": sum(1 for item in status if item.get("ok")),
                "kept_per_source": per_source,
                "sources": status,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps({"proxy_count": len(proxies), "sources": status}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
