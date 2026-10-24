"""«قطعه» از دل تحلیل علت ایراد (نه از ستون‌های خود اخطار).

کاربر می‌خواهد پارتو قطعه از متن «آنالیز علت ایراد» برگهٔ بررسی مشتری خوانده شود؛
همان‌جا که کارشناس می‌نویسد «اتصالی اهمی زیر پایه میکرو» یا «شیفت IC1059» یا
«ایراد LCD». این ماژول نام قطعهٔ معیوب را از همان متن بیرون می‌کشد.

نکته: اگر متن تحلیل قطعه‌ای نام نبرد (مثلاً «ایراد قالب»، «خطای اپراتور»،
«عدم دریافت قطعه»)، رشتهٔ خالی برمی‌گردد و در پارتو شمرده نمی‌شود.
"""
from __future__ import annotations

import re

import pandas as pd

from src.normalize import normalize, squash

ANALYSIS_COLUMN = "آنالیز علت ایراد"
PART_COLUMN = "قطعهٔ تحلیل"
GROUP_COLUMN = "قطعه (گروه‌بندی)"

# (نام یکتا، الگوها) — ترتیب مهم است: خاص‌ترها بالاتر
PART_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("دسته سیم", ("دسته سیم", "دسته سيم", "دسته دسیم", "دسته دسيم")),
    ("لایت باکس", ("لایت باکس", "لايت باکس", "light box")),
    ("استپر موتور", ("استپر موتور", "استپرموتور", "استپر")),
    ("میکروسوئیچ", ("میکروسوئیچ", "ميكروسوئيچ", "microswitch")),
    ("کپ عقربه", ("کپ عقربه",)),
    ("RF ماژول", ("rf module", "rf ماژول", "ماژول rf")),
    ("کانکتور", ("کانکتور", "كانكتور", "connector")),
    ("سوکت", ("سوکت", "سوكت", "socket")),
    ("تراشه", ("تراشه", "چیپ", "chip")),
    ("میکرو", ("میکرو", "ميكرو", "micro")),
    ("کریستال", ("کریستال", "كريستال", "crystal")),
    ("خازن", ("خازن",)),
    ("مقاومت", ("مقاومت",)),
    ("دیود", ("دیود", "ديود", "diode")),
    ("ترانزیستور", ("ترانزیستور", "ترانزيستور", "transistor")),
    ("رگولاتور", ("رگولاتور", "رگولاتور")),
    ("رله", ("رله", "relay")),
    ("بازر", ("بازر", "بزل", "buzzer")),
    ("باسبار", ("باسبار", "باس بار", "busbar")),
    ("اسپیکر", ("اسپیکر", "اسپيكر", "speaker")),
    ("براکت", ("براکت", "براكت", "bracket")),
    ("پلیت", ("پلیت", "پليت", "plate")),
    ("کلمپ", ("کلمپ", "كلمپ", "clamp")),
    ("رینگ", ("رینگ", "رينگ", "ring")),
    ("نگهدارنده", ("نگهدارنده", "نگه دارنده")),
    ("ساپورت", ("ساپورت", "support")),
    ("شفت", ("شفت", "shaft")),
    ("پمپ", ("پمپ", "pump")),
    ("پیچ", ("پیچ", "پيچ", "screw")),
    ("واشر", ("واشر", "washer")),
    ("کاور", ("کاور", "cover")),
    ("ترمینال", ("ترمینال", "ترمينال", "terminal")),
    ("بست", ("بست", "بست نگهدارنده")),
    ("خار", ("خار ",)),
    ("سوئیچ", ("سوئیچ", "سوييچ", "سوییچ", "switch")),
    ("برد", ("برد", "board")),
    ("PCB", ("pcb",)),
    ("ASIC", ("asic",)),
    ("BTS", ("bts",)),
    ("BCM", ("bcm", "sbcm", "nbcm")),
    ("ECU", ("ecu",)),
    ("LCD", ("lcd",)),
    ("LED", ("led",)),
    ("IC", (r"(?<![a-z])ic(?![a-z])", r"ic\d+")),
    ("تگ", ("تگ", "tag")),
    ("فنر", ("فنر", "فنر")),
    ("پین", ("پین", "پين", "pin")),
    ("پد", ("پد",)),
    ("سیم", ("سیم", "سيم", "wire")),
    ("لیبل", ("لیبل", "ليبل", "label")),
    ("نمایشگر", ("نمایشگر", "نمايشگر")),
    ("سنسور", ("سنسور", "sensor")),
    ("موتور", ("موتور", "motor")),
)

# متن‌هایی که «قطعه» ندارند و نباید از واژه‌های عمومی داخلشان قطعه ساخت
NON_PART_HINTS = (
    "عدم دریافت", "سالم بودن", "تحت بررسی", "عدم رویت", "خاتمه یافته",
    "اقدام نشده", "نیاز به دریافت نیست", "ارسال اشتباه", "شرکت",
)


def _match(text: str, pattern: str) -> re.Match | None:
    key = normalize(pattern)
    if not key:
        return None
    if pattern.startswith("(?") or "\\" in pattern:
        return re.search(pattern, text)
    return re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text)


def extract_part(value: object) -> str:
    """نام قطعهٔ معیوب از متن تحلیل علت (یا رشتهٔ خالی)."""
    text = normalize(value)
    if not text or len(text) < 3:
        return ""

    best: tuple[tuple[int, int], str] | None = None
    for name, patterns in PART_RULES:
        for pattern in patterns:
            found = _match(text, pattern)
            if not found:
                continue
            span = found.end() - found.start()
            score = (span, -found.start())
            if best is None or score > best[0]:
                best = (score, name)
    if best:
        return best[1]
    return ""


def group_path(frame: pd.DataFrame) -> list[str]:
    """مسیر گروه‌بندی هر ردیف: «گروه محصول / خانواده / محصول»."""
    columns = [("گروه محصول نهایی", "گروه محصول"), ("خانواده محصول", "خانواده محصول"), ("محصول", "محصول")]
    available = [(source, label) for source, label in columns if source in frame.columns]
    if not available:
        return ["نامشخص"] * len(frame)
    paths: list[str] = []
    for _, row in frame.iterrows():
        parts = []
        for source, _ in available:
            value = " ".join(str(row.get(source) or "").split())
            if value and value not in parts:
                parts.append(value)
        paths.append(" / ".join(parts) if parts else "نامشخص")
    return paths


def add_analysis_part(frame: pd.DataFrame) -> pd.DataFrame:
    """ستون‌های «قطعهٔ تحلیل» و «قطعه (گروه‌بندی)» را اضافه می‌کند."""
    result = frame.copy()
    if result.empty:
        result[PART_COLUMN] = []
        result[GROUP_COLUMN] = []
        return result

    if ANALYSIS_COLUMN in result.columns:
        result[PART_COLUMN] = [extract_part(value) for value in result[ANALYSIS_COLUMN]]
    else:
        result[PART_COLUMN] = ""
    result[GROUP_COLUMN] = group_path(result)
    return result


def part_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """خلاصهٔ قطعه‌های تحلیل‌شده برای گزارش اکسل."""
    if frame.empty or PART_COLUMN not in frame.columns:
        return pd.DataFrame()
    known = frame[frame[PART_COLUMN].astype(str).str.len() > 0]
    if known.empty:
        return pd.DataFrame()
    counts = known[PART_COLUMN].value_counts()
    return pd.DataFrame(
        {
            PART_COLUMN: counts.index,
            "تعداد برگهٔ بررسی": counts.to_numpy(),
            "سهم": (counts / len(known)).to_numpy(),
            "محصولات": [known.loc[known[PART_COLUMN] == name, "محصول"].nunique() for name in counts.index],
            "گروه‌ها": [
                known.loc[known[PART_COLUMN] == name, "گروه محصول نهایی"].nunique()
                for name in counts.index
            ] if "گروه محصول نهایی" in known.columns else 0,
        }
    ).reset_index(drop=True)


def _unused(value: object) -> str:  # pragma: no cover - نگه‌داشتن squash برای سازگاری
    return squash(value)
