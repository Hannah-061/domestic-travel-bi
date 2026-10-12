# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""把 work/travel_stats.csv 轉成網頁可直接載入的 docs/data.js。

docs/index.html 用 <script src="data.js"></script> 載入後，資料在 window.TRAVEL_DATA：
    meta  標題、單位、來源註記、年份與分類清單
    rows  原始 CSV 每一列 {year, roc_year, dimension, category, percent}，不加總、不重算

CSV 只讀不寫。轉換後會讀回 data.js 逐筆比對，不一致就停止。
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "work" / "travel_stats.csv"
OUT = ROOT / "docs" / "data.js"
VAR = "TRAVEL_DATA"
PREFIX = f"window.{VAR} = "

EXPECTED_COLS = ["year", "roc_year", "dimension", "category", "percent"]
EXPECTED_ROWS = 208
EXPECTED_YEARS = [1997, 1999, *range(2001, 2025)]
EXPECTED_CATEGORIES = {
    "性別": ["男", "女"],
    "年齡": ["12-19", "20-29", "30-39", "40-49", "50-59", "60以上"],
}
# 原始 .ods 表末註記（原文照錄）
SOURCE_NOTE = "註：86年、88年資料來源為「國人國內旅遊狀況調查」，90年以前為每兩年調查一次，90年後更名為「臺灣旅遊狀況調查」。"


def fail(msg: str) -> None:
    print(f"停止：{msg}", file=sys.stderr)
    sys.exit(1)


def read_csv() -> tuple[list[dict], list[dict]]:
    """回傳 (原始字串列, 轉型後的列)。"""
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != EXPECTED_COLS:
            fail(f"CSV 欄位為 {reader.fieldnames}，預期 {EXPECTED_COLS}")
        raw = list(reader)
    rows = [{"year": int(r["year"]), "roc_year": int(r["roc_year"]),
             "dimension": r["dimension"], "category": r["category"],
             "percent": float(r["percent"])} for r in raw]
    return raw, rows


def check(rows: list[dict], label: str) -> None:
    problems = []
    if len(rows) != EXPECTED_ROWS:
        problems.append(f"筆數 {len(rows)}，預期 {EXPECTED_ROWS}")
    years = sorted({r["year"] for r in rows})
    if years != EXPECTED_YEARS:
        problems.append(f"年份 {years}，預期 {EXPECTED_YEARS}")
    dims = {r["dimension"] for r in rows}
    if dims != set(EXPECTED_CATEGORIES):
        problems.append(f"維度 {sorted(dims)}，預期 {list(EXPECTED_CATEGORIES)}")
    for dim, cats in EXPECTED_CATEGORIES.items():
        found = {r["category"] for r in rows if r["dimension"] == dim}
        if found != set(cats):
            problems.append(f"{dim} 分類 {sorted(found)}，預期 {cats}")
    if problems:
        fail(f"{label}核對失敗：" + "；".join(problems))


def main() -> None:
    sha_before = hashlib.sha256(SRC.read_bytes()).hexdigest()
    raw, rows = read_csv()
    check(rows, "CSV ")

    data = {
        "meta": {
            "title": "歷年國人國內旅行按性別及年齡分",
            "title_en": "Domestic Travelers by Gender and Age",
            "unit": "%",
            "description": "各年度國內旅行者中，各性別、各年齡層所占百分比",
            "source_file": "1997、1999、2001~2024年國人國內旅行按性別及年齡統計.ods",
            "source_note": SOURCE_NOTE,
            "years": EXPECTED_YEARS,
            "dimensions": list(EXPECTED_CATEGORIES),
            "categories": EXPECTED_CATEGORIES,
        },
        "rows": rows,
    }

    OUT.parent.mkdir(exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=1)
    OUT.write_text(
        "// 由 work/build_data.py 從 work/travel_stats.csv 產生，請勿手動修改。\n"
        f"{PREFIX}{body};\n",
        encoding="utf-8",
    )

    # 讀回 data.js，逐筆與 CSV 原始字串比對
    text = OUT.read_text(encoding="utf-8")
    start = text.index(PREFIX) + len(PREFIX)
    back = json.loads(text[start:text.rindex(";")])["rows"]
    check(back, "data.js ")
    for i, (src, out) in enumerate(zip(raw, back), 2):
        if ({k: str(v) for k, v in out.items() if k != "percent"} != {k: src[k] for k in EXPECTED_COLS if k != "percent"}
                or out["percent"] != float(src["percent"]) or repr(out["percent"]) != src["percent"]):
            fail(f"CSV 第 {i} 列與 data.js 不一致：CSV {src}，data.js {out}")

    if hashlib.sha256(SRC.read_bytes()).hexdigest() != sha_before:
        fail("travel_stats.csv 在執行期間被改動")

    print(f"已產生 {OUT.relative_to(ROOT)}（{OUT.stat().st_size:,} bytes）")
    print(f"核對通過：{len(back)} 筆、{len({r['year'] for r in back})} 個年份，"
          f"每筆的 year/roc_year/dimension/category/percent 與 CSV 完全一致")


if __name__ == "__main__":
    main()
