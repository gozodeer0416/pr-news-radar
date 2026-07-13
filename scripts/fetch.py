"""抓取目標媒體的 Google News RSS，產出候選文章清單。

讀取 config/monitor.yaml，對每家媒體 × 每組 topic 查一次 Google News，
過濾 lookback_days 內的文章，對 docs/data/seen.json 去重後，
寫出 .pipeline/candidates.json 供 classify.py 使用。
"""

import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "monitor.yaml"
SEEN = ROOT / "docs" / "data" / "seen.json"
OUT = ROOT / ".pipeline" / "candidates.json"

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; pr-news-radar/1.0)"}
SEEN_RETENTION_DAYS = 90


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def clean_title(title: str) -> str:
    # Google News 標題結尾會帶 " - 媒體名"
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def fetch_feed(domain: str, topic: str, lookback_days: int) -> list[dict]:
    query = f"site:{domain} {topic} when:{lookback_days}d"
    url = RSS_URL.format(query=quote(query))
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        guid = item.findtext("guid") or link
        pub = item.findtext("pubDate") or ""
        desc = strip_html(item.findtext("description") or "")
        try:
            pub_dt = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            pub_dt = None
        items.append({
            "title": clean_title(title),
            "link": link,
            "guid": guid,
            "published": pub_dt.isoformat() if pub_dt else None,
            "snippet": desc[:500],
        })
    return items


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text())
    lookback = int(cfg.get("lookback_days", 8))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback)

    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}

    candidates: dict[str, dict] = {}
    for media in cfg["media"]:
        for topic in cfg["topics"]:
            try:
                items = fetch_feed(media["domain"], topic, lookback)
            except Exception as e:  # 單一查詢失敗不中斷整體
                print(f"[warn] {media['name']} / {topic}: {e}", file=sys.stderr)
                continue
            for it in items:
                if it["published"]:
                    pub_dt = datetime.fromisoformat(it["published"])
                    if pub_dt < cutoff:
                        continue
                key = it["guid"]
                title_key = f"{media['domain']}::{it['title'].lower()}"
                if key in seen or title_key in seen:
                    continue
                if key in candidates or any(
                    c["title"].lower() == it["title"].lower()
                    and c["media"] == media["name"]
                    for c in candidates.values()
                ):
                    continue
                candidates[key] = {
                    **it,
                    "media": media["name"],
                    "tier": media["tier"],
                    "topic": topic,
                }
            time.sleep(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    result = list(candidates.values())
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"fetched {len(result)} new candidate articles")


if __name__ == "__main__":
    main()
