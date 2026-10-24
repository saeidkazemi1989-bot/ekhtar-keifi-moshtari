"""اجرای کامل: خواندن ورودی‌ها ← تطبیق ← ساخت گزارش اکسل و داشبورد HTML.

اجرا:
    python build_report.py            # ساخت گزارش
    python build_report.py --check    # فقط بررسی پیش‌نیازها و فایل‌های ورودی
    python build_report.py --pause    # در پایان منتظر زدن Enter می‌ماند
    python build_report.py --defect-template   # ساخت فایل نمونهٔ اصلاح متن ایرادها
    python build_report.py --learn-defects "فرم ثبت محصولات برگشتی1403.xlsx"  # یادگیری دوبارهٔ الگوی دستی
    python build_report.py --no-pattern        # بدون استفاده از الگوی دستی

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
DEFECT_OVERRIDES_FILE = ROOT / "اصلاح ایرادها.xlsx"
EIGHT_D_TEMPLATE = ROOT / "QA-DA-02-C.docx"
WARNINGS_SHEET = "گزارش اخطار کيفي"

# داده‌ها و اصلاح‌های دستی در پوشهٔ پایدار data/ نگه داشته می‌شوند تا با
# به‌روزرسانی برنامه پاک نشوند (src/storage.py)
DATA_DIR = ROOT / "data"

REQUIRED_MODULES = {
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "rapidfuzz": "rapidfuzz",
    "jdatetime": "jdatetime",
}

# کتابخانه‌های اختیاری: نبودشان ساخت گزارش را متوقف نمی‌کند
OPTIONAL_MODULES = {
    "docx": "python-docx",
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
def check_dependencies(modules: dict[str, str] | None = None) -> list[str]:
    missing = []
    for module, package in (modules or REQUIRED_MODULES).items():
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
    optional_missing = check_dependencies(OPTIONAL_MODULES)
    if optional_missing:
        log("  [هشدار] این کتابخانه اختیاری نصب نیست: " + ", ".join(optional_missing))
        log("          بدون آن، فرم‌های 8D ساخته نمی‌شوند (بقیهٔ گزارش ساخته می‌شود).")
        log("          نصب:  pip install -r requirements.txt")
    else:
        log("  [OK] کتابخانهٔ فرم 8D (python-docx) نصب است.")
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

    optional_missing = check_dependencies(OPTIONAL_MODULES)
    if optional_missing:
        log("  [هشدار] این کتابخانه اختیاری نصب نیست: " + ", ".join(optional_missing))
        log("          بدون آن، فرم‌های 8D ساخته نمی‌شوند (بقیهٔ گزارش ساخته می‌شود).")
        log("          نصب:  pip install -r requirements.txt")
    else:
        log("  [OK] کتابخانهٔ فرم 8D (python-docx) نصب است.")
    absent = check_inputs()
    if absent:
        fail("فایل‌های ورودی زیر پیدا نشدند: " + "، ".join(p.name for p in absent))
        log("این فایل‌ها باید کنار build_report.py در پوشهٔ پروژه باشند.")
        print_environment()
        return 2

    # ایمپورت‌ها بعد از بررسی انجام می‌شوند تا پیام خطا خوانا باشد
    import pandas as pd

    from src import eight_d_store
    from src.aggregate import tech_table
    from src.catalog import add_branch, load_catalog
    from src import defect_learn
    from src.defects import add_defect_fields, apply_defect_overrides, load_defect_overrides, make_defect_template
    from src import storage
    from src.mapper import ProductMapper, enrich_warnings, product_table
    from src.report_8d import build_8d_document, build_official_form
    from src.report_excel import build_excel
    from src.report_html import build_html
    from src.analysis_part import add_analysis_part, part_summary
    from src.root_cause import add_root_cause, root_summary
    from src.overrides import apply_overrides, load_overrides
    from src.status import PRIORITY_ORDER, add_priority
    from src.review import attach_review, eight_d_rows, grouping_checks, load_claims, load_review

    storage.ensure_data_dir()
    if "--defect-template" in sys.argv:
        path = make_defect_template(storage.DATA_DIR / DEFECT_OVERRIDES_FILE.name)
        log(f"فایل نمونه ساخته شد: {path.relative_to(ROOT)}")
        log("سریال اخطار و متن درست را در آن بنویسید و دوباره گزارش را بسازید.")
        return 0

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
    overrides_file = storage.resolve_input(OVERRIDES_FILE.name)
    if overrides_file.exists():
        overrides = load_overrides(overrides_file)
        enriched, fixed = apply_overrides(enriched, overrides)
        log(f"   اصلاح دستی گروه‌بندی: {fixed:,} ردیف از {overrides_file.relative_to(ROOT)}")
    else:
        log("   فایل اصلاحات گروه‌بندی نیست (اختیاری).")

    # برنچ (ELE/EMS/POL) — از فایل گروه‌بندی و در صورت نبود، استنباط از خانواده
    enriched = add_branch(enriched, catalog)
    branch_counts = enriched["برنچ"].value_counts().to_dict()
    log("   برنچ: " + " | ".join(f"{k} {v:,}" for k, v in branch_counts.items()))

    # وضعیت مؤثر و اولویت: اخطارهای باز قدیمی‌تر از یک سال خودکار خاتمه می‌یابند
    enriched, status_stats = add_priority(enriched)
    counts = status_stats["counts"]
    log(
        f"   اولویت اخطار: "
        + " | ".join(f"{PRIORITY_ORDER[rank]} {counts.get(PRIORITY_ORDER[rank], 0):,}" for rank in range(5))
    )
    log(
        f"   مبنای امروز: {status_stats['today']} | مرز یک‌سال: {status_stats['cutoff_label']} | "
        f"خاتمهٔ خودکار: {status_stats['auto_closed']:,} | باز مؤثر: {status_stats['open']:,}"
    )

    # توصیف ایراد مشتری، دسته‌بندی دوگانه و یکسان‌سازی علت‌های بررسی
    defect_overrides = {}
    defect_overrides_file = storage.resolve_input(DEFECT_OVERRIDES_FILE.name)
    if defect_overrides_file.exists():
        defect_overrides = load_defect_overrides(defect_overrides_file)
        log(f"   اصلاح دستی متن ایراد: {len(defect_overrides):,} سریال از {defect_overrides_file.relative_to(ROOT)}")
    else:
        log("   فایل «اصلاح ایرادها.xlsx» نیست (اختیاری).")
    enriched = add_defect_fields(enriched)

    # الگوی دستی «فرم ثبت محصولات برگشتی»: اگر فایل باشد و الگو قدیمی باشد،
    # دوباره یاد گرفته می‌شود و متن ایراد با همان روش یکسان‌سازی می‌شود.
    manual_file = None
    learned = {}
    if "--no-pattern" not in sys.argv:
        requested = _option_value("--learn-defects")
        if requested:
            manual_file = Path(requested)
            if not manual_file.is_absolute():
                manual_file = ROOT / manual_file
        else:
            manual_file = defect_learn.find_manual_file(storage.DATA_DIR, ROOT)
        if manual_file and manual_file.exists():
            library_path = storage.DATA_DIR / defect_learn.LIBRARY_NAME
            stale = (
                "--learn-defects" in sys.argv
                or not library_path.exists()
                or library_path.stat().st_mtime < manual_file.stat().st_mtime
            )
            try:
                if stale:
                    payload = defect_learn.learn(manual_file, storage.DATA_DIR)
                    log(
                        f"   الگوی ایراد از «{manual_file.name}» یاد گرفته شد: "
                        f"{len(payload['patterns']):,} الگو از {payload['texts']:,} متن دستی"
                    )
                learned = defect_learn.load(storage.DATA_DIR)
            except Exception as error:
                log(f"   [هشدار] خواندن الگوی فایل دستی ناموفق بود: {error}")
        elif "--learn-defects" in sys.argv:
            fail("فایل «فرم ثبت محصولات برگشتی» پیدا نشد.")
            return 3

    if learned:
        enriched, sources = defect_learn.apply(enriched, learned)
        matched = sum(1 for source in sources if source.startswith("الگوی دستی"))
        log(
            f"   ایراد مطابق الگوی دستی: {matched:,} | "
            f"بدون الگو (استخراج خودکار): {len(sources) - matched:,}"
        )

    if defect_overrides:
        enriched = apply_defect_overrides(enriched, defect_overrides)
    enriched = defect_learn.refresh_keys(enriched)

    # ریشهٔ ایراد (اتصالی، نشتی، شکستگی، …) برای نمودار نمای کلی
    enriched = add_root_cause(enriched)
    roots = root_summary(enriched, top=5)
    if not roots.empty:
        top_roots = " | ".join(
            f"{row['ریشهٔ ایراد']} {int(row['تعداد اخطار']):,}" for _, row in roots.iterrows()
        )
        log(f"   ریشهٔ ایراد: {top_roots}")

    # «قطعه» از دل «آنالیز علت ایراد» برگهٔ بررسی (مثل میکرو، LCD، کانکتور)
    enriched = add_analysis_part(enriched)
    parts = part_summary(enriched)
    if not parts.empty:
        named = int(parts["تعداد برگهٔ بررسی"].sum())
        top_parts = " | ".join(
            f"{row['قطعهٔ تحلیل']} {int(row['تعداد برگهٔ بررسی']):,}" for _, row in parts.head(5).iterrows()
        )
        log(f"   قطعه در تحلیل (از {named:,} برگهٔ بررسی): {top_parts}")

    categories = enriched["دسته‌بندی ایراد"].value_counts().to_dict()
    log(
        f"   ایراد مشتری یکتا: {enriched['ایراد مشتری'].nunique():,} | "
        f"عملکردی/ظاهری: {categories.get('عملکردی', 0):,}/{categories.get('ظاهری', 0):,} | "
        f"علت استاندارد یکتا: {enriched['علت استاندارد'].nunique():,}"
    )

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
        "review": REVIEW_FILE.name,
    }
    if learned and manual_file:
        sources["manual_pattern"] = manual_file.name

    excel_path = OUTPUT_DIR / "گزارش دسته‌بندی اخطارهای کیفی.xlsx"
    html_path = OUTPUT_DIR / "داشبورد اخطارهای کیفی.html"
    data_path = OUTPUT_DIR / "داده کامل اخطارها.xlsx"
    forms_path = OUTPUT_DIR / "فرم 8D اخطارها.docx"

    checks = grouping_checks(enriched)

    log("۳) ساخت فرم‌های 8D…")
    eight_d = pd.DataFrame()
    forms_written = False
    store_file = eight_d_store.store_path()
    entries = eight_d_store.load(store_file)
    if entries:
        log(f"   فرم‌های ذخیره‌شده در داشبورد: {len(entries):,}")
    if not EIGHT_D_TEMPLATE.exists():
        log("   قالب فرم 8D پیدا نشد؛ فرم‌ها ساخته نشدند.")
    else:
        form_rows = eight_d_rows(enriched)          # فرم‌های فایل ورد (باز یا دارای بررسی)
        all_forms = eight_d_rows(enriched, scope="all")
        all_forms = eight_d_store.merge_into(all_forms, entries)
        docx_serials = set(form_rows["سریال اخطار"].astype(str))
        all_forms["در فایل ورد"] = [
            "بله" if str(s) in docx_serials else "خیر" for s in all_forms["سریال اخطار"]
        ]
        eight_d = all_forms
        forms = dict(zip(form_rows["سریال اخطار"], form_rows["شماره فرم 8D"]))
        enriched["شماره فرم 8D"] = [
            forms.get(serial, "") for serial in enriched["سریال اخطار"]
        ]
        serial_arg = _option_value("--8d-serial")
        if serial_arg:
            match = form_rows[form_rows["سریال اخطار"].astype(str) == str(serial_arg)]
            if match.empty:
                fail(f"اخطاری با سریال {serial_arg} پیدا نشد.")
                return 4
            try:
                official = build_official_form(
                    match.iloc[0],
                    EIGHT_D_TEMPLATE,
                    OUTPUT_DIR / "فرم 8D رسمی" / f"8D-{serial_arg}.docx",
                    entry=entries.get(str(serial_arg)),
                )
            except Exception as error:
                fail(f"ساخت فرم رسمی 8D ناموفق بود: {error}")
                log("دستور نصب:  pip install -r requirements.txt")
                return 5
            log(f"   فرم رسمی QA-DA-02-C: {official.relative_to(ROOT)}")
            return 0
        try:
            path, count = build_8d_document(
                form_rows, EIGHT_D_TEMPLATE, forms_path, entries=entries
            )
            forms_written = True
            log(f"   {count:,} فرم 8D ساخته شد: {path.name} (فرم برای هر {len(all_forms):,} اخطار در داشبورد)")
        except Exception as error:
            log(f"   [هشدار] فایل ورد فرم‌های 8D ساخته نشد: {error}")
            log("           بقیهٔ گزارش ساخته می‌شود. برای ساخت فرم‌ها اجرا کنید:")
            log("           pip install -r requirements.txt")
            log(f"   فهرست {len(form_rows):,} فرم در شیت «فرم 8D» گزارش اکسل هست.")

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
        entries=entries,
    )
    log("   " + str(excel_path.relative_to(ROOT)))

    log("۵) ساخت داشبورد HTML…")
    build_html(
        enriched,
        html_path,
        sources,
        checks=checks,
        unmatched=unmatched_review,
        entries=entries,
        status_stats=status_stats,
    )
    log("   " + str(html_path.relative_to(ROOT)))
    build_html(
        enriched,
        OUTPUT_DIR / "index.html",
        sources,
        data_file=OUTPUT_DIR / "dashboard-data.js",
        checks=checks,
        unmatched=unmatched_review,
        entries=entries,
        status_stats=status_stats,
    )
    log("   " + str((OUTPUT_DIR / "index.html").relative_to(ROOT)) + " + dashboard-data.js")

    enriched.to_excel(data_path, index=False)
    log("   " + str(data_path.relative_to(ROOT)))

    log("")
    log("فایل‌های ساخته‌شده:")
    for path in (excel_path, html_path, data_path, forms_path):
        if path == forms_path and not forms_written:
            log(f"  {path.name}  (ساخته نشد — python-docx نصب نیست)")
        elif path.exists():
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
