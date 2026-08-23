"""抓取觀測來源，產出候選文章清單。

兩種來源並行：
  1. media × topics —— 組 Google News RSS 搜尋，只拿關鍵字命中的文章
  2. feeds        —— 直接讀指定的 RSS 網址（該來源發的全部文章，補關鍵字的盲區）

讀取 config/monitor.yaml，過濾 lookback_days 內的文章，
對 docs/data/seen.json 去重後，寫出 .pipeline/candidates.json 供 classify.py 使用。
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
from urllib.parse import quote, urlparse

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


def norm_domain(value: str) -> str:
    """把網址或網域正規化成比對用的形式（去掉 scheme、www.、路徑）。"""
    v = (value or "").strip().lower()
    netloc = urlparse(v).netloc if "//" in v else v.split("/")[0]
    return netloc.removeprefix("www.")


def get_xml(url: str, timeout: int = 60) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def parse_items(content: bytes, *, strip_source_suffix: bool) -> list[dict]:
    """把 RSS 內容解析成統一格式的文章清單。"""
    root = ET.fromstring(content)
    items = []
    for item in root.iter("item"):
        raw_title = html.unescape(item.findtext("title") or "").strip()
        link = item.findtext("link") or ""
        guid = item.findtext("guid") or link
        source_el = item.find("source")
        try:
            pub_dt = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            pub_dt = None
        items.append({
            "title": clean_title(raw_title) if strip_source_suffix else raw_title,
            "link": link,
            "guid": guid,
            "published": pub_dt.isoformat() if pub_dt else None,
            "snippet": strip_html(item.findtext("description") or "")[:500],
            "source": html.unescape((source_el.text or "").strip()) if source_el is not None else "",
        })
    return items


def fetch_google(domain: str, topic: str, lookback_days: int) -> list[dict]:
    query = f"site:{domain} {topic} when:{lookback_days}d"
    return parse_items(get_xml(RSS_URL.format(query=quote(query)), timeout=30),
                       strip_source_suffix=True)


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text())
    lookback = int(cfg.get("lookback_days", 8))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback)

    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    media_by_domain = {norm_domain(m["domain"]): m for m in cfg["media"]}

    candidates: dict[str, dict] = {}
    title_keys: set[str] = set()

    def add(item: dict, *, media: str, tier: int, domain: str, topic: str) -> None:
        """加入候選，並對 seen.json 與本次結果雙重去重。"""
        if not item["title"] or not item["link"]:
            return  # 少數 feed 會夾帶空白項目，送進分類器只會產生垃圾資料
        if item["published"] and datetime.fromisoformat(item["published"]) < cutoff:
            return
        guid, title_key = item["guid"], f"{domain}::{item['title'].lower()}"
        if guid in seen or title_key in seen:
            return
        if guid in candidates or title_key in title_keys:
            return
        title_keys.add(title_key)
        candidates[guid] = {
            "title": item["title"],
            "link": item["link"],
            "guid": guid,
            "published": item["published"],
            "snippet": item["snippet"],
            "media": media,
            "tier": tier,
            "domain": domain,
            "topic": topic,
        }

    # --- 來源 1：Google News 關鍵字搜尋 ---
    for m in cfg["media"]:
        for topic in cfg["topics"]:
            try:
                items = fetch_google(m["domain"], topic, lookback)
            except Exception as e:  # 單一查詢失敗不中斷整體
                print(f"[warn] {m['name']} / {topic}: {e}", file=sys.stderr)
                continue
            for it in items:
                add(it, media=m["name"], tier=m["tier"],
                    domain=norm_domain(m["domain"]), topic=topic)
            time.sleep(1)

    # --- 來源 2：直接訂閱的 RSS ---
    for feed in cfg.get("feeds", []):
        label = feed.get("name", feed["url"])
        try:
            items = parse_items(get_xml(feed["url"]), strip_source_suffix=False)
        except Exception as e:  # 單一 feed 失敗不中斷整體
            print(f"[warn] feed {label}: {e}", file=sys.stderr)
            continue

        default_tier = int(feed.get("default_tier", 3))
        for it in items:
            dom = norm_domain(it["link"])
            known = media_by_domain.get(dom)
            if known:
                add(it, media=known["name"], tier=known["tier"],
                    domain=norm_domain(known["domain"]), topic=f"feed:{label}")
            else:
                # 不在 media 名單上的來源：用網域當媒體名，方便日後決定要不要正式納管
                add(it, media=dom or label, tier=default_tier,
                    domain=dom, topic=f"feed:{label}")

        # feed 只回傳最新 N 篇時會悄悄漏掉舊文章——回看範圍沒被蓋滿就示警
        dates = [datetime.fromisoformat(i["published"]) for i in items if i["published"]]
        if dates and min(dates) > cutoff:
            print(f"[warn] feed {label}: 只回溯到 {min(dates).date()}，未蓋滿 {lookback} 天回看範圍——"
                  f"該來源可能限制回傳篇數，請調高網址的筆數參數（如 ?n=1000）", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    result = list(candidates.values())
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"fetched {len(result)} new candidate articles")


if __name__ == "__main__":
    main()
