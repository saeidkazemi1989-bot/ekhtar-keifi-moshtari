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

# فایل‌های ورودی خام (گزارش اخطار، کاتالوگ راهکاران، گروه‌بندی محصولات، برگه‌های
# بررسی و قالب 8D). هر فایل تازه‌ای که با همین کلید در داشبورد بارگذاری شود در
# `data/inputs/` و با تاریخ نسخه در نام ذخیره می‌شود و از آن به بعد مبنای ساخت
# گزارش است؛ نسخهٔ قبلی هم به `data/backups/inputs/` منتقل می‌شود.
INPUT_DIR_NAME = "inputs"
BACKUP_KEEP = 40

# کلید ورودی ← (نام فایل پیش‌فرض در ریشهٔ پروژه، نام نمایشی فارسی)
INPUT_FILES: dict[str, tuple[str, str]] = {
    "warnings": ("گزارش اخطار کيفي (3).xlsx", "گزارش اخطارهای کیفی"),
    "listdata": ("ListData - 2026-10-21T094225.228.xlsx", "کاتالوگ محصولات راهکاران (ListData)"),
    "catalog": ("گروه بندی محصولات.xlsx", "فایل گروه‌بندی محصولات"),
    "review": ("C_Plus_405(20).xlsx", "برگه‌های بررسی مشتری (C_Plus)"),
    "template": ("QA-DA-02-C.docx", "قالب رسمی فرم 8D"),
    "manual": ("فرم ثبت محصولات برگشتی1403.xlsx", "فرم دستی محصولات برگشتی (الگوی ایراد)"),
}

INPUT_LABELS = {key: label for key, (_name, label) in INPUT_FILES.items()}

# پسوندهای مجاز برای بارگذاری هر ورودی
INPUT_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "warnings": (".xlsx", ".xlsm"),
    "listdata": (".xlsx", ".xlsm"),
    "catalog": (".xlsx", ".xlsm"),
    "review": (".xlsx", ".xlsm"),
    "template": (".docx",),
    "manual": (".xlsx", ".xlsm"),
}

# بزرگ‌ترین حجم مجاز برای هر فایل ورودی (مگابایت)
INPUT_MAX_MB = 60


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


# --------------------------------------------------------------- فایل‌های ورودی
def inputs_dir() -> Path:
    """پوشهٔ نسخه‌های بارگذاری‌شدهٔ فایل‌های ورودی."""
    target = DATA_DIR / INPUT_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def input_backup_dir() -> Path:
    """پوشهٔ نسخه‌های قبلی فایل‌های ورودی (قبل از جایگزینی)."""
    target = BACKUP_DIR / INPUT_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def input_key_of_name(name: str) -> str | None:
    """نام فایل را به کلید ورودی نگاشت می‌کند (برای ارسال بدون کلید از داشبورد)."""
    text = " ".join(str(name).split()).lower()
    for key, (default_name, _label) in INPUT_FILES.items():
        if text == " ".join(default_name.split()).lower():
            return key
    # تطبیق نرم: کلمات کلیدی نام فایل پیش‌فرض
    keywords = {
        "warnings": ("اخطار", "اخطارها"),
        "listdata": ("listdata",),
        "catalog": ("گروه بندی محصولات", "گروه‌بندی محصولات"),
        "review": ("c_plus", "برگه بررسی", "برگه‌های بررسی"),
        "template": ("qa-da", "8d"),
        "manual": ("برگشتی",),
    }
    for key, words in keywords.items():
        if any(word in text for word in words):
            return key
    return None


def input_extension_ok(key: str, name: str) -> bool:
    allowed = INPUT_EXTENSIONS.get(key, ())
    return Path(name).suffix.lower() in allowed


def input_path(key: str) -> Path:
    """جدیدترین نسخهٔ بارگذاری‌شدهٔ یک ورودی؛ اگر نبود، فایل پیش‌فرض پروژه.

    مسیر برگشتی همیشه یک فایل قابل‌استفاده است (یا نسخهٔ بارگذاری‌شده در
    `data/inputs/` یا فایل اصلی کنار `build_report.py`). اگر هیچ‌کدام نبود،
    مسیر پیش‌فرض ریشه برگردانده می‌شود تا پیام خطای «فایل پیدا نشد» روشن بماند.
    """
    default_name = INPUT_FILES[key][0]
    uploaded = sorted(
        (inputs_dir().glob(f"{key}-*")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if uploaded:
        return uploaded[0]
    return ROOT / default_name


def input_paths() -> dict[str, Path]:
    """مسیر مؤثر همهٔ ورودی‌ها برای ساخت گزارش."""
    return {key: input_path(key) for key in INPUT_FILES}


def _input_versions(key: str) -> list[Path]:
    return sorted(inputs_dir().glob(f"{key}-*"), key=lambda p: p.stat().st_mtime, reverse=True)


def save_input(key: str, filename: str, payload: bytes) -> dict:
    """ذخیرهٔ نسخهٔ تازهٔ یک ورودی و پشتیبان‌گیری از نسخهٔ قبلی.

    نام فایل به‌شکل `key-YYYYmmdd-HHMMSS.ext` ذخیره می‌شود تا نسخه‌های قبلی
    قابل بازگشت بمانند و ساخت گزارش همیشه جدیدترین را بردارد.
    """
    if key not in INPUT_FILES:
        raise KeyError(f"ورودی ناشناخته: {key}")
    if not payload:
        raise ValueError("فایل خالی است")
    if not input_extension_ok(key, filename):
        allowed = "، ".join(INPUT_EXTENSIONS.get(key, ()))
        raise ValueError(f"پسوند فایل باید یکی از {allowed} باشد")
    target_dir = inputs_dir()
    previous = _input_versions(key)
    if previous:
        # نسخهٔ فعلی قبل از جایگزینی پشتیبان می‌شود
        backup_target = input_backup_dir() / f"{previous[0].stem}-{datetime.now():%Y%m%d-%H%M%S}{previous[0].suffix}"
        try:
            if not backup_target.exists():
                shutil.copy2(previous[0], backup_target)
        except OSError:
            pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = Path(filename).suffix.lower()
    target = target_dir / f"{key}-{stamp}{suffix}"
    counter = 2
    while target.exists():
        target = target_dir / f"{key}-{stamp}-{counter}{suffix}"
        counter += 1
    target.write_bytes(payload)
    # نسخه‌های بارگذاری‌شده هر ورودی: ۵ نسخهٔ آخر نگه داشته می‌شود
    for old in _input_versions(key)[5:]:
        try:
            old.unlink()
        except OSError:
            pass
    return input_status(key)


def input_status(key: str) -> dict:
    """وضعیت یک ورودی: مسیر، تاریخ، حجم و اینکه بارگذاری شده یا فایل اصلی است."""
    default_name, label = INPUT_FILES[key]
    path = input_path(key)
    versions = _input_versions(key)
    uploaded = path if path in versions else None
    stats = {"key": key, "label": label, "defaultName": default_name}
    if not path.exists():
        stats.update({"exists": False, "uploaded": False, "name": path.name})
        return stats
    info = path.stat()
    stats.update(
        {
            "exists": True,
            "uploaded": bool(uploaded),
            "name": path.name,
            "sizeMB": round(info.st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "modifiedNs": info.st_mtime_ns,
            "versions": len(versions),
        }
    )
    return stats


def inputs_status() -> list[dict]:
    return [input_status(key) for key in INPUT_FILES]


def watched_paths() -> list[Path]:
    """فایل‌هایی که تغییرشان باید گزارش را خودکار تازه کند."""
    paths: list[Path] = []
    # هم نسخهٔ بارگذاری‌شده (data/inputs) و هم فایل اصلی ریشه؛ اگر فایل تازه‌ای
    # در داشبورد بارگذاری شود، اثر انگشت عوض می‌شود و گزارش خودکار ساخته می‌شود.
    for key, (name, _label) in INPUT_FILES.items():
        candidate = ROOT / name
        if candidate.exists():
            paths.append(candidate)
        if key in {"warnings", "listdata", "catalog", "review", "template"}:
            paths.extend(_input_versions(key))
    # فرم دستی «فرم ثبت محصولات برگشتی» هر زمان اضافه/ویرایش شود، الگو دوباره
    # یاد گرفته می‌شود و گزارش خودکار تازه می‌شود
    for base in (DATA_DIR, ROOT):
        for pattern in ("فرم ثبت محصولات برگشتی*.xls*", "*محصولات برگشتی*.xls*"):
            paths.extend(sorted(base.glob(pattern)))
    # فرم‌های 8D در داشبورد زنده خوانده می‌شوند؛ ذخیرهٔ فرم نیازی به ساخت دوباره ندارد
    for name in (DEFECT_OVERRIDES_NAME, GROUP_OVERRIDES_NAME):
        candidate = DATA_DIR / name
        if candidate.exists():
            paths.append(candidate)
    paths.extend(sorted((ROOT / "src").glob("*.py")))
    paths.append(ROOT / "build_report.py")
    return list(dict.fromkeys(paths))


def fingerprint(paths: list[Path] | None = None) -> dict[str, int]:
    """اثر انگشت فایل‌ها (زمان تغییر) برای تشخیص خودکار تغییرات."""
    result: dict[str, int] = {}
    for path in paths if paths is not None else watched_paths():
        try:
            result[str(path)] = path.stat().st_mtime_ns
        except OSError:
            continue
    return result
