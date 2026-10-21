"""ابزارهای نرمال‌سازی متن فارسی و شماره فنی.

هدف: یکسان‌سازی «ي/ك» عربی، ارقام فارسی/عربی، نیم‌فاصله، علائم و فاصله‌ها
تا مقایسهٔ نام محصول‌ها و شماره‌های فنی دقیق و قابل تکرار باشد.
"""

from __future__ import annotations

import re

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

_CHARS = str.maketrans(
    {
        "ي": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ؤ": "و",
        "ئ": "ی",
        "ى": "ی",
    }
)

# کاراکترهای کنترلی جهت‌دهی، نیم‌فاصله، کشیده و اعراب
_IGNORED = re.compile(r"[\u200b-\u200f\u202a-\u202e\u064b-\u0652\u0640\ufeff]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_TECH_NOISE = re.compile(r"[^A-Z0-9]")


def normalize(value: object) -> str:
    """متن را برای مقایسهٔ واژه‌ای نرمال می‌کند (فاصله‌ها حفظ می‌شوند)."""
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "none", "null"}:
        return ""
    text = text.translate(_DIGITS).translate(_CHARS)
    text = _IGNORED.sub(" ", text)
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text)
    return text.strip()


def squash(value: object) -> str:
    """نسخهٔ بدون فاصلهٔ متن؛ برای تطبیق کلیدواژه‌هایی که با فاصله شکسته شده‌اند."""
    return normalize(value).replace(" ", "")


def tech_key(value: object) -> str:
    """کلید مقایسهٔ شماره فنی (حذف IK، صفرهای ابتدایی و علائم)."""
    if value is None:
        return ""
    text = str(value).translate(_DIGITS).upper()
    text = _IGNORED.sub("", text)
    text = _TECH_NOISE.sub("", text)
    text = re.sub(r"^IK", "", text)
    text = text.lstrip("0")
    return text


def tech_variants(value: object) -> set[str]:
    """کلیدهای ممکن یک شماره فنی برای تطبیق مقاوم."""
    if value is None:
        return set()
    raw = str(value).translate(_DIGITS).upper()
    raw = _IGNORED.sub("", raw)
    raw = _TECH_NOISE.sub("", raw)
    if not raw:
        return set()
    variants = {raw}
    if raw.startswith("IK"):
        variants.add(raw[2:])
    if raw.startswith("K"):
        variants.add(raw[1:])
    stripped = raw
    for prefix in ("IK", "K"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
    variants.add(stripped)
    variants.update({item.lstrip("0") for item in list(variants)})
    return {item for item in variants if item and item.strip("0")}


def is_probably_tech(value: object) -> bool:
    """آیا مقدار، شماره فنی معتبر است (نه خالی/علامت سؤال/شرح)؟"""
    if value is None:
        return False
    text = str(value).strip()
    if not text or text in {"-", "//", "?", "؟", "؟؟؟", "???"}:
        return False
    return bool(re.search(r"\d", text))


def jalali_parts(value: object) -> tuple[int | None, int | None, int | None]:
    """سال/ماه/روز تاریخ جلالی را برمی‌گرداند؛ برای مقادیر نامعتبر None."""
    if value is None:
        return (None, None, None)
    text = str(value).translate(_DIGITS)
    match = re.match(r"^\s*(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})\s*$", text)
    if not match:
        return (None, None, None)
    year, month, day = (int(x) for x in match.groups())
    if not (1300 <= year <= 1500 and 1 <= month <= 12 and 1 <= day <= 31):
        return (None, None, None)
    return (year, month, day)
