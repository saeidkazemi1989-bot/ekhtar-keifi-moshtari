"""یادگیری الگوی دستی «فرم ثبت محصولات برگشتی» برای یکسان‌سازی متن ایراد.

کاربر ایراد هر محصول برگشتی را با دست و با عبارت یکسان وارد می‌کند. این ماژول
همان فرم را می‌خواند، عبارت‌های تکراری را در یک «الگو» جمع می‌کند و بعد متن
استخراج‌شدهٔ خودکارِ هر اخطار را به نزدیک‌ترین الگوی دستی می‌چسباند.

قرارداد خروجی:
    learn(path, data_dir)  -> payload
    load(data_dir)         -> library ({} اگر فایلی نباشد)
    apply(frame, library)  -> (frame, sources)
    refresh_keys(frame)    -> frame
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from src.defects import (
    _clean_text,
    _cut_subject,
    _drop_verb_echo,
    _find_verb,
    _strip_filler,
    polish_statement,
)
from src.normalize import normalize, squash

LIBRARY_NAME = "الگوی ایراد.json"
REPORT_NAME = "الگوی ایراد.xlsx"
MANUAL_GLOBS = (
    "فرم ثبت محصولات برگشتی*.xls*",
    "*محصولات برگشتی*.xls*",
    "فرم برگشتی*.xls*",
)

# سرستون‌هایی که کاربر برای متن ایراد به کار می‌برد (به ترتیب اولویت)
DEFECT_HEADERS = (
    "شرح ایراد",
    "متن ایراد",
    "شرح عیب",
    "شرح خرابی",
    "دلیل برگشت",
    "علت برگشت",
    "شرح مشکل",
    "ایراد",
    "عیب",
    "خرابی",
)

SERIAL_HEADERS = (
    "سریال اخطار",
    "شماره اخطار",
    "سریال",
    "شماره فرم",
    "شماره",
    "ردیف",
)

# فعل‌هایی که کاربر در فرم دستی به کار می‌برد ولی در الگوی خودکار نیستند
EXTRA_HEADS: tuple[tuple[str, str], ...] = (
    (r"روشن شدن", "روشن شدن"),
    (r"خاموش شدن", "خاموش شدن"),
    (r"قطع شدن", "قطع شدن"),
    (r"قفل نشدن|قفل نمی\u200cشود|قفل نمی شود", "قفل نشدن"),
    (r"مردود شدن", "مردود شدن"),
    (r"نشت(?:ی)?", "نشتی"),
    (r"سختی", "سختی"),
    (r"زیاد بودن|بیشتر بودن", "زیاد بودن"),
    (r"کم بودن|کمتر بودن", "کم بودن"),
    (r"بهم?\u200c?ریختگی|به هم ریختگی", "به هم ریختگی"),
    (r"زنگ\u200c?زدگی", "زنگ زدگی"),
    (r"صدا(?:ی)?", "صدا"),
)

SOURCES = {
    "serial": "الگوی دستی (سریال)",
    "pattern": "الگوی دستی",
    "auto": "استخراج خودکار",
    "manual": "اصلاح دستی",
}


# ---------------------------------------------------------------- خواندن فرم


def _norm_header(value: object) -> str:
    return squash(normalize(value))


def _guess_header(grid: pd.DataFrame) -> tuple[int, int, int | None]:
    """سطر و ستون متن ایراد (و ستون سریال) را در شبکهٔ خام پیدا می‌کند."""
    best_rank: int | None = None
    best_cell: tuple[int, int, int | None] = (0, 0, None)
    rows = min(len(grid), 20)
    for row in range(rows):
        values = [(col, _norm_header(grid.iat[row, col])) for col in range(grid.shape[1])]
        for col, text in values:
            if not text:
                continue
            rank = None
            for order, header in enumerate(DEFECT_HEADERS):
                key = _norm_header(header)
                if text == key:
                    rank = order
                    break
                if key and key in text and len(text) <= len(key) + 12:
                    rank = order + 20
                    break
            if rank is None:
                continue
            serial_col = None
            for header in SERIAL_HEADERS:
                key = _norm_header(header)
                match_col = next((other_col for other_col, other in values if other_col != col and other == key), None)
                if match_col is not None:
                    serial_col = match_col
                    break
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_cell = (row, col, serial_col)
            break
    return best_cell


def _collect_sheet(grid: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    row, col, serial_col = _guess_header(grid)
    texts: list[str] = []
    serials: dict[str, str] = {}
    for index in range(row + 1, len(grid)):
        value = grid.iat[index, col]
        text = " ".join(str(value).split()) if value is not None else ""
        if not text or text.lower() in {"nan", "none", "nat"}:
            continue
        if not re.search(r"[آ-یA-Za-z]", text) or len(text) < 4:
            continue
        texts.append(text)
        if serial_col is not None:
            serial = grid.iat[index, serial_col]
            serial = str(serial).strip() if serial is not None else ""
            if serial.endswith(".0"):
                serial = serial[:-2]
            if serial and serial.lower() not in {"nan", "none"}:
                serials[serial] = text
    return texts, serials


def read_manual(path: str | Path) -> dict:
    """متن‌های دستی و نگاشت سریال→متن را از فایل فرم برمی‌گرداند."""
    path = Path(path)
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    best: dict | None = None
    for sheet, grid in book.items():
        if grid.empty:
            continue
        text_cols, serial_map = _collect_sheet(grid)
        if not text_cols:
            continue
        row, col, _ = _guess_header(grid)
        header = " ".join(str(grid.iat[row, col]).split()) if grid.shape[1] > col else ""
        candidate = {
            "sheet": sheet,
            "column_index": col,
            "column": header,
            "texts": text_cols,
            "serials": serial_map,
        }
        if best is None or len(candidate["texts"]) > len(best["texts"]):
            best = candidate
    if not best:
        raise ValueError(f"در «{path.name}» ستون شرح ایراد پیدا نشد.")
    return best


# ------------------------------------------------------------- ساخت الگوها


@dataclass
class Pattern:
    canonical: str
    head: str
    objects: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    count: int = 0

    @property
    def object(self) -> str:
        return self.objects[0] if self.objects else ""


def _find_extra_head(text: str) -> str:
    for pattern, canonical in EXTRA_HEADS:
        if re.search(rf"(?:^|(?<=\s))(?:{pattern})(?=\s|$|،|\.)", text):
            return canonical
    return ""


def _parts(text: str) -> tuple[str, str, str]:
    """(عبارت پاک، سرِ فعل، موضوع) را از یک متن دستی بیرون می‌کشد."""
    cleaned = polish_statement(_strip_filler(_clean_text(text)))
    if not cleaned:
        return "", "", ""
    head, _, _ = _find_verb(cleaned)
    if not head:
        head = _find_extra_head(cleaned)
    subject = _cut_subject(cleaned)
    if head:
        subject = _cut_subject(_drop_verb_echo(head, subject))
    if not subject:
        subject = cleaned
    return cleaned, head, subject


def build_patterns(texts: list[str]) -> list[Pattern]:
    """متن‌های دستی را به الگوهای یکتا تبدیل می‌کند (هم‌سر و هم‌موضوع یکی می‌شوند)."""
    buckets: dict[tuple[str, str], Counter] = {}
    for text in texts:
        cleaned, head, subject = _parts(text)
        if len(cleaned) < 4 or len(subject) < 2:
            continue
        key = (head, squash(normalize(subject)))
        buckets.setdefault(key, Counter())[cleaned] += 1

    patterns: list[Pattern] = []
    for (head, _), counter in buckets.items():
        variants = [item for item, _ in counter.most_common()]
        canonical = min(variants[:3], key=len) if variants else ""
        subject = _cut_subject(canonical)
        patterns.append(
            Pattern(
                canonical=canonical,
                head=head,
                objects=[subject] if subject else [],
                variants=variants,
                count=sum(counter.values()),
            )
        )
    patterns.sort(key=lambda item: (-item.count, item.canonical))
    return patterns


def consolidate(patterns: list[Pattern], threshold: int = 97) -> list[Pattern]:
    """الگوهای هم‌سر و تقریباً یکسان (غلط املایی/فاصله) را در یک الگو جمع می‌کند."""
    ordered = sorted(patterns, key=lambda item: (-item.count, len(item.canonical)))
    merged: list[Pattern] = []
    for pattern in ordered:
        target = None
        for existing in merged:
            if existing.head != pattern.head:
                continue
            best = 0.0
            for obj in pattern.objects or [""]:
                for other in existing.objects or [""]:
                    best = max(best, fuzz.token_set_ratio(squash(normalize(obj)), squash(normalize(other))))
            if best >= threshold:
                target = existing
                break
        if target is None:
            merged.append(
                Pattern(
                    canonical=pattern.canonical,
                    head=pattern.head,
                    objects=list(pattern.objects),
                    variants=list(pattern.variants),
                    count=pattern.count,
                )
            )
            continue
        target.count += pattern.count
        for obj in pattern.objects:
            if obj not in target.objects:
                target.objects.append(obj)
        for variant in pattern.variants:
            if variant not in target.variants:
                target.variants.append(variant)
    return merged


def _index(patterns: list[Pattern]) -> dict:
    items = []
    heads: dict[str, list[int]] = {}
    for position, pattern in enumerate(patterns):
        object_key = squash(normalize(pattern.object))
        items.append(
            {
                "canonical": pattern.canonical,
                "head": pattern.head,
                "object": pattern.object,
                "key": object_key,
                "variants": list(pattern.variants),
                "count": pattern.count,
                "tokens": {squash(normalize(word)) for word in pattern.object.split() if len(word) > 2},
            }
        )
        for variant in pattern.variants:
            heads.setdefault(squash(normalize(variant)), []).append(position)
    return {"items": items, "heads": heads}


# --------------------------------------------------------------- یادگیری


def learn(path: str | Path, data_dir: str | Path) -> dict:
    """الگو را از فرم دستی یاد می‌گیرد و در پوشهٔ داده ذخیره می‌کند."""
    path = Path(path)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    manual = read_manual(path)
    patterns = consolidate(build_patterns(manual["texts"]))
    if not patterns:
        raise ValueError("هیچ الگوی قابل استفاده‌ای در فرم دستی نبود.")

    payload = {
        "source": path.name,
        "sheet": manual["sheet"],
        "column": manual["column"],
        "texts": len(manual["texts"]),
        "learned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "patterns": [
            {
                "canonical": item.canonical,
                "head": item.head,
                "objects": item.objects,
                "variants": item.variants,
                "count": item.count,
            }
            for item in patterns
        ],
        "serials": manual["serials"],
    }
    (data_dir / LIBRARY_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    _write_report(patterns, data_dir / REPORT_NAME, payload)
    return payload


def _write_report(patterns: list[Pattern], path: Path, payload: dict) -> None:
    frame = pd.DataFrame(
        [
            {
                "عبارت یکتا (دستی)": item.canonical,
                "سر عبارت": item.head,
                "موضوع": item.object,
                "تعداد در فرم": item.count,
                "شکل‌های ثبت‌شده": " | ".join(item.variants),
            }
            for item in patterns
        ]
    )
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="الگوی ایراد", index=False)
        pd.DataFrame(
            [
                {
                    "منبع": payload["source"],
                    "برگه": payload["sheet"],
                    "ستون": payload["column"],
                    "تعداد متن دستی": payload["texts"],
                    "تعداد الگو": len(patterns),
                    "زمان یادگیری": payload["learned_at"],
                }
            ]
        ).to_excel(writer, sheet_name="اطلاعات", index=False)


def load(data_dir: str | Path) -> dict:
    """الگوی ذخیره‌شده را می‌خواند (۰ اگر هنوز یاد گرفته نشده باشد)."""
    path = Path(data_dir) / LIBRARY_NAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    patterns = [
        Pattern(
            canonical=item.get("canonical", ""),
            head=item.get("head", ""),
            objects=list(item.get("objects") or []),
            variants=list(item.get("variants") or []),
            count=int(item.get("count") or 0),
        )
        for item in payload.get("patterns", [])
        if item.get("canonical")
    ]
    payload["_index"] = _index(patterns)
    payload["patterns"] = [
        {
            "canonical": item.canonical,
            "head": item.head,
            "objects": item.objects,
            "variants": item.variants,
            "count": item.count,
        }
        for item in patterns
    ]
    return payload


def find_manual_file(*roots: str | Path) -> Path | None:
    """جدیدترین فایل «فرم ثبت محصولات برگشتی» را در مسیرهای داده‌شده پیدا می‌کند."""
    found: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for glob in MANUAL_GLOBS:
            found.extend(path for path in root.glob(glob) if path.is_file())
    if not found:
        return None
    return max(found, key=lambda path: path.stat().st_mtime)


# -------------------------------------------------------------- تطبیق


def _snap(obj: str, items: list[dict], obj_key: str) -> str:
    """موضوع با چند واژهٔ توصیفی اضافه را به نزدیک‌ترین موضوعِ ثبت‌شده می‌چسباند."""
    tokens = {squash(normalize(word)) for word in obj.split() if len(word) > 2}
    best_canonical, best_score = "", None
    for item in items:
        other = item["tokens"]
        if not tokens or not other:
            continue
        shared = tokens & other
        if not shared:
            continue
        shorter, longer = (other, tokens) if len(other) <= len(tokens) else (tokens, other)
        if not shorter <= longer or len(longer) - len(shorter) > 2:
            continue
        score = (len(shared) / len(longer), fuzz.token_set_ratio(obj_key, item["key"]))
        if best_score is None or score > best_score:
            best_canonical, best_score = item["canonical"], score
    return best_canonical


def match(text: object, library: dict) -> str:
    """عبارت یکتای دستی متناظر با این متن (یا رشتهٔ خالی).

    فقط وقتی چیزی برمی‌گرداند که «سرِ عبارت» یکی باشد یا کل عبارت دستی داخل
    متن آمده باشد؛ در غیر این صورت متن فعلی (استخراج خودکار) دست‌نخورده می‌ماند.
    """
    index = library.get("_index") if library else None
    if not index or not text:
        return ""
    cleaned = polish_statement(_strip_filler(_clean_text(text)))
    if len(cleaned) < 3:
        return ""
    key = squash(normalize(cleaned))

    for position in index["heads"].get(key, []):
        return index["items"][position]["canonical"]

    _, head, subject = _parts(cleaned)
    obj = subject or cleaned
    obj_norm = normalize(obj)
    if not obj_norm:
        return ""

    candidates = [item for item in index["items"] if item["head"] == head] if head else []
    if head and not candidates:
        return ""

    words = {squash(normalize(word)) for word in cleaned.split() if len(word) > 2}
    contained = ""
    for item in candidates or index["items"]:
        tokens = item["tokens"]
        if len(tokens) < 2 or len(item["key"]) < 10:
            continue
        if tokens <= words and len(item["canonical"]) > len(contained):
            contained = item["canonical"]
    if contained:
        return contained

    if not candidates:
        # بدون سرِ شناخته‌شده فقط تطبیق خیلی نزدیک قبول است
        close = ""
        for item in index["items"]:
            if fuzz.token_sort_ratio(cleaned, item["canonical"]) >= 96:
                return item["canonical"]
        return close

    best, best_score = "", 0.0
    for item in candidates:
        score = fuzz.token_sort_ratio(obj_norm, normalize(item["object"]))
        if score > best_score:
            best, best_score = item["canonical"], score
    if best_score >= 92:
        return best

    snapped = _snap(obj, candidates, obj_key=squash(obj_norm))
    if snapped:
        return snapped

    if best_score >= 88:
        return best
    return ""


def apply(
    frame: pd.DataFrame,
    library: dict,
    notes_column: str = "توضیحات",
    error_column: str = "شرح خطا",
) -> tuple[pd.DataFrame, list[str]]:
    """متن ایراد هر سطر را با الگوی دستی یکسان می‌کند.

    ترتیب اولویت: سریال اخطار در فرم دستی → تطبیق الگو → متن فعلی (خودکار).
    """
    result = frame.copy()
    if result.empty:
        return result, []
    if "ایراد مشتری" not in result.columns:
        return result, [SOURCES["auto"]] * len(result)

    serials = {str(k): v for k, v in (library.get("serials") or {}).items()} if library else {}
    statements: list[str] = []
    sources: list[str] = []
    for _, row in result.iterrows():
        current = str(row.get("ایراد مشتری") or "").strip()
        serial = str(row.get("سریال اخطار") or "").strip()
        if serial.endswith(".0"):
            serial = serial[:-2]
        from_serial = serials.get(serial)
        if from_serial:
            statements.append(from_serial)
            sources.append(SOURCES["serial"])
            continue
        learned = match(current, library) if library else ""
        if learned:
            statements.append(learned)
            sources.append(SOURCES["pattern"])
        else:
            statements.append(current)
            sources.append(SOURCES["auto"])

    result["ایراد مشتری"] = statements
    existing = result["منبع ایراد"].astype(str) if "منبع ایراد" in result.columns else pd.Series([""] * len(result))
    result["منبع ایراد"] = [
        source if source != SOURCES["auto"] or not old else old
        for source, old in zip(sources, existing)
    ]
    return result, sources


def refresh_keys(frame: pd.DataFrame) -> pd.DataFrame:
    """کلید ایراد و شمارش تکرارها را بعد از یکسان‌سازی دوباره می‌سازد."""
    if frame.empty or "ایراد مشتری" not in frame.columns:
        return frame
    result = frame.copy()
    result["کلید ایراد"] = result["ایراد مشتری"].map(lambda value: squash(normalize(str(value))))
    if "محصول" in result.columns:
        product_key = result["محصول"].astype(str) + "|" + result["کلید ایراد"]
        result["تکرار ایراد در محصول"] = product_key.map(product_key.value_counts()).astype(int)
    if "شماره فنی" in result.columns:
        tech_key = result["شماره فنی"].astype(str) + "|" + result["کلید ایراد"]
        result["تکرار ایراد در قطعه"] = tech_key.map(tech_key.value_counts()).astype(int)
    if "کلید علت" in result.columns and "محصول" in result.columns:
        cause_key = result["محصول"].astype(str) + "|" + result["کلید علت"].astype(str)
        result["تکرار علت در محصول"] = cause_key.map(cause_key.value_counts()).astype(int)
    result["تکرار ایراد کل"] = result["کلید ایراد"].map(result["کلید ایراد"].value_counts()).astype(int)
    return result


def export_review(frame: pd.DataFrame, path: str | Path) -> Path:
    """خروجی بازبینی: متن هر اخطار در کنار الگوی دستی و منبع آن."""
    path = Path(path)
    columns = [
        column
        for column in ("سریال اخطار", "محصول", "شماره فنی", "ایراد مشتری", "منبع ایراد", "تکرار ایراد در محصول")
        if column in frame.columns
    ]
    frame.loc[:, columns].to_excel(path, sheet_name="بازبینی ایراد", index=False)
    return path
