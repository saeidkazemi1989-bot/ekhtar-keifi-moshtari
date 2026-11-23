"""اصلاح‌های پایدار ریشه، قطعه و واحد مسئول هر اخطار."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import storage

FILE_NAME = "اصلاح ریشه و قطعه.json"
FIELDS = {"root": "ریشهٔ ایراد", "part": "قطعهٔ تحلیل", "process": "منشاء ایراد"}
_LOCK = threading.RLock()


def store_path() -> Path:
    storage.ensure_data_dir()
    return storage.DATA_DIR / FILE_NAME


def load(path: str | Path | None = None) -> dict[str, dict]:
    path = Path(path) if path else store_path()
    with _LOCK:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("entries", payload) if isinstance(payload, dict) else None
        if not isinstance(entries, dict) or any(not isinstance(v, dict) for v in entries.values()):
            raise ValueError("فایل اصلاح‌ها ساختار معتبری ندارد؛ نسخهٔ پشتیبان را بررسی کنید")
        return {str(key): value for key, value in entries.items()}


def save(entries: dict[str, dict], path: str | Path | None = None) -> Path:
    path = Path(path) if path else store_path()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        storage.backup(path)
        payload = {"updated": datetime.now().isoformat(timespec="seconds"), "count": len(entries), "fields": FIELDS, "entries": entries}
        # جایگزینی اتمی مانع خواندن فایل نیمه‌نوشته توسط گزارش می‌شود.
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
                name = f.name
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(name, path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
    return path


def update_many(serials: list[object], values: dict, path: str | Path | None = None) -> dict[str, dict]:
    """اصلاح گروهی اتمی؛ فیلدهای ارسال‌نشده حفظ و مقدار خالی حذف می‌شود."""
    with _LOCK:
        entries = load(path)
        for serial in serials:
            key = str(serial).strip()
            if not key:
                raise ValueError("شماره اخطار لازم است")
            entry = dict(entries.get(key, {}))
            for field in FIELDS:
                if field in values:
                    value = " ".join(str(values[field] or "").split())
                    if value:
                        entry[field] = value
                    else:
                        entry.pop(field, None)
            if any(entry.get(f) for f in FIELDS):
                entry["updated"] = datetime.now().isoformat(timespec="seconds")
                entries[key] = entry
            else:
                entries.pop(key, None)
        save(entries, path)
        return entries


def update(serial: object, values: dict, path: str | Path | None = None) -> dict:
    return update_many([serial], values, path).get(str(serial).strip(), {})


def apply(frame: pd.DataFrame, entries: dict[str, dict] | None = None) -> tuple[pd.DataFrame, int]:
    entries = entries if entries is not None else load()
    result = frame.copy()
    # مقدار اصلی برای بازگرداندن اصلاح و نمایش درست در فرم لازم است.
    for field, column in FIELDS.items():
        if column not in result:
            result[column] = ""
        result[f"مقدار خودکار {field}"] = result[column]
    serials = result["سریال اخطار"].astype(str) if "سریال اخطار" in result else pd.Series("", index=result.index)
    for field, column in FIELDS.items():
        result[column] = [entries.get(serial, {}).get(field) or current for serial, current in zip(serials, result[column])]
    result["اصلاح دستی"] = ["بله" if any(entries.get(serial, {}).get(f) for f in FIELDS) else "خیر" for serial in serials]
    result["ریشهٔ دستی ثبت شده"] = ["بله" if entries.get(serial, {}).get("root") else "خیر" for serial in serials]
    return result, int((result["اصلاح دستی"] == "بله").sum())


def root_values(entries: dict[str, dict] | None = None) -> list[str]:
    entries = entries if entries is not None else load()
    return sorted({entry["root"] for entry in entries.values() if entry.get("root")})
