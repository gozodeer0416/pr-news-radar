"""用 Claude API 依 config/monitor.yaml 的 principles 分類候選文章。

讀 .pipeline/candidates.json，分批送 Claude（structured outputs 保證回 JSON），
每篇標記：是否相關、排除原因、切角、公司名、規模分級、一句話繁中判讀。
寫出 .pipeline/classified.json 供 build.py 使用。
需要環境變數 ANTHROPIC_API_KEY。
"""

import json
import os
import sys
from pathlib import Path

import anthropic
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "monitor.yaml"
IN = ROOT / ".pipeline" / "candidates.json"
OUT = ROOT / ".pipeline" / "classified.json"

MODEL = "claude-haiku-4-5"
BATCH_SIZE = 12

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "excluded_reason": {"type": ["string", "null"]},
                    "angle": {"type": "string"},
                    "company": {"type": ["string", "null"]},
                    "size_grade": {"type": "string", "enum": ["A", "B", "U", "unknown", "na"]},
                    "note_zh": {"type": "string"},
                },
                "required": [
                    "index", "relevant", "excluded_reason",
                    "angle", "company", "size_grade", "note_zh",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def build_system(cfg: dict) -> str:
    p = cfg["principles"]
    angle_lines = "\n".join(
        f"- {a['id']}: {a['label']} — {a['desc']}" for a in p["angles"]
    )
    return f"""你是一位 PR 媒體觀測分析師，為 Ragic（台灣的 no-code 資料庫公司，約 64 人）\
篩選每週值得參考的媒體報導。逐篇判斷以下事項並輸出 JSON。

## 可比公司定義
{p['company_profile']}

## 排除規則
{p['exclude']}

## 切角分類（angle 欄位只能填以下 id 之一）
{angle_lines}

## 欄位規則
- relevant: 文章是否值得列入觀測（主角是小型軟體/AI/no-code 公司的 earned media，\
且不觸犯排除規則）。趨勢文若有小公司被具體引用也算 relevant。
- excluded_reason: relevant=false 時用一句繁體中文說明排除原因；relevant=true 時填 null。
- angle: 切角分類 id。
- company: 文章主角公司名（趨勢文填最主要被引用的小公司）；判斷不出來填 null。
- size_grade: 依可比公司定義給 A/B/U；資訊不足填 unknown；relevant=false 填 na。
- note_zh: 一句繁體中文判讀——這篇的切角對 Ragic PR 的參考點是什麼；\
relevant=false 時可簡短說明。

只依標題與摘要判斷，摘要資訊有限時保守給 unknown，不要臆測公司規模。"""


def classify_batch(client: anthropic.Anthropic, system: str, batch: list[dict]) -> list[dict]:
    lines = []
    for i, art in enumerate(batch):
        lines.append(
            f"[{i}] media={art['media']} (Tier {art['tier']})\n"
            f"title: {art['title']}\n"
            f"snippet: {art['snippet'] or '(無摘要)'}"
        )
    user = "請分類以下文章：\n\n" + "\n\n".join(lines)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["results"]


def main() -> None:
    candidates = json.loads(IN.read_text()) if IN.exists() else []
    if not candidates:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("[]")
        print("no candidates to classify")
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is missing or empty — aborting so bad data "
                 "is never committed. Set the repo secret and re-run.")

    cfg = yaml.safe_load(CONFIG.read_text())
    system = build_system(cfg)
    client = anthropic.Anthropic()

    classified = []
    ok_batches = 0
    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        try:
            results = classify_batch(client, system, batch)
            ok_batches += 1
        except Exception as e:
            print(f"[warn] batch {start} failed: {e}", file=sys.stderr)
            results = []
        by_index = {r["index"]: r for r in results}
        for i, art in enumerate(batch):
            r = by_index.get(i)
            if r is None:
                # 分類失敗的文章保留原始資料，標 unclassified 供人工檢視
                classified.append({**art, "relevant": True, "excluded_reason": None,
                                   "angle": "other", "company": None,
                                   "size_grade": "unknown",
                                   "note_zh": "（自動分類失敗，請人工判讀）"})
            else:
                classified.append({**art,
                                   "relevant": r["relevant"],
                                   "excluded_reason": r["excluded_reason"],
                                   "angle": r["angle"],
                                   "company": r["company"],
                                   "size_grade": r["size_grade"],
                                   "note_zh": r["note_zh"]})

    if ok_batches == 0:
        sys.exit("all classification batches failed — aborting so bad data "
                 "is never committed.")

    OUT.write_text(json.dumps(classified, ensure_ascii=False, indent=2))
    passed = sum(1 for c in classified if c["relevant"])
    print(f"classified {len(classified)} articles ({passed} relevant)")


if __name__ == "__main__":
    main()
