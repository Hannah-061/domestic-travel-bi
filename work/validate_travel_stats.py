# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas>=2.0",
# ]
# ///
"""驗證 work/travel_stats.csv。

1. 結構：BOM、欄位名稱、年份完整性、每年 8 筆（性別 2、年齡 6）、分類、無重複、無缺漏、型別。
2. 合理性：0~100、民國/西元換算、各維度每年加總約 100。
3. 對照原始 .ods：不經 pandas/odfpy，直接解析 .ods 內的 content.xml 建立參照值，
   逐格比對年份、性別、年齡層與百分比，確認沒有錯位或遺漏。
原始檔只讀不寫。
"""
import math
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "work" / "travel_stats.csv"
SRC = ROOT / "1997、1999、2001~2024年國人國內旅行按性別及年齡統計.ods"

T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
O = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
YEAR_RE = re.compile(r"^\s*(\d+)年\((\d{4})\)\s*$")

EXPECTED_COLS = ["year", "roc_year", "dimension", "category", "percent"]
EXPECTED_YEARS = [1997, 1999, *range(2001, 2025)]
CATEGORIES = {
    "性別": ["男", "女"],
    "年齡": ["12-19", "20-29", "30-39", "40-49", "50-59", "60以上"],
}
# 原表表頭由左至右：性別 3 欄（合計、男、女）、年齡 7 欄（合計、6 個年齡層）
SOURCE_LAYOUT = [("性別", c) for c in ["合計", *CATEGORIES["性別"]]] + \
                [("年齡", c) for c in ["合計", *CATEGORIES["年齡"]]]
TOLERANCE = 0.3  # 原表各項為小數 1 位，加總可能因四捨五入偏離 100

errors: list[str] = []


def stop() -> None:
    print("驗證失敗：")
    for e in errors:
        print(" -", e)
    sys.exit(1)


# ---------- 讀取原始 .ods（第一個工作表） ----------

def read_ods_rows(path: Path) -> list[list[tuple[str, str | None]]]:
    """回傳每列的 [(顯示文字, office:value 或 None), ...]，合併儲存格佔位保留。"""
    root = ET.fromstring(zipfile.ZipFile(path).read("content.xml"))
    table = next(root.iter(T + "table"))
    rows = []
    for r in table.iter(T + "table-row"):
        cells = []
        for c in r:
            if c.tag not in (T + "table-cell", T + "covered-table-cell"):
                continue
            rep = min(int(c.get(T + "number-columns-repeated", "1")), 64)
            value = c.get(O + "value") if c.get(O + "value-type") == "float" else None
            cells.extend([("".join(c.itertext()).strip(), value)] * rep)
        has_content = any(t or v for t, v in cells)
        rep_rows = int(r.get(T + "number-rows-repeated", "1")) if has_content else 1
        rows.extend([cells] * rep_rows)
    return rows


def build_reference() -> dict[tuple[int, str, str], float]:
    rows = read_ods_rows(SRC)
    labels = [c for _, c in SOURCE_LAYOUT]

    # 找表頭列與數值欄起點
    start = None
    for cells in rows:
        texts = [t for t, _ in cells]
        for s in range(len(texts) - len(labels) + 1):
            if texts[s:s + len(labels)] == labels:
                start = s
                break
        if start is not None:
            break
    if start is None:
        errors.append(f"原始檔找不到表頭 {labels}")
        stop()
    if not any(len(r) > start + 3 and r[start][0] == "性別" and r[start + 3][0] == "年齡" for r in rows):
        errors.append("原始檔「性別」「年齡」表頭位置與預期不符")
        stop()

    copies: dict[int, list[list[float]]] = {}
    for n, cells in enumerate(rows, 1):
        m = YEAR_RE.match(cells[start - 1][0]) if len(cells) >= start else None
        if not m:
            continue
        raw = [cells[start + k][1] if start + k < len(cells) else None for k in range(len(labels))]
        if None in raw:
            errors.append(f"原始檔第 {n} 列有缺值：{raw}")
            continue
        copies.setdefault(int(m.group(2)), []).append([float(v) for v in raw])

    if sorted(copies) != EXPECTED_YEARS:
        errors.append(f"原始檔年份與預期不符：{sorted(copies)}")
    for y, cs in copies.items():
        if any(c != cs[0] for c in cs[1:]):
            errors.append(f"原始檔 {y} 年的重複資料不一致")
        if cs[0][0] != 100 or cs[0][3] != 100:
            errors.append(f"原始檔 {y} 年合計欄不是 100：性別 {cs[0][0]}、年齡 {cs[0][3]}")

    return {(y, dim, cat): cs[0][k]
            for y, cs in copies.items()
            for k, (dim, cat) in enumerate(SOURCE_LAYOUT) if cat != "合計"}


# ---------- 讀取 CSV ----------

if not CSV.exists():
    errors.append(f"找不到 {CSV.relative_to(ROOT)}，請先執行 ETL：uv run work/etl_travel_stats.py")
    stop()

if not CSV.read_bytes().startswith(b"\xef\xbb\xbf"):
    errors.append("CSV 不是 UTF-8 with BOM")

df = pd.read_csv(CSV, encoding="utf-8-sig", dtype={"dimension": str, "category": str})

if list(df.columns) != EXPECTED_COLS:
    errors.append(f"欄位不符：{list(df.columns)}，預期 {EXPECTED_COLS}")
    stop()  # 欄位錯就無法繼續檢查

# ---------- 結構 ----------

# 缺值會讓後續的排序、分組與比對失準或出錯，先列出後停止
if df.isna().any().any():
    counts = df.isna().sum()
    errors.append(f"有缺漏值（各欄缺值數：{counts[counts > 0].to_dict()}），"
                  f"CSV 第 {[i + 2 for i in df.index[df.isna().any(axis=1)]]} 列：\n"
                  f"{df[df.isna().any(axis=1)]}")
    stop()

for col, kind in [("year", "i"), ("roc_year", "i"), ("percent", "f")]:
    if df[col].dtype.kind != kind:
        errors.append(f"{col} 型別為 {df[col].dtype}")

n_expected = len(EXPECTED_YEARS) * sum(len(v) for v in CATEGORIES.values())
if len(df) != n_expected:
    errors.append(f"筆數 {len(df)}，預期 {n_expected}")

if sorted(df["year"].unique()) != EXPECTED_YEARS:
    missing = sorted(set(EXPECTED_YEARS) - set(df["year"]))
    extra = sorted(set(df["year"]) - set(EXPECTED_YEARS))
    errors.append(f"年份不完整或有多餘：缺 {missing}，多 {extra}")

if set(df["dimension"]) != set(CATEGORIES):
    errors.append(f"dimension 出現非預期的值：{sorted(set(df['dimension']))}")

dups = df[df.duplicated(["year", "dimension", "category"], keep=False)]
if not dups.empty:
    errors.append(f"有重複的 (year, dimension, category)：\n{dups}")

per_year = df.groupby("year").size()
bad_year_counts = per_year[per_year != 8]
if not bad_year_counts.empty:
    errors.append(f"每年應有 8 筆，不符的年份：{bad_year_counts.to_dict()}")

for dim, cats in CATEGORIES.items():
    sub = df[df["dimension"] == dim]
    dim_counts = sub.groupby("year").size().reindex(EXPECTED_YEARS, fill_value=0)
    bad_dim_counts = dim_counts[dim_counts != len(cats)]
    if not bad_dim_counts.empty:
        errors.append(f"{dim} 每年應有 {len(cats)} 筆，不符的年份：{bad_dim_counts.to_dict()}")
    for y, g in sub.groupby("year"):
        if sorted(g["category"]) != sorted(cats):
            errors.append(f"{y} 年 {dim} 分類不符：{sorted(g['category'])}")

# ---------- 合理性 ----------

if not (df["year"] - df["roc_year"] == 1911).all():
    errors.append(f"西元年與民國年不一致：\n{df[df['year'] - df['roc_year'] != 1911]}")

if not df["percent"].between(0, 100).all():
    errors.append(f"percent 超出 0~100：\n{df[~df['percent'].between(0, 100)]}")

for dim in CATEGORIES:
    sums = df[df["dimension"] == dim].groupby("year")["percent"].sum()
    bad_sums = sums[(sums - 100).abs() > TOLERANCE]
    if not bad_sums.empty:
        errors.append(f"{dim} 加總偏離 100 超過 {TOLERANCE} 的年份：{bad_sums.round(2).to_dict()}")

# ---------- 對照原始 .ods ----------

ref = build_reference()
csv_vals = {(r.year, r.dimension, r.category): r.percent for r in df.itertuples()}

for key in sorted(set(ref) - set(csv_vals)):
    errors.append(f"CSV 缺少原始檔的 {key}")
for key in sorted(set(csv_vals) - set(ref)):
    errors.append(f"CSV 有原始檔沒有的 {key}")
for key in sorted(set(ref) & set(csv_vals)):
    if not math.isclose(ref[key], csv_vals[key], rel_tol=0, abs_tol=1e-9):
        errors.append(f"{key} 數值不符：CSV {csv_vals[key]!r}，原始檔 {ref[key]!r}")

if errors:
    stop()

print(f"驗證通過：{len(df)} 列，{df['year'].nunique()} 個年份（{df['year'].min()}~{df['year'].max()}），"
      f"每年性別 2 筆、年齡 6 筆，{len(ref)} 個數值與原始 .ods 逐格一致")
