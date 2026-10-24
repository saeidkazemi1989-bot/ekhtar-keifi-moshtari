"""ریشه‌یابی سریع ایراد از متن اخطار.

کاربر می‌خواهد در «نمای کلی» ببیند ریشهٔ ایرادها چیست (مثلاً «اتصالی» چند مورد
بوده) و پارتو قطعه نشان دهد. بیشتر متن‌های اخطار این ریشه را به‌صورت واژه
در «شرح منشا»، «توضیحات»، «شرح خطا» یا «آنالیز علت ایراد» دارند؛ این ماژول
آن واژه را به یک ریشهٔ یکتا تبدیل می‌کند و اگر هیچ نشانه‌ای نبود «اعلام نشده»
می‌گذارد (هیچ ریشه‌ای به‌زور حدس زده نمی‌شود).
"""
from __future__ import annotations

import pandas as pd

from src.normalize import normalize, squash

ROOT_COLUMN = "ریشهٔ ایراد"
PART_COLUMN = "قطعهٔ ریشه"

# ترتیب مهم است: قاعدهٔ خاص‌تر اول بررسی می‌شود
ROOT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("اتصالی", ("اتصالي", "اتصالی", "اتصال کوتاه", "شورت", "سوختگي", "سوختگی", "سوخته", "سوزاندن")),
    ("نشتی", ("نشت", "چکه", "آب بندي", "آب بندی", "آب‌بندی")),
    ("شکستگی / ترک", ("شکست", "شکستگي", "شکستگی", "ترک خورد", "ترکي", "ترک برداشت", "پارگ", "خرد شد")),
    ("نرم‌افزار", ("نرم افزار", "نرم‌افزار", "برنامه", "کاليبر", "کالیبر", "فالت", "پيکربندي", "پیکربندی", "تعریف کد", "پارامتر", "ورژن")),
    ("سیم و سوکت", ("سيم", "سیم", "سوکت", "کابل", "شلنگ", "کانکتور", "ترمينال", "ترمینال")),
    ("صدای غیرعادی", ("صدا", "لرزش", "سوت", "تق تق", "وزوز")),
    ("مونتاژ", ("مونتاژ", "جا نيافت", "جا نیفت", "قفل نشد", "گير کرد", "گیر کرد", "شل ", "لق ", "بست نبود", "پيچ", "پیچ", "هم راستا", "همراستا", "نصب اشتباه", "تكميل كاري", "تکمیل کاری")),
    ("بسته‌بندی و لیبل", ("ليبل", "لیبل", "برچسب", "بسته بندي", "بسته بندی", "بسته‌بندی")),
    ("ظاهری / دفرمگی", ("خش ", "خراش", "پوسته", "دفرم", "کجي", "کجی", "رنگ ", "شکاف", "سوراخ")),
    ("عدم دریافت قطعه", ("عدم دريافت", "عدم دریافت", "کمبود", "نرسيد", "نرسید")),
    ("خطای اپراتور", ("اپراتور", "نيروي انساني", "نیروی انسانی", "خطاي انساني", "خطای انسانی")),
    ("قالب", ("قالب", "تزريق", "تزریق")),
    ("قطعه معیوب", ("معيوب", "معیوب", "خراب", "ايراد داخلي", "ایراد داخلی", "سالم نبود", "نقص كيفي", "نقص کیفی", "ايراد كيفي قطعه", "ایراد کیفی قطعه")),
)

UNKNOWN_ROOT = "اعلام نشده"
UNKNOWN_PART = "نامشخص"

TEXT_COLUMNS = ("شرح منشا", "توضیحات", "شرح خطا", "آنالیز علت ایراد", "ایراد مشتری")


def _column_map(frame: pd.DataFrame) -> dict[str, str]:
    """نگاشت نام نرمال‌شدهٔ ستون‌ها به نام واقعی (تفاوت ي/ی و ک/ك)."""
    return {squash(name): str(name) for name in frame.columns}


def _pick(frame: pd.DataFrame, column: str, mapping: dict[str, str] | None = None) -> str | None:
    mapping = mapping or _column_map(frame)
    key = squash(column)
    if key in mapping:
        return mapping[key]
    for candidate_key, name in mapping.items():
        if key and (key in candidate_key or candidate_key in key) and len(key) > 4:
            return name
    return None


def _haystack(row: pd.Series) -> str:
    parts = []
    mapping = _column_map(pd.DataFrame(columns=row.index))
    for column in TEXT_COLUMNS:
        actual = _pick(pd.DataFrame(columns=row.index), column, mapping)
        if actual:
            parts.append(str(row.get(actual) or ""))
    return normalize(" ".join(parts))


def root_cause(text: str) -> str:
    """ریشهٔ ایراد از متن نرمال‌شده (یا «اعلام نشده»)."""
    padded = f" {text} "
    for name, keywords in ROOT_RULES:
        for keyword in keywords:
            key = normalize(keyword)
            if not key:
                continue
            if key.endswith(" "):
                # واژهٔ کوتاه باید تنها و کامل بیاید تا «شل» با «شلنگ» قاطی نشود
                if f" {key}" in padded:
                    return name
            elif key in padded:
                return name
    return UNKNOWN_ROOT


def add_root_cause(frame: pd.DataFrame) -> pd.DataFrame:
    """ستون‌های «ریشهٔ ایراد» و «قطعهٔ ریشه» را اضافه می‌کند."""
    if frame.empty:
        frame = frame.copy()
        frame[ROOT_COLUMN] = []
        frame[PART_COLUMN] = []
        return frame

    result = frame.copy()
    result[ROOT_COLUMN] = [_root_of_row(row) for _, row in result.iterrows()]
    result[PART_COLUMN] = _part_labels(result)
    return result


def _root_of_row(row: pd.Series) -> str:
    defect = str(row.get("ایراد مشتری") or "")
    if defect:
        label = root_cause(normalize(defect))
        if label != UNKNOWN_ROOT:
            return label
    return root_cause(_haystack(row))


def _part_labels(frame: pd.DataFrame) -> list[str]:
    """«شرح منشا» را گروه‌بندی می‌کند و کوتاه‌ترین شکل را به‌عنوان برچسب می‌گذارد."""
    column = "شرح منشا"
    actual = _pick(frame, column)
    if not actual:
        return [UNKNOWN_PART] * len(frame)
    raw = [" ".join(str(value or "").split()) for value in frame[actual]]
    keys = [squash(value) for value in raw]
    labels: dict[str, str] = {}
    for key, text in zip(keys, raw):
        if not key or len(text) < 3 or text.replace(".", "").isdigit():
            continue
        current = labels.get(key)
        if current is None or len(text) < len(current):
            labels[key] = text
    return [labels.get(key, UNKNOWN_PART) if key else UNKNOWN_PART for key in keys]


def root_summary(frame: pd.DataFrame, top: int = 8) -> pd.DataFrame:
    """جدول خلاصهٔ ریشه‌ها برای گزارش اکسل."""
    if frame.empty or ROOT_COLUMN not in frame.columns:
        return pd.DataFrame()
    counts = frame[ROOT_COLUMN].value_counts()
    share = counts / len(frame)
    return (
        pd.DataFrame(
            {
                ROOT_COLUMN: counts.index,
                "تعداد اخطار": counts.to_numpy(),
                "سهم": share.to_numpy(),
                "قطعهٔ ریشه یکتا": [
                    frame.loc[frame[ROOT_COLUMN] == name, PART_COLUMN].nunique()
                    if PART_COLUMN in frame.columns
                    else 0
                    for name in counts.index
                ],
            }
        )
        .head(top)
        .reset_index(drop=True)
    )
