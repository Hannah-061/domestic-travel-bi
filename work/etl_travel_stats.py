# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas>=2.0",
#     "odfpy>=1.4",
# ]
# ///
"""把「國人國內旅行按性別及年齡統計」.ods 整理成長格式 CSV。

輸出欄位：
    year       西元年（int）
    roc_year   民國年（int）
    dimension  性別 / 年齡
    category   男、女，或 12-19、20-29、…、60以上
    percent    占比（%，float，保留原始儲存值，不另行四捨五入）

原始檔只讀不寫。任何結構不符、缺值或重複資料不一致都會停止並列出原因。
"""
import math
import numbers
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "1997、1999、2001~2024年國人國內旅行按性別及年齡統計.ods"
OUT = ROOT / "work" / "travel_stats.csv"

YEAR_RE = re.compile(r"^\s*(\d+)年\((\d{4})\)\s*$")
EXPECTED_LABELS = {
    "性別": ["合計", "男", "女"],
    "年齡": ["合計", "12-19", "20-29", "30-39", "40-49", "50-59", "60以上"],
}
EXPECTED_DUP_YEARS = list(range(2001, 2015))  # 原表 2001~2014 出現兩次


def fail(title: str, details: list[str]) -> None:
    print(f"停止：{title}", file=sys.stderr)
    for d in details:
        print(f"  - {d}", file=sys.stderr)
    sys.exit(1)


def to_number(v) -> float | None:
    """原始儲存格的數值；空白、文字或 NaN 回傳 None。"""
    if isinstance(v, bool) or not isinstance(v, numbers.Real):
        return None
    if math.isnan(v):
        return None
    return float(v)


def locate_columns(raw: pd.DataFrame) -> dict[int, tuple[str, str]]:
    """從跨列表頭找出每個數值欄的 (dimension, category)，含合計欄。

    表頭結構：一列是「性別」「年齡」（合併儲存格，只有第一格有值），
    下一列是 Gender/Age，再下一列是 合計/男/女/合計/12-19/…/60以上。
    """
    label_row = next((i for i, row in raw.iterrows() if (row == "男").any()), None)
    if label_row is None:
        fail("找不到必要表頭", ["Sheet1 中沒有內容為「男」的儲存格，無法定位 合計/男/女/年齡層 那一列"])
    dim_row = next((i for i in range(label_row - 1, -1, -1) if (raw.iloc[i] == "性別").any()), None)
    if dim_row is None:
        fail("找不到必要表頭", [f"第 {label_row + 1} 列以上沒有內容為「性別」的儲存格，無法判斷各欄屬於性別或年齡"])

    # 合併儲存格只在第一格有值，向右補齊
    dims = raw.iloc[dim_row].ffill()
    labels = raw.iloc[label_row]

    cols = {}
    for c in raw.columns:
        dim, cat = dims[c], labels[c]
        if dim in EXPECTED_LABELS and isinstance(cat, str) and cat.strip():
            cols[c] = (dim, cat.strip())

    found = {dim: [cat for d, cat in cols.values() if d == dim] for dim in EXPECTED_LABELS}
    if found != EXPECTED_LABELS:
        fail("表頭結構與預期不符", [f"{d}：找到 {found[d]}，預期 {EXPECTED_LABELS[d]}" for d in EXPECTED_LABELS])
    return cols


def main() -> None:
    raw = pd.read_excel(SRC, sheet_name=0, header=None, engine="odf", dtype=object)
    cols = locate_columns(raw)

    year_col = next((c for c in raw.columns if raw[c].astype(str).str.match(YEAR_RE).any()), None)
    if year_col is None:
        fail("找不到年份欄", ["Sheet1 中沒有符合「民國年(西元年)」格式（例如 90年(2001)，半形括號）的儲存格"])

    # 讀出所有年份列（含合計欄）的原始數值
    copies: dict[int, list[tuple[int, int, dict[int, float]]]] = defaultdict(list)
    problems = []
    for i, row in raw.iterrows():
        m = YEAR_RE.match(str(row[year_col]))
        if not m:  # 標題、表頭、註解列
            continue
        src_row = i + 1
        roc, year = int(m.group(1)), int(m.group(2))
        if year - roc != 1911:
            problems.append(f"第 {src_row} 列民國/西元年不一致：{row[year_col]}")
        values = {}
        for c, (dim, cat) in cols.items():
            v = to_number(row[c])
            if v is None:
                problems.append(f"第 {src_row} 列（{year}）{dim}/{cat} 缺值或非數值：{row[c]!r}")
            values[c] = v
        copies[year].append((src_row, roc, values))
    if problems:
        fail("原始資料有缺值或年份錯誤", problems)

    # 重複年份必須正好是 2001~2014，且每年各兩份
    dup_years = sorted(y for y, cs in copies.items() if len(cs) > 1)
    problems = [f"{y} 年出現 {len(copies[y])} 次（第 {', '.join(str(r) for r, _, _ in copies[y])} 列）"
                for y in dup_years if len(copies[y]) != 2]
    if dup_years != EXPECTED_DUP_YEARS:
        problems.append(f"重複年份為 {dup_years}，預期 {EXPECTED_DUP_YEARS}")
    if problems:
        fail("重複年份與預期不符", problems)

    # 兩份逐欄（含合計欄）以原始數值比對，完全相同才去重
    problems = []
    for y in dup_years:
        (r1, _, v1), (r2, _, v2) = copies[y]
        for c, (dim, cat) in cols.items():
            if v1[c] != v2[c]:
                problems.append(f"{y} 年 {dim}/{cat}：第 {r1} 列 = {v1[c]!r}，第 {r2} 列 = {v2[c]!r}")
    if problems:
        fail("重複年份的兩份資料不一致，無法自動去重", problems)

    records = []
    for year in sorted(copies):
        _, roc, values = copies[year][-1]  # 兩份已確認相同，取後段按年份排序的區塊
        for c, (dim, cat) in cols.items():
            if cat == "合計":  # 恆為 100，不輸出
                continue
            records.append({"year": year, "roc_year": roc, "dimension": dim,
                            "category": cat, "percent": values[c]})

    df = pd.DataFrame(records)
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"已確認並移除重複年份：{dup_years}（各 2 份，逐欄一致）")
    print(f"輸出 {len(df)} 列、{df['year'].nunique()} 個年份 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
