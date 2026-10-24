"""محل نگهداری داده‌های کاربر و پشتیبان‌گیری خودکار.

هنگام به‌روزرسانی برنامه (گرفتن نسخهٔ تازه یا ساخت دوبارهٔ گزارش)، داده‌هایی که
کاربر وارد کرده باید از بین نرود؛ بنابراین همهٔ داده‌های دستی بیرون از پوشهٔ
خروجی و در پوشهٔ `data/` نگه داشته می‌شوند:

- `data/8d-forms.json` — فرم‌های 8D که در داشبورد تکمیل و ذخیره شده‌اند
- `data/اصلاح ایرادها.xlsx` — اصلاح دستی متن ایراد مشتری
- `data/اصلاحات گروه‌بندی.xlsx` — اصلاح دستی گروه/خانواده/محصول/برنچ
- `data/backups/` — نسخهٔ پشتیبان خودکار پیش از هر ذخیره یا ساخت گزارش

اگر نسخهٔ قدیمی فایل‌ها در ریشهٔ پروژه یا در `output/` باشد، یک بار به `data/`
منتقل (کپی) می‌شود و از آن به بعد همان نسخهٔ `data/` مبنا است.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
OUTPUT_DIR = ROOT / "output"

FORMS_NAME = "8d-forms.json"
DEFECT_OVERRIDES_NAME = "اصلاح ایرادها.xlsx"
GROUP_OVERRIDES_NAME = "اصلاحات گروه‌بندی.xlsx"

BACKUP_KEEP = 40


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def forms_path() -> Path:
    """مسیر فایل فرم‌های 8D؛ در صورت وجود نسخهٔ قدیمی، یک بار منتقل می‌شود."""
    ensure_data_dir()
    target = DATA_DIR / FORMS_NAME
    legacy = OUTPUT_DIR / FORMS_NAME
    if not target.exists() and legacy.exists():
        shutil.copy2(legacy, target)
    return target


def resolve_input(name: str) -> Path:
    """فایل‌های ورودی قابل ویرایش کاربر را از `data/` (یا یک بار از ریشه) می‌گیرد.

    اگر فایل فقط در ریشهٔ پروژه باشد، به `data/` کپی می‌شود تا ویرایش‌های بعدی
    روی نسخهٔ پایدار انجام شود و با به‌روزرسانی برنامه پاک نشود.
    """
    ensure_data_dir()
    target = DATA_DIR / name
    legacy = ROOT / name
    if not target.exists() and legacy.exists():
        shutil.copy2(legacy, target)
    return target if target.exists() else legacy


def backup(path: str | Path, keep: int = BACKUP_KEEP) -> Path | None:
    """یک نسخهٔ زمان‌دار از فایل می‌سازد و نسخه‌های قدیمی را هرس می‌کند."""
    source = Path(path)
    if not source.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{source.stem}-{stamp}{source.suffix}"
    if not target.exists():
        shutil.copy2(source, target)
    _prune(source.stem, keep)
    return target


def _prune(stem: str, keep: int) -> None:
    files = sorted(BACKUP_DIR.glob(f"{stem}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def watched_paths() -> list[Path]:
    """فایل‌هایی که تغییرشان باید گزارش را خودکار تازه کند."""
    paths: list[Path] = []
    for name in (
        "گزارش اخطار کيفي (3).xlsx",
        "ListData - 2026-10-21T094225.228.xlsx",
        "گروه بندی محصولات.xlsx",
        "C_Plus_405(20).xlsx",
        "QA-DA-02-C.docx",
    ):
        for base in (DATA_DIR, ROOT):
            candidate = base / name
            if candidate.exists():
                paths.append(candidate)
                break
    # فرم‌های 8D در داشبورد زنده خوانده می‌شوند؛ ذخیرهٔ فرم نیازی به ساخت دوباره ندارد
    for name in (DEFECT_OVERRIDES_NAME, GROUP_OVERRIDES_NAME):
        candidate = DATA_DIR / name
        if candidate.exists():
            paths.append(candidate)
    paths.extend(sorted((ROOT / "src").glob("*.py")))
    paths.append(ROOT / "build_report.py")
    return paths


def fingerprint(paths: list[Path] | None = None) -> dict[str, int]:
    """اثر انگشت فایل‌ها (زمان تغییر) برای تشخیص خودکار تغییرات."""
    result: dict[str, int] = {}
    for path in paths if paths is not None else watched_paths():
        try:
            result[str(path)] = path.stat().st_mtime_ns
        except OSError:
            continue
    return result
