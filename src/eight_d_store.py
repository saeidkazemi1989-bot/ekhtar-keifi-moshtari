"""ذخیره‌سازی فرم‌های 8D که کاربر در داشبورد تکمیل می‌کند.

داده‌ها در یک فایل JSON کنار خروجی‌ها نگه داشته می‌شوند
(`output/8d-forms.json`) تا بین اجراهای مختلف و بین اکسل/ورد/داشبورد
مشترک باشند.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

# ترتیب نمایش در فرم
FIELDS: dict[str, str] = {
    "owner": "مسئول پیگیری",
    "due": "تاریخ تکمیل",
    "team": "D1 — اعضای تیم",
    "problem": "D2 — تعریف مسئله",
    "containment": "D3 — اقدام محدودکنندهٔ موقت",
    "root_cause": "D4 — تحلیل علت ریشه‌ای",
    "corrective": "D5 — اقدام اصلاحی دائم",
    "verification": "D6 — اجرا و صحه‌گذاری",
    "prevention": "D7 — پیشگیری از تکرار",
    "lesson": "D8 — بستن پرونده و درس آموخته",
}

# بخش‌هایی که درصد تکمیل را می‌سازند (D1 تا D8)
CORE_FIELDS = ("team", "containment", "root_cause", "corrective", "verification", "prevention", "lesson")

STATUS_OPTIONS = ("شروع نشده", "در جریان", "آماده تأیید", "بسته شده")
STATUS_CLOSED = "بسته شده"


def store_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "8d-forms.json"


def load(path: str | Path) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = data.get("entries", data) if isinstance(data, dict) else {}
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)}


def save_all(entries: dict[str, dict], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "count": len(entries),
        "entries": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def update(serial: object, values: dict, path: str | Path) -> dict:
    entries = load(path)
    key = str(serial)
    entry = dict(entries.get(key, {}))
    for field, value in values.items():
        if field in FIELDS or field in {"status", "number", "updated"}:
            entry[field] = "" if value is None else str(value).strip()
    entry["updated"] = datetime.now().isoformat(timespec="seconds")
    entries[key] = entry
    save_all(entries, path)
    return entry


def percent(entry: dict | None) -> int:
    if not entry:
        return 0
    filled = sum(1 for field in CORE_FIELDS if str(entry.get(field, "")).strip())
    return round(filled / len(CORE_FIELDS) * 100)


def status_of(entry: dict | None) -> str:
    if not entry:
        return STATUS_OPTIONS[0]
    saved = str(entry.get("status", "")).strip()
    if saved == STATUS_CLOSED:
        return STATUS_CLOSED
    value = percent(entry)
    if value >= 100:
        return STATUS_OPTIONS[2]
    if value > 0:
        return STATUS_OPTIONS[1]
    return STATUS_OPTIONS[0]


def merge_into(frame: pd.DataFrame, entries: dict[str, dict]) -> pd.DataFrame:
    """ستون‌های فرم 8D را به ردیف‌های فرم اضافه می‌کند."""
    if frame.empty:
        return frame
    result = frame.copy()
    keys = result["سریال اخطار"].astype(str)

    result["مسئول پیگیری"] = [entries.get(k, {}).get("owner", "") for k in keys]
    result["تاریخ تکمیل"] = [entries.get(k, {}).get("due", "") for k in keys]
    result["وضعیت فرم"] = [status_of(entries.get(k)) for k in keys]
    result["درصد تکمیل"] = [percent(entries.get(k)) for k in keys]
    result["D4 — علت ریشه‌ای"] = [
        entries.get(k, {}).get("root_cause", "") or row.get("علت استاندارد", "")
        for k, (_, row) in zip(keys, result.iterrows())
    ]
    result["D5 — اقدام اصلاحی دائم"] = [entries.get(k, {}).get("corrective", "") for k in keys]
    result["D3 — اقدام محدودکنندهٔ موقت"] = [entries.get(k, {}).get("containment", "") for k in keys]
    result["آخرین به‌روزرسانی"] = [
        entries.get(k, {}).get("updated", "").replace("T", " ")[:16] for k in keys
    ]
    return result


def stats(entries: dict[str, dict], serials: list[str] | None = None) -> dict:
    keys = [str(s) for s in serials] if serials else list(entries.keys())
    total = len(keys)
    done = sum(1 for k in keys if percent(entries.get(k)) >= 100)
    doing = sum(1 for k in keys if 0 < percent(entries.get(k)) < 100)
    closed = sum(1 for k in keys if status_of(entries.get(k)) == STATUS_CLOSED)
    return {
        "total": total,
        "done": done,
        "doing": doing,
        "closed": closed,
        "empty": total - done - doing,
        "percent": round(done / total * 100) if total else 0,
    }
