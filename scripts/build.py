"""把分類結果寫進 docs/data/，供 dashboard 讀取。

- docs/data/weeks/{YYYY-Www}.json：該週文章（同週重跑會合併去重）
- docs/data/index.json：週次清單 + config 摘要（前端顯示觀測原則用）
- docs/data/seen.json：已處理文章的去重紀錄
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "monitor.yaml"
IN = ROOT / ".pipeline" / "classified.json"
DATA = ROOT / "docs" / "data"
WEEKS = DATA / "weeks"
SEEN = DATA / "seen.json"
INDEX = DATA / "index.json"

SEEN_RETENTION_DAYS = 90


def week_id(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text())
    classified = json.loads(IN.read_text()) if IN.exists() else []
    now = datetime.now(timezone.utc)
    wid = week_id(now.date())

    WEEKS.mkdir(parents=True, exist_ok=True)

    # 合併同週既有資料（手動重跑時不覆蓋）
    week_file = WEEKS / f"{wid}.json"
    existing = json.loads(week_file.read_text()) if week_file.exists() else {"articles": []}
    known_keys = {a["guid"] for a in existing["articles"]}
    articles = existing["articles"] + [a for a in classified if a["guid"] not in known_keys]
    articles.sort(key=lambda a: (a.get("published") or ""), reverse=True)

    week_file.write_text(json.dumps({
        "week": wid,
        "generated_at": now.isoformat(),
        "articles": articles,
    }, ensure_ascii=False, indent=2))

    # 更新 seen.json（記 guid 與 標題鍵，並清掉過期紀錄）
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    today = now.date().isoformat()
    for a in classified:
        seen[a["guid"]] = today
        domain = next((m["domain"] for m in cfg["media"] if m["name"] == a["media"]), "")
        seen[f"{domain}::{a['title'].lower()}"] = today
    cutoff = (now.date() - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=2))

    # 重建 index.json
    weeks = []
    for f in sorted(WEEKS.glob("*.json"), reverse=True):
        data = json.loads(f.read_text())
        arts = data["articles"]
        weeks.append({
            "id": data["week"],
            "generated_at": data["generated_at"],
            "total": len(arts),
            "passed": sum(1 for a in arts if a["relevant"]),
            "hits": sum(1 for a in arts if a["relevant"] and a["size_grade"] in ("A", "B")),
        })

    INDEX.write_text(json.dumps({
        "updated_at": now.isoformat(),
        "weeks": weeks,
        "config": {
            "media": cfg["media"],
            "topics": cfg["topics"],
            "lookback_days": cfg["lookback_days"],
            "principles": {
                "company_profile": cfg["principles"]["company_profile"],
                "exclude": cfg["principles"]["exclude"],
                "angles": cfg["principles"]["angles"],
            },
        },
    }, ensure_ascii=False, indent=2))

    print(f"week {wid}: {len(articles)} articles total "
          f"({sum(1 for a in articles if a['relevant'])} relevant)")


if __name__ == "__main__":
    main()
