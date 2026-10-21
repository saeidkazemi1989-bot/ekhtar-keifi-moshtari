"""اجرای کامل: خواندن ورودی‌ها ← تطبیق ← ساخت گزارش اکسل و داشبورد HTML.

اجرا:
    python build_report.py
خروجی‌ها در پوشهٔ output/ ساخته می‌شوند.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import pandas as pd

from src.aggregate import tech_table
from src.catalog import load_catalog
from src.mapper import ProductMapper, enrich_warnings, product_table
from src.report_excel import build_excel
from src.report_html import build_html

ROOT = Path(__file__).resolve().parent
WARNINGS_FILE = ROOT / "گزارش اخطار کيفي (3).xlsx"
LISTDATA_FILE = ROOT / "ListData - 2026-10-21T094225.228.xlsx"
CATALOG_FILE = ROOT / "گروه بندی محصولات.xlsx"
OUTPUT_DIR = ROOT / "output"
WARNINGS_SHEET = "گزارش اخطار کيفي"


def main() -> int:
    started = time.time()
    for path in (WARNINGS_FILE, LISTDATA_FILE, CATALOG_FILE):
        if not path.exists():
            print(f"فایل ورودی پیدا نشد: {path.name}", file=sys.stderr)
            return 2

    print("۱) خواندن فایل‌های ورودی…")
    warnings = pd.read_excel(WARNINGS_FILE, sheet_name=WARNINGS_SHEET)
    catalog = load_catalog(CATALOG_FILE)
    print(f"   اخطار: {len(warnings):,} ردیف | کاتالوگ: {len(catalog.products):,} محصول")

    print("۲) ساخت نقشهٔ محصولات و تطبیق اخطارها…")
    mapper = ProductMapper(LISTDATA_FILE, catalog)
    enriched = enrich_warnings(warnings, mapper)
    products = product_table(mapper)
    techs = tech_table(enriched)
    print(f"   نقشه محصولات: {len(products):,} | شماره فنی یکتا: {len(techs):,}")

    in_catalog = int((enriched["در فایل گروه‌بندی"] == "بله").sum())
    in_scope = int((enriched["در دامنه گروه‌بندی"] == "بله").sum())
    review = int((enriched["نیاز به بازبینی"] == "بله").sum())
    print(f"   در کاتالوگ: {in_catalog:,} | در دامنه: {in_scope:,} | نیاز به بازبینی: {review:,}")

    sources = {
        "warnings": WARNINGS_FILE.name,
        "listdata": LISTDATA_FILE.name,
        "catalog": CATALOG_FILE.name,
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    excel_path = OUTPUT_DIR / "گزارش دسته‌بندی اخطارهای کیفی.xlsx"
    html_path = OUTPUT_DIR / "داشبورد اخطارهای کیفی.html"

    print("۳) ساخت گزارش اکسل…")
    build_excel(enriched, products, techs, excel_path, sources)
    print(f"   {excel_path.relative_to(ROOT)}")

    print("۴) ساخت داشبورد HTML…")
    build_html(enriched, html_path, sources)
    shutil.copyfile(html_path, OUTPUT_DIR / "index.html")  # برای نمایش مستقیم با وب‌سرور
    print(f"   {html_path.relative_to(ROOT)}")

    # خروجی کمکی برای بازبینی/ویرایش دستی نقشه‌ها
    enriched.to_excel(OUTPUT_DIR / "داده کامل اخطارها.xlsx", index=False)
    stop = time.time()
    print(f"پایان در {stop - started:.1f} ثانیه.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
