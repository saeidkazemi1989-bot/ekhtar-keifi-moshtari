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


# خانواده‌هایی که در فایل گروه‌بندی با دو نام نوشته شده‌اند و یک خط محصول‌اند
FAMILY_ALIASES = {
    "ESC": "مدولاتور",
}


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = " ".join(str(value).split())
    return "" if text.lower() in {"nan", "none"} else text


# خانواده‌های خارج از دامنه‌ای که به برنچ پلیمر (POL) تعلق دارند
POL_FAMILIES = {
    "خارج از دامنه - داشبورد",
    "خارج از دامنه - بدنه/درب/سپر",
    "خارج از دامنه - صندلی/تزئینات",
}

BRANCH_UNKNOWN = "نامشخص"
BRANCH_POL = "POL"


def canonical_family(family: str) -> str:
    name = " ".join(str(family).split())
    return FAMILY_ALIASES.get(name, name)


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
        family = canonical_family(_clean(row["خانواده محصول"]))
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


def add_branch(frame, catalog: "Catalog"):
    """ستون‌های «برنچ» و «منبع برنچ» را به دادهٔ اخطارها اضافه می‌کند.

    اولویت: کد محصول راهکاران ← نام محصول ← استنباط POL از خانواده.
    """
    by_code: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for item in catalog.products:
        if item.branch:
            by_code.setdefault(item.code_raw, item.branch)
            by_title.setdefault(normalize(item.product), item.branch)

    branches: list[str] = []
    sources: list[str] = []
    for _, row in frame.iterrows():
        code = str(row.get("کد گروه محصول") or "").strip()
        if code.endswith(".0"):
            code = code[:-2]
        title = normalize(str(row.get("نام محصول راهکاران") or ""))
        family = str(row.get("خانواده محصول") or "").strip()
        branch = by_code.get(code) or (by_title.get(title) if title else None)
        if branch:
            branches.append(branch)
            sources.append("فایل گروه‌بندی")
            continue
        if family in POL_FAMILIES:
            branches.append(BRANCH_POL)
            sources.append("استنباط از خانواده")
            continue
        branches.append(BRANCH_UNKNOWN)
        sources.append("نامشخص")

    result = frame.copy()
    result["برنچ"] = branches
    result["منبع برنچ"] = sources
    return result
