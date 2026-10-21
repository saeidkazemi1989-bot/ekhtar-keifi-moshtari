"""اتصال «برگه‌های بررسی اخطار» و «کلیم‌ها» به دادهٔ اخطارها.

فایل `C_Plus_405(20).xlsx` دو شیت دارد:

* ``اخطار``: برگهٔ بررسی هر اخطار شامل آنالیز علت، اقدام اصلاحی، منشا ایراد،
  شماره کارت نارنجی و شماره کلیم. کلید اتصال ستون ``سريال`` است که همان
  «سریال اخطار» در فایل اخطارهای کیفی است.
* ``کلیم``: فهرست کلیم‌های ثبت‌شده به تفکیک شماره فنی.

خروجی این ماژول، دادهٔ اخطارها به‌همراه ستون‌های بررسی است.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .normalize import normalize, squash, tech_key

# ستون‌های برگهٔ بررسی که به دادهٔ اخطار اضافه می‌شوند
REVIEW_FIELDS = {
    "آنالیز علت ایراد": "آنالیز علت ایراد",
    "شرح اقدام اصلاحی": "شرح اقدام اصلاحی",
    "منشاء ایراد": "منشاء ایراد",
    "شماره کارت نارنجی": "شماره کارت نارنجی",
    "شماره کلیم": "شماره کلیم",
    "دسته محصول": "دسته محصول (بررسی)",
    "گروه بازرگانی": "گروه بازرگانی (بررسی)",
    "تامین کننده": "تامین‌کننده (بررسی)",
    "دوره": "دوره (بررسی)",
}

EMPTY_REVIEW_COLUMNS = [
    "دارای برگه بررسی",
    *REVIEW_FIELDS.values(),
    "تعداد کلیم",
    "تعداد کلیم پذیرفته‌شده",
]


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = " ".join(str(value).split())
    return "" if text.lower() in {"nan", "none"} else text


def _number(value: object) -> str:
    """شماره‌هایی مثل ۱۰۴۶۱۱۱ یا 582510 را بدون اعشار برمی‌گرداند."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _text(value)


def load_review(path: str | Path) -> pd.DataFrame:
    """خواندن شیت «اخطار» به‌صورت یک ردیف برای هر سریال اخطار."""
    frame = pd.read_excel(path, sheet_name="اخطار")
    rename = {
        "سريال": "سریال اخطار",
        "شماره فني": "شماره فنی (بررسی)",
        "شرح قطعه": "شرح قطعه (بررسی)",
        "توضيحات": "توضیحات (بررسی)",
        "خودرو": "خودرو (بررسی)",
        "دوره": "دوره (بررسی)",
    }
    frame = frame.rename(columns=rename)
    if "سریال اخطار" not in frame.columns:
        raise ValueError("ستون «سريال» در شیت اخطار فایل بررسی پیدا نشد.")

    frame["سریال اخطار"] = pd.to_numeric(frame["سریال اخطار"], errors="coerce")
    frame = frame.dropna(subset=["سریال اخطار"]).copy()
    frame["سریال اخطار"] = frame["سریال اخطار"].astype("int64")
    frame = frame.drop_duplicates(subset=["سریال اخطار"], keep="last")

    for source, target in REVIEW_FIELDS.items():
        if source in frame.columns:
            frame[target] = frame[source].map(_number if source.startswith("شماره") else _text)
        else:
            frame[target] = ""

    keep = ["سریال اخطار", *REVIEW_FIELDS.values()]
    extra = [c for c in ("شرح قطعه (بررسی)", "توضیحات (بررسی)", "خودرو (بررسی)", "شماره فنی (بررسی)") if c in frame.columns]
    return frame[keep + extra].reset_index(drop=True)


def load_claims(path: str | Path) -> pd.DataFrame:
    """تجمیع کلیم‌ها به تفکیک شماره فنی."""
    frame = pd.read_excel(path, sheet_name="کلیم")
    columns = {
        "شماره فني": "شماره فنی",
        "تعداد اعلامی": "اعلامی",
        "تعداد پذیرفته": "پذیرفته",
    }
    frame = frame.rename(columns=columns)
    if "شماره فنی" not in frame.columns:
        return pd.DataFrame(columns=["شماره فنی", "کلید فنی", "تعداد کلیم", "تعداد کلیم پذیرفته‌شده"])
    frame["کلید فنی"] = frame["شماره فنی"].map(lambda v: tech_key(_text(v)))
    frame["اعلامی"] = pd.to_numeric(frame.get("اعلامی"), errors="coerce").fillna(0)
    frame["پذیرفته"] = pd.to_numeric(frame.get("پذیرفته"), errors="coerce").fillna(0)
    frame = frame[frame["کلید فنی"] != ""]
    table = (
        frame.groupby("کلید فنی")
        .agg(
            **{
                "شماره فنی": ("شماره فنی", lambda s: _text(s.iloc[0])),
                "تعداد کلیم": ("اعلامی", "sum"),
                "تعداد کلیم پذیرفته‌شده": ("پذیرفته", "sum"),
            }
        )
        .reset_index()
    )
    table["تعداد کلیم"] = table["تعداد کلیم"].astype(int)
    table["تعداد کلیم پذیرفته‌شده"] = table["تعداد کلیم پذیرفته‌شده"].astype(int)
    return table


def attach_review(
    enriched: pd.DataFrame,
    review: pd.DataFrame,
    claims: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """افزودن ستون‌های بررسی به دادهٔ اخطارها.

    خروجی دوم، ردیف‌های بررسی است که اخطار متناظر در فایل اخطارها ندارند.
    """
    frame = enriched.copy()
    for column in EMPTY_REVIEW_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    if not review.empty:
        review_only = review.drop(
            columns=[
                c
                for c in ("شرح قطعه (بررسی)", "توضیحات (بررسی)", "خودرو (بررسی)", "شماره فنی (بررسی)")
                if c in review.columns
            ]
        )
        # ستون‌های خالی بررسی حذف می‌شوند تا ادغام، ستون‌های فایل بررسی را نگه دارد
        base = frame.drop(columns=[c for c in REVIEW_FIELDS.values() if c in frame.columns])
        merged = base.merge(review_only, on="سریال اخطار", how="left", validate="one_to_one")
        for target in REVIEW_FIELDS.values():
            merged[target] = merged[target].map(_text).fillna("")
        merged["دارای برگه بررسی"] = [
            "بله" if any(_text(merged[target].iloc[i]) for target in REVIEW_FIELDS.values()) else "خیر"
            for i in range(len(merged))
        ]
        frame = merged
        unmatched = review[~review["سریال اخطار"].isin(set(frame["سریال اخطار"]))].copy()
    else:
        unmatched = pd.DataFrame(columns=review.columns if not review.empty else ["سریال اخطار"])

    if claims is not None and not claims.empty:
        frame["کلید فنی"] = frame["شماره فنی"].map(lambda v: tech_key(_text(v)))
        frame = frame.merge(
            claims[["کلید فنی", "تعداد کلیم", "تعداد کلیم پذیرفته‌شده"]],
            on="کلید فنی",
            how="left",
            suffixes=("", "__claim"),
        )
        for column in ("تعداد کلیم", "تعداد کلیم پذیرفته‌شده"):
            duplicate = f"{column}__claim"
            if duplicate in frame.columns:
                frame[column] = frame[duplicate].fillna(frame[column])
                frame = frame.drop(columns=[duplicate])
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
        frame = frame.drop(columns=["کلید فنی"])
    else:
        frame["تعداد کلیم"] = 0
        frame["تعداد کلیم پذیرفته‌شده"] = 0

    frame["دارای برگه بررسی"] = frame["دارای برگه بررسی"].replace("", "خیر").fillna("خیر")
    return frame, unmatched


# --------------------------------------------------------------------- فرم 8D
def eight_d_number(serial: object, year: object) -> str:
    """شماره فرم 8D: 8D-سال-سریال اخطار."""
    try:
        year_text = str(int(year)) if pd.notna(year) else "XXXX"
    except Exception:
        year_text = "----"
    return f"8D-{year_text}-{serial}"


def eight_d_rows(enriched: pd.DataFrame, only_open: bool = False, scope: str = "working") -> pd.DataFrame:
    """ردیف‌هایی که برایشان فرم 8D ساخته می‌شود.

    scope="working" (پیش‌فرض): اخطارهای دارای برگهٔ بررسی یا خاتمه‌نیافته.
    scope="all": همهٔ اخطارها (فرم برای هر اخطار).
    """
    frame = enriched.copy()
    has_review = frame["دارای برگه بررسی"] == "بله"
    is_open = frame["وضعیت اخطار"] != "خاتمه يافته"
    mask = has_review | is_open
    if scope == "all":
        mask = frame.index == frame.index
    if only_open:
        mask = is_open
    with_form = frame[mask].copy()
    with_form["شماره فرم 8D"] = [
        eight_d_number(row["سریال اخطار"], row.get("سال"))
        for _, row in with_form.iterrows()
    ]
    return with_form.sort_values(["سال", "سریال اخطار"]).reset_index(drop=True)


def eight_d_status(enriched: pd.DataFrame) -> pd.DataFrame:
    """وضعیت تکمیل فرم 8D برای هر اخطار."""
    frame = eight_d_rows(enriched)
    if frame.empty:
        return pd.DataFrame()
    table = pd.DataFrame(
        {
            "سریال اخطار": frame["سریال اخطار"],
            "شماره فرم 8D": frame["شماره فرم 8D"],
            "تاریخ تایید": frame["تاریخ تایید"],
            "گروه خودرو": frame["گروه خودرو"],
            "شرح قطعه": frame["شرح قطعه"],
            "محصول": frame["محصول"],
            "وضعیت اخطار": frame["وضعیت اخطار"],
            "دارای برگه بررسی": frame["دارای برگه بررسی"],
            "آنالیز علت ایراد": frame["آنالیز علت ایراد"],
            "شرح اقدام اصلاحی": frame["شرح اقدام اصلاحی"],
            "منشاء ایراد": frame["منشاء ایراد"],
            "وضعیت فرم": [
                "آمادهٔ تایید" if (r["دارای برگه بررسی"] == "بله" and _text(r["آنالیز علت ایراد"])) else "در انتظار تکمیل"
                for _, r in frame.iterrows()
            ],
        }
    )
    return table.reset_index(drop=True)


# --------------------------------------------------------------------- کنترل گروه‌بندی
# دستهٔ اعلامی مشتری در برگهٔ بررسی ← کلیدواژه‌های خانوادهٔ متناظر در گروه‌بندی داخلی
# نگاشت «خانواده محصول داخلی» ← «دسته محصول اعلامی مشتری»
FAMILY_CATEGORY = {
    "NBCM": "NBCM",
    "NBCM (سایر)": "NBCM",
    "Switch": "بالابر شیشه",
    "Switch (سایر)": "بالابر شیشه",
    "ICN1 207": "جلوآمپر",
    "ICN1 TARA": "جلوآمپر",
    "ICN1 DENA": "جلوآمپر",
    "ICN1 SOREN": "جلوآمپر",
    "ICN (سایر)": "جلوآمپر",
    "ECU": "ECU",
    "ECU مونتاژی": "ECU",
    "مدولاتور": "ترمز",
    "SBM": "SBM",
    "یونیت": "یونیت",
    "APM": "پدال",
    "سنسور ABS": "سنسور ترمز",
    "MFD": "صفحه نمایش",
    "BCMI": "BCMI",
    "آنتن ايموبلايزر": "آنتن",
    "سنسور موقعیت": "میل سوپاپ",
    "TMAP": "T-MAP",
    "سنسور اكسيژن": "اکسیژن",
    "انژکتور بنزین": "انژکتور",
    "TV (سایر)": "رگلاتور",
    "دریچه گاز برقی": "دریچه گاز",
    "دسته سیم": "دسته سیم",
    "براکت": "براکت",
}

# دسته‌هایی که در عمل با هم یکی هستند (تفاوت نام‌گذاری، نه خطای گروه‌بندی)
_CATEGORY_ALIASES = {
    "براکت": {"براکت", "NBCM"},
    "میل سوپاپ": {"میل سوپاپ", "سنسور میل سوپاپ"},
    "رگلاتور": {"رگلاتور", "رگولاتور", "دریچه گاز"},
    "آنتن": {"آنتن", "یونیت"},
}


def grouping_checks(enriched: pd.DataFrame) -> pd.DataFrame:
    """ردیف‌هایی که گروه‌بندی داخلی با دستهٔ اعلامی مشتری هم‌خوان نیست.

    مقایسه بر پایهٔ نگاشت صریح «خانواده محصول ← دسته محصول» انجام می‌شود؛
    ردیف‌های خارج از دامنه (که دستهٔ داخلی ندارند) بررسی نمی‌شوند.
    """
    if "دسته محصول (بررسی)" not in enriched.columns:
        return pd.DataFrame()
    frame = enriched[enriched["دارای برگه بررسی"] == "بله"].copy()
    if frame.empty:
        return pd.DataFrame()

    rows = []
    for _, row in frame.iterrows():
        category = _text(row["دسته محصول (بررسی)"])
        if not category:
            continue
        family = _text(row["خانواده محصول"])
        expected = FAMILY_CATEGORY.get(family)
        if not expected:
            continue  # خارج از دامنه یا خانوادهٔ ثبت‌نشده
        allowed = _CATEGORY_ALIASES.get(expected, {expected})
        if category in allowed:
            continue
        rows.append(
            {
                "سریال اخطار": row["سریال اخطار"],
                "تاریخ تایید": row.get("تاریخ تایید", ""),
                "دسته اعلامی مشتری": category,
                "شرح قطعه": row["شرح قطعه"],
                "خانواده فعلی": family,
                "محصول فعلی": row["محصول"],
                "روش تطبیق": row["روش تطبیق"],
                "پیشنهاد": f"در صورت نیاز به «{category}» اصلاح شود",
            }
        )
    return pd.DataFrame(rows)
