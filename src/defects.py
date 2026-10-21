"""توصیف ایراد مشتری، دسته‌بندی دوگانه و یکسان‌سازی علت‌ها.

سه کار انجام می‌شود:

۱) «ایراد مشتری» از متن «توضیحات» استخراج می‌شود تا خودِ ایراد را نشان دهد،
   نه دسته‌بندی آن. نمونه: اخطار ۲۳۵۹۱۱ ← «عدم عملکرد نشانگر درب‌ها».
   اگر توضیحات فقط ارجاع باشد (مثلاً «مطابق فرم 8D به پیوست»)، از
   «شرح منشا» + «شرح خطا» استفاده می‌شود.

۲) «دسته‌بندی ایراد» فقط دو مقدار دارد: عملکردی / ظاهری (از ستون «نوع ایراد»).

۳) «علت ایراد» (ستون `آنالیز علت ایراد` برگه‌های بررسی) به شکل
   «ایراد <نوع> قطعه <قطعه>» یکسان می‌شود و به گروه ۶M (نیروی انسانی،
   تجهیزات، مواد، روش، اندازه‌گیری، محیط) نگاشت می‌شود.
   نمونه: «اتصالی پد ic micro» ← «ایراد اتصالی قطعه IC Micro» با ۶M «تجهیزات».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .normalize import normalize, normalize_keep_punctuation, squash

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
        "عدم درج اطلاعات", "خطوط رنگ يا برچسب", "كارت رديابي", "باركد", "برچسپ",
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
        "خاموش شدن و باز ايستادن موتور", "تكان خوردن و ضربه متناوب موتور", "عمل نمي كند",
        "عمل نمي‌كند",
    )),
    DefectRule("روشن نشدن", "عملکردی", ("روشن نشدن",)),
    DefectRule("روشن شدن چراغ هشدار", "عملکردی", ("روشن شدن چراغ هشدار",)),
    DefectRule("خاموش نشدن / روشن ماندن", "عملکردی", ("خاموش نشدن", "روشن ماندن")),
    DefectRule("نشتی سوخت", "نشتی", ("نشتي سوخت", "نشت بنزين", "نشتي بنزين")),
    DefectRule("نشتی گاز", "نشتی", ("نشتي گاز", "نشت گاز", "بروز نشتي")),
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
        "بسته بندي", "بسته‌بندي", "پالت", "چيدمان", "كاوركشي", "ملزومات بسته بندي", "شبكه سلولي",
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


def defect_group(value: object, defect_type: object = "") -> tuple[str, str]:
    """گروه تفصیلی ایراد از روی متن «شرح خطا» (مثلاً نشتی، مونتاژ، ظاهری)."""
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


# ------------------------------------------------------------------ توصیف واقعی ایراد
# فعل‌های ایراد به‌همراه الگوی متنی؛ در ابتدای واژه جست‌وجو می‌شوند
VERB_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"عدم عملکرد(?: صحیح| کامل| درست)?", "عدم عملکرد"),
    (r"عملکرد(?:\u200c)?(?: ندارد| نداشت| ندارند| نمی\u200cکند| نمی\u200cشود)", "عدم عملکرد"),
    (r"عدم روشن شدن", "روشن نشدن"),
    (r"گیر(?: کردن| داشتن| دارد| کرد)", "گیر داشتن"),
    (r"عدم کارکرد(?: صحیح)?", "عدم عملکرد"),
    (r"عدم کار نمودن", "عدم عملکرد"),
    (r"عملکرد نادرست", "عملکرد نادرست"),
    (r"عملکرد اشتباه", "عملکرد اشتباه"),
    (r"عملکرد نامناسب", "عملکرد نامناسب"),
    (r"عملکرد ناقص", "عملکرد ناقص"),
    (r"عدم نمایش(?: صحیح| کامل)?", "عدم نمایش"),
    (r"عدم ثبت(?: صحیح)?", "عدم ثبت"),
    (r"خطای(?: دائم| ثابت| شبکه| سنسور)?|خطا(?:ی)?", "خطا"),
    (r"نمایش (?:اشتباه|نادرست|ناقص)", "نمایش نادرست"),
    (r"روشن نشدن", "روشن نشدن"),
    (r"روشن ماندن", "روشن ماندن"),
    (r"خاموش نشدن", "خاموش نشدن"),
    (r"ترک و پارگی", "ترک و پارگی"),
    (r"ترک خوردگی", "ترک خوردگی"),
    (r"ترک(?! خوردگی| و پارگی)", "ترک"),
    (r"شکستن|شکستگی", "شکستگی"),
    (r"دفرمگی|دفرمه", "دفرمگی"),
    (r"پلیسه(?:\u200cگیری| گیری)?", "پلیسه"),
    (r"اتصالی", "اتصالی"),
    (r"عدم ارسال", "عدم ارسال"),
    (r"نداشتن|ندارد", "نداشتن"),
    (r"فاقد", "فاقد"),
    (r"بالا (?:بودن|نشان دادن|رفتن)", "بالا بودن"),
    (r"پایین (?:بودن|آمدن)", "پایین بودن"),
    (r"بیرون زدن", "بیرون زدن"),
    (r"مغایرت لیبل", "مغایرت لیبل"),
    (r"مغایرت ابعادی", "مغایرت ابعادی"),
    (r"مغایرت", "مغایرت"),
    (r"نشتی|نشت", "نشتی"),
    (r"صدای اضافی|صدای غیرعادی|صدای غیر عادی|صدای", "صدای"),
    (r"سختی مونتاژ", "سختی مونتاژ"),
    (r"جا نرفتن|جا نبودن", "جا نرفتن"),
    (r"فعال شدن", "فعال شدن"),
    (r"غیرفعال شدن", "غیرفعال شدن"),
    (r"خرابی|خراب(?!ی)", "خرابی"),
    (r"سوختگی|سوخته", "سوختگی"),
    (r"کثیفی|آلودگی", "کثیفی"),
    (r"نصب (?:نادرست|نامناسب)", "نصب نادرست"),
    (r"شل بودن|لق شدن", "شل بودن"),
    (r"لقی", "لقی"),
    (r"باز شدن", "باز شدن"),
    (r"بسته نشدن", "بسته نشدن"),
    (r"قطع(?:ی)? شدن|قطع(?:ی)? می", "قطع شدن"),
    (r"قطع(?!ه|ات)", "قطع"),
    (r"کمبود", "کمبود"),
    (r"تاخیر", "تاخیر"),
    (r"خش(?!ک)", "خش"),
    (r"حرکت برگشت", "حرکت برگشت"),
    (r"نوسان", "نوسان"),
    (r"عمل نمی کند|عمل نمي كند|عملنمی‌کند", "عدم عملکرد"),
)

BOUNDARY: tuple[str, ...] = tuple(sorted((
    "بر روی", "برروی", "روی", "بر", "به دلیل", "بدلیل", "به علت", "بعلت", "بابت",
    "به", "در", "از", "با", "که", "داخل", "جهت", "مطابق", "طبق", "عطف به",
    "بعد از", "قبل از", "در صورت", "می باشد", "میباشد", "است", "شد", "گردید",
    "گردیده", "رویت", "مشاهده", "نماینده", "کارشناس", "شرکت", "سازه پویش",
    "ساپکو", "ایران خودرو", "فایل", "پیوست", "نامه", "مبلغ", "تومان",
    "دلیل", "علت", "طی", "درخواست", "لازم", "مجدد", "وجود دارد", "دارد",
    "ندارد", "دارای", "با توجه", "لذا", "لذلك", "همچنین", "پس از", "حین",
    "صورت", "خصوص", "مندرج", "درج شده", "تحویل", "ایراد", "اشکال", "توضیحات",
    "توضیح", "مشروح", "الصاق", "تماس", "داخلی", "مذکور", "فوق", "ذکر شده",
    "مورد اشاره", "درخواست شد", "لازم است", "میگردد", "می گردد", "نمی شود",
    "پیرو", "منجر", "لطفا", "ارجاع", "ضمائم", "ضمیمه", "مستندات", "گزارش",
    "بررسی", "ملاحظه", "سایر", "جهت اطلاع",
    "قطعه مربوطه", "قطعه مربوط", "شرکت سازه پویش", "شرکت ساپکو",
), key=len, reverse=True))

PUNCT = "،.:؛()[]{}«»\"'/\\-_*=+!?؟|"

FILLER: tuple[str, ...] = tuple(sorted((
    "طی مراجعه", "در مراجعه", "با مراجعه", "در پی مراجعه", "مطابق", "با توجه به",
    "باتوجه به", "باتوجه", "ا توجه به", "ا توجه", "ناشی از", "ناشي از",
    "این اخطار کیفی", "باسلام", "با سلام",
    "بر اساس", "شرح ایراد", "موضوع", "ایراد", "اشکال فنی", "اشکال",
    "ظاهری", "عملکردی", "ایراد عملکردی", "یک",
), key=len, reverse=True))

TAIL_JUNK = (
    "می باشد", "میباشد", "میگردد", "می گردد", "است", "شد", "گردید", "گردیده",
    "رویت شد", "مشاهده شد", "وجود دارد", "روشن نمی شود", "نمی شود", "دارد",
    "یک نمونه", "نمونه", "بوده", "می باشد که", "به پیوست", "پیوست", "لطفا",
    "جهت اطلاع", "رویت گردید", "مشاهده گردید",
)

JUNK_ONLY = (
    "مطابق توضیحات", "طبق توضیحات", "توضیحات در فایل", "توضیحات در فایل پیوست",
    "فرم 8d به پیوست", "مطابق فایل", "طبق فایل", "مطابق پیوست", "به پیوست",
    "توضیحات ارسالی", "مطابق نامه", "طبق نامه", "در فایل پیوست", "شرح در پیوست",
    "مطابق مستندات", "طبق مستندات", "ایراد مذکور", "مورد مذکور", "ارجاع گردد",
    "به ضمائم", "لطفا اقدامات", "جهت اطلاع", "به استحضار",
)

ACRONYMS = (
    "abs", "ecu", "esc", "lcd", "led", "cng", "bcm", "nbcm", "bcm i", "ic", "pcb",
    "rf", "mfd", "tmap", "sbm", "bcmi", "esp", "tle", "ulq", "bts", "asic", "smd",
    "aoi", "atob", "btoa", "gps", "usb", "srs", "tpms", "eps", "in",
)

SUFFIX_FRAGMENTS = {"ی", "اي", "های", "ها"}
_ZWNJ = "\u200c"


def _clean_text(value: object) -> str:
    text = str(value or "")
    text = text.replace("_x000D_", " ").replace("\r", " ").replace("\n", " ")
    text = normalize_keep_punctuation(text)
    # چسبیدن واژه‌های کلیدی به واژهٔ قبل (مثل «ایرادعدم عملکرد» یا «NBCMعدم عملکرد»)
    text = re.sub(r"(?<=[^\s])(عدم عملکرد|عدم روشن شدن|عملکرد نادرست)", r" \1", text)
    text = text.replace("عملکردنادرست", "عملکرد نادرست").replace("عملکردنمی", "عملکرد نمی")
    text = text.replace("عملکردمناسب", "عملکرد مناسب").replace("عملکردنامناسب", "عملکرد نامناسب")
    # چسبیدن حروف لاتین و فارسی («BCMروشن») و «عدم» به واژهٔ قبل («مونتاژعدم»)
    text = re.sub(r"(?<=[A-Za-z])(?=[آ-ی])", " ", text)
    text = re.sub(r"(?<=[آ-ی])(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[^\s])(عدم)(?=\s)", r" \1", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_filler(text: str) -> str:
    text = re.sub(r"^(?:ایراد|اشکال)\s*(?:ظاهری|عملکردی)?\s*[:،-]?\s*", "", text)
    # شمارش نمونه‌ها بخشی از توصیف ایراد نیست
    text = re.sub(r"(?:^|\s)(?:یک|دو|سه|چهار|پنج|چند|\d+)\s*مورد(?=\s|$)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed:
        changed = False
        for filler in FILLER:
            if text.startswith(filler + " ") or text == filler:
                text = text[len(filler):].lstrip(" :،-")
                changed = True
        while text and text[0] in " :-،.":
            text = text[1:].lstrip()
    return text


def _find_verb(text: str) -> tuple[str, int, int]:
    best: tuple[str, int, int] | None = None
    for pattern, canonical in VERB_PATTERNS:
        match = re.search(
            rf"(?:^|(?<=\s))(?:{pattern})(?=\s|$|،|\.|\(|\))", text
        )
        if not match:
            continue
        if best is None or match.start() < best[1] or (match.start() == best[1] and match.end() > best[2]):
            best = (canonical, match.start(), match.end())
    return best if best else ("", -1, -1)


def _cut_subject(text: str) -> str:
    text = text.strip().lstrip(" :،-.")
    text = re.sub(r"^یک\s+", "", text)
    text = re.sub(r"^و\s+", "", text)
    # حرف اضافه/قید ابتدای عبارت، بخشی از موضوع ایراد نیست
    changed = True
    while changed and text:
        changed = False
        for word in BOUNDARY:
            if re.match(rf"^{re.escape(word)}(?=\s|$)", text):
                text = text[len(word):].lstrip(" :،-.")
                changed = True
                break
    cut = len(text)
    for char in PUNCT:
        pos = text.find(char)
        if 0 <= pos < cut:
            cut = pos
    for word in BOUNDARY:
        match = re.search(rf"(?:^|\s){re.escape(word)}(?=\s|$)", text)
        if match and match.start() < cut:
            cut = match.start()
    model = re.search(r"\d{2,}", text)
    if model and model.start() < cut and model.start() > 0:
        cut = model.start()
    long_number = re.search(r"\d{6,}", text)
    if long_number and long_number.start() < cut:
        cut = long_number.start()
    text = text[:cut].strip()

    changed = True
    while changed:
        changed = False
        for word in ("از", "در", "به", "بر", "با", "برای", "روی", "که"):
            if text.startswith(word + " "):
                text = text[len(word) + 1:]
                changed = True
    for junk in TAIL_JUNK:
        if text.endswith(" " + junk):
            text = text[: -(len(junk) + 1)]
    text = text.strip(" :،-.")
    text = re.sub(r"\s+(و|یا|از|در|به|با|بر|که|را|هم)$", "", text)
    text = re.sub(rf"(\S+) ها(?=\s|$)", rf"\1{_ZWNJ}ها", text)
    words = [word for word in text.split() if word not in SUFFIX_FRAGMENTS]
    while words and words[-1] in {"و", "یا", "از", "در", "به", "با", "بر", "که", "را", "هم"}:
        words.pop()
    if len(words) > 10:
        words = words[:10]
    return " ".join(words)


def _drop_verb_echo(verb: str, subject: str) -> str:
    words = subject.split()
    verb_words = {squash(word) for word in verb.split() if word}
    while words and squash(words[0]) in verb_words:
        words.pop(0)
    return " ".join(words)


JUNK_TAIL = {
    "عدم", "نادرست", "نمونه", "مورد", "و", "یا", "از", "در", "به", "با", "بر",
    "که", "را", "هم", "عملکرد", "بودن", "شدن", "کردن", "تنها", "می", "شود",
    "گردد", "گردید", "شد", "بود", "بوده",
}


def polish_statement(text: str) -> str:
    """اصلاح نهایی: بزرگ‌کردن حروف اختصاری لاتین و حذف فاصله‌های اضافه."""
    if not text:
        return text
    out = text
    for word in ACRONYMS:
        out = re.sub(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", word.upper(), out, flags=re.I)
    out = re.sub(r"\s+", " ", out).strip(" :،-.")
    words = out.split()
    while len(words) > 2 and words[-1] in JUNK_TAIL:
        words.pop()
    return " ".join(words)


def _is_junk(text: str) -> bool:
    key = squash(normalize(text))
    if len(key) < 4:
        return True
    for pattern in JUNK_ONLY:
        block = squash(normalize(pattern))
        if block and block in key and len(key) < len(block) + 25:
            return True
    return False


WEAK_STARTS = {
    "عملکرد", "عملکردی", "نادرست", "عدم", "ایراد", "اشکال", "تاخیر", "ناشی",
    "ا", "یک", "مورد", "نمونه", "حضور", "قطعه", "با", "در", "به", "از", "بر", "که", "و",
}
GENERIC_SUBJECTS = {"قطعه", "خودرو", "محصول", "نامشخص", "سایر", "1", "0"}
DEFECT_MARKERS = (
    "ناخوانا", "نامتعارف", "معیوب", "خراب", "شکست", "برید", "کسری", "اضافه",
    "ناقص", "اشتباه", "غلط", "بدون", "نبود", "ندار", "نشد", "نکرد", "نخورد",
    "نگیر", "نرف", "شدن", "کردن", "بودن", "دارد", "کیفی", "مغایر", "نشتی",
    "پلیسه", "دفرم", "خش", "ترک", "سوخت", "کثیف", "آلود", "شل", "لق", "گیر",
    "عدم", "قطع", "پارگی", "صدا", "اتصال", "نوسان", "خراش", "افتادگی",
    "بریدگی", "قفل", "شکاف", "سوراخ", "زدگی", "پوسیدگی", "ریختگی",
    "اختلال", "نقص", "عیب", "مردود", "ناهمخوان",
)


def _weak_subject(text: str) -> bool:
    """آیا عبارت بعد از فعل، موضوع مشخصی برای ایراد نیست؟"""
    cleaned = text.strip(" :،-.")
    key = squash(normalize(cleaned))
    if len(key) < 4 or key.isdigit():
        return True
    words = cleaned.split()
    first = squash(words[0]) if words else ""
    if first in {squash(word) for word in ("عدم", "نادرست")} and len(words) >= 3:
        return False
    return any(first == squash(word) for word in WEAK_STARTS)


def _strip_light(text: str) -> str:
    """فقط «ایراد/اشکال» و صفت‌های ابتدایی را برمی‌دارد؛ فعل ایراد حفظ می‌شود."""
    text = re.sub(r"^(?:ایراد|اشکال)\s*(?:ظاهری|عملکردی)?\s*[:،-]?\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _origin_subject(origin: object) -> str:
    text = _clean_text(origin)
    if not text or squash(text) in {squash(word) for word in GENERIC_SUBJECTS}:
        return ""
    return _cut_subject(text)


def _fallback_from_error(error: object, origin: object) -> str:
    """وقتی توضیحات ایراد مشخصی ندارد، از «شرح خطا» و «شرح منشا» استفاده می‌کند."""
    error_text = _strip_light(_clean_text(error))
    if not error_text or squash(error_text) in {"nan", "none"}:
        subject = _origin_subject(origin)
        return subject
    verb, _, end = _find_verb(error_text)
    if verb:
        subject = _cut_subject(error_text[end:])
        if (
            not subject
            or _weak_subject(subject)
            or squash(subject) in {squash(word) for word in GENERIC_SUBJECTS}
        ):
            subject = _origin_subject(origin)
        return f"{verb} {subject}".strip()
    subject = _cut_subject(error_text)
    if subject and not _weak_subject(subject):
        return subject
    return _origin_subject(origin)


def _has_defect_marker(text: str) -> bool:
    key = normalize(text)
    return any(marker in key for marker in DEFECT_MARKERS)


def _extract_statement(text: str, error: object, origin: object) -> str:
    """منطق اصلی استخراج از یک متن از پیش آماده‌شده."""
    verb, index, end = _find_verb(text)
    head = _cut_subject(text)
    subject = _cut_subject(text[end:]) if verb else ""

    if verb:
        # جمله‌هایی مثل «X دارای سختی مونتاژ است»: فعل بعد از موضوع آمده است
        if index > 25 and head and not _weak_subject(head):
            before = text[:index]
            if re.search(r"\b(?:دارای|دارد|داراي)\b", before):
                return polish_statement(f"{verb} {head}")
            if _has_defect_marker(head):
                return polish_statement(head)
        # جمله‌هایی مثل «فرستنده‌ها عملکرد ندارد»: موضوع قبل از فعل است
        if not subject and head and not _weak_subject(head) and squash(head) != squash(verb):
            subject = head
        if subject:
            subject = re.sub(r"\s+(?:عملکرد|کار|کارکرد)$", "", subject).strip()
        # جمله‌های «X دچار عدم عملکرد می‌شود»: آنچه بعد از فعل آمده موضوع ایراد نیست
        if re.match(r"^(?:می\u200c?شود|می\u200c?گردد|می شود|می گردد|شد|گردید|گردیده)\b", subject):
            subject = ""
        if subject.startswith(("عدم عملکرد", "عملکرد نادرست", "عدم نمایش", "روشن نشدن", "نشتی", "خرابی")):
            return polish_statement(subject)
        if not subject or _weak_subject(subject):
            fallback = _fallback_from_error(error, origin)
            if fallback:
                return polish_statement(fallback)
            if subject:
                return polish_statement(subject)
        if subject:
            return polish_statement(f"{verb} {subject}")
        return polish_statement(verb)

    # در توضیحات فعل ایراد پیدا نشد
    if head and not _weak_subject(head) and _has_defect_marker(head):
        return polish_statement(head)
    fallback = _fallback_from_error(error, origin)
    if fallback:
        return polish_statement(fallback)
    if head and not _weak_subject(head):
        return polish_statement(head)
    return polish_statement(head or "نامشخص")


PAREN_NOISE = (
    "بعد از", "قبل از", "تعویض", "بررسی", "نماینده", "شرکت", "سازه", "ساپکو",
    "گزارش", "نامه", "تومان", "مبلغ", "درخواست", "لطفا", "تماس", "داخلی",
    "ضمیمه", "پیوست", "فایل", "تصویر", "عکس", "شماره", "کد",
)
COMPONENT_WORDS = (
    "چراغ", "نشانگر", "کلید", "شیشه", "درب", "سنسور", "موتور", "پمپ", "رله",
    "سوکت", "دسته", "کاور", "صفحه", "نمایشگر", "امپر", "عقربه", "بوق", "فن",
    "برف", "پاک", "قفل", "اینه", "آینه", "صندلی", "کمربند", "ترمز", "فرمان",
    "دینام", "استارت", "باتری", "ecu", "bcm", "nbcm", "واحد", "یونیت", "برد",
    "فیوز", "سیم", "اتصال", "کلاچ", "گیربکس", "رادیاتور", "فنر", "کمک", "سیستم",
    "کولر", "گرمکن", "ریموت", "سوییچ", "سوئیچ", "کویل", "انژکتور", "پدال",
)


def _parenthetical_statement(text: str, error: object, origin: object) -> str:
    """اگر توضیحات داخل پرانتز توصیف دقیق‌تری دارد، همان را برمی‌دارد."""
    error_text = _strip_light(_clean_text(error))
    error_verb, _, _ = _find_verb(error_text)
    for match in re.finditer(r"\(([^()]*)\)", text):
        raw = match.group(1).strip(" :،-.")
        group = _strip_filler(raw)
        if not group or _is_junk(group):
            continue
        words = group.split()
        if not words:
            continue
        verb, _, _ = _find_verb(group)
        if verb:
            return _extract_statement(group, error, origin)
        if _has_defect_marker(group) and len(group) > 6:
            return _extract_statement(group, error, origin)
        if group.startswith("عملکرد ") and error_verb == "عملکرد نادرست":
            return _extract_statement("عملکرد نادرست " + group[len("عملکرد "):], error, origin)
        key = normalize(group)
        if (
            error_verb
            and 2 <= len(words) <= 4
            and any(word in key for word in COMPONENT_WORDS)
            and not any(noise in key for noise in PAREN_NOISE)
            and not re.search(r"\d{3,}", group)
        ):
            return polish_statement(f"{error_verb} {_cut_subject(group)}")
    return ""


BARE_STATEMENTS = {
    "نشتی", "عدم عملکرد", "عدم عملکرد کامل", "عدم عملکرد صحیح", "عملکرد نادرست",
    "عملکرد اشتباه", "خرابی", "شکستگی", "شکست", "ترک", "دفرمگی", "روشن نشدن",
    "مغایرت ابعادی", "عدم انطباق", "عدم انطباق ظاهری", "عدم انطباق عملکردی", "نقص",
}


def defect_statement(notes: object, error: object = "", origin: object = "") -> str:
    """توصیف واقعی ایراد از متن «توضیحات» (مثلاً «عدم عملکرد نشانگر درب‌ها»)."""
    text = _strip_filler(_clean_text(notes))
    statement = _parenthetical_statement(text, error, origin) or _extract_statement(text, error, origin)
    if statement in BARE_STATEMENTS:
        origin_subject = _origin_subject(origin)
        if origin_subject:
            return polish_statement(f"{statement} {origin_subject}")
    return statement


def defect_category(defect_type: object, statement: str = "") -> str:
    """دسته‌بندی دوگانهٔ ایراد: عملکردی / ظاهری."""
    value = normalize(str(defect_type or ""))
    if "ظاهر" in value:
        return "ظاهری"
    if "عملکرد" in value:
        return "عملکردی"
    key = normalize(statement)
    cosmetics = ("لیبل", "دفرمگی", "خش", "پلیسه", "شکستگی", "ترک", "ابعادی", "بسته بندی", "کثیفی", "رنگ")
    return "ظاهری" if any(word in key for word in cosmetics) else "عملکردی"


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
def load_defect_overrides(path: str | Path) -> dict[str, dict]:
    """اصلاح‌های دستی متن ایراد از فایل «اصلاح ایرادها.xlsx»."""
    path = Path(path)
    if not path.exists():
        return {}
    frame = pd.read_excel(path, sheet_name=0)
    if "سریال اخطار" not in frame.columns:
        return {}
    result: dict[str, dict] = {}
    for _, row in frame.iterrows():
        serial = str(row.get("سریال اخطار", "")).strip()
        if serial.endswith(".0"):
            serial = serial[:-2]
        if not serial or serial.lower() == "nan":
            continue
        entry: dict[str, str] = {}
        for column, field in (("ایراد مشتری", "statement"), ("دسته‌بندی ایراد", "category")):
            if column not in frame.columns:
                continue
            value = " ".join(str(row.get(column) or "").split())
            if not value or value.lower() == "nan":
                continue
            if field == "category" and value not in {"عملکردی", "ظاهری"}:
                continue
            entry[field] = value
        if entry:
            result[serial] = entry
    return result


def apply_defect_overrides(frame: pd.DataFrame, overrides: dict[str, dict]) -> pd.DataFrame:
    """اعمال متن‌های دستی روی ستون‌های ایراد."""
    if not overrides or frame.empty:
        return frame
    result = frame.copy()
    serials = result["سریال اخطار"].astype(str)
    for serial, entry in overrides.items():
        mask = serials == str(serial)
        if not mask.any():
            continue
        if entry.get("statement"):
            result.loc[mask, "ایراد مشتری"] = entry["statement"]
        if entry.get("category"):
            result.loc[mask, "دسته‌بندی ایراد"] = entry["category"]
        result.loc[mask, "منبع ایراد"] = "اصلاح دستی"
    return result


def make_defect_template(path: str | Path) -> Path:
    """ساخت فایل نمونهٔ اصلاح متن ایرادها."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "اصلاح ایرادها"
    sheet.sheet_view.rightToLeft = True
    sheet.append(["سریال اخطار", "ایراد مشتری", "دسته‌بندی ایراد", "توضیح"])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0F766E")
        cell.alignment = Alignment(horizontal="center")
    for column, width in {"A": 14, "B": 46, "C": 18, "D": 40}.items():
        sheet.column_dimensions[column].width = width
    guide = workbook.create_sheet("راهنما")
    guide.sheet_view.rightToLeft = True
    for row in [
        ("راهنمای اصلاح متن ایرادها", ""),
        ("", ""),
        ("۱", "ستون «ایراد مشتری» توصیف واقعی ایراد است؛ مثل «عدم عملکرد نشانگر درب‌ها»."),
        ("۲", "ستون «دسته‌بندی ایراد» فقط دو مقدار دارد: عملکردی یا ظاهری."),
        ("۳", "اگر سریالی را وارد کنید، همان اخطار در اجرای بعدی با متن شما جایگزین می‌شود."),
        ("۴", "ردیف‌های اصلاح‌شده با منبع «اصلاح دستی» مشخص می‌شوند."),
    ]:
        guide.append(list(row))
    guide.column_dimensions["A"].width = 8
    guide.column_dimensions["B"].width = 100
    workbook.save(path)
    return path


def add_defect_fields(
    frame: pd.DataFrame,
    overrides: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """ستون‌های ایراد مشتری (توصیف واقعی)، دسته‌بندی و علت را اضافه می‌کند."""
    result = frame.copy()

    statements = [
        defect_statement(row.get("توضیحات"), row.get("شرح خطا"), row.get("شرح منشا"))
        for _, row in result.iterrows()
    ]
    groups = [
        defect_group(row.get("شرح خطا"), row.get("نوع ایراد"))
        for _, row in result.iterrows()
    ]
    result["ایراد مشتری"] = statements
    result["دسته‌بندی ایراد"] = [
        defect_category(row.get("نوع ایراد"), statement)
        for (_, row), statement in zip(result.iterrows(), statements)
    ]
    result["گروه ایراد"] = [item[0] for item in groups]
    result["منبع ایراد"] = "استخراج خودکار"

    if overrides:
        result = apply_defect_overrides(result, overrides)

    result["کلید ایراد"] = result["ایراد مشتری"].map(lambda value: squash(normalize(str(value))))

    causes = [
        canonical_cause(row.get("آنالیز علت ایراد"), row.get("منشاء ایراد"))
        for _, row in result.iterrows()
    ]
    result["علت استاندارد"] = [item[0] for item in causes]
    result["گروه علت"] = [item[1] for item in causes]
    result["گروه ۶M"] = [item[2] for item in causes]
    result["کلید علت"] = result["علت استاندارد"].map(lambda value: squash(normalize(str(value))))

    product_key = result["محصول"].astype(str) + "|" + result["کلید ایراد"]
    tech_key = result["شماره فنی"].astype(str) + "|" + result["کلید ایراد"]
    cause_key = result["محصول"].astype(str) + "|" + result["کلید علت"]

    result["تکرار ایراد در محصول"] = product_key.map(product_key.value_counts()).astype(int)
    result["تکرار ایراد در قطعه"] = tech_key.map(tech_key.value_counts()).astype(int)
    result["تکرار علت در محصول"] = cause_key.map(cause_key.value_counts()).astype(int)
    result["تکرار ایراد کل"] = result["کلید ایراد"].map(result["کلید ایراد"].value_counts()).astype(int)
    return result


def defect_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """جدول ایرادهای واقعی مشتری با دسته‌بندی و تعداد تکرار."""
    if frame.empty or "ایراد مشتری" not in frame.columns:
        return pd.DataFrame()
    grouped = (
        frame.groupby(["ایراد مشتری", "دسته‌بندی ایراد"], dropna=False)
        .agg(
            گروه_ایراد=("گروه ایراد", lambda values: values.value_counts().idxmax()),
            تعداد_اخطار=("سریال اخطار", "size"),
            تعداد_محصول=("محصول", "nunique"),
            تعداد_خانواده=("خانواده محصول", "nunique"),
            قطعات_معیوب=("تعداد قطعات معیوب", "sum"),
            اخطار_باز=("وضعیت اخطار", lambda s: int((s != "خاتمه يافته").sum())),
            بیشترین_تکرار=("تکرار ایراد در محصول", "max"),
            آخرین_تاریخ=("تاریخ تایید", "max"),
        )
        .reset_index()
        .rename(
            columns={
                "دسته‌بندی ایراد": "دسته‌بندی ایراد",
                "گروه_ایراد": "گروه ایراد",
                "تعداد_اخطار": "تعداد اخطار",
                "تعداد_محصول": "تعداد محصول",
                "تعداد_خانواده": "تعداد خانواده",
                "قطعات_معیوب": "تعداد قطعات معیوب",
                "اخطار_باز": "اخطار باز",
                "بیشترین_تکرار": "بیشترین تکرار",
                "آخرین_تاریخ": "آخرین تاریخ تایید",
            }
        )
        .sort_values(["تعداد اخطار", "بیشترین تکرار"], ascending=False)
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
