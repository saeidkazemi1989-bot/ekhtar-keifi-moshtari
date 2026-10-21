"""قواعد تشخیص خانواده/محصول از روی نام قطعه.

این قواعد عمداً شفاف و قابل بازبینی هستند: هر قاعده یک الگوی متنی روی نسخهٔ
بدون‌فاصلهٔ نام دارد و در صورت تشخیص خانواده، نزدیک‌ترین محصولِ همان خانواده در
فایل «گروه بندی محصولات» انتخاب می‌شود.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import normalize, squash

OUT_GROUP = "خارج از دامنه گروه‌بندی"
UNKNOWN = "نامشخص"


@dataclass(frozen=True)
class Mapping:
    group: str
    family: str
    product: str
    in_scope: bool
    in_catalog: bool
    confidence: str
    method: str
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.family}|{self.product}"


def _mapping(
    group: str,
    family: str,
    product: str,
    *,
    in_catalog: bool = False,
    confidence: str = "متوسط",
    method: str = "قاعده نام",
    note: str = "",
) -> Mapping:
    return Mapping(
        group=group,
        family=family,
        product=product,
        in_scope=group != OUT_GROUP,
        in_catalog=in_catalog,
        confidence=confidence,
        method=method,
        note=note,
    )


# ---------------------------------------------------------------- خودرو / موتور
_VEHICLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("DENA+", ("دناپلاس", "دنا پلاس", "denaplus", "dena plus", "dena+", "dena plus")),
    ("DENA", ("دنا", "dena")),
    ("TARA", ("تارا", "tara", "k132")),
    ("SOREN", ("سورن", "soren")),
    ("ARISUN", ("اریسان", "آریسان", "arisun")),
    ("207", ("207", "p7l", "p207", "k132")),
    ("206", ("206", "p206")),
    ("405", ("405",)),
    ("PARS", ("پارس", "pars")),
    ("SAMAND", ("سمند", "samand")),
    ("RANA", ("رانا", "runna", "rana")),
    ("X100", ("x100", "پراید", "pride", "131")),
    ("SAINA", ("ساینا", "saina")),
    ("SHAHIN", ("شاهین", "shahin")),
    ("X200", ("x200", "تیبا", "tiba")),
    ("301", ("301", "p301")),
    ("P90", ("p90",)),
    ("QUIK", ("کوییک", "کوئیک", "quik", "quick")),
    ("ATLAS", ("اطلس", "atlas")),
    ("SAHAND", ("سهند", "sahand")),
    ("NISSAN", ("نیسان", "nissan")),
    ("XUP", ("xup",)),
]

_CAR_GROUP = {
    "تارا": "TARA",
    "پژو پارس": "PARS",
    "پژو 207": "207",
    "پژو 206": "206",
    "پژو 206 صندوق دار": "206",
    "دناپلاس": "DENA+",
    "سمند": "SAMAND",
    "دنا": "DENA",
    "پژو 405": "405",
    "سورن": "SOREN",
    "رانا": "RANA",
    "آریسان": "ARISUN",
    "اریسان": "ARISUN",
    "پژو 301": "301",
}

_VEHICLE_FA = {
    "DENA+": "دناپلاس",
    "DENA": "دنا",
    "TARA": "تارا",
    "SOREN": "سورن",
    "ARISUN": "آریسان",
    "207": "207",
    "206": "206",
    "405": "405",
    "PARS": "پارس",
    "SAMAND": "سمند",
    "RANA": "رانا",
    "X100": "پراید/X100",
    "SAINA": "ساینا",
    "SHAHIN": "شاهین",
    "X200": "تیبا/X200",
    "301": "301",
    "P90": "P90",
    "QUIK": "کوییک",
    "ATLAS": "اطلس",
    "SAHAND": "سهند",
    "NISSAN": "نیسان",
    "XUP": "XUP",
}


def detect_vehicle(text: str, car_group: str | None = None) -> str | None:
    """تشخیص خودرو از روی عنوان یا ستون «گروه خودرو»."""
    if car_group:
        key = normalize(car_group)
        if key in _CAR_GROUP:
            return _CAR_GROUP[key]
    norm = normalize(text)
    padded = f" {norm} "
    for vehicle, patterns in _VEHICLE_PATTERNS:
        for pattern in patterns:
            if len(pattern) <= 3 and pattern.isdigit():
                if re.search(rf"(?<!\d){re.escape(pattern)}(?!\d)", norm):
                    return vehicle
            elif pattern in {"xup", "p90"}:
                if re.search(rf"(?<![a-z]){re.escape(pattern)}(?![a-z])", norm):
                    return vehicle
            elif pattern in padded:
                return vehicle
    return None


def vehicle_label(vehicle: str | None) -> str:
    if not vehicle:
        return UNKNOWN
    return _VEHICLE_FA.get(vehicle, vehicle)


def _has(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _flag(text: str, kind: str) -> bool:
    if kind == "auto":
        return _has(text, "اتومات", "auto")
    if kind == "full_lcd":
        return _has(text, "full_lcd", "full lcd", "full-lcd", "fulllcd")
    if kind == "pin46":
        return _has(text, "46pin", "46 pin", "46پین", "46پين")
    if kind == "mt":
        return bool(re.search(r"(?<![a-z])mt(?![a-z])", text)) or "دستی" in text
    if kind == "at":
        return bool(re.search(r"(?<![a-z])at(?![a-z])", text))
    if kind == "assembly":
        return _has(text, "مونتاژ", "تکمیل")
    if kind == "digital":
        return _has(text, "دیجیتال", "digital")
    if kind == "front":
        return _has(text, "جلو", "front")
    if kind == "rear":
        return _has(text, "عقب", "rear")
    if kind == "left":
        return _has(text, "چپ", "left", "lh")
    if kind == "right":
        return _has(text, "راست", "right", "rh")
    if kind == "disc":
        return "دیسک" in text
    return False


# ---------------------------------------------------------------- خانواده‌ها
@dataclass(frozen=True)
class Rule:
    family: str
    group: str
    patterns: tuple[str, ...]
    priority: int
    exclude: tuple[str, ...] = ()


_RULES: tuple[Rule, ...] = (
    Rule("آنتن ایموبلایزر", "EMS-توسعه و نگاشت موتور", ("انتن.*ایمو", "antennainmo"), 10),
    Rule(
        "یونیت",
        "EMS-توسعه و نگاشت موتور",
        ("ایمو.*لایزر", "ایموبیلایزر", "eim", "واحدالکترونیکیsatt", "واحداکترونیکیsatt", "کنترلیونیت", "یونیتکنترل"),
        12,
        exclude=("انتن",),
    ),
    Rule("کارت حاوی کد دسترسی", "EMS-توسعه و نگاشت موتور", ("کددسترسی", "کارتحاوی", "روتکارت"), 14),
    Rule("MFD", "Display Unit", ("mfd", "نمایشگردیجیتال", "صفحهنمایش", "نمایشگردیجیتالی"), 20, exclude=("پنل", "پوشش", "قاب")),
    Rule("TMAP", "EMS-توسعه و نگاشت موتور", ("tmap", "مپسنسور", "سنسوردما.*فشار", "دماوفشارهوا"), 22),
    Rule(
        "سنسور موقعیت",
        "EMS-توسعه و نگاشت موتور",
        ("سنسورمیل", "میلسوپاپ", "میلبادامک", "حسگرزاویه", "سنسورموقعیتمیل"),
        24,
    ),
    Rule("سنسور اكسيژن", "TP-قطعات جانبی قوای محرکه", ("سنسوراکسیژن", "حسگراکسیژن", "اکسیژن"), 26),
    Rule(
        "انژکتور بنزین",
        "EMS-توسعه و نگاشت موتور",
        ("انژکتور", "injector"),
        28,
        exclude=("دسته‌سیم", "دستهسیم", "سیم", "سوکت", "کابل", "بچه"),
    ),
    Rule("دریچه گاز برقی", "TP-قطعات جانبی قوای محرکه", ("دریچهگاز", "محفظهدریچهگاز", "هوایورودی"), 30),
    Rule("TV", "TP-قطعات جانبی قوای محرکه", ("شیر.*مخزن", "سرسمخزن", "رگلاتور", "رگولاتور"), 32),
    Rule("APM", "TP-قطعات جانبی قوای محرکه", ("پدالگاز", "apm"), 34),
    Rule(
        "ECU",
        "EMS-توسعه و نگاشت موتور",
        (
            "رایانهموتور",
            "رایانه.*موتور",
            "ecu",
            "واحد.*کنترل.*موتور",
            "جعبهالکترونیکیموتور",
            "جعبهکنترل.*الکترونیک",
            "کنترلرموتور",
            "یونیتکنترل",
            "واحدپردازش",
            "جعبهالکترونیکی.*(xu7|tu5|ef7|s4|lx)",
        ),
        11,
    ),
    Rule("مدولاتور", "SBS-سیستم های ایمنی ترمز", ("مدولاتور", "بلوک.*ترمز", "ایاسسی", "esc"), 44),
    Rule(
        "سنسور ABS",
        "SBS-سیستم های ایمنی ترمز",
        ("سنسور.*abs", "سنسور.*ضدقفل", "سنسور.*ترمز", "سنسور.*سرعتچرخ", "سنسور.*چرخ", "ضدقفل", "abs"),
        46,
        exclude=("مدولاتور", "بلوک"),
    ),
    Rule(
        "Switch",
        "Switch",
        ("کلیدشیشه", "شیشهبالابر", "switch", "دستگیره", "قابکلیدشیشه"),
        50,
        exclude=("پوشش", "لچ", "طلق", "بدنه"),
    ),
    Rule("BCMI", "Nodes", ("bcmi",), 54),
    Rule(
        "NBCM",
        "Nodes",
        (
            "nbcm",
            "bcm",
            "مالتیپلکس",
            "نود",
            "واحدمرکزی",
            "cec",
            "dcn",
            "کنترلکنندهدرها",
            "جعبهالکترونیکیجلو",
            "جعبهالکترونیکیعقب",
            "جلوfn",
            "عقبrn",
            "fnتبادلی",
            "rnتبادلی",
        ),
        56,
        exclude=("داشبورد", "صندلی", "کنسول", "جلوامپر", "دستهسیم", "سیمکشی", "درب", "درپوش", "قاب", "پوشش", "لچ"),
    ),
    Rule("SBM", "Nodes", ("sbm",), 58),
    Rule(
        "ICN",
        "Cluster Instrument",
        ("icn", "ipd", "جلوامپر", "جلوامپردیجیتال", "امپردورموتور", "امپرسوخت", "امپراب", "امپردما", "امپر"),
        60,
        exclude=("دینام", "باتری", "شارژ", "کولرگازی", "دستهسیم", "سیمکشی", "سیمبرق"),
    ),
    Rule("ماژول RF Module", "سایر", ("rfmodule", "ماژولrf"), 64),
    Rule("درایو کولر", "درایو کولر", ("درایوکولر",), 66),
)

_OUT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("قفل و سوئیچ", ("قفل", "مغزی", "سوییچ", "سوئیچ", "سوئیچی")),
    ("داشبورد", ("داشبورد",)),
    ("دسته سیم", ("دستهسیم", "سیمکشی", "سیمبرق", "دستهسیمها", "سوکتایربگ", "سوکتایربک", "سوکتاربگ")),
    ("کویل/جرقه", ("کویل", "جرقه", "ignitioncoil", "ignitioncoils")),
    ("بدنه/درب/سپر", ("سپر", "بدنه", "گلگیر", "صندوق", "درب")),
    ("رادیو/صوتی", ("رادیو", "پخش", "بلندگو", "اسپیکر")),
    ("آژیر/هشدار", ("آژیر", "اژیر", "بوق", "هشداردهنده")),
    ("قفل/ریموت", ("rke", "گیرندهفرستنده", "قفلرادیویی", "ریموت", "تگ")),
    ("دینام/استارت/باتری", ("دینام", "استارت", "باتری", "الترناتور")),
    ("سوخت‌رسانی", ("ریلسوخت", "ریل", "شیربخارات", "بخارات", "پمپبنزین")),
    ("صندلی/تزئینات", ("صندلی", "تزئینات", "کنسول", "پنل", "تودوزی")),
    ("جعبه فیوز", ("جعبهفیوز", "فیوزورله", "جعبهمحافظکنترل")),
    ("کلید و دسته فرمان", ("کلیدچراغ", "دستهراهنما", "ستونفرمان", "قابستون", "زیروروییفرمان")),
    ("مخزن CNG", ("مخزن", "کپسولگاز")),
    ("اکسل/تعلیق", ("اکسل", "رودری", "تعلیق")),
    ("سایر", ()),
)


def detect_family(text: str) -> Rule | None:
    body = squash(text)
    if not body:
        return None
    for rule in sorted(_RULES, key=lambda item: item.priority):
        if any(keyword in body for keyword in rule.exclude):
            continue
        if any(re.search(pattern, body) for pattern in rule.patterns):
            return rule
    return None


def out_of_scope_category(text: str) -> str:
    body = squash(text)
    for label, patterns in _OUT_RULES:
        if not patterns:
            return label
        if any(pattern in body for pattern in patterns):
            return label
    return "سایر"


# ---------------------------------------------------------------- انتخاب محصول
def _score_candidate(candidate: str, text: str, vehicle: str | None, rule: str) -> float:
    c_norm = normalize(candidate)
    c_squash = squash(candidate)
    score = 0.0

    c_vehicle = detect_vehicle(candidate)
    if c_vehicle:
        if vehicle:
            score += 40 if c_vehicle == vehicle or {c_vehicle, vehicle} <= {"DENA", "DENA+"} else -80
        else:
            score -= 2
    elif vehicle:
        score += 2

    # موتور / پلتفرم
    for token, weight in (("ef7", 18), ("me17", 14), ("tu5", 14), ("ec5", 12), ("xu7", 10), ("xup", 8), ("s4", 6)):
        if token in c_squash or token in squash(text):
            if token in c_squash and token in squash(text):
                score += weight
            elif token in c_squash:
                score -= 3

    # حالت‌ها
    for kind, weight in (("auto", 12), ("full_lcd", 12), ("pin46", 10), ("mt", 6), ("digital", 8), ("assembly", 8)):
        if _flag(c_squash, kind) and _flag(squash(text), kind):
            score += weight
        elif _flag(c_squash, kind):
            score -= 2

    # موقعیت
    for kind, weight in (("front", 8), ("rear", 8), ("left", 6), ("right", 6), ("disc", 6)):
        if _flag(c_squash, kind) and _flag(squash(text), kind):
            score += weight
        elif _flag(c_squash, kind):
            score -= 1

    # شباهت واژگانی
    c_tokens = set(c_norm.split())
    t_tokens = set(normalize(text).split())
    if c_tokens and t_tokens:
        overlap = len(c_tokens & t_tokens)
        score += overlap * 2
        score += 6 * overlap / max(len(c_tokens), 1)

    return score


def _best(candidates: list[str], text: str, vehicle: str | None, rule: str) -> tuple[str | None, float]:
    best: tuple[str | None, float] = (None, float("-inf"))
    for candidate in candidates:
        value = _score_candidate(candidate, text, vehicle, rule)
        if value > best[1]:
            best = (candidate, value)
    return best


def _pick_icn(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "ipd1" in body:
        return ("IPD1 ARISUN", "IPD1 2AB", True)
    if "ipd2" in body or "ipd4" in body:
        return ("ICN2 X100", "ICN2 X100", True)
    if vehicle in {"DENA", "DENA+"}:
        return ("ICN1 DENA", "ICN1 DENA", True)
    if vehicle == "TARA":
        if _flag(body, "full_lcd"):
            return ("ICN1 TARA (FULL_LCD)", "ICN1 TARA", True)
        if _flag(body, "auto"):
            return ("ICN1 TARA اتوماتیک", "ICN1 TARA", True)
        return ("ICN1 TARA", "ICN1 TARA", True)
    if vehicle == "SOREN":
        return ("ICN1 SOREN", "ICN1 SOREN", True)
    if vehicle == "207":
        product = "ICN1 207 اتوماتیک" if _flag(body, "auto") else "ICN1 207"
        return (product, "ICN1 207", True)
    if vehicle == "ARISUN":
        return ("ICN1 ARISUN", "ICN1 ARISUN", True)
    if vehicle in {"X100", "X200"}:
        return ("ICN2 X100", "ICN2 X100", True)
    return (f"جلوآمپر {vehicle_label(vehicle)}", "ICN (سایر)", False)


def _pick_mfd(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    if vehicle in {"206", "207"}:
        return ("MFD 206 PLUS", "MFD", True)
    if vehicle == "RANA":
        return ("MFD RUNNA", "MFD", True)
    return ("نمایشگر دیجیتال - سایر", "MFD (سایر)", False)


def _pick_nbcm(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    mapping = {
        "DENA": ("NBCM DENA", "NBCM"),
        "DENA+": ("NBCM DENA", "NBCM"),
        "TARA": ("NBCM TARA", "NBCM"),
        "207": ("NBCM 207", "NBCM"),
        "SOREN": ("NBCM SOREN", "NBCM"),
    }
    if vehicle in mapping:
        product, family = mapping[vehicle]
        return (product, family, True)
    return ("NBCM - سایر", "NBCM (سایر)", False)


def _pick_sbm(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    mapping = {
        "207": ("SBM207", "SBM"),
        "206": ("SBM207", "SBM"),
        "SOREN": ("SBM SOREN", "SBM"),
        "ARISUN": ("SBM ARISUN", "SBM"),
    }
    if vehicle in mapping:
        product, family = mapping[vehicle]
        return (product, family, True)
    return ("SBM", "SBM", True)


def _pick_bcmi(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    mapping = {
        "DENA": ("BCMI DENA", "BCMI"),
        "DENA+": ("BCMI DENA", "BCMI"),
        "TARA": ("BCMI TARA", "BCMI"),
        "207": ("BCMI207", "BCMI"),
    }
    if vehicle in mapping:
        product, family = mapping[vehicle]
        return (product, family, True)
    return ("BCMI - سایر", "BCMI (سایر)", False)


def _pick_ecu(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "ef7" in body:
        if "euro5" in body or "euro 5" in normalize(text):
            return ("جعبه الکترونیکی موتور بنزینی EF7-S2 Euro5", "ECU مونتاژی", True)
        return ("ECU S4 EF7P TARA", "ECU", True)
    if "ec5" in body and vehicle in {"207", "206"}:
        return ("ECU S4 EC5 207 MT5", "ECU مونتاژی", True)
    if "ec5" in body and vehicle == "TARA":
        return ("ECU S4 EC5 TARA MT6", "ECU مونتاژی", True)
    if "tu5" in body:
        if "pars" in body or "euro5" in body or "etc" in body:
            return ("ECU TU5 ETC PARS EURO 5 KESENS", "ECU", True)
        return ("ECU TU5", "ECU", True)
    if "xu7" in body or "xup" in body or "sbcm" in body:
        return ("ECU S4 XUP SBCM", "ECU مونتاژی", True)
    if "s4" in body:
        return ("ECU S4 4coil", "ECU مونتاژی", True)
    if vehicle == "TARA":
        return ("ECU S4 4coil", "ECU مونتاژی", True)
    if _flag(body, "assembly"):
        return ("ECU S4 4coil", "ECU مونتاژی", True)
    return ("ECU - سایر", "ECU (سایر)", False)


def _pick_apm(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "ef7" in body:
        return ("APM EF7", "APM", True)
    if "tu5" in body or "me17" in body:
        return ("APM ME17 TU5 - مونتاژی", "APM", True)
    if "xup" in body or "xu7" in body:
        return ("پدال گاز برقی XUP", "APM", True)
    return ("APM - سایر", "APM (سایر)", False)


def _pick_o2(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "براکت" in body:
        return ("براکت سنسور اکسیژن P301", "سنسور اكسيژن", True)
    if "tu5" in body:
        if "بالا" in body or "گلویی" in body:
            return ("سنسور اکسیژن روی گلویی اگزوز( بالایی) TU5-SSAT", "سنسور اكسيژن", True)
        return ("سنسور اکسیژن LSF TU5 سمندی", "سنسور اكسيژن", True)
    return ("سنسور اکسیژن - سایر", "سنسور اكسيژن (سایر)", False)


def _pick_injector(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "ef7" in body:
        return ("انژکتور بنزین  EF7", "انژکتور بنزین", True)
    if "tu5" in body or "405" in body:
        return ("انژکتور بنزین TU5 405", "انژکتور بنزین", True)
    return ("انژکتور - سایر", "انژکتور بنزین (سایر)", False)


def _pick_throttle(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "ef7" in body:
        return ("دریچه گاز EF7 - S2 کبودا", "دریچه گاز برقی", True)
    if "tu5" in body or "ec5" in body or "301" in body or "206" in body:
        return ("دریچه گاز TU5 - EC5 کبودا", "دریچه گاز برقی", True)
    return ("دریچه گاز - سایر", "دریچه گاز برقی (سایر)", False)


def _pick_cng(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "رگلاتور" in body or "رگولاتور" in body:
        return ("رگلاتور گاز - سایر", "TV (سایر)", False)
    return ("شیر سر مخزن CNG SPCO کامل", "TV", True)


def _pick_tmap(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "xu7" in body:
        return ("سنسور دما و فشار هوای ورودی XU7 - S", "TMAP", True)
    if "tu5" in body or "ec5" in body:
        return ("TMAP TU5 SSAT", "TMAP", True)
    return ("TMAP - سایر", "TMAP (سایر)", False)


def _pick_cam(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if vehicle in {"TARA", "207"}:
        return ("سنسور میل سوپاپ TARA/207 EC5", "سنسور موقعیت", True)
    if "tu5" in body or "ec5" in body:
        return ("سنسور میل بادامک TU5 EC5", "سنسور موقعیت", True)
    return ("سنسور موقعیت - سایر", "سنسور موقعیت (سایر)", False)


def _pick_card(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "xup" in body:
        return ("کارت حاوی کد دسترسی XUP", "کارت حاوی کد دسترسی", True)
    if "ssat" in body or "etc" in body:
        return ("کارت حاوی کد دسترسی SSAT ETC", "کارت حاوی کد دسترسی", True)
    return ("کارت کد دسترسی - سایر", "کارت حاوی کد دسترسی (سایر)", False)


def _pick_abs(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "مدولاتور" in body or "بلوک" in body:
        return ("", "", False)  # توسط قاعده مدولاتور مدیریت می‌شود
    if vehicle in {"405", "SAMAND"}:
        if _flag(body, "rear"):
            side = "چپ" if _flag(body, "left") else "راست" if _flag(body, "right") else ""
            if side:
                return (f"سنسور ABS عقب {side} 405 و سمند یوفین - دیسکی", "سنسور ABS", True)
        if _flag(body, "front"):
            return ("سنسور ترمز ضد قفل جلو 405 یوفین", "سنسور ABS", True)
        return ("سنسور ABS عقب راست 405 و سمند یوفین - دیسکی", "سنسور ABS", True)
    if vehicle == "301" and "301" in body:
        if _flag(body, "front"):
            return ("سنسور سرعت چرخ جلو خودروی P301 یوفین", "سنسور ABS", True)
        if _flag(body, "rear"):
            return ("سنسور سرعت چرخ عقب خودروی P301 یوفین", "سنسور ABS", True)
    if vehicle in {"206", "RANA"}:
        if _flag(body, "front"):
            return ("سنسور سرعت چرخ جلو (TU5) 206/RUNNA یوفین", "سنسور ABS", True)
        return ("سنسور سرعت چرخ عقب(TU5) 206/RUNNAیوفین", "سنسور ABS", True)
    if vehicle == "207":
        if _flag(body, "front"):
            return ("سنسور سرعت چرخ جلو (TU5) 206/RUNNA یوفین", "سنسور ABS", True)
        return ("سنسور عقب 207 TU5 ABS YF", "سنسور", True)
    return ("سنسور ABS - سایر", "سنسور ABS (سایر)", False)


def _pick_modulator(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    is_esc = "esc" in body or "ایاسسی" in body or _flag(body, "pin46")
    family = "مدولاتور"  # در فایل گروه‌بندی، خط ESC و مدولاتور یک خانواده حساب می‌شود
    if vehicle in {"301"}:
        return ("ESC" if is_esc else "مدولاتور اتوماتیک ABS P301 ESC یوفین", family, True)
    if vehicle in {"207", "206", "RANA"}:
        if is_esc:
            return ("ESC 207 46Pin", family, True)
        if vehicle == "RANA":
            return ("مدولاتور ABS یوفین 206+", family, True)
        return ("مجموعه مدولاتور 207 - یوفین", family, True)
    if vehicle in {"DENA", "DENA+"}:
        if is_esc:
            return ("ESC DENA+ 46PIN", family, True)
        return ("مدولاتور DENA- AT" if _flag(body, "auto") else "مدولاتور DENA- MT", family, True)
    if vehicle == "TARA":
        return ("ESC TARA MT6 46Pin", family, True)
    if vehicle == "SOREN":
        return ("ESC SOREN XUP 46Pin" if is_esc else "SOREN -MT  مدولاتور", family, True)
    if vehicle in {"QUIK", "ATLAS"}:
        return (" مدولاتور کوئیک و اطلس دستی", family, True)
    if vehicle == "SAINA" or vehicle == "SAHAND":
        return (" مدولاتورساینا و سهند CVT", family, True)
    if vehicle == "SHAHIN":
        return ("  ESC مدولاتور شاهین پلاس", family, True)
    if vehicle == "P90":
        return ("مدولاتور ESC P90 MT", family, True)
    if vehicle == "X200":
        return ("مدولاتور ABS تیبا X200 YF9 یوفین", family, True)
    return ("مدولاتور/ESC - سایر", "مدولاتور (سایر)", False)


def _pick_switch(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if vehicle in {"DENA", "DENA+"}:
        if _flag(body, "rear"):
            return ("DENA-RWS DENA", "Switch", True)
        return ("DENA-DWMS DENA", "Switch", True)
    if vehicle == "207":
        return ("PRW 207", "Switch", True)
    if vehicle == "SOREN":
        if _flag(body, "front"):
            return ("SOREN-FR-LH SOREN" if not _flag(body, "right") else "SOREN-FR-RH SOREN", "Switch", True)
        if _flag(body, "rear"):
            return ("SOREN-RE-LH SOREN" if not _flag(body, "right") else "SOREN-RE-RH SOREN", "Switch", True)
        return ("SOREN-FR-LH SOREN", "Switch", True)
    return ("Switch - سایر", "Switch (سایر)", False)


def _pick_rf(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "m211" in body:
        return ("ماژول RF Module_M211", "ماژول RF Module", True)
    if "t312" in body:
        return ("ماژول RF Module_T312", "ماژول RF Module", True)
    return ("ماژول RF Module - سایر", "ماژول RF Module", False)


def _pick_immobilizer(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    body = squash(text)
    if "برد" in body:
        if "ماشین" in body:
            return ("برد الکترونیکی ایموبلایزر EIM -مونتاژ ماشینی شده", "یونیت", True)
        return ("برد الکترونیکی ایموبلایزر EIM -مونتاژ و لحیم شده", "یونیت", True)
    if "دسته‌سیم" in body or "دسته سیم" in normalize(text):
        return ("بچه دسته سیم آنتن ایموبلایزر SSAT-مونتاژ شده", "یونیت", True)
    if "جعبه" in body:
        return ("جعبه الکترونیکی ایموبلایزر EIM -تکمیل کاری شده", "یونیت", True)
    return ("يونيت ایموبلایزر موتور EC5", "یونیت", True)


def _pick_antenna(text: str, vehicle: str | None) -> tuple[str, str, bool]:
    if "xup" in squash(text):
        return ("آنتن ایموبلایزر XU7 - S  -XUP مونتاژی", "آنتن ايموبلايزر", True)
    return ("آنتن ایموبلایزر XU7 - S  - مونتاژی", "آنتن ايموبلايزر", True)


_PICKERS = {
    "ICN": _pick_icn,
    "MFD": _pick_mfd,
    "NBCM": _pick_nbcm,
    "SBM": _pick_sbm,
    "BCMI": _pick_bcmi,
    "ECU": _pick_ecu,
    "APM": _pick_apm,
    "سنسور اكسيژن": _pick_o2,
    "انژکتور بنزین": _pick_injector,
    "دریچه گاز برقی": _pick_throttle,
    "TV": _pick_cng,
    "TMAP": _pick_tmap,
    "سنسور موقعیت": _pick_cam,
    "کارت حاوی کد دسترسی": _pick_card,
    "سنسور ABS": _pick_abs,
    "مدولاتور": _pick_modulator,
    "Switch": _pick_switch,
    "ماژول RF Module": _pick_rf,
    "یونیت": _pick_immobilizer,
    "آنتن ایموبلایزر": _pick_antenna,
}


def classify_text(text: str, car_group: str | None = None) -> Mapping:
    """تشخیص گروه/خانواده/محصول از روی متن نام قطعه."""
    raw = "" if text is None else str(text)
    rule = detect_family(raw)
    vehicle = detect_vehicle(raw, car_group)
    if rule is None:
        category = out_of_scope_category(raw)
        return _mapping(
            OUT_GROUP,
            f"خارج از دامنه - {category}",
            category,
            confidence="—",
            method="خارج از دامنه",
        )

    picker = _PICKERS.get(rule.family)
    if picker is None:
        return _mapping(
            rule.group,
            rule.family,
            rule.family,
            in_catalog=True,
            confidence="متوسط",
            method="قاعده نام",
        )

    product, family, exact = picker(raw, vehicle)
    if not product:
        # موردی که باید با قاعدهٔ دیگری بررسی شود
        category = out_of_scope_category(raw)
        return _mapping(
            OUT_GROUP,
            f"خارج از دامنه - {category}",
            category,
            confidence="—",
            method="خارج از دامنه",
        )

    if exact:
        return _mapping(
            rule.group,
            family,
            product,
            in_catalog=True,
            confidence="بالا" if vehicle or rule.family in {"یونیت", "آنتن ایموبلایزر"} else "متوسط",
            method="قاعده نام + خودرو" if vehicle else "قاعده نام",
            note=vehicle_label(vehicle) if vehicle else "",
        )

    return _mapping(
        rule.group,
        family,
        product,
        in_catalog=False,
        confidence="پایین",
        method="قاعده نام (محصول خارج از فایل گروه‌بندی)",
        note=vehicle_label(vehicle) if vehicle else "",
    )
