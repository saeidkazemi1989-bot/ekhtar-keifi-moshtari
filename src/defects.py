"""یکسان‌سازی متن ایرادها و علت‌ها.

دو کار انجام می‌شود:

۱) «ایراد مشتری» (ستون `شرح خطا`) به یک عبارت استاندارد تبدیل می‌شود تا بتوان
   شمرد یک ایراد چند بار تکرار شده است (مثلاً «عملكرد نادرست» و «عدم عملكرد
   قطعه/ عملكرد اشتباه» هر دو یک ایراد حساب شوند).

۲) «علت ایراد» (ستون `آنالیز علت ایراد` برگه‌های بررسی) به شکل
   «ایراد <نوع> قطعه <قطعه>» یکسان می‌شود و به گروه ۶M (نیروی انسانی،
   تجهیزات، مواد، روش، اندازه‌گیری، محیط) نگاشت می‌شود.
   نمونه: «اتصالی پد ic micro» ← «ایراد اتصالی قطعه IC Micro» با ۶M «تجهیزات».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .normalize import normalize, squash

# ------------------------------------------------------------------ ۶M
M6_PEOPLE = "نیروی انسانی"
M6_MACHINE = "تجهیزات"
M6_MATERIAL = "مواد"
M6_METHOD = "روش"
M6_MEASURE = "اندازه‌گیری"
M6_ENV = "محیط"
M6_UNKNOWN = "نامشخص"

M6_ORDER = (M6_PEOPLE, M6_MACHINE, M6_MATERIAL, M6_METHOD, M6_MEASURE, M6_ENV, M6_UNKNOWN)

# نگاشت «منشاء ایراد» برگهٔ بررسی به ۶M
ORIGIN_M6 = {
    "مواد اولیه": M6_MATERIAL,
    "اپراتور": M6_PEOPLE,
    "تجهیزات": M6_MACHINE,
    "روش": M6_METHOD,
    "محیط": M6_ENV,
    "اندازه گیری": M6_MEASURE,
    "طراحی مهندسی": M6_METHOD,
    "مهندسی": M6_METHOD,
    "ایراد مهندسی": M6_METHOD,
    "مشتری": "عوامل خارجی",
    "دسته سیم": M6_MATERIAL,
    "تحت بررسی": M6_UNKNOWN,
    "عدم دریافت قطعه": M6_UNKNOWN,
}

# ------------------------------------------------------------------ ایراد مشتری
@dataclass(frozen=True)
class DefectRule:
    canonical: str
    group: str
    patterns: tuple[str, ...]


# ترتیب مهم است: خاص‌ترین قاعده اول
CUSTOMER_DEFECTS: tuple[DefectRule, ...] = (
    DefectRule("مغایرت لیبل / ردیابی", "شناسایی و بسته‌بندی", (
        "مغايرت ليبل", "ليبل اشتباه", "عدم الصاق", "رديابي", "علائم هشدار", "ليبل هاي دست",
        "عدم درج اطلاعات", "خطوط رنگ يا برچسب", "كارت رديابي",
    )),
    DefectRule("مغایرت ابعادی", "ابعادی", (
        "مغايرت ابعادي", "خارج از تلورانس", "مغايرت پارامترهاي آزمايشگاهي", "مغايرت در ريزساختار",
    )),
    DefectRule("عدم انطباق ظاهری", "ظاهری", ("عدم انطباق - ظاهري", "عدم انطباق ظاهري", "عدم انطباق")),
    DefectRule("عدم انطباق عملکردی", "عملکردی", (
        "عدم انطباق - عملكردي", "عدم انطباق عملكرد موتور", "عدم انطباق عملکرد", "عدم انطباق عملكردي",
    )),
    DefectRule("عدم عملکرد / عملکرد نادرست", "عملکردی", (
        "عملكرد نادرست", "عدم عملكرد", "عملكرد اشتباه", "عملكرد نامناسب", "عملکرد نادرست",
        "عدم عملکرد قطعه", "فاقد توان", "كشش نداشتن", "گاز نخوردن", "مشكل در روشن كردن موتور سرد",
        "عدم تنظيم دور موتور", "زود عمل كردن ترمز", "حساسيت نامناسب سنسورها", "افت ولتاژ",
        "خاموش شدن و باز ايستادن موتور", "تكان خوردن و ضربه متناوب موتور",
    )),
    DefectRule("روشن نشدن", "عملکردی", ("روشن نشدن",)),
    DefectRule("روشن شدن چراغ هشدار", "عملکردی", ("روشن شدن چراغ هشدار",)),
    DefectRule("خاموش نشدن / روشن ماندن", "عملکردی", ("خاموش نشدن", "روشن ماندن")),
    DefectRule("نشتی سوخت", "نشتی", ("نشتي سوخت", "نشت بنزين", "نشتي بنزين", "نشتي بنزين")),
    DefectRule("نشتی گاز", "نشتی", ("نشتي گاز", "نشت گاز", "نشتي گاز", "بروز نشتي")),
    DefectRule("نشتی روغن", "نشتی", ("نشتي روغن",)),
    DefectRule("نشتی آب", "نشتی", ("نشتي آب", "نشت آب", "نشت آب از سيستم خنك")),
    DefectRule("نفوذ آب", "نشتی", ("نفوذ آب",)),
    DefectRule("دفرمگی / موج", "ظاهری", (
        "دفرمگي", "قري و دفرمگي", "قري", "موج و ناهمواري", "افتادگي", "ايراد موج",
    )),
    DefectRule("شکستگی / ترک", "ظاهری", (
        "شكستگي", "شكست", "ترك خوردگي", "ترك سرد", "لب پريدگي", "عدم استحكام", "پريدگي رنگ",
    )),
    DefectRule("صدا / لرزش", "عملکردی", (
        "صداي", "صدا دهي", "صداي اضافي", "صدا از تجهيزات", "لرزش و نوسان", "ارتعاش",
        "عدم جذب صدا",
    )),
    DefectRule("سختی مونتاژ / جا نرفتن", "مونتاژ", (
        "جانرفتن", "سختي مونتاژ", "جا نبودن", "گير داشتن", "گيرپاژ", "سخت باز شدن",
        "جذب نبودن", "جفت نشدن", "عدم چسبندگي",
    )),
    DefectRule("مونتاژ / نصب نامناسب", "مونتاژ", (
        "عدم مونتاژ", "مونتاژ ناقص", "نصب اشتباه", "نصب نامناسب", "نصب و مهار", "عدم نصب",
        "مونتاژ ناقص/ اشتباه", "قرارگيري نامناسب", "قرار گيري و جهت نامناسب",
    )),
    DefectRule("ارسال / مدل اشتباه", "شناسایی و بسته‌بندی", (
        "ارسال اشتباه", "مدل اشتباه", "ست نبودن", "قاطي بودن قطعات", "تزريق اشتباه",
        "عدم  رعايت تعداد و بچ سايز",
    )),
    DefectRule("کسری قطعه", "ظاهری", ("كسري", "نداشتن")),
    DefectRule("پلیسه / براده", "ظاهری", ("پليسه", "براده")),
    DefectRule("مخدوش بودن / حکاکی", "ظاهری", ("مخدوش", "حكاكي", "چاپ و علائم", "ايراد چاپ")),
    DefectRule("ایراد رنگ", "ظاهری", (
        "رنگ", "دورنگي", "تاول", "حباب", "شيميايي بودن رنگ", "اثر هاله", "پوسته كردن",
    )),
    DefectRule("زنگ‌زدگی / اکسید", "ظاهری", ("زنگ زدگي", "اكسيدگي")),
    DefectRule("خراش / سایش", "ظاهری", ("خش عميق", "خراش", "خش سطحي", "سايش", "سائيدگي", "تماس")),
    DefectRule("بسته‌بندی نامناسب", "شناسایی و بسته‌بندی", (
        "بسته بندي", "بستهبندي", "پالت", "چيدمان", "كاوركشي", "ملزومات بسته بندي", "شبكه سلولي",
    )),
    DefectRule("آلودگی / جسم خارجی", "ظاهری", (
        "اجسام اضافي", "كثيفي", "مواد خارجي", "جسم خارجي", "اثر مواد خارجي",
    )),
    DefectRule("سوختگی", "ظاهری", ("سوخته", "سوختگي")),
    DefectRule("عدم اتصال الکتریکی", "عملکردی", ("عدم اتصال", "عدم  اتصال")),
    DefectRule("شل بودن / لقی", "عملکردی", ("شل بودن", "لقي", "بازي بيش از حد", "هرز بودن")),
    DefectRule("خرابی رزوه", "ظاهری", ("رزوه",)),
    DefectRule("بیرون زدن قطعه", "ظاهری", ("بيرون زدن",)),
    DefectRule("از جا در آمدن", "ظاهری", ("از جا در آمدن",)),
    DefectRule("باز بودن / بسته نشدن", "ظاهری", ("باز بودن", "بسته نشدن")),
    DefectRule("مسدود بودن", "عملکردی", ("مسدود",)),
    DefectRule("تنظیم نامناسب", "عملکردی", ("تنظيم نبودن", "تنظيم نامناسب")),
    DefectRule("ایراد مواد اولیه", "مواد", ("مواد اوليه", "متريال", "سختي و ساختار")),
    DefectRule("پوشش / گریس نامناسب", "ظاهری", ("پوشش نامناسب", "گريس كاري", "چسبكاري", "پخت ناقص")),
    DefectRule("کنده شدن پوشش", "ظاهری", ("كنده نشدن", "كنده شدن")),
    DefectRule("ریپ زدن", "ظاهری", ("ريپ زدن",)),
    DefectRule("عدم یکسری / قطعی", "عملکردی", ("يكسره بودن", "قطع يا بريدگي")),
)


def canonical_defect(value: object, defect_type: object = "") -> tuple[str, str]:
    """ایراد مشتری را به (ایراد استاندارد، گروه ایراد) تبدیل می‌کند."""
    text = normalize(str(value or ""))
    key = squash(text)
    if not key or key in {"nan", "none"}:
        kind = normalize(str(defect_type or ""))
        return ("نامشخص" if not kind else f"سایر ({kind})", kind or "نامشخص")
    for rule in CUSTOMER_DEFECTS:
        for pattern in rule.patterns:
            if squash(pattern) in key:
                return rule.canonical, rule.group
    cleaned = " ".join(str(value).split())
    return cleaned, normalize(str(defect_type or "")) or "سایر"


# ------------------------------------------------------------------ علت ایراد
@dataclass(frozen=True)
class ActionRule:
    action: str          # بخش «نوع ایراد» در عبارت استاندارد
    group: str           # گروه علت
    m6: str              # ۶M پیش‌فرض
    patterns: tuple[str, ...]
    bare: bool = False   # عبارت به‌تنهایی کامل است (بدون «ایراد … قطعه …»)


ACTION_RULES: tuple[ActionRule, ...] = (
    ActionRule("عدم دریافت", "عدم دریافت قطعه", M6_UNKNOWN, ("عدم دریافت", "عدم دريافت")),
    ActionRule("تحت بررسی", "تحت بررسی", M6_UNKNOWN, (
        "تحت بررسی", "در دست بررسی", "تحت بررسي", "بررسی و سلامت", "درافت شد", "تحویل آقای",
        "تحویل اقای", "نمونه تحویل", "نمونه دریافت", "ارسال به مانا", "ارسال شد",
    )),
    ActionRule("سالم بودن", "سالم بودن قطعه", M6_UNKNOWN, (
        "سالم بودن", "سالم است", "سالم بوده", "فاقد ایراد", "ایرادی مشاهده نشد", "مطابق نقشه",
        "عدم رویت ایراد", "ایراد موردی رویت", "تستر قبول", "تست خودرو", "بررسی و سلامت",
    )),
    ActionRule("خطای مشتری", "عوامل خارجی", "عوامل خارجی", ("خطای مشتری", "خطای مشتري"), bare=True),
    ActionRule("اتصالی", "اتصالی", M6_MACHINE, (
        "اتصالی", "اتصال کوتاه", "اتصال كوتاه", "اتصال مویی", "پاشش قلع", "قلع پاشی", "پلیسه مویی",
    )),
    ActionRule("پلیسه", "پلیسه", M6_MATERIAL, ("پلیسه", "پليسه", "براده")),
    ActionRule("قلع‌کاری نامناسب", "قلع‌کاری", M6_METHOD, (
        "قلع کاری", "قلعکاری", "لحیم کاری", "لحیمکاری", "کمبود قلع", "کمبود قلع", "قلع نگرفتن",
        "نداشتن قلع", "لنت کاری", "لحیم",
    )),
    ActionRule("عدم اتصال", "عدم اتصال", M6_METHOD, ("عدم اتصال", "عدم  اتصال", "قطع شدن", "قطعی", "جدا شدن")),
    ActionRule("شکستگی", "شکستگی", M6_METHOD, ("شکستگی", "شکستگي", "شکست", "پارگی", "ترك", "بریدگی")),
    ActionRule("دفرمگی", "دفرمگی", M6_MACHINE, ("دفرمگی", "دفرمگي", "قری", "کجی", "کج بودن", "همراستا نبودن")),
    ActionRule("سوختگی", "سوختگی", M6_MACHINE, ("سوختگی", "سوختن", "سوخته")),
    ActionRule("لقی", "لقی", M6_MATERIAL, ("لقی", "لقي", "شل بودن", "بازی")),
    ActionRule("قالب", "قالب", M6_MACHINE, (
        "قالب", "تزریق", "تزريق", "پرس", "استنسیل", "دستگاه", "اپلیکیتور", "اپليكيتور",
    )),
    ActionRule("نرم‌افزار", "نرم‌افزار", M6_METHOD, (
        "نرم افزار", "نرم‌افزار", "نرمافزار", "فلش", "برنامه", "سنک", "synch", "کالیبراسیون",
    )),
    ActionRule("طراحی", "طراحی", M6_METHOD, ("طراحی", "نقشه مشتری", "نقشه")),
    ActionRule("بسته‌بندی / لیبل", "بسته‌بندی و لیبل", M6_METHOD, (
        "بسته بندی", "بسته‌بندی", "لیبل", "تگ", "چاپ", "حک", "پالت", "کارتن",
    )),
    ActionRule("نفوذ آب", "محیط", M6_ENV, ("نفوذ آب", "رطوبت", "ارتعاش", "ضربه", "حمل و نقل"), bare=True),
    ActionRule("خطای اپراتور", "نیروی انسانی", M6_PEOPLE, bare=True, patterns=(
        "اپراتور", "اپراتور", "بی دقتی", "اشتباه اپراتور", "مونتاژ دستی", "نصب اشتباه",
        "ارسال اشتباه", "جا نزدن", "جازدن",
    )),
    ActionRule("مونتاژ نامناسب", "مونتاژ", M6_PEOPLE, (
        "مونتاژ", "نصب", "عدم نصب", "چفت نشدن", "جا نخوردن",
    )),
    ActionRule("", "قطعه معیوب", M6_MATERIAL, (
        "معیوب", "معيوب", "کیفی", "كيفي", "نامناسب", "ناسازگار", "مشکل", "ایراد",
    )),
)


OBJECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("IC Micro", ("ic micro", "icmicro", "میکرو", "ميكرو")),
    ("IC", ("ic ", "i c", "ای سی")),
    ("ASIC", ("asic", "چیپ asic")),
    ("RF Module", ("rf module", "rf ماژول", "ماژول rf")),
    ("BTS", ("bts",)),
    ("PCB", ("pcb", "برد")),
    ("کانکتور ۴۰ پین", ("40 پین", "40پین")),
    ("کانکتور ۱۸ پین", ("18 پین", "18پین")),
    ("کانکتور", ("کانکتور", "كنكتور")),
    ("خازن", ("خازن",)),
    ("کریستال", ("کریستال", "كريستال")),
    ("بازر", ("بازر",)),
    ("LED", ("led",)),
    ("LCD", ("lcd",)),
    ("دیود", ("دیود", "دیود")),
    ("مقاومت", ("مقاومت", "مقاومت")),
    ("ترانزیستور", ("ترانزیستور",)),
    ("پین", ("پین", "پايه", "پایه")),
    ("ترمینال", ("ترمینال", "ترمينال")),
    ("سوکت", ("سوکت", "سوكت")),
    ("سنسور", ("سنسور",)),
    ("فنر", ("فنر",)),
    ("پلیت", ("پلیت", "پليت")),
    ("لیبل", ("لیبل", "ليبل")),
    ("استپر موتور", ("استپر",)),
    ("پمپ", ("پمپ",)),
    ("شفت", ("شفت",)),
    ("باسبار", ("باسبار", "باس بار")),
    ("میکروسوئیچ", ("میکروسوئیچ", "ميكروسوئيچ")),
    ("اسپیکر", ("اسپیکر",)),
    ("آنتن", ("آنتن", "انتن")),
    ("قالب", ("قالب",)),
)


def _detect_object(text: str) -> str:
    key = squash(normalize(text))
    for label, patterns in OBJECTS:
        for pattern in patterns:
            if squash(normalize(pattern)) in key:
                return label
    return ""


def canonical_cause(cause: object, origin: object = "") -> tuple[str, str, str]:
    """علت را به (علت استاندارد، گروه علت، ۶M) تبدیل می‌کند."""
    raw = " ".join(str(cause or "").split())
    text = normalize(raw)
    key = squash(text)
    if not key or key in {"nan", "none"}:
        return "ثبت نشده", "نامشخص", M6_UNKNOWN

    action: ActionRule | None = None
    for rule in ACTION_RULES:
        if any(squash(normalize(pattern)) in key for pattern in rule.patterns):
            action = rule
            break

    if action is None:
        return f"سایر: {raw}", "سایر", _origin_m6(origin)

    if action.bare or action.group in {"عدم دریافت قطعه", "تحت بررسی", "سالم بودن قطعه", "عوامل خارجی"}:
        return action.action, action.group, action.m6

    obj = _detect_object(raw)
    if action.action == "":
        # ایراد عمومی قطعه: «ایراد LCD» یا «ایراد قطعه»
        phrase = f"ایراد {obj}" if obj else "ایراد قطعه"
    elif obj and squash(normalize(obj)) not in squash(normalize(action.action)):
        phrase = f"ایراد {action.action} قطعه {obj}"
    else:
        phrase = f"ایراد {action.action}"

    m6 = action.m6
    if action.group in {"قطعه معیوب"}:
        m6 = M6_MATERIAL
    # منشاء ثبت‌شده در برگهٔ بررسی، دقیق‌تر از تشخیص متنی است
    origin_m6 = _origin_m6(origin)
    if origin_m6 != M6_UNKNOWN and action.group in {"قطعه معیوب", "سایر"}:
        m6 = origin_m6
    return phrase, action.group, m6


def _origin_m6(origin: object) -> str:
    text = normalize(str(origin or ""))
    for name, m6 in ORIGIN_M6.items():
        if normalize(name) and normalize(name) in text:
            return m6
    return M6_UNKNOWN


# ------------------------------------------------------------------ اعمال روی دادهٔ اخطار
def add_defect_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """ستون‌های یکسان‌شدهٔ ایراد مشتری و علت را اضافه می‌کند."""
    result = frame.copy()

    defects = [
        canonical_defect(row.get("شرح خطا"), row.get("نوع ایراد"))
        for _, row in result.iterrows()
    ]
    result["ایراد مشتری"] = [item[0] for item in defects]
    result["گروه ایراد مشتری"] = [item[1] for item in defects]
    result["کلید ایراد مشتری"] = result["ایراد مشتری"].map(lambda v: squash(normalize(str(v))))

    causes = [
        canonical_cause(row.get("آنالیز علت ایراد"), row.get("منشاء ایراد"))
        for _, row in result.iterrows()
    ]
    result["علت استاندارد"] = [item[0] for item in causes]
    result["گروه علت"] = [item[1] for item in causes]
    result["گروه ۶M"] = [item[2] for item in causes]
    result["کلید علت"] = result["علت استاندارد"].map(lambda v: squash(normalize(str(v))))

    # شمارش تکرار: ایراد مشتری یکسان برای همان محصول و همان شماره فنی
    product_key = result["محصول"].astype(str) + "|" + result["کلید ایراد مشتری"]
    tech_key = result["شماره فنی"].astype(str) + "|" + result["کلید ایراد مشتری"]
    cause_key = result["محصول"].astype(str) + "|" + result["کلید علت"]

    result["تکرار ایراد در محصول"] = product_key.map(product_key.value_counts()).astype(int)
    result["تکرار ایراد در قطعه"] = tech_key.map(tech_key.value_counts()).astype(int)
    result["تکرار علت در محصول"] = cause_key.map(cause_key.value_counts()).astype(int)
    result["تکرار ایراد کل"] = result["کلید ایراد مشتری"].map(
        result["کلید ایراد مشتری"].value_counts()
    ).astype(int)
    return result


def defect_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """جدول ایرادهای یکسان‌شدهٔ مشتری با تعداد تکرار."""
    if frame.empty:
        return pd.DataFrame()
    grouped = (
        frame.groupby(["ایراد مشتری", "گروه ایراد مشتری"], dropna=False)
        .agg(
            تعداد_اخطار=("سریال اخطار", "size"),
            تعداد_محصول=("محصول", "nunique"),
            تعداد_خانواده=("خانواده محصول", "nunique"),
            قطعات_معیوب=("تعداد قطعات معیوب", "sum"),
            اخطار_باز=("وضعیت اخطار", lambda s: int((s != "خاتمه يافته").sum())),
            آخرین_تاریخ=("تاریخ تایید", "max"),
        )
        .reset_index()
        .rename(
            columns={
                "ایراد مشتری": "ایراد مشتری (استاندارد)",
                "گروه ایراد مشتری": "گروه ایراد",
                "تعداد_اخطار": "تعداد اخطار",
                "تعداد_محصول": "تعداد محصول",
                "تعداد_خانواده": "تعداد خانواده",
                "قطعات_معیوب": "تعداد قطعات معیوب",
                "اخطار_باز": "اخطار باز",
                "آخرین_تاریخ": "آخرین تاریخ تایید",
            }
        )
        .sort_values("تعداد اخطار", ascending=False)
        .reset_index(drop=True)
    )
    total = grouped["تعداد اخطار"].sum() or 1
    grouped["سهم"] = grouped["تعداد اخطار"] / total
    return grouped


def cause_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """جدول علت‌های یکسان‌شده با گروه علت و ۶M."""
    if frame.empty or "کلید علت" not in frame.columns:
        return pd.DataFrame()
    reviewed = frame[frame["دارای برگه بررسی"] == "بله"] if "دارای برگه بررسی" in frame.columns else frame
    grouped = (
        reviewed.groupby(["علت استاندارد", "گروه علت", "گروه ۶M"], dropna=False)
        .agg(
            تعداد_اخطار=("سریال اخطار", "size"),
            تعداد_محصول=("محصول", "nunique"),
            قطعات_معیوب=("تعداد قطعات معیوب", "sum"),
        )
        .reset_index()
        .rename(
            columns={
                "علت استاندارد": "علت استاندارد",
                "گروه علت": "گروه علت",
                "گروه ۶M": "گروه ۶M",
                "تعداد_اخطار": "تعداد اخطار",
                "تعداد_محصول": "تعداد محصول",
                "قطعات_معیوب": "تعداد قطعات معیوب",
            }
        )
        .sort_values("تعداد اخطار", ascending=False)
        .reset_index(drop=True)
    )
    return grouped


def m6_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "گروه ۶M" not in frame.columns:
        return pd.DataFrame()
    reviewed = frame[frame["دارای برگه بررسی"] == "بله"] if "دارای برگه بررسی" in frame.columns else frame
    table = (
        reviewed["گروه ۶M"]
        .fillna(M6_UNKNOWN)
        .value_counts()
        .rename_axis("گروه ۶M")
        .reset_index(name="تعداد اخطار")
    )
    total = table["تعداد اخطار"].sum() or 1
    table["سهم"] = table["تعداد اخطار"] / total
    return table
