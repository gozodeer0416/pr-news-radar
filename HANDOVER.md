# 交接文件（HANDOVER）— PR News Radar

> 給接手維護本系統的 AI（或人類工程師）。讀完這份文件你應該能安全地修改、除錯、擴充這個系統。
> 姊妹專案：[ragic-competitor-monitor](https://github.com/gozodeer0416/ragic-competitor-monitor)（競品週報 dashboard，另有自己的 HANDOVER.md）。

## 0. 最重要的三件事

1. **使用者（Lillian）做 Ragic 的 PR，非工程背景。** 跟她溝通用繁體中文、一步一步講、需要她操作時優先給「網頁 UI 上的步驟」（有可見的輸入框），避免要她跑終端機指令或剪貼簿管線（曾因 `pbpaste | gh secret set` 把空字串存成 secret，造成整批分類失敗）。
2. **她調整系統的唯一入口是 `config/monitor.yaml`**，在 GitHub 網頁上編輯、按 Commit changes 即完成——workflow 會自動重跑（`on.push.paths` 觸發）。不要引入任何需要她本機操作的流程。
3. **改壞的代價是「一週沒有觀測資料」**，不是即時災難。但錯誤資料一旦 commit 就會累積在 `seen.json` 裡（見 §4 陷阱），清理比避免麻煩，改動前先在本機驗證。

## 1. 系統在做什麼

每週一 09:00（台北時間）自動掃描 11 家英文科技/商業媒體，找出「與 Ragic 規模相近的公司」獲得的報導，用 Claude 分類切角（產品發布/記者實測/客戶案例…）與可比性分級（A/B/U），產出 dashboard 供 PR 題目發想。

- Dashboard：https://gozodeer0416.github.io/pr-news-radar/
- 基準研究（2026 上半年人工研究，觀測原則的源頭）：`docs/baseline.html`

## 2. 架構與資料流

```
GitHub Actions（.github/workflows/weekly.yml）
  每週一 01:00 UTC ＋ config/monitor.yaml 被 push 時 ＋ 手動 workflow_dispatch
    │
    ├─ scripts/fetch.py     Google News RSS（site:媒體 domain ＋ topics 關鍵字）
    │                       → .pipeline/candidates.json（對 seen.json 去重）
    ├─ scripts/classify.py  Claude API（claude-haiku-4-5，structured outputs）
    │                       → .pipeline/classified.json
    └─ scripts/build.py     → docs/data/weeks/{ISO週次}.json（同週合併不覆蓋）
                            → docs/data/index.json（週次清單＋config 摘要）
                            → docs/data/seen.json（去重紀錄，90 天滾動）
                            → git commit + push（GITHUB_TOKEN）
    │
GitHub Pages（main 分支 /docs 目錄）→ docs/index.html 讀 data/*.json 渲染
```

`.pipeline/` 是中繼目錄，已 gitignore，不會出現在 repo。

## 3. 使用者的操作模式（不要破壞）

- **調原則**：網頁編輯 `config/monitor.yaml` → Commit → 自動重跑 → 約 10 分鐘後 dashboard 更新。這條「零指令」路徑是刻意設計的，任何改動都必須保持它成立。
- config 內每個區塊都有中文註解，是寫給她看的，修改時保持註解與實際行為一致。
- `principles.company_profile` 與 `principles.exclude` 的文字**原封不動進入分類 prompt**（`classify.py` 的 `build_system()`）。她改的是「判準的自然語言描述」，不是程式參數。分類器只看單篇標題＋摘要，無法查證「LinkedIn followers」「歷史曝光次數」這類外部事實——她寫這種判準時，模型只能按「知名度印象」近似判斷，效果邊界要向她說明。

## 4. 已知陷阱（每一條都是實際踩過的）

| 陷阱 | 說明 |
|---|---|
| **空的 ANTHROPIC_API_KEY** | secret 存成空字串時 SDK 會拋認證錯誤。`classify.py` 已加 fail-fast（key 缺失或全部批次失敗→整個 workflow 失敗、不 commit）。不要移除這個保護。 |
| **seen.json 的去重語意** | 文章一旦進過 pipeline（無論分類結果）就記入 seen，之後**永不重新分類**。所以「改了原則想重跑本週」必須先刪 `docs/data/weeks/{本週}.json`＋`docs/data/index.json`＋`docs/data/seen.json` 再觸發，否則重跑抓不到已見過的文章。 |
| **同週合併** | `build.py` 對同週檔案是合併（append 去重）不是覆蓋。舊分類結果會留著。理由同上。 |
| **API 529 過載** | client 設 `max_retries=6`。批次失敗的文章會標「（自動分類失敗，請人工判讀）」並保留（relevant=True），這是刻意的 fallback，讓她能人工補判而不是默默消失。 |
| **Pages 部署時間差** | data commit 後 Pages 要 1–2 分鐘才更新；截圖驗證時用 `--virtual-time-budget=15000`（週次 JSON 較大，async fetch 比截圖慢會拍到空頁）。 |
| **gh token 需要 workflow scope** | 推 `.github/workflows/` 需要它。目前帳號（gozodeer0416）已補。若換機器要 `gh auth refresh -h github.com -s workflow`。 |
| **本機 git 推送用 gh 當 credential helper** | 曾遇 osxkeychain 快取舊 token 導致推送被拒，已 `gh auth setup-git` 解決。 |

## 5. 常見維護任務

- **加/減媒體、改關鍵字、改判準**：都在 `config/monitor.yaml`，她自己會改；你只在她要求時代改。
- **手動重跑**：Actions → Weekly PR News Monitor → Run workflow（或 `gh workflow run weekly.yml -R gozodeer0416/pr-news-radar`）。
- **用新原則重分類本週**：刪三個 data 檔（見 §4）→ commit push → 自動觸發。
- **除錯失敗的 run**：`gh run view <id> --log | grep -E "fetched|classified|warn"`。三支 script 的 stdout 都有一行統計。
- **本機驗證**：README 有完整指令（venv + 三支 script + `http.server -d docs`）。本機通常沒有 API key，classify 可用假資料測 build/前端。
- **改前端**：`docs/index.html` 單檔（vanilla JS，無建置步驟），改完本機 serve 起來用 headless Chrome 截圖確認再 push。

## 6. 金鑰與權限（取得與更換方式）

本系統只依賴一組金鑰＋一種 GitHub 權限：

### ANTHROPIC_API_KEY（分類步驟用，存於 repo secret）

- **取得**：登入 [Anthropic Console](https://platform.claude.com/settings/keys)（使用者的 Anthropic 帳號）→ **Create Key** → 複製 `sk-ant-...` 開頭的字串。帳號需有有效的付費方式或額度。
- **存放**：repo → Settings → Secrets and variables → **Actions** → secret 名稱固定為 `ANTHROPIC_API_KEY`。網頁 UI 上直接貼即可（適合使用者自己操作）；指令派用 `gh secret set ANTHROPIC_API_KEY -R gozodeer0416/pr-news-radar`。
- **更換/失效時的症狀**：workflow 在「Classify with Claude」步驟失敗（fail-fast 保護，不會 commit 壞資料）。到 Console 作廢舊 key、建新 key、更新 secret、手動 Run workflow 即可。
- **注意**：secret 值任何人都讀不回來（包括存的人），只能覆寫。曾發生過存成空字串的事故——存完最好手動觸發一次 run 驗證。

### GitHub 權限

- **workflow 內的 push**：用 Actions 內建的 `GITHUB_TOKEN`（`permissions: contents: write` 已在 weekly.yml 宣告），零設定、不會過期。
- **維護者本機 push**：需要 repo 的寫入權（目前為擁有者帳號 gozodeer0416 的 gh CLI 登入）。若要修改 `.github/workflows/` 下的檔案，token 必須有 **workflow scope**——沒有的話 push 會被拒，補法：`gh auth refresh -h github.com -s workflow`（會開瀏覽器授權）。

## 7. 費用與模型

- 分類用 `claude-haiku-4-5`，每週約 400–500 篇、成本 < US$1。
- 若升級模型，注意 `classify.py` 用 `output_config={"format": {"type": "json_schema", ...}}`（structured outputs），確認目標模型支援。

## 8. 歷史決策（為什麼是現在這樣）

- **Google News RSS 而非各站爬蟲**：免金鑰、免維護 selector、涵蓋付費牆媒體（WSJ）的標題摘要。代價是摘要短，分類只能靠標題+摘要。
- **分類只看標題+摘要不抓全文**：成本低、避開付費牆與反爬。判準寫法要配合這個限制。
- **被排除文章保留在資料裡**（折疊區顯示排除原因）：讓她能稽核 AI 誤判，這是信任機制，不要為了省空間拿掉。
- **每週跑而非每日**：她的工作節奏是週會發想，量也才值得一次人工掃描。

## 9. 待辦與未實作的想法

- 台灣媒體、具名同類公司追蹤（Softr、Kilo 等）：config 結構已可容納（加 media/topics 即可），她未啟用。
- Slack/Email 通知：未做。
