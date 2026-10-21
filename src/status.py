"""وضعیت مؤثر اخطار و اولویت‌بندی بر اساس باز بودن و سن اخطار.

قاعدهٔ کاری (درخواست کاربر):

۱) اخطار باز با تاریخ تایید در سال جاری ← اولویت ۱ «باز — سال جاری».
۲) اخطار باز با تاریخ تایید در ۱۲ ماه گذشته ← اولویت ۲ «باز — یک‌سال گذشته».
۳) اخطار بازِ قدیمی‌تر از ۱۲ ماه ← به‌صورت خودکار «خاتمه يافته» می‌شود
   (اولویت ۴ «خاتمهٔ خودکار») و وضعیت ثبت‌شدهٔ اصلی در ستون جداگانه می‌ماند.
۴) اخطار باز بدون تاریخ تایید ← باز می‌ماند ولی در اولویت ۳
   «باز — بدون تاریخ» گزارش می‌شود تا پنهان نشود.
۵) اخطار خاتمه‌یافتهٔ ثبت‌شده ← اولویت ۵ «خاتمه‌یافته».

مبنا «امروز» است؛ بنابراین با گذشت زمان، اخطارهای باز قدیمی‌تر خودبه‌خود
خاتمه‌یافته می‌شوند و نیازی به ویرایش دستی نیست.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .normalize import jalali_parts

CLOSED = "خاتمه يافته"

RAW_COLUMN = "وضعیت ثبت‌شده"
STATUS_COLUMN = "وضعیت اخطار"
AUTO_COLUMN = "خاتمهٔ خودکار"
PRIORITY_COLUMN = "اولویت اخطار"
PRIORITY_RANK = "رتبه اولویت"
MONTH_KEY = "کلید ماه"
DATE_KEY = "کلید تاریخ"

P1 = "باز — سال جاری"
P2 = "باز — یک‌سال گذشته"
P3 = "باز — بدون تاریخ"
P4 = "خاتمهٔ خودکار"
P5 = "خاتمه‌یافته"

PRIORITY_ORDER = (P1, P2, P3, P4, P5)


def today_jalali() -> tuple[int, int, int] | None:
    """تاریخ امروز به شمسی؛ اگر jdatetime نصب نباشد None."""
    try:
        import jdatetime

        now = jdatetime.date.today()
        return int(now.year), int(now.month), int(now.day)
    except Exception:  # pragma: no cover - فقط محیط بدون jdatetime
        return None


def cutoff_key(year: int, month: int) -> int:
    """کلید ماهِ مرزِ ۱۲ ماه پیش؛ مثال: ۱۴۰۵/۰۷ ← ۱۴۰۴۰۷."""
    total = year * 12 + (month - 1) - 12
    return (total // 12) * 100 + (total % 12 + 1)


def month_key_of(value: object) -> int:
    year, month, _ = jalali_parts(value)
    if year is None or month is None:
        return 0
    return int(year) * 100 + int(month)


def date_key_of(value: object) -> int:
    """کلید مرتب‌سازی روزانه: ۱۴۰۵/۰۷/۲۹ ← ۱۴۰۵۰۷۲۹."""
    year, month, day = jalali_parts(value)
    if year is None or month is None or day is None:
        return 0
    return int(year) * 10000 + int(month) * 100 + int(day)


def add_priority(
    frame: pd.DataFrame,
    today: tuple[int, int, int] | date | None = None,
    date_column: str = "تاریخ تایید",
) -> tuple[pd.DataFrame, dict]:
    """ستون‌های وضعیت مؤثر، خاتمهٔ خودکار و اولویت را اضافه می‌کند.

    ستون «وضعیت اخطار» به وضعیت مؤثر تبدیل می‌شود و وضعیت اصلی ورودی در
    «وضعیت ثبت‌شده» نگه داشته می‌شود. خروجی دوم خلاصهٔ آمار برای گزارش است.
    """
    result = frame.copy()

    # وضعیت خام را فقط یک بار نگه می‌داریم تا اجرای دوباره روی همان داده،
    # وضعیت خودکارِ قبلی را به‌عنوان وضعیت ثبت‌شده نگیرد.
    if RAW_COLUMN in result.columns:
        raw = result[RAW_COLUMN].fillna("").astype(str).str.strip()
    elif STATUS_COLUMN in result.columns:
        raw = result[STATUS_COLUMN].fillna("").astype(str).str.strip()
        result[RAW_COLUMN] = raw
    else:
        raw = pd.Series([""] * len(result), index=result.index)
        result[RAW_COLUMN] = raw

    if today is None:
        calculated = today_jalali()
    elif isinstance(today, date):
        calculated = (today.year, today.month, today.day)
    else:
        calculated = (int(today[0]), int(today[1]), int(today[2]))

    if calculated is None:
        # بدون تاریخ شمسی، هیچ اخطاری خودکار بسته نمی‌شود.
        calculated = (0, 0, 0)
    current_year, current_month, current_day = calculated
    cutoff = cutoff_key(current_year, current_month) if current_year else 0
    current_start = current_year * 100 + 1 if current_year else 0

    keys = [
        month_key_of(result.at[index, date_column]) if date_column in result.columns else 0
        for index in result.index
    ]
    date_keys = [
        date_key_of(result.at[index, date_column]) if date_column in result.columns else 0
        for index in result.index
    ]

    statuses: list[str] = []
    auto_flags: list[str] = []
    labels: list[str] = []
    ranks: list[int] = []
    auto_serials: list[dict] = []

    for index, raw_status, key in zip(result.index, raw, keys):
        if raw_status == CLOSED:
            statuses.append(CLOSED)
            auto_flags.append("خیر")
            labels.append(P5)
            ranks.append(5)
        elif not key:
            statuses.append(raw_status)
            auto_flags.append("خیر")
            labels.append(P3)
            ranks.append(3)
        elif not current_year:
            # بدون تاریخ امروز، هیچ اخطاری خودکار بسته نمی‌شود.
            statuses.append(raw_status)
            auto_flags.append("خیر")
            labels.append(P2)
            ranks.append(2)
        elif key >= current_start:
            statuses.append(raw_status)
            auto_flags.append("خیر")
            labels.append(P1)
            ranks.append(1)
        elif cutoff and key >= cutoff:
            statuses.append(raw_status)
            auto_flags.append("خیر")
            labels.append(P2)
            ranks.append(2)
        else:
            statuses.append(CLOSED)
            auto_flags.append("بله")
            labels.append(P4)
            ranks.append(4)
            serial = result.at[index, "سریال اخطار"] if "سریال اخطار" in result.columns else index
            try:
                serial = int(serial)
            except (TypeError, ValueError):
                serial = str(serial)
            date_value = result.at[index, date_column] if date_column in result.columns else ""
            auto_serials.append(
                {
                    "سریال اخطار": serial,
                    "تاریخ تایید": "" if pd.isna(date_value) else str(date_value),
                    "وضعیت ثبت‌شده": raw_status,
                }
            )

    result[STATUS_COLUMN] = statuses
    result[AUTO_COLUMN] = auto_flags
    result[PRIORITY_COLUMN] = labels
    result[PRIORITY_RANK] = ranks
    result[MONTH_KEY] = keys
    result[DATE_KEY] = date_keys

    counts = pd.Series(labels).value_counts().to_dict()
    stats = {
        "today": f"{current_year:04d}/{current_month:02d}/{current_day:02d}" if current_year else "",
        "current_year": current_year,
        "cutoff": cutoff,
        "cutoff_label": f"{cutoff // 100:04d}/{cutoff % 100:02d}" if cutoff else "",
        "counts": {label: int(counts.get(label, 0)) for label in PRIORITY_ORDER},
        "open": int(sum(1 for status in statuses if status != CLOSED)),
        "auto_closed": len(auto_serials),
        "auto_serials": auto_serials,
    }
    return result, stats


def sort_for_report(frame: pd.DataFrame) -> pd.DataFrame:
    """مرتب‌سازی پیش‌فرض: اولویت، سپس جدیدترین تاریخ، سپس سریال بزرگ‌تر."""
    if PRIORITY_RANK not in frame.columns or DATE_KEY not in frame.columns:
        return frame
    columns = [PRIORITY_RANK, DATE_KEY] + (["سریال اخطار"] if "سریال اخطار" in frame.columns else [])
    ascending = [True, False] + ([False] if "سریال اخطار" in frame.columns else [])
    return frame.sort_values(columns, ascending=ascending, kind="stable")
