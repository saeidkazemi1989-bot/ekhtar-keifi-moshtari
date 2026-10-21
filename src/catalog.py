"""بارگذاری و مدل‌سازی فایل «گروه بندی محصولات»."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .normalize import normalize


@dataclass(frozen=True)
class CatalogProduct:
    code: str
    code_raw: str
    product: str
    family: str
    combo: str
    group: str
    branch: str
    station: str
    owner: str

    @property
    def key(self) -> str:
        return f"{self.family}|{self.product}"


@dataclass
class Catalog:
    products: list[CatalogProduct]
    by_code: dict[str, CatalogProduct]
    by_product: dict[str, list[CatalogProduct]]
    by_family: dict[str, list[CatalogProduct]]
    families: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)

    @property
    def family_to_group(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in self.products:
            result.setdefault(item.family, item.group)
        return result

    def family_products(self, family: str) -> list[str]:
        seen: list[str] = []
        for item in self.by_family.get(family, []):
            if item.product not in seen:
                seen.append(item.product)
        return seen

    def lookup_name(self, value: str) -> CatalogProduct | None:
        target = normalize(value)
        if not target:
            return None
        for item in self.products:
            if normalize(item.product) == target or normalize(item.combo) == target:
                return item
        for item in self.products:
            if normalize(item.code_raw) == target:
                return item
        return None


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def load_catalog(path: str | Path) -> Catalog:
    frame = pd.read_excel(path)
    required = {
        "کد گروه محصول",
        "کد محصول",
        "نام محصول",
        "خانواده محصول",
        "نام محصول ترکیبی",
        "گروه محصول نهایی",
        "ایستگاه",
        "برنچ",
        "نفر گروه محصول",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"ستون‌های ضروری فایل گروه‌بندی موجود نیست: {sorted(missing)}")

    products: list[CatalogProduct] = []
    seen_codes: set[str] = set()
    for _, row in frame.iterrows():
        code_raw = _clean(row["کد گروه محصول"])
        if not code_raw:
            continue
        code = normalize(code_raw).replace(" ", "")
        if code in seen_codes:
            continue
        seen_codes.add(code)
        product = _clean(row["نام محصول"])
        family = _clean(row["خانواده محصول"])
        group = _clean(row["گروه محصول نهایی"])
        if not product or product == "-" or not family or family == "-" or not group or group == "-":
            continue
        products.append(
            CatalogProduct(
                code=code,
                code_raw=code_raw,
                product=product,
                family=family,
                combo=_clean(row["نام محصول ترکیبی"]),
                group=group,
                branch=_clean(row["برنچ"]),
                station=_clean(row["ایستگاه"]),
                owner=_clean(row["نفر گروه محصول"]),
            )
        )

    by_code = {item.code: item for item in products}
    by_product: dict[str, list[CatalogProduct]] = {}
    by_family: dict[str, list[CatalogProduct]] = {}
    for item in products:
        by_product.setdefault(item.product, []).append(item)
        by_family.setdefault(item.family, []).append(item)

    families = sorted(by_family)
    groups = sorted({item.group for item in products})
    return Catalog(
        products=products,
        by_code=by_code,
        by_product=by_product,
        by_family=by_family,
        families=families,
        groups=groups,
    )
