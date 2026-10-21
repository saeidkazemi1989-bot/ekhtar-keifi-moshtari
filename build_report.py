"""اجرای کامل: خواندن ورودی‌ها ← تطبیق ← ساخت گزارش اکسل و داشبورد HTML.

اجرا:
    python build_report.py            # ساخت گزارش
    python build_report.py --check    # فقط بررسی پیش‌نیازها و فایل‌های ورودی
    python build_report.py --pause    # در پایان منتظر زدن Enter می‌ماند

خروجی‌ها در پوشهٔ output/ ساخته می‌شوند و گزارش کامل در output/build.log ثبت می‌شود.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
LOG_FILE = OUTPUT_DIR / "build.log"

# اجرای اسکریپت از هر پوشه‌ای مجاز باشد
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WARNINGS_FILE = ROOT / "گزارش اخطار کيفي (3).xlsx"
LISTDATA_FILE = ROOT / "ListData - 2026-10-21T094225.228.xlsx"
CATALOG_FILE = ROOT / "گروه بندی محصولات.xlsx"
REVIEW_FILE = ROOT / "C_Plus_405(20).xlsx"
OVERRIDES_FILE = ROOT / "اصلاحات گروه‌بندی.xlsx"
EIGHT_D_TEMPLATE = ROOT / "QA-DA-02-C.docx"
WARNINGS_SHEET = "گزارش اخطار کيفي"

REQUIRED_MODULES = {
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "rapidfuzz": "rapidfuzz",
    "jdatetime": "jdatetime",
}


# --------------------------------------------------------------------- گزارش‌گیری
def _setup_console() -> None:
    """در ویندوز، چاپ متن فارسی را در کنسول فعال می‌کند."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def log(message: str = "") -> None:
    print(message, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


def fail(message: str) -> None:
    log("")
    log("خطا: " + message)
    log("")
    log("راهنما: فایل README.md بخش «عیب‌یابی» را ببینید.")


# --------------------------------------------------------------------- بررسی‌ها
def check_dependencies() -> list[str]:
    missing = []
    for module, package in REQUIRED_MODULES.items():
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    return missing


def check_inputs() -> list[Path]:
    return [path for path in (WARNINGS_FILE, LISTDATA_FILE, CATALOG_FILE) if not path.exists()]


def print_environment() -> None:
    log(f"پایتون: {sys.version.split()[0]}  ({sys.executable})")
    log(f"پوشهٔ پروژه: {ROOT}")
    log("")
    log("فایل‌های ورودی:")
    for path in (WARNINGS_FILE, LISTDATA_FILE, CATALOG_FILE, REVIEW_FILE, EIGHT_D_TEMPLATE):
        if path.exists():
            size = path.stat().st_size / 1024
            log(f"  [موجود]  {path.name}  ({size:,.0f} کیلوبایت)")
        else:
            log(f"  [پیدا نشد]  {path.name}")
    log("")


def run_check() -> int:
    problems = 0
    log("بررسی پیش‌نیازها")
    log("=" * 60)
    log(f"پایتون: {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 10):
        log("  [خطا] نسخهٔ پایتون باید ۳.۱۰ یا بالاتر باشد.")
        problems += 1
    missing = check_dependencies()
    if missing:
        log("  [خطا] این کتابخانه‌ها نصب نیستند: " + ", ".join(missing))
        log("        نصب با دستور:  pip install -r requirements.txt")
        problems += 1
    else:
        log("  [OK] همهٔ کتابخانه‌های لازم نصب هستند.")
    absent = check_inputs()
    if absent:
        log("  [خطا] این فایل‌های ورودی در پوشهٔ پروژه نیستند:")
        for path in absent:
            log("        " + path.name)
        problems += 1
    else:
        log("  [OK] هر سه فایل ورودی موجود هستند.")
    log("")
    if problems:
        log(f"نتیجه: {problems} مشکل پیدا شد.")
        return 1
    log("نتیجه: همه‌چیز آماده است؛ اجرا کنید:  python build_report.py")
    return 0


# --------------------------------------------------------------------- اجرا
def main() -> int:
    started = time.time()
    OUTPUT_DIR.mkdir(exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")

    log("ساخت گزارش دسته‌بندی اخطارهای کیفی")
    log("=" * 60)

    missing = check_dependencies()
    if missing:
        fail("این کتابخانه‌ها نصب نیستند: " + ", ".join(missing))
        log("دستور نصب:  pip install -r requirements.txt")
        return 3

    absent = check_inputs()
    if absent:
        fail("فایل‌های ورودی زیر پیدا نشدند: " + "، ".join(p.name for p in absent))
        log("این فایل‌ها باید کنار build_report.py در پوشهٔ پروژه باشند.")
        print_environment()
        return 2

    # ایمپورت‌ها بعد از بررسی انجام می‌شوند تا پیام خطا خوانا باشد
    import pandas as pd

    from src.aggregate import tech_table
    from src.catalog import load_catalog
    from src.mapper import ProductMapper, enrich_warnings, product_table
    from src.report_8d import build_8d_document, build_official_form
    from src.report_excel import build_excel
    from src.report_html import build_html
    from src.overrides import apply_overrides, load_overrides
    from src.review import attach_review, eight_d_rows, grouping_checks, load_claims, load_review

    log("۱) خواندن فایل‌های ورودی…")
    warnings = pd.read_excel(WARNINGS_FILE, sheet_name=WARNINGS_SHEET)
    catalog = load_catalog(CATALOG_FILE)
    log(f"   اخطار: {len(warnings):,} ردیف | کاتالوگ: {len(catalog.products):,} محصول")

    log("۲) ساخت نقشهٔ محصولات و تطبیق اخطارها…")
    mapper = ProductMapper(LISTDATA_FILE, catalog)
    enriched = enrich_warnings(warnings, mapper)

    # برگه‌های بررسی و کلیم‌ها بر اساس سریال اخطار به داده متصل می‌شوند
    unmatched_review = None
    if REVIEW_FILE.exists():
        review = load_review(REVIEW_FILE)
        claims = load_claims(REVIEW_FILE)
        enriched, unmatched_review = attach_review(enriched, review, claims)
        log(f"   برگه بررسی: {len(review):,} | متصل: {(enriched['دارای برگه بررسی'] == 'بله').sum():,} | بدون اخطار متناظر: {len(unmatched_review)}")
    else:
        log("   فایل بررسی اخطارها پیدا نشد؛ گزارش بدون برگهٔ بررسی ساخته می‌شود.")

    # اصلاحات دستی گروه‌بندی (اختیاری)
    if OVERRIDES_FILE.exists():
        overrides = load_overrides(OVERRIDES_FILE)
        enriched, fixed = apply_overrides(enriched, overrides)
        log(f"   اصلاح دستی گروه‌بندی: {fixed:,} ردیف")
    else:
        log("   فایل اصلاحات گروه‌بندی نیست (اختیاری).")

    products = product_table(mapper)
    techs = tech_table(enriched)
    log(f"   نقشه محصولات: {len(products):,} | شماره فنی یکتا: {len(techs):,}")

    in_catalog = int((enriched["در فایل گروه‌بندی"] == "بله").sum())
    in_scope = int((enriched["در دامنه گروه‌بندی"] == "بله").sum())
    review = int((enriched["نیاز به بازبینی"] == "بله").sum())
    log(f"   در کاتالوگ: {in_catalog:,} | در دامنه: {in_scope:,} | نیاز به بازبینی: {review:,}")

    sources = {
        "warnings": WARNINGS_FILE.name,
        "listdata": LISTDATA_FILE.name,
        "catalog": CATALOG_FILE.name,
    }

    excel_path = OUTPUT_DIR / "گزارش دسته‌بندی اخطارهای کیفی.xlsx"
    html_path = OUTPUT_DIR / "داشبورد اخطارهای کیفی.html"
    data_path = OUTPUT_DIR / "داده کامل اخطارها.xlsx"
    forms_path = OUTPUT_DIR / "فرم 8D اخطارها.docx"

    checks = grouping_checks(enriched)

    log("۳) ساخت فرم‌های 8D…")
    eight_d = pd.DataFrame()
    if EIGHT_D_TEMPLATE.exists():
        form_rows = eight_d_rows(enriched)
        serial_arg = _option_value("--8d-serial")
        if serial_arg:
            match = form_rows[form_rows["سریال اخطار"].astype(str) == str(serial_arg)]
            if match.empty:
                fail(f"اخطاری با سریال {serial_arg} پیدا نشد.")
                return 4
            row = match.iloc[0]
            official = build_official_form(
                row,
                EIGHT_D_TEMPLATE,
                OUTPUT_DIR / "فرم 8D رسمی" / f"8D-{serial_arg}.docx",
            )
            log(f"   فرم رسمی QA-DA-02-C: {official.relative_to(ROOT)}")
            return 0
        build_8d_document(form_rows, EIGHT_D_TEMPLATE, forms_path)
        eight_d = form_rows
        forms = dict(zip(form_rows["سریال اخطار"], form_rows["شماره فرم 8D"]))
        enriched["شماره فرم 8D"] = [
            forms.get(serial, "") for serial in enriched["سریال اخطار"]
        ]
        log(f"   {len(form_rows):,} فرم 8D ساخته شد: {forms_path.name}")
    else:
        log("   قالب فرم 8D پیدا نشد؛ فرم‌ها ساخته نشدند.")

    log("۴) ساخت گزارش اکسل…")
    build_excel(
        enriched,
        products,
        techs,
        excel_path,
        sources,
        eight_d=eight_d,
        grouping_checks=checks,
        unmatched_review=unmatched_review,
    )
    log("   " + str(excel_path.relative_to(ROOT)))

    log("۵) ساخت داشبورد HTML…")
    build_html(enriched, html_path, sources, checks=checks, unmatched=unmatched_review)
    log("   " + str(html_path.relative_to(ROOT)))
    build_html(
        enriched,
        OUTPUT_DIR / "index.html",
        sources,
        data_file=OUTPUT_DIR / "dashboard-data.js",
        checks=checks,
        unmatched=unmatched_review,
    )
    log("   " + str((OUTPUT_DIR / "index.html").relative_to(ROOT)) + " + dashboard-data.js")

    enriched.to_excel(data_path, index=False)
    log("   " + str(data_path.relative_to(ROOT)))

    log("")
    log("فایل‌های ساخته‌شده:")
    for path in (excel_path, html_path, data_path, forms_path):
        if path.exists():
            log(f"  {path.name}  ({path.stat().st_size / 1024:,.0f} کیلوبایت)")
    log("")
    log(f"پایان در {time.time() - started:.1f} ثانیه. پوشهٔ خروجی: {OUTPUT_DIR}")
    return 0


def _option_value(name: str) -> str | None:
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def _pause_if_needed() -> None:
    if "--pause" in sys.argv or (sys.platform == "win32" and len(sys.argv) == 1 and sys.stdin.isatty()):
        try:
            input("\nبرای بستن پنجره Enter بزنید…")
        except Exception:
            pass


if __name__ == "__main__":
    _setup_console()
    try:
        if "--check" in sys.argv:
            code = run_check()
        else:
            code = main()
    except Exception:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write("\n" + traceback.format_exc() + "\n")
        log("")
        log("خطای پیش‌بینی‌نشده رخ داد:")
        log(traceback.format_exc())
        log("شرح کامل در فایل output/build.log ذخیره شد.")
        code = 1
    _pause_if_needed()
    raise SystemExit(code)
