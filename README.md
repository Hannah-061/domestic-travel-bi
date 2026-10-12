# 國人國內旅行者組成 BI 儀表板

把公開的「歷年國人國內旅行按性別及年齡分」統計表，經 ETL 整理後做成可互動篩選的 BI 網頁，並用 GitHub Pages 發布。

- 網站：https://hannah-061.github.io/domestic-travel-bi/
- 主題：國內旅行者的性別與年齡組成如何隨年份改變（例如 60 歲以上旅行者的占比變化）

## 資料來源

- 原始檔：`1997、1999、2001~2024年國人國內旅行按性別及年齡統計.ods`（未經修改）
- 內容：各年度國內旅行者中，男女及各年齡層（12-19、20-29、30-39、40-49、50-59、60以上）所占百分比
- 期間：1997、1999，以及 2001～2024 年，共 26 個年份；1998、2000 年原表沒有資料
- 原表註記：86年、88年資料來源為「國人國內旅遊狀況調查」，90年以前為每兩年調查一次，90年後更名為「臺灣旅遊狀況調查」。

資料是組成比例（%），不是旅遊人數或人次。

## ETL 流程

```
原始 .ods ──etl_travel_stats.py──▶ work/travel_stats.csv ──build_data.py──▶ docs/data.js ──▶ docs/index.html
                     │
          validate_travel_stats.py（逐格對照原始 .ods）
```

1. **`work/etl_travel_stats.py`**：讀取 .ods 的 Sheet1，處理原表的問題後輸出長格式 CSV（UTF-8 with BOM）。
   - 表頭跨三列，「性別」「年齡」是合併儲存格：向右補齊後判斷每一欄屬於哪個維度
   - 2001～2014 年在原表重複出現兩次：先確認重複年份正好是這 14 年、每年兩份，且逐欄（含合計欄）完全一致，才保留一份
   - 排除恆為 100 的合計欄與表末註記列；百分比保留原始儲存值，不另行四捨五入
2. **`work/validate_travel_stats.py`**：檢查欄位、筆數（208）、年份完整性、每年性別 2 筆與年齡 6 筆、無重複與缺值、各維度加總約 100；並另外直接解析 .ods 的 XML，逐格比對 CSV 的 208 個數值。
3. **`work/build_data.py`**：把 CSV 轉成 `docs/data.js`（`window.TRAVEL_DATA`），讓網頁直接雙擊也能載入；轉換後讀回逐筆比對。

重新產生資料（需要 [uv](https://docs.astral.sh/uv/)）：

```bash
uv run work/etl_travel_stats.py
uv run work/validate_travel_stats.py
uv run work/build_data.py
```

## 檔案

| 檔案 | 用途 |
|---|---|
| `1997、1999、2001~2024年國人國內旅行按性別及年齡統計.ods` | 原始資料 |
| `work/etl_travel_stats.py` | ETL：.ods → CSV |
| `work/validate_travel_stats.py` | 驗證 CSV 並與原始 .ods 對照 |
| `work/travel_stats.csv` | 處理後資料：year, roc_year, dimension, category, percent |
| `work/build_data.py` | CSV → 網頁資料檔 |
| `docs/data.js` | 網頁使用的資料 |
| `docs/index.html` | BI 網頁（ECharts，GitHub Pages 從 `docs/` 發布） |
