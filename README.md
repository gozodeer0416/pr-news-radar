# PR News Radar

每週自動觀測目標媒體對「與 Ragic 規模相近公司」的報導切角，
作為 PR 題目發想參考的 dashboard。

- **Dashboard**：https://gozodeer0416.github.io/pr-news-radar/
- **基準研究**（2026/01–07 半年期人工研究）：https://gozodeer0416.github.io/pr-news-radar/baseline.html

## 運作方式

每週一 09:00（台北時間）GitHub Actions 自動執行：

1. `scripts/fetch.py` — 對 11 家目標媒體 × 5 組關鍵字查 Google News RSS，去重
2. `scripts/classify.py` — 用 Claude（Haiku 4.5）依觀測原則分類：
   排除募資/財務/大廠新聞、標記切角類型、判斷公司規模是否與 Ragic 可比（A/B/U）
3. `scripts/build.py` — 產出 `docs/data/weeks/{週次}.json` 並 commit，GitHub Pages 即時更新

## 調整觀測原則

所有原則集中在 **`config/monitor.yaml`**，直接編輯後 push 即可：

| 想調整什麼 | 改哪裡 |
|---|---|
| 增刪目標媒體、改 Tier | `media:` 區塊 |
| 搜尋關鍵字 | `topics:` 區塊 |
| 「同規模公司」的定義 | `principles.company_profile` |
| 排除規則（如是否排除募資新聞） | `principles.exclude` |
| 切角分類法 | `principles.angles` |
| 回看天數 | `lookback_days` |

改完想立即重跑：repo → **Actions** → **Weekly PR News Monitor** → **Run workflow**。

## 本機執行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install requests pyyaml anthropic
python scripts/fetch.py
ANTHROPIC_API_KEY=sk-... python scripts/classify.py
python scripts/build.py
python3 -m http.server -d docs 8000   # 開 http://localhost:8000 看結果
```

## 必要設定

- Repo secret `ANTHROPIC_API_KEY`（Settings → Secrets and variables → Actions）
- GitHub Pages：Settings → Pages → Deploy from branch → `main` / `/docs`
