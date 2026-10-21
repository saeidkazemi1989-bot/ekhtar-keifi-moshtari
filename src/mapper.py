"""ساخت نقشهٔ «محصول نهایی راهکاران ← گروه بندی محصولات» و غنی‌سازی اخطارها."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from .catalog import Catalog, CatalogProduct
from .normalize import jalali_parts, normalize, tech_variants
from .taxonomy import Mapping, classify_text, detect_vehicle, vehicle_label, OUT_GROUP

MONTH_NAMES = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


@dataclass
class ProductRecord:
    code: str
    title: str
    latin: str
    status: str
    tech_raw: str
    tech_keys: set[str]
    mapping: Mapping
    vehicle: str | None
    catalog: CatalogProduct | None = None


@dataclass
class TechMatch:
    record: ProductRecord
    candidates: list[ProductRecord]
    score: float
    exact: bool


@dataclass
class WarningMapping:
    group: str
    family: str
    product: str
    product_code: str
    product_family: str
    product_desc: str
    method: str
    confidence: str
    in_catalog: bool
    rahkaran_code: str = ""
    rahkaran_title: str = ""
    candidates: int = 0
    note: str = ""


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _preferred(records: list[ProductRecord]) -> ProductRecord:
    def score(record: ProductRecord) -> tuple:
        pool = record.mapping.in_catalog, record.mapping.in_scope
        exchange = "تبادلی" in record.title
        active = record.status != "غیر فعال"
        exchange_code = record.code.startswith("39")
        return (pool, not exchange, not exchange_code, active, -len(record.title), -int(record.code or 0))

    return sorted(records, key=score, reverse=True)[0]


def _catalog_product(catalog: Catalog, mapping: Mapping) -> CatalogProduct | None:
    if not mapping.product:
        return None
    items = catalog.by_product.get(mapping.product, [])
    for item in items:
        if item.family == mapping.family:
            return item
    return items[0] if items else None


class ProductMapper:
    def __init__(self, listdata_path: str | Path, catalog: Catalog):
        self.catalog = catalog
        self.frame = pd.read_excel(listdata_path)
        self.records: list[ProductRecord] = []
        self.by_code: dict[str, ProductRecord] = {}
        self.by_tech: dict[str, list[ProductRecord]] = {}
        self.by_title: dict[str, list[ProductRecord]] = {}
        self._build()

    def _build(self) -> None:
        for _, row in self.frame.iterrows():
            code = _clean(row.get("کد"))
            title = _clean(row.get("عنوان"))
            latin = _clean(row.get("عنوان لاتین"))
            status = _clean(row.get("وضعیت"))
            tech_raw = _clean(row.get("مشخصه فنی"))
            mapping = classify_text(title)
            catalog_product = self.catalog.by_code.get(normalize(code).replace(" ", ""))
            if catalog_product is not None:
                mapping = Mapping(
                    group=catalog_product.group,
                    family=catalog_product.family,
                    product=catalog_product.product,
                    in_scope=catalog_product.group != OUT_GROUP and catalog_product.group != "-",
                    in_catalog=True,
                    confidence="قطعی",
                    method="کد راهکاران در فایل گروه‌بندی",
                    note="",
                )
            record = ProductRecord(
                code=code,
                title=title,
                latin=latin,
                status=status,
                tech_raw=tech_raw,
                tech_keys=tech_variants(tech_raw),
                mapping=mapping,
                vehicle=detect_vehicle(title),
                catalog=catalog_product,
            )
            self.records.append(record)
            self.by_code[code] = record
            for key in record.tech_keys:
                self.by_tech.setdefault(key, []).append(record)
            self.by_title.setdefault(normalize(title), []).append(record)

    # ------------------------------------------------------------------ tech
    def resolve_tech(self, tech_value: object, part_text: str = "", car_group: str = "") -> TechMatch | None:
        keys = tech_variants(tech_value)
        if not keys:
            return None
        seen: dict[str, ProductRecord] = {}
        for key in keys:
            for record in self.by_tech.get(key, []):
                seen[record.code] = record
        if not seen:
            return None
        candidates = list(seen.values())
        car_vehicle = detect_vehicle("", car_group)
        part_norm = normalize(part_text)

        def score(record: ProductRecord) -> float:
            value = 0.0
            if record.mapping.in_catalog:
                value += 6
            if record.mapping.in_scope:
                value += 3
            if record.vehicle and car_vehicle and record.vehicle == car_vehicle:
                value += 6
            if record.vehicle and car_vehicle and record.vehicle != car_vehicle:
                value -= 3
            if part_norm:
                value += fuzz.token_set_ratio(part_norm, normalize(record.title)) / 25
            if "تبادلی" in record.title:
                value -= 2
            if record.code.startswith("39"):
                value -= 1
            if record.status == "غیر فعال":
                value -= 2
            return value

        best = sorted(candidates, key=score, reverse=True)[0]
        return TechMatch(record=best, candidates=candidates, score=score(best), exact=len(candidates) == 1)

    # ------------------------------------------------------------------ name
    def resolve_name(self, name: str) -> ProductRecord | None:
        target = normalize(name)
        if not target:
            return None
        exact = self.by_title.get(target)
        if exact:
            return _preferred(exact)
        if len(target) < 8:
            return None
        best_title: str | None = None
        best_score = 0.0
        for title in self.by_title:
            if len(title) < 8:
                continue
            value = fuzz.token_set_ratio(target, title)
            if value > best_score:
                best_title, best_score = title, value
        if best_title and best_score >= 93:
            return _preferred(self.by_title[best_title])
        return None

    # ------------------------------------------------------------------ warning
    def map_warning(
        self,
        part_text: str,
        origin_text: str,
        tech_value: object,
        car_group: str,
    ) -> WarningMapping:
        tech = self.resolve_tech(tech_value, part_text, car_group)
        if tech is not None:
            record = tech.record
            mapping = record.mapping
            # اگر خودِ عنوان محصول خودرو را مشخص نکرده باشد، از گروه خودروی اخطار کمک می‌گیریم
            if record.vehicle is None and car_group:
                refined = classify_text(record.title, car_group)
                if refined.in_catalog or (
                    refined.group != OUT_GROUP and mapping.group == OUT_GROUP
                ):
                    mapping = refined
            catalog_product = record.catalog or _catalog_product(self.catalog, mapping)
            return WarningMapping(
                group=mapping.group,
                family=mapping.family,
                product=mapping.product,
                product_code=(catalog_product.code_raw if catalog_product else ""),
                product_family=mapping.family,
                product_desc=record.title,
                method=(
                    "شماره فنی ← کد راهکاران ← کد گروه"
                    if catalog_product
                    else "شماره فنی ← کد راهکاران ← نام محصول"
                ),
                confidence=(
                    "قطعی"
                    if record.catalog
                    else ("بالا" if catalog_product else ("متوسط" if tech.exact else "پایین"))
                ),
                in_catalog=catalog_product is not None,
                rahkaran_code=record.code,
                rahkaran_title=record.title,
                candidates=len(tech.candidates),
                note=mapping.note,
            )

        # بدون شماره فنی: ابتدا نام قطعه، سپس شرح منشا
        part_mapping = classify_text(part_text, car_group)
        used_origin = False
        generic_out = part_mapping.group == OUT_GROUP and part_mapping.family.endswith("سایر")
        if (
            generic_out
            and origin_text
            and not origin_text.strip().isdigit()
        ):
            origin_mapping = classify_text(origin_text, car_group)
            if origin_mapping.group != OUT_GROUP:
                part_mapping = origin_mapping
                used_origin = True

        if part_mapping.group == OUT_GROUP:
            method = "بدون تطابق" if generic_out else "شرح قطعه (خارج از دامنه)"
        else:
            method = "شرح منشا" if used_origin else "شرح قطعه"
        catalog_product = _catalog_product(self.catalog, part_mapping) if part_mapping.in_catalog else None
        return WarningMapping(
            group=part_mapping.group,
            family=part_mapping.family,
            product=part_mapping.product,
            product_code=(catalog_product.code_raw if catalog_product else ""),
            product_family=part_mapping.family,
            product_desc="",
            method=method,
            confidence=part_mapping.confidence,
            in_catalog=catalog_product is not None,
            note=part_mapping.note,
        )

    def map_product(self, record: ProductRecord) -> Mapping:
        return record.mapping


def product_table(mapper: ProductMapper) -> pd.DataFrame:
    rows = []
    for record in mapper.records:
        mapping = record.mapping
        cat = _catalog_product(mapper.catalog, mapping)
        rows.append(
            {
                "کد محصول (راهکاران)": record.code,
                "نام محصول (راهکاران)": record.title,
                "عنوان لاتین": record.latin,
                "وضعیت": record.status,
                "مشخصه فنی": record.tech_raw,
                "خودرو": vehicle_label(record.vehicle) if record.vehicle else "",
                "گروه محصول نهایی": mapping.group,
                "خانواده محصول": mapping.family,
                "محصول": mapping.product,
                "کد گروه محصول": (cat.code_raw if cat else ""),
                "در فایل گروه‌بندی": "بله" if mapping.in_catalog else "خیر",
                "روش تطبیق": mapping.method,
                "اطمینان": mapping.confidence,
                "توضیح": mapping.note,
            }
        )
    return pd.DataFrame(rows)


def enrich_warnings(warnings: pd.DataFrame, mapper: ProductMapper) -> pd.DataFrame:
    rows = []
    for _, row in warnings.iterrows():
        part = _clean(row.get("شرح قطعه"))
        origin = _clean(row.get("شرح منشا"))
        tech = row.get("شماره فني")
        car = _clean(row.get("گروه خودرو"))
        mapping = mapper.map_warning(part, origin, tech, car)
        year, month, day = jalali_parts(row.get("تاريخ تاييد"))
        car_vehicle = detect_vehicle("", car)
        product_vehicle = detect_vehicle(mapping.rahkaran_title) if mapping.rahkaran_title else None
        same_dena = {car_vehicle, product_vehicle} <= {"DENA", "DENA+"}
        car_mismatch = bool(
            car_vehicle
            and product_vehicle
            and car_vehicle != product_vehicle
            and not same_dena
        )
        name_score = (
            fuzz.token_set_ratio(normalize(part), normalize(mapping.rahkaran_title))
            if part and mapping.rahkaran_title
            else None
        )
        needs_review = (
            mapping.confidence == "پایین"
            or mapping.method in {"شرح قطعه", "شرح منشا"}
            or mapping.candidates > 3
        )
        rows.append(
            {
                "سریال اخطار": row.get("سريال اخطار"),
                "تاریخ تایید": _clean(row.get("تاريخ تاييد")),
                "سال": year,
                "ماه": month,
                "ماه شمسی": (f"{MONTH_NAMES[month - 1]} {year}" if year and month else "نامشخص"),
                "گروه خودرو": car,
                "گروه ساخت": _clean(row.get("گروه ساخت")),
                "شرح قطعه": part,
                "شرح منشا": origin,
                "شماره فنی": _clean(tech),
                "کد راهکاران": mapping.rahkaran_code,
                "نام محصول راهکاران": mapping.rahkaran_title,
                "محصول (شرح راهکاران)": mapping.product_desc,
                "گروه محصول نهایی": mapping.group,
                "خانواده محصول": mapping.family,
                "محصول": mapping.product,
                "کد گروه محصول": mapping.product_code,
                "در فایل گروه‌بندی": "بله" if mapping.in_catalog else "خیر",
                "در دامنه گروه‌بندی": "بله" if mapping.group != OUT_GROUP else "خیر",
                "روش تطبیق": mapping.method,
                "اطمینان": mapping.confidence,
                "تعداد قطعات معیوب": row.get("تعداد قطعات معيوب"),
                "نمره منفی مرجع": row.get("نمره منفي مرجع"),
                "نمره منفی سازنده": row.get("نمره منفي سازنده"),
                "وضعیت اخطار": _clean(row.get("وضعيت اخطار کيفي")),
                "وضعیت اقدام کوتاه مدت": _clean(row.get("وضعيت اقدام کوتاه مدت")),
                "وضعیت اقدام میان مدت": _clean(row.get("وضعيت اقدام ميان مدت")),
                "گرید ایراد": _clean(row.get("گريد ايراد")),
                "نوع ایراد": _clean(row.get("نوع ايراد")),
                "محل صدور": _clean(row.get("محل صدور")),
                "نام سازنده": _clean(row.get("نام سازنده")),
                "شرح خطا": _clean(row.get("شرح خطا")),
                "توضیحات": _clean(row.get("توضيحات")),
                "تاریخ شروع اقدام میان مدت": _clean(row.get("تاريخ شروع اقدام ميان مدت")),
                "صادر کننده": _clean(row.get("صادر کننده")),
                "تعداد کاندید شماره فنی": mapping.candidates,
                "مغایرت خودرو": "بله" if car_mismatch else "خیر",
                "شباهت نام قطعه و محصول": (round(name_score) if name_score is not None else None),
                "نیاز به بازبینی": "بله" if needs_review else "خیر",
                "یادداشت تطبیق": mapping.note,
            }
        )
    return pd.DataFrame(rows)
