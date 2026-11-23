"""تولید داشبورد HTML تک‌فایلی، بدون وابستگی خارجی."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from .eight_d_store import FIELDS as FORM_FIELDS
from .eight_d_store import STATUS_OPTIONS, percent as form_percent, status_of as form_status
from .aggregate import (
    family_summary,
    group_summary,
    kpis,
    month_summary,
    out_of_scope_summary,
    product_summary,
    vehicle_summary,
    year_summary,
)
from .status import AUTO_COLUMN, DATE_KEY, PRIORITY_COLUMN, PRIORITY_RANK, RAW_COLUMN
from .taxonomy import OUT_GROUP


# نگاشت «منشاء ایراد» برگهٔ بررسی (C-Plus) به فرآیند مسئول.
# ترتیب مهم است: عبارت‌های تک‌واژه‌ای و مرکب هر دو پوشش داده می‌شوند.
PROCESS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("تامین‌کننده", ("تامین", "تأمین")),
    ("مواد اولیه", ("مواد",)),
    ("طراحی مهندسی", ("طراحی", "مهندسی", "قالب")),
    ("مشتری", ("مشتری",)),
    ("تولید", ("اپراتور", "تجهیزات", "روش", "تولید", "نیروی انسانی", "محیط", "ماشین")),
)
PROCESS_UNKNOWN = "نامشخص"


def _review_link_stats(enriched: pd.DataFrame, unmatched: pd.DataFrame | None) -> dict:
    """وضعیت اتصال فایل C-Plus به فایل اخطارهای کیفی (برای نمایش شفاف در داشبورد)."""
    rows = 0 if unmatched is None else len(unmatched)
    return {
        "rows": rows,                      # ردیف‌های C-Plus بدون اخطار متناظر
        "matched": int((enriched["دارای برگه بررسی"] == "بله").sum()) if "دارای برگه بررسی" in enriched else 0,
        "warnings": int(len(enriched)),
    }


STATUS_CLOSED = "خاتمه‌یافته"
STATUS_IN_REVIEW = "در حال بررسی"
STATUS_NOT_RECEIVED = "عدم دریافت قطعه"


def add_status_group(enriched: pd.DataFrame) -> pd.DataFrame:
    """گروه وضعیت یکتا برای هر اخطار؛ سه گروه، افراز کامل.

    * «عدم دریافت قطعه»: «آنالیز علت ایراد» برگهٔ بررسی این عبارت را دارد.
    * «در حال بررسی»: برگهٔ بررسی دارد ولی «منشاء ایراد» (ریشهٔ فرآیندی) ثبت نشده،
      یا اخطارِ بازی است که هنوز برگهٔ بررسی ندارد.
    * «خاتمه‌یافته»: بقیه.

    جمع این سه همیشه برابر تعداد اخطارهاست و در داشبورد و اکسل همین ستون مبناست.
    """
    frame = enriched.copy()
    cause = frame.get("آنالیز علت ایراد", pd.Series([""] * len(frame), index=frame.index))
    cause = cause.fillna("").astype(str).str.replace("ي", "ی", regex=False)
    not_received = cause.str.contains("عدم دریافت قطعه", regex=False)
    has_review = (frame["دارای برگه بررسی"] == "بله") if "دارای برگه بررسی" in frame else pd.Series(False, index=frame.index)
    origin = frame.get("منشاء ایراد", pd.Series([""] * len(frame), index=frame.index)).fillna("").astype(str)
    has_root = origin.map(lambda v: _process_bucket(v) != PROCESS_UNKNOWN)
    is_open = frame["وضعیت اخطار"] != "خاتمه يافته"
    in_review = ~not_received & ((has_review & ~has_root) | is_open)
    closed = ~not_received & ~in_review
    frame["گروه وضعیت"] = [
        STATUS_NOT_RECEIVED if a else (STATUS_IN_REVIEW if b else STATUS_CLOSED)
        for a, b in zip(not_received, in_review)
    ]
    frame["ریشهٔ فرآیندی ثبت شده"] = has_root.map(lambda v: "بله" if v else "خیر")
    frame["_closed"] = closed
    frame["_in_review"] = in_review
    frame["_not_received"] = not_received
    return frame


def _process_bucket(value: object) -> str:
    """فرآیند مسئول از ستون «منشاء ایراد»؛ چیزی حدس زده نمی‌شود."""
    text = _clean_text(value).replace("ي", "ی").replace("ك", "ک")
    if not text or text in {"nan", "None", "تحت بررسی", "ابطال"}:
        return PROCESS_UNKNOWN
    for name, keys in PROCESS_RULES:
        if any(key in text for key in keys):
            return name
    return PROCESS_UNKNOWN


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("_x000D_", " ")
        .replace("\\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _jalali_now() -> str:
    try:
        import jdatetime

        now = jdatetime.datetime.now()
        stamp = f"{now.year:04d}/{now.month:02d}/{now.day:02d} - {now.hour:02d}:{now.minute:02d}"
    except Exception:  # pragma: no cover - فقط اگر jdatetime نصب نباشد
        stamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    return stamp.translate(FA_DIGITS)


def _payload(
    enriched: pd.DataFrame,
    source_names: dict[str, str],
    checks: pd.DataFrame | None = None,
    unmatched: pd.DataFrame | None = None,
    entries: dict[str, dict] | None = None,
    status_stats: dict | None = None,
) -> dict:
    entries = entries or {}
    status_stats = status_stats or {}
    records: list[dict] = []
    for _, row in enriched.iterrows():
        year = row.get("سال")
        month = row.get("ماه")
        month_key = int(year) * 100 + int(month) if pd.notna(year) and pd.notna(month) else 0
        qty = int(row["تعداد قطعات معیوب"]) if pd.notna(row["تعداد قطعات معیوب"]) else 0
        score = int(row["نمره منفی مرجع"]) if pd.notna(row["نمره منفی مرجع"]) else 0
        score_maker = int(row["نمره منفی سازنده"]) if pd.notna(row["نمره منفی سازنده"]) else 0
        candidates = int(row["تعداد کاندید شماره فنی"]) if pd.notna(row["تعداد کاندید شماره فنی"]) else 0
        records.append(
            {
                "id": int(row["سریال اخطار"]),
                "date": _clean_text(row["تاریخ تایید"]),
                "month": _clean_text(row["ماه شمسی"]),
                "monthKey": month_key,
                "dateKey": int(row[DATE_KEY]) if pd.notna(row.get(DATE_KEY)) else 0,
                "year": int(year) if pd.notna(year) else 0,
                "car": _clean_text(row["گروه خودرو"]),
                "make": _clean_text(row["گروه ساخت"]),
                "part": _clean_text(row["شرح قطعه"]),
                "origin": _clean_text(row["شرح منشا"]),
                "tech": _clean_text(row["شماره فنی"]),
                "code": _clean_text(row["کد راهکاران"]),
                "rahkaran": _clean_text(row["نام محصول راهکاران"]),
                "group": _clean_text(row["گروه محصول نهایی"]),
                "family": _clean_text(row["خانواده محصول"]),
                "product": _clean_text(row["محصول"]),
                "catalogCode": _clean_text(row["کد گروه محصول"]),
                "inCatalog": row["در فایل گروه‌بندی"] == "بله",
                "inScope": row["در دامنه گروه‌بندی"] == "بله",
                "method": _clean_text(row["روش تطبیق"]),
                "confidence": _clean_text(row["اطمینان"]),
                "qty": qty,
                "score": score,
                "scoreMaker": score_maker,
                "grade": _clean_text(row["گرید ایراد"]),
                "status": _clean_text(row["وضعیت اخطار"]),
                "rawStatus": _clean_text(row.get(RAW_COLUMN, "")),
                "autoClosed": row.get(AUTO_COLUMN) == "بله",
                "priority": int(row[PRIORITY_RANK]) if pd.notna(row.get(PRIORITY_RANK)) else 5,
                "priorityLabel": _clean_text(row.get(PRIORITY_COLUMN, "")),
                "open": row["وضعیت اخطار"] != "خاتمه يافته",
                "stAction": _clean_text(row["وضعیت اقدام کوتاه مدت"]),
                "mtAction": _clean_text(row["وضعیت اقدام میان مدت"]),
                "cause": _clean_text(row.get("آنالیز علت ایراد", "")),
                "action": _clean_text(row.get("شرح اقدام اصلاحی", "")),
                "reviewOrigin": _clean_text(row.get("منشاء ایراد", "")),
                "process": _process_bucket(row.get("منشاء ایراد", "")),
                "statusGroup": _clean_text(row.get("گروه وضعیت", "")),
                "hasRoot": row.get("ریشهٔ فرآیندی ثبت شده", "خیر") == "بله",
                "claimNo": _clean_text(row.get("شماره کلیم", "")),
                "orangeCard": _clean_text(row.get("شماره کارت نارنجی", "")),
                "reviewCategory": _clean_text(row.get("دسته محصول (بررسی)", "")),
                "reviewDealGroup": _clean_text(row.get("گروه بازرگانی (بررسی)", "")),
                "supplier": _clean_text(row.get("تامین‌کننده (بررسی)", "")),
                "reviewPeriod": _clean_text(row.get("دوره (بررسی)", "")),
                "reviewNotes": _clean_text(row.get("توضیحات (بررسی)", "")),
                "claims": int(row.get("تعداد کلیم") or 0) if pd.notna(row.get("تعداد کلیم")) else 0,
                "claimsAccepted": int(row.get("تعداد کلیم پذیرفته‌شده") or 0) if pd.notna(row.get("تعداد کلیم پذیرفته‌شده")) else 0,
                "hasReview": row.get("دارای برگه بررسی") == "بله",
                "form8d": (
                    f"8D-{int(year) if pd.notna(year) else 'XXXX'}-{int(row['سریال اخطار'])}"
                ),
                "inDocx": bool(
                    row["دارای برگه بررسی"] == "بله" or row["وضعیت اخطار"] != "خاتمه يافته"
                ),
                "type": _clean_text(row["نوع ایراد"]),
                "location": _clean_text(row["محل صدور"]),
                "maker": _clean_text(row["نام سازنده"]),
                "error": _clean_text(row["شرح خطا"]),
                "notes": _clean_text(row["توضیحات"]),
                "review": row["نیاز به بازبینی"] == "بله",
                "mismatch": row["مغایرت خودرو"] == "بله",
                "candidates": candidates,
                "branch": _clean_text(row.get("برنچ", "")),
                "branchSource": _clean_text(row.get("منبع برنچ", "")),
                "defect": _clean_text(row.get("ایراد مشتری", "")),
                "defectSrc": _clean_text(row.get("منبع ایراد", "")),
                "rootCause": _clean_text(row.get("ریشهٔ ایراد", "")),
                "analysisPart": _clean_text(row.get("قطعهٔ تحلیل", "")),
                "groupPath": _clean_text(row.get("قطعه (گروه‌بندی)", "")),
                "defectCat": _clean_text(row.get("دسته‌بندی ایراد", "")),
                "defectGroup": _clean_text(row.get("گروه ایراد", "")),
                "defectRepeat": int(row.get("تکرار ایراد در محصول", 0) or 0),
                "defectRepeatTech": int(row.get("تکرار ایراد در قطعه", 0) or 0),
                "causeStd": _clean_text(row.get("علت استاندارد", "")),
                "causeGroup": _clean_text(row.get("گروه علت", "")),
                "m6": _clean_text(row.get("گروه ۶M", "")),
                "causeRepeat": int(row.get("تکرار علت در محصول", 0) or 0),
                "form": entries.get(str(row["سریال اخطار"]), {}),
                "formStatus": form_status(entries.get(str(row["سریال اخطار"]))),
                "formPercent": form_percent(entries.get(str(row["سریال اخطار"]))),
            }
        )

    # ترتیب پیش‌فرض: اولویت (باز سال جاری، باز یک‌سال، بدون تاریخ، خودکار، خاتمه)
    # و در هر اولویت، جدیدترین تاریخ اول.
    records.sort(key=lambda item: (item["priority"], -item["dateKey"], -item["id"]))

    groups = group_summary(enriched)
    families = family_summary(enriched)
    products = product_summary(enriched)
    months = month_summary(enriched)
    years = year_summary(enriched)
    vehicles = vehicle_summary(enriched)
    out_categories = out_of_scope_summary(enriched)

    values = kpis(enriched)
    values["reviewed"] = int((enriched["دارای برگه بررسی"] == "بله").sum()) if "دارای برگه بررسی" in enriched.columns else 0
    values["reviewed_pct"] = values["reviewed"] / len(enriched) if len(enriched) else 0
    values["staged"] = int((enriched["وضعیت اخطار"] == "اقدام كوتاه مدت").sum())
    values["medium"] = int((enriched["وضعیت اخطار"] == "اقدام ميان مدت").sum())
    values["closed"] = int((enriched["وضعیت اخطار"] == "خاتمه يافته").sum())
    values["claims"] = int(pd.to_numeric(enriched.get("تعداد کلیم"), errors="coerce").fillna(0).sum()) if "تعداد کلیم" in enriched.columns else 0
    return {
        "meta": {
            "title": "داشبورد دسته‌بندی اخطارهای کیفی",
            "subtitle": "بر اساس محصول، خانواده و گروه محصول — کاتالوگ راهکاران و فایل گروه‌بندی محصولات",
            "sources": source_names,
            "generated": _jalali_now(),
            "review": _review_link_stats(enriched, unmatched),
        },
        "kpis": values,
        "groups": groups.to_dict(orient="records"),
        "families": families.to_dict(orient="records"),
        "products": products.to_dict(orient="records"),
        "months": months.to_dict(orient="records"),
        "years": years.to_dict(orient="records") if not years.empty else [],
        "vehicles": vehicles.to_dict(orient="records"),
        "outCategories": out_categories.to_dict(orient="records") if not out_categories.empty else [],
        "warnings": records,
        "groupingChecks": checks.to_dict(orient="records") if checks is not None and not checks.empty else [],
        "unmatchedReview": (
            unmatched.to_dict(orient="records")
            if unmatched is not None and not unmatched.empty
            else []
        ),
        "formFields": FORM_FIELDS,
        "formStatuses": list(STATUS_OPTIONS),
        "statusRule": {
            "today": status_stats.get("today", ""),
            "cutoff": status_stats.get("cutoff_label", ""),
            "currentYear": status_stats.get("current_year", 0),
            "counts": status_stats.get("counts", {}),
            "autoClosed": status_stats.get("auto_serials", []),
        },
        "eightD": entries,
        "eightDStats": {
            "total": int(
                (
                    (enriched["دارای برگه بررسی"] == "بله")
                    | (enriched["وضعیت اخطار"] != "خاتمه يافته")
                ).sum()
            ) if "دارای برگه بررسی" in enriched.columns else 0,
            "saved": len(entries),
            "done": sum(1 for e in entries.values() if form_percent(e) >= 100),
            "doing": sum(1 for e in entries.values() if 0 < form_percent(e) < 100),
        },
    }


def build_html(
    enriched: pd.DataFrame,
    output_path: str | Path,
    source_names: dict[str, str] | None = None,
    data_file: str | Path | None = None,
    checks: pd.DataFrame | None = None,
    unmatched: pd.DataFrame | None = None,
    entries: dict[str, dict] | None = None,
    status_stats: dict | None = None,
) -> Path:
    """ساخت داشبورد.

    اگر ``data_file`` داده شود، داده در یک فایل جاوااسکریپت جداگانه ذخیره می‌شود
    (برای بارگذاری سریع‌تر در وب‌سرور/پیش‌نمایش)؛ در غیر این صورت همه‌چیز در یک
    فایل HTML مستقل جاسازی می‌شود.
    """
    source_names = source_names or {}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if "گروه وضعیت" not in enriched.columns:
        enriched = add_status_group(enriched)
    data = _payload(enriched, source_names, checks, unmatched, entries, status_stats)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    if data_file is None:
        script = f"<script>window.DASHBOARD_DATA = {payload};</script>"
    else:
        data_path = Path(data_file)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(
            "/* دادهٔ داشبورد اخطارهای کیفی - تولید خودکار */\n"
            f"window.DASHBOARD_DATA = {payload};\n",
            encoding="utf-8",
        )
        script = f'<script src="{data_path.name}?v={int(time.time())}"></script>'

    html = TEMPLATE.replace("__DATA_SCRIPT__", script)
    output_path.write_text(html, encoding="utf-8")
    return output_path


TEMPLATE = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>داشبورد دسته‌بندی اخطارهای کیفی</title>
<style>
:root{
  --bg:#eef4fb; --card:#ffffff; --ink:#0b1b2b; --muted:#64748b; --line:#dbe7f3;
  --accent:#0b64c8; --accent2:#0e9fd8; --accent-soft:#e8f3ff;
  --teal:#0e7f9a; --teal2:#12b3d6; --blue:#0b64c8; --violet:#1e4fd8; --amber:#c47f0a;
  --rose:#d92d5c; --cyan:#0891b2; --lime:#4d7c0f; --slate:#5b7288;
  --shadow:0 1px 2px rgba(12,42,72,.05),0 12px 26px -24px rgba(12,42,72,.55);
  --shadow-sm:0 1px 2px rgba(12,42,72,.06);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"Vazirmatn","IRANSansX","IRANSans","Segoe UI",Tahoma,Arial,sans-serif;
  background:
    radial-gradient(1200px 560px at 100% -14%, #e8f1ff 0%, rgba(232,241,255,0) 62%),
    radial-gradient(900px 480px at -6% -12%, #eef1ff 0%, rgba(238,241,255,0) 58%),
    var(--bg);
  background-attachment:fixed;
  color:var(--ink); line-height:1.7; font-size:14px;
  -webkit-font-smoothing:antialiased;
}
a{color:inherit}
.topbar{
  position:relative;
  background:
    radial-gradient(760px 280px at 92% -70%, rgba(91,124,250,.5) 0%, rgba(91,124,250,0) 66%),
    radial-gradient(620px 250px at 4% 150%, rgba(15,159,143,.32) 0%, rgba(15,159,143,0) 62%),
    linear-gradient(118deg,#0a1120 0%,#101d3a 52%,#0c2b34 100%);
  color:#fff; padding:15px 24px; display:flex; gap:20px; align-items:center; justify-content:space-between;
  flex-wrap:wrap; border-bottom:1px solid rgba(255,255,255,.07);
}
.topbar:before{content:"";position:absolute;inset-inline:0;top:0;height:3px;background:linear-gradient(90deg,#0b64c8 0%,#1487e0 28%,#0f9f8f 62%,#7c3aed 100%)}
.topbar .dot-live{width:8px;height:8px;border-radius:50%;background:#34d399;box-shadow:0 0 0 3px rgba(52,211,153,.18);display:inline-block}
.topbar .dot-live.off{background:#8b9bb4;box-shadow:0 0 0 3px rgba(139,155,180,.18)}
.brand{display:flex; gap:14px; align-items:center}
.logo{
  width:42px;height:42px;border-radius:12px;
  background:linear-gradient(150deg,rgba(91,124,250,.9) 0%,rgba(59,91,219,.85) 45%,rgba(15,159,143,.85) 100%);
  display:grid;place-items:center;font-size:18px;font-weight:800;color:#fff;
  border:1px solid rgba(255,255,255,.22);
  box-shadow:0 18px 30px -18px rgba(59,91,219,1), inset 0 1px 0 rgba(255,255,255,.35);
}
.brand h1{font-size:18px;margin:0 0 2px;font-weight:800;letter-spacing:-.3px;color:#fff}
.brand p{margin:0;color:#9fb5d6;font-size:11.5px}
.meta{font-size:11.5px;color:#a9bcdb;text-align:left;line-height:1.8}
.meta b{color:#fff;font-weight:700}
.tabs{
  position:sticky; top:0; z-index:30; background:rgba(255,255,255,.86); backdrop-filter:saturate(140%) blur(14px);
  border-bottom:1px solid var(--line); display:flex; gap:4px; padding:7px 18px; overflow-x:auto;
  box-shadow:0 4px 14px -14px rgba(16,24,40,.5);
}
.tab{
  border:0;background:transparent;padding:7px 13px;border-radius:8px;font-family:inherit;font-size:12.6px;
  color:var(--muted);cursor:pointer;white-space:nowrap;font-weight:700;transition:background .15s,color .15s,box-shadow .15s;
}
.tab:hover{background:#eaf1f9;color:var(--ink)}
.tab.active{
  background:linear-gradient(135deg,#0b64c8,#1487e0);color:#fff;
  box-shadow:0 8px 18px -14px rgba(11,100,200,.95), inset 0 1px 0 rgba(255,255,255,.22);
}
.filters{
  padding:10px 18px; background:#f8fbff; border-bottom:1px solid var(--line);
  display:grid; grid-template-columns:repeat(7,minmax(110px,1fr)); gap:8px; align-items:end;
}
.field label{display:block;font-size:10.4px;color:var(--muted);margin-bottom:3px;font-weight:700;letter-spacing:.1px}
.field select,.field input{
  width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:#fff;
  font-family:inherit;font-size:12px;color:var(--ink);outline:none;transition:border-color .15s,box-shadow .15s,background .15s;
}
.field select:focus,.field input:focus{border-color:#7fb6ea;background:#fff;box-shadow:0 0 0 3px rgba(11,100,200,.1)}
.filter-actions{display:flex;gap:6px}
.btn{
  border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 11px;font-family:inherit;
  font-size:12px;cursor:pointer;color:var(--ink);font-weight:700;white-space:nowrap;
  box-shadow:var(--shadow-sm);transition:transform .12s,box-shadow .15s,background .15s;
}
.btn:hover{background:#f5f9ff;transform:translateY(-1px);box-shadow:0 6px 14px -12px rgba(16,24,40,.55)}
.btn.primary{background:linear-gradient(135deg,#0b64c8,#1487e0);border-color:#0b64c8;color:#fff}
.btn.primary:hover{background:linear-gradient(135deg,#0a55ac,#0f7ac9)}
.btn.ghost{background:transparent}
main{padding:14px 18px 34px;max-width:1760px;margin:0 auto}
.tab-panel{display:none}
.tab-panel.active{display:block;animation:fade .18s ease}
@keyframes fade{from{opacity:.4;transform:translateY(3px)}to{opacity:1;transform:none}}
.kpi-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:12px}
/* یک کارت واحد برای گزارش کلی؛ پنج کاشی هم‌اندازه، بدون فضای خالی */
.ov-kpis{background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow-sm);margin-bottom:12px;overflow:hidden}
.ov-kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0}
.ov-kpi-grid .kpi{
  border:0;border-radius:0;box-shadow:none;background:transparent;
  border-inline-start:1px solid var(--line);padding:14px 16px 13px;min-height:104px;
  display:flex;flex-direction:column;justify-content:flex-start;
}
.ov-kpi-grid .kpi:first-child{border-inline-start:0}
.ov-kpi-grid .kpi:before{height:3px;inset-inline:0;border-radius:0}
.ov-kpi-grid .kpi:hover{transform:none;background:#f7faff}
.ov-kpi-grid .kpi .label{display:flex;align-items:center;gap:6px}
.ov-kpi-grid .kpi .cdot{width:7px;height:7px;border-radius:50%;flex:none;display:inline-block}
.ov-kpi-grid .kpi .sub{min-height:30px;line-height:1.6}
.ov-kpi-grid .kpi .vs{min-height:18px}
.ov-note{border-top:1px solid var(--line);padding:8px 16px;font-size:10.8px;color:var(--muted);background:#fbfcff;line-height:1.9}
.ov-note b{color:#4b5b70}
@media(max-width:1100px){.ov-kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
  .ov-kpi-grid .kpi:nth-child(3n+1){border-inline-start:0}
  .ov-kpi-grid .kpi:nth-child(n+4){border-top:1px solid var(--line)}}
@media(max-width:680px){.ov-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .ov-kpi-grid .kpi{border-top:1px solid var(--line);border-inline-start:1px solid var(--line)}
  .ov-kpi-grid .kpi:nth-child(odd){border-inline-start:0}
  .ov-kpi-grid .kpi:nth-child(-n+2){border-top:0}}
.kpi{
  background:#fff;border:1px solid var(--line);border-radius:10px;
  padding:12px 14px 11px;box-shadow:var(--shadow-sm);position:relative;overflow:hidden;transition:transform .15s,box-shadow .2s;
}
.kpi:hover{transform:translateY(-2px);box-shadow:0 1px 2px rgba(16,24,40,.04),0 18px 34px -22px rgba(16,24,40,.45)}
.kpi[data-kpi]{cursor:pointer}
.kpi[data-kpi]:after{content:"›";position:absolute;inset-inline-end:12px;top:10px;color:#c9d4e8;font-size:16px;font-weight:700;opacity:0;transition:opacity .15s}
.kpi[data-kpi]:hover:after{opacity:1}
.kpi[data-kpi]:focus-visible{outline:2px solid #7c93ff;outline-offset:2px}
.kpi:before{content:"";position:absolute;inset-inline:0;top:0;height:3px;background:linear-gradient(90deg,#0b64c8,#1487e0)}
.kpi.blue:before{background:linear-gradient(90deg,#38bdf8,#0284c7)} .kpi.violet:before{background:linear-gradient(90deg,#6d8cf5,#1e4fd8)}
.kpi.amber:before{background:linear-gradient(90deg,#fbbf24,#c47f0a)} .kpi.rose:before{background:linear-gradient(90deg,#fb7185,#d92d5c)} .kpi.slate:before{background:linear-gradient(90deg,#94a3b8,#5b7288)}
.kpi.teal:before{background:linear-gradient(90deg,#34d3c0,#0e7f9a)}
.kpi .label{font-size:10.8px;color:var(--muted);font-weight:700;letter-spacing:.15px}
.kpi .value{font-size:21px;font-weight:800;letter-spacing:-.4px;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .sub{font-size:10.2px;color:var(--muted);margin-top:1px}
.kpi .vs{font-size:10.2px;font-weight:700;margin-top:3px;display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.kpi .vs .up{color:#c2410c}.kpi .vs .down{color:#0e7490}.kpi .vs .flat{color:#64748b}
.kpi .vs .muted{font-weight:500}
.cov-card{
  background:#fff;border:1px solid var(--line);border-radius:10px;
  box-shadow:var(--shadow-sm);margin-bottom:12px;overflow:hidden;
}
.cov-strip{display:grid;grid-template-columns:repeat(5,1fr)}
.cov-item{
  padding:10px 14px;min-width:0;cursor:pointer;transition:background .15s;
  border-inline-start:1px solid var(--line);position:relative;
}
.cov-item:first-child{border-inline-start:0}
.cov-item:hover{background:#f6f8ff}
.cov-item:hover .v{color:var(--accent)}
.cov-item:after{content:"›";position:absolute;inset-inline-end:12px;top:50%;transform:translateY(-50%);color:#c6d0e2;font-size:16px;font-weight:700;opacity:0;transition:opacity .15s}
.cov-item:hover:after{opacity:1}
.cov-item .k{font-size:10.8px;color:var(--muted);font-weight:700;display:flex;align-items:center;gap:6px}
.cov-item .v{font-size:18px;font-weight:800;letter-spacing:-.3px;margin-top:1px;font-variant-numeric:tabular-nums;transition:color .15s}
.cov-item .s{font-size:10.4px;color:var(--muted)}
.cov-item .cdot{width:7px;height:7px;border-radius:50%;flex:none}
.cov-note{border-top:1px solid var(--line);padding:8px 18px;font-size:10.8px;color:var(--muted);background:#fbfcff;line-height:1.9}
.cov-note b{color:#4b5b70}
@media(max-width:900px){.cov-strip{grid-template-columns:repeat(2,1fr)}.cov-item:nth-child(odd){border-inline-start:0}.cov-item:nth-child(n+3){border-top:1px solid var(--line)}}

/* ------------------------------------------------------------ ریزش اطلاعات */
.drill-hero{
  position:relative;overflow:hidden;border-radius:18px;padding:18px 18px 16px;margin-bottom:14px;color:#fff;
  background:radial-gradient(620px 240px at 90% -40%, rgba(91,124,250,.5) 0%, rgba(91,124,250,0) 65%),
    linear-gradient(135deg,#0b1220 0%,#13224a 52%,#0d2f38 100%);
  box-shadow:0 24px 44px -34px rgba(11,18,32,.95);border:1px solid rgba(255,255,255,.07);
}
.drill-kicker{font-size:10.8px;color:#a9c0f5;font-weight:700;letter-spacing:.2px}
.drill-title{font-size:19px;font-weight:800;margin:4px 0 2px;letter-spacing:-.3px}
.drill-sub{font-size:11.8px;color:#c2d1ee;line-height:1.9}
.drill-stats{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:13px}
.drill-stat{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.16);border-radius:12px;padding:8px 10px}
.drill-stat .l{font-size:10.2px;color:#b7c7e6}
.drill-stat .v{font-size:15.5px;font-weight:800;margin-top:1px;font-variant-numeric:tabular-nums}
.drill-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.drill-card{border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:#fff;min-width:0}
.drill-card h4{margin:0 0 10px;font-size:12px;color:#334155;font-weight:800;display:flex;align-items:center;gap:7px}
.drill-card h4:before{content:"";width:4px;height:13px;border-radius:2px;background:linear-gradient(180deg,#7c93ff,#0b64c8);display:inline-block}
.drill-table th{font-size:11px}
.drill-table td{font-size:11.5px}
.drill-table tbody tr{cursor:pointer}
.drill-empty{border:1px dashed #d7dfec;border-radius:12px;padding:18px;text-align:center;color:var(--muted);font-size:11.5px;background:#fbfcff}
/* مقایسهٔ سال جاری/قبل داخل ریزش اطلاعات */
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.cmp-side{border:1px solid var(--line);border-radius:8px;padding:9px 11px;background:#f8fbff}
.cmp-l{font-size:10.8px;color:var(--muted);font-weight:700}
.cmp-v{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums}
.cmp-s{font-size:10.4px;color:var(--muted);margin-bottom:6px}
.cmp-side .track{height:8px;background:#e8eef6;border-radius:2px;overflow:hidden}
.cmp-side .fill{height:100%}
.cmp-delta{margin-top:9px;font-size:11.4px}
.cmp-delta .up{color:#c2410c;font-weight:700}.cmp-delta .down{color:#0e7490;font-weight:700}.cmp-delta .flat{color:#64748b;font-weight:700}
@media(max-width:760px){.cmp{grid-template-columns:1fr}}
@media(max-width:900px){.drill-stats{grid-template-columns:repeat(2,1fr)}.drill-grid{grid-template-columns:1fr}}
/* شبکهٔ نمای کلی به سبک داشبورد مدیریتی */
.ov-row{display:grid;gap:10px;margin-bottom:10px;align-items:stretch}
.ov-row>.card{display:flex;flex-direction:column;min-height:100%}
.ov-row>.card>.bars,.ov-row>.card>.table-wrap{flex:1}
.ov-row>.ov-col{display:grid;gap:10px;grid-auto-rows:1fr;min-height:100%}
.ov-row>.ov-col>.card{display:flex;flex-direction:column;justify-content:flex-start}
.ov-row-trend{grid-template-columns:minmax(0,2.55fr) minmax(300px,1fr)}
.ov-row-four{grid-template-columns:repeat(4,minmax(0,1fr))}
.ov-row-two{grid-template-columns:minmax(0,1fr) minmax(0,1.35fr)}
.ov-row-three{grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) minmax(0,1fr)}
.ov-col{display:grid;gap:10px}
.trend-card{display:flex;flex-direction:column}
@media(max-width:1250px){.ov-row-trend{grid-template-columns:1fr}.ov-row-four{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){.ov-row-four,.ov-row-two,.ov-row-three{grid-template-columns:1fr}}
.grid-2{display:grid;grid-template-columns:1.05fr 1fr;gap:10px;margin-bottom:10px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow-sm);min-width:0}
.card h3{margin:0 0 10px;font-size:12.8px;font-weight:800;display:flex;align-items:center;gap:8px;letter-spacing:-.1px;
  padding-bottom:8px;border-bottom:1px solid #eef3f9}
.card h3:before{content:"";width:4px;height:14px;border-radius:2px;background:linear-gradient(180deg,#1487e0,#0b64c8);flex:none}
.card h3 .hint{font-size:10.2px;color:var(--muted);font-weight:500;margin-inline-start:auto}
.card .empty{color:var(--muted);font-size:12px;padding:24px;text-align:center}
.donut-wrap{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.donut-legend{display:flex;flex-direction:column;gap:7px;flex:1;min-width:200px}
.legend-item{display:flex;align-items:center;gap:7px;font-size:11.5px;cursor:pointer;border-radius:6px;padding:3px 5px}
.legend-item:hover{background:#f8fafc}
.dot{width:9px;height:9px;border-radius:99px;flex:none}
.legend-item .name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.legend-item .num{color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.bars{display:flex;flex-direction:column;gap:9px}
.bar-row{display:grid;grid-template-columns:minmax(110px,1.35fr) 3fr auto;gap:9px;align-items:center;font-size:11.5px;padding:2px 0}
.bar-row.clickable{cursor:pointer;border-radius:5px;padding-inline:4px;margin-inline:-4px;transition:background .12s}
.bar-row.clickable:hover{background:#eef6ff}
.bar-row.clickable:focus-visible{outline:2px solid #7fb6ea;outline-offset:1px}
.bar-row .track{position:relative}
.bar-row .fill.prev{position:absolute;inset-block:0;inset-inline-start:0;background:#cbd8e6;opacity:.75;border-radius:2px}
.bar-delta{display:inline-block;margin-inline-start:5px;font-size:10px;font-weight:700}
.bar-delta .up{color:#c2410c}.bar-delta .down{color:#0e7490}.bar-delta .flat{color:#94a3b8}
.ov-empty{border:1px dashed #d7dfec;border-radius:8px;padding:14px 12px;text-align:center;color:var(--muted);font-size:11.4px;background:#fbfdff;line-height:2}
.bar-legend{display:flex;gap:14px;font-size:10.4px;color:var(--muted);margin-top:7px;flex-wrap:wrap;align-items:center}
.bar-legend .sw{width:16px;height:7px;border-radius:2px;display:inline-block;margin-inline-end:5px;vertical-align:middle}
.bar-row .label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155;font-weight:600}
.bar-row .track{height:8px;background:#edf2f8;border-radius:2px;overflow:hidden}
.bar-row .fill{height:100%;border-radius:2px;min-width:2px;transition:width .3s ease}
.bar-row .val{font-variant-numeric:tabular-nums;color:#334155;font-size:11px;min-width:46px;text-align:left;font-weight:700}
.seg{display:inline-flex;background:#eef3f9;border-radius:7px;padding:2px;gap:2px;margin-bottom:6px}
.seg button{border:0;background:transparent;padding:4px 11px;border-radius:6px;font-family:inherit;font-size:11.2px;font-weight:700;color:var(--muted);cursor:pointer;transition:background .15s,color .15s}
.seg button.active{background:#fff;color:var(--accent);box-shadow:0 1px 4px -1px rgba(16,24,40,.22)}
.trend-wrap{position:relative;width:100%;overflow:hidden}
.trend-wrap svg{width:100%;height:auto;display:block}
/* جدول دادهٔ روند (زیر نمودار) */
.trend-legend{display:flex;gap:16px;align-items:center;flex-wrap:wrap;font-size:11.5px;color:#334155;margin-bottom:6px}
.trend-legend .k{display:inline-flex;align-items:center;gap:6px;font-weight:700}
.trend-legend .sw{width:18px;height:3px;border-radius:2px;display:inline-block}
.trend-legend .sw.dash{background:repeating-linear-gradient(90deg,#93a7bd 0 5px,transparent 5px 9px)}
.trend-table{width:100%;border-collapse:collapse;font-size:11.3px;margin-top:8px;direction:rtl}
.trend-table th,.trend-table td{border:1px solid #e3ecf6;padding:4px 6px;text-align:center;font-variant-numeric:tabular-nums;white-space:nowrap}
.trend-table th{background:#f2f7fd;color:#33506e;font-weight:700;font-size:10.8px}
.trend-table td.lbl{background:#f8fbff;font-weight:700;text-align:right;white-space:nowrap}
.trend-table tr.cur td{background:#eef7ff}
.trend-table tr.prev td{background:#fff}
.trend-table .up{color:#c2410c;font-weight:700}
.trend-table .down{color:#0e7490;font-weight:700}
.trend-table .flat{color:#64748b}
.trend-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:9px}
.trend-canvas{position:relative}
.trend-details{margin-top:8px;border:1px solid #e3ecf6;border-radius:8px;background:#fbfdff;overflow:hidden}
.trend-details>summary{cursor:pointer;padding:7px 11px;font-size:11.4px;font-weight:700;color:#33506e;list-style:none;display:flex;align-items:center;gap:8px}
.trend-details>summary::-webkit-details-marker{display:none}
.trend-details>summary:before{content:"▸";color:#0b64c8;font-size:12px;transition:transform .15s}
.trend-details[open]>summary:before{transform:rotate(90deg)}
.trend-details>summary:hover{background:#f1f7ff}
.trend-details #trend-table{padding:0 8px 9px;overflow-x:auto}
.trend-kpi{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:#f8fbff}
.trend-kpi .l{font-size:10.4px;color:var(--muted);font-weight:700}
.trend-kpi .v{font-size:16px;font-weight:800;margin-top:1px;font-variant-numeric:tabular-nums}
.trend-kpi .d{font-size:10.6px;font-weight:700;margin-top:1px}
.trend-kpi .d.up{color:#c2410c}.trend-kpi .d.down{color:#0e7490}.trend-kpi .d.flat{color:#64748b}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px;max-height:640px;background:#fff}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:12px}
thead th{
  position:sticky;top:0;z-index:2;background:#f2f7fd;color:#33506e;font-weight:700;text-align:right;
  padding:8px 8px;border-bottom:1px solid #dbe7f3;white-space:nowrap;font-size:10.9px;letter-spacing:.1px;
}
thead th.sortable{cursor:pointer;user-select:none}
thead th.sortable:hover{color:var(--accent)}
tbody td{padding:6px 8px;border-bottom:1px solid #eff4f9;vertical-align:middle;font-size:11.6px}
tbody tr:nth-child(even){background:#fbfdff}
tbody tr:hover{background:#eff6ff}
tbody tr.clickable{cursor:pointer}
tbody tr:last-child td{border-bottom:0}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.muted{color:var(--muted)}
.tiny{font-size:10.5px}
.badge{display:inline-block;padding:1px 8px;border-radius:4px;font-size:10.2px;font-weight:700;white-space:nowrap;border:1px solid transparent}
.badge.green{background:#e7f8f4;color:#0b6b5f;border-color:#c6f0e6}
.badge.blue{background:#eaf1fe;color:#1d4ed8;border-color:#d9e6fd}
.badge.amber{background:#fdf3e1;color:#8a5a05;border-color:#f8e5c3}
.badge.red{background:#fdeef1;color:#b4123e;border-color:#fbdde3}
.badge.slate{background:#eff3f8;color:#4b5b70;border-color:#e3e9f1}
.badge.violet{background:#f2edfe;color:#6229c9;border-color:#e6dcfc}
.group-pill{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.group-pill .dot{width:7px;height:7px}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.toolbar .right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.search-mini{position:relative}
.search-mini input{padding:6px 28px 6px 10px;border:1px solid var(--line);border-radius:7px;font-family:inherit;font-size:12px;width:240px;background:#fff;transition:box-shadow .15s,border-color .15s}
.search-mini input:focus{outline:none;border-color:#7fb6ea;box-shadow:0 0 0 3px rgba(11,100,200,.1)}
.search-mini:after{content:"⌕";position:absolute;right:9px;top:5px;color:var(--muted);font-size:16px}
.pager{display:flex;gap:6px;align-items:center;justify-content:center;padding:10px 0 0;flex-wrap:wrap}
.pager button{min-width:32px;height:30px;border:1px solid var(--line);background:#fff;border-radius:8px;cursor:pointer;font-family:inherit;font-size:12px}
.pager button.active{background:var(--teal);color:#fff;border-color:var(--teal)}
.pager button:disabled{opacity:.4;cursor:default}
.progress{height:8px;background:#eef2f7;border-radius:99px;overflow:hidden;min-width:80px}
.progress .fill{height:100%;border-radius:99px;background:var(--teal2)}
.mini-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.mini{background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.mini .k{font-size:10.5px;color:var(--muted);font-weight:600}
.mini .v{font-size:18px;font-weight:800;margin-top:2px}
.quality-note{background:linear-gradient(180deg,#fffdf5,#fffaeb);border:1px solid #f6e3b4;border-inline-start:4px solid #f0b429;color:#7c5310;border-radius:12px;padding:11px 13px;font-size:11.5px;margin-top:10px;line-height:1.9}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px;margin-top:6px}
.form-grid .field{display:flex;flex-direction:column;gap:4px}
.form-grid .field.full{grid-column:1/-1}
.form-grid label{font-size:11px;font-weight:700;color:#334155}
.form-grid input,.form-grid textarea,.form-grid select{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:9px;font-family:inherit;font-size:12px;background:#f8fafc}
.form-grid textarea{min-height:52px;resize:vertical}
.form-actions{display:flex;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap}
.form-state{font-size:11px;color:var(--muted)}
.store-badge{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;padding:4px 10px;border-radius:99px}
.store-badge.server{background:#ccfbf1;color:#0e7f9a}
.store-badge.local{background:#fef3c7;color:#92400e}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#0f172a;color:#fff;padding:10px 18px;border-radius:12px;font-size:12.5px;z-index:200;opacity:0;transition:opacity .25s;pointer-events:none}
.update-banner{position:fixed;bottom:20px;right:20px;z-index:210;display:none;gap:10px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 34px rgba(15,23,42,.18);padding:10px 14px;font-size:12.5px}
.update-banner.show{display:flex}
.update-banner .dot-live{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.18)}
.update-banner .dot-live.off{background:#94a3b8;box-shadow:0 0 0 3px rgba(148,163,184,.18)}
.toast.show{opacity:1}
.modal{position:fixed;inset:0;background:rgba(7,19,31,.62);display:grid;place-items:center;z-index:100;padding:18px;backdrop-filter:blur(6px)}
.modal.hidden{display:none}
.modal-box{background:#fff;border-radius:22px;max-width:1040px;width:100%;max-height:92vh;overflow:auto;box-shadow:0 40px 90px -20px rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.5)}
.modal-head{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 20px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#fff;z-index:3}
.modal-head h2{margin:0;font-size:14px;color:var(--muted);font-weight:700}
.modal-body{padding:16px 20px 22px}
.modal-foot:empty{display:none}
.modal-foot{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 20px;border-top:1px solid var(--line);position:sticky;bottom:0;background:#fff;z-index:3;font-size:11.5px;color:var(--muted)}
.kv{display:grid;grid-template-columns:140px 1fr;gap:8px 12px;font-size:12.5px}
.kv .k{color:var(--muted);font-weight:600}
.kv .v{color:var(--ink)}
.note-box{background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:10px 12px;font-size:12px;margin-top:12px;white-space:pre-wrap}
/* ------------------------------------------------------------ کارت اخطار */
.wm-hero{
  background:
    radial-gradient(620px 240px at 90% -40%, rgba(91,124,250,.5) 0%, rgba(91,124,250,0) 65%),
    linear-gradient(135deg,#0b1220 0%,#13224a 52%,#0d2f38 100%);
  color:#fff;border-radius:18px;padding:19px 19px 17px;margin-bottom:14px;
  box-shadow:0 24px 44px -34px rgba(11,18,32,.95);border:1px solid rgba(255,255,255,.07);
}
.wm-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.wm-serial{font-size:11.5px;color:#ccfbf1;font-weight:700;letter-spacing:.3px}
.wm-serial b{font-size:21px;color:#fff;letter-spacing:0;margin-right:2px}
.wm-meta{font-size:11.5px;color:#ccfbf1;margin-top:3px}
.wm-defect{font-size:17px;font-weight:800;line-height:1.6;margin:11px 0 3px}
.wm-part{font-size:12.5px;color:#ccfbf1}
.wm-badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;max-width:52%}
.wm-badges .badge{box-shadow:0 1px 3px rgba(0,0,0,.18)}
.wm-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
.wm-stat{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:8px 10px}
.wm-stat .l{font-size:10.5px;color:#ccfbf1}
.wm-stat .v{font-size:14.5px;font-weight:800;margin-top:1px}
.wm-tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:0 0 14px;flex-wrap:wrap}
.wm-tab{border:0;background:transparent;font-family:inherit;font-size:12.5px;font-weight:700;color:var(--muted);padding:9px 13px;border-radius:10px 10px 0 0;cursor:pointer;border-bottom:2px solid transparent;display:inline-flex;align-items:center;gap:6px}
.wm-tab:hover{background:#f8fafc;color:var(--ink)}
.wm-tab.active{color:var(--accent);border-bottom-color:var(--accent);background:#f4f6ff}
.wm-panel{display:none}
.wm-panel.active{display:block}
.wm-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.wm-card{border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:#fff}
.wm-card.full{grid-column:1/-1}
.wm-card h4{margin:0 0 10px;font-size:12px;color:#2f49b8;display:flex;align-items:center;gap:7px;font-weight:800}
.wm-card h4::before{content:"";width:4px;height:14px;border-radius:2px;background:linear-gradient(180deg,#1487e0,#0b64c8);display:inline-block}
.wm-rows{display:grid;grid-template-columns:118px 1fr;gap:7px 10px;font-size:12.5px}
.wm-rows .k{color:var(--muted);font-weight:600}
.wm-rows .v{color:var(--ink);word-break:break-word}
.bar-row.clickable{cursor:pointer;border-radius:8px}
.bar-row.clickable:hover{background:#f1f5f9}
.fchips{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px}
.fchip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:11.5px;font-weight:600;border:1px solid #e0e7ff}
.fchip button{border:0;background:none;color:#4338ca;cursor:pointer;font-size:13px;line-height:1;padding:0}
.fchip.clear{background:#fff1f2;color:#9f1239;border-color:#ffe4e6}
.wm-tag{display:inline-block;margin-inline-start:8px;padding:1px 7px;border-radius:999px;background:#eef2ff;color:#4338ca;font-size:10.5px;font-weight:700;vertical-align:middle}
.wm-tag.manual{background:#ecfdf5;color:#047857}
.wm-text{background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:11px 13px;font-size:12.5px;line-height:1.9;white-space:pre-wrap;color:#0f172a}
.wm-empty{border:1px dashed #cbd5e1;border-radius:14px;padding:22px;text-align:center;color:var(--muted);font-size:12.5px;background:#f8fafc;line-height:2}
.wm-source{display:flex;gap:9px;align-items:flex-start;background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;border-radius:12px;padding:9px 12px;font-size:11.5px;margin-bottom:12px;line-height:1.8}
.wm-link{background:none;border:0;color:var(--accent);font-family:inherit;font-size:11.5px;font-weight:700;cursor:pointer;text-decoration:underline;padding:0}
@media(max-width:760px){.wm-grid{grid-template-columns:1fr}.wm-stats{grid-template-columns:repeat(2,1fr)}.wm-badges{max-width:100%;justify-content:flex-start}.wm-rows{grid-template-columns:94px 1fr}}
/* ------------------------------------------------------- بارگذاری داده */
.up-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:4px}
.up-item{border:1px solid var(--line);border-radius:14px;padding:11px 13px;background:#fff;display:flex;flex-direction:column;gap:8px}
.up-item.ok{border-color:#c6f0e6;background:#f7fefb}
.up-item.missing{border-color:#fbdde3;background:#fff7f9}
.up-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.up-title{font-size:12.5px;font-weight:800;color:var(--ink);line-height:1.6}
.up-meta{font-size:10.8px;color:var(--muted);line-height:1.9;word-break:break-all}
.up-meta b{color:#334155;font-weight:700}
.up-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.up-actions input[type=file]{display:none}
.up-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid #c7d2fe;background:#eef2ff;color:#3730a3;border-radius:10px;padding:7px 11px;font-family:inherit;font-size:11.8px;font-weight:700;cursor:pointer;transition:background .15s,transform .12s}
.up-btn:hover{background:#e0e7ff;transform:translateY(-1px)}
.up-btn[disabled]{opacity:.55;cursor:not-allowed;transform:none}
.up-status{font-size:11px;color:var(--muted);min-height:16px}
.up-status.busy{color:#1d4ed8;font-weight:700}
.up-status.done{color:#047857;font-weight:700}
.up-status.fail{color:#b4123e;font-weight:700}
.up-bar{height:5px;border-radius:99px;background:#e2e8f0;overflow:hidden;display:none}
.up-bar.show{display:block}
.up-bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#0b64c8,#1487e0);transition:width .2s}
.up-steps{margin:0;padding-inline-start:18px;font-size:12px;line-height:2.1;color:#334155}
.up-steps b{color:var(--ink)}
.up-note{background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:10px 12px;font-size:11.6px;line-height:2;color:#334155;margin-bottom:12px}
.up-note b{color:var(--ink)}
@media(max-width:760px){.up-grid{grid-template-columns:1fr}}
footer{padding:18px 22px;color:var(--muted);font-size:11px;text-align:center}
@media(max-width:1200px){.kpi-grid{grid-template-columns:repeat(3,1fr)}.filters{grid-template-columns:repeat(4,1fr)}.grid-3{grid-template-columns:1fr}}
@media(max-width:760px){
  .kpi-grid{grid-template-columns:repeat(2,1fr)} .filters{grid-template-columns:repeat(2,1fr)}
  .grid-2,.mini-grid{grid-template-columns:1fr} .topbar{padding:12px 14px}
  main{padding:10px} .search-mini input{width:100%} .bar-row{grid-template-columns:minmax(80px,1.2fr) 2fr auto}
  .ov-row-four,.ov-row-two,.ov-row-three,.ov-row-trend{grid-template-columns:1fr}
  .trend-kpis{grid-template-columns:repeat(2,1fr)}
  .brand h1{font-size:15px}.brand p{display:none}.logo{width:34px;height:34px;font-size:15px}
}
/* تبلت و لپ‌تاپ کوچک: ردیف چهارتایی دو ستونه و KPI سه‌ستونه */
@media(max-width:1100px) and (min-width:761px){
  .kpi-grid{grid-template-columns:repeat(3,1fr)}
  .ov-row-four{grid-template-columns:repeat(2,minmax(0,1fr))}
  .filters{grid-template-columns:repeat(5,minmax(100px,1fr))}
}
@media print{
  .tabs,.filters,.toolbar,.pager,.btn{display:none!important}
  .tab-panel{display:block!important;page-break-inside:avoid}
  body{background:#fff}.card,.kpi{box-shadow:none}
}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">
    <div class="logo">ک</div>
    <div>
      <h1>داشبورد دسته‌بندی اخطارهای کیفی</h1>
      <p>محصول / خانواده / گروه محصول — بر پایه کاتالوگ راهکاران و فایل گروه‌بندی محصولات</p>
    </div>
  </div>
  <div class="meta" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;justify-content:flex-end">
    <div id="meta"></div>
    <button class="btn" id="open-upload" title="بارگذاری فایل‌های تازهٔ ورودی (اخطار، ListData، گروه‌بندی، برگهٔ بررسی) و ساخت خودکار گزارش" style="background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.28);padding:9px 15px;white-space:nowrap;backdrop-filter:blur(6px);box-shadow:inset 0 1px 0 rgba(255,255,255,.18)">⤒ بارگذاری داده</button>
    <button class="btn" id="refresh-data" title="ساخت دوبارهٔ گزارش از فایل‌های ورودی (داده‌های ذخیره‌شده حفظ می‌شوند)" style="background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.28);padding:9px 15px;white-space:nowrap;backdrop-filter:blur(6px);box-shadow:inset 0 1px 0 rgba(255,255,255,.18)">⟳ به‌روزرسانی</button>
    <span id="auto-refresh-badge" class="tiny" style="display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:5px 11px;color:#d6e2ff" title="اگر فایل‌های ورودی یا برنامه تغییر کند، گزارش خودکار تازه می‌شود"><span class="dot-live off"></span><span id="auto-refresh-text">به‌روزرسانی خودکار</span></span>
  </div>
</header>
<nav class="tabs" id="tabs">
  <button class="tab active" data-tab="overview">نمای کلی</button>
  <button class="tab" data-tab="groups">گروه‌های محصول</button>
  <button class="tab" data-tab="families">خانواده‌ها</button>
  <button class="tab" data-tab="products">محصولات</button>
  <button class="tab" data-tab="warnings">فهرست اخطارها</button>
  <button class="tab" data-tab="reviews">برگه‌های بررسی مشتری</button>
  <button class="tab" data-tab="defects">ایرادهای مشتری</button>
  <button class="tab" data-tab="forms8d">فرم‌های 8D</button>
  <button class="tab" data-tab="quality">کیفیت تطبیق</button>
</nav>
<div class="filters">
  <div class="field"><label>گروه محصول</label><select id="f-group"></select></div>
  <div class="field"><label>خانواده محصول</label><select id="f-family"></select></div>
  <div class="field"><label>محصول</label><select id="f-product"></select></div>
  <div class="field"><label>برنچ</label><select id="f-branch"></select></div>
  <div class="field"><label>گروه خودرو</label><select id="f-car"></select></div>
  <div class="field"><label>گرید ایراد</label><select id="f-grade"></select></div>
  <div class="field"><label>سال</label><select id="f-year"></select></div>
  <div class="field"><label>از ماه</label><select id="f-from"></select></div>
  <div class="field"><label>تا ماه</label><select id="f-to"></select></div>
  <div class="field" style="grid-column:span 3"><label>جستجو (شرح قطعه، شماره فنی، محصول، سریال)</label><input id="f-q" placeholder="مثلاً NBCM یا جلوآمپر یا IK01750880"></div>
  <div class="field" style="grid-column:span 2"><label>وضعیت مؤثر اخطار</label><select id="f-status"></select></div>
  <div class="field"><label>اولویت اخطار</label><select id="f-priority"></select></div>
  <div class="field"><label>برگه بررسی</label><select id="f-review"></select></div>
  <div class="field"><label>ریشهٔ ایراد</label><select id="f-root"></select></div>
  <div class="field"><label>قطعهٔ تحلیل</label><select id="f-rootpart"></select></div>
  <div class="field"><label>فرآیند مسئول</label><select id="f-process"></select></div>
  <div class="filter-actions" style="grid-column:span 4">
    <button class="btn" id="reset">پاک‌کردن</button>
    <button class="btn primary" id="export">خروجی CSV</button>
    <button class="btn" id="print">چاپ</button>
  </div>
</div>
<main>
  <section class="tab-panel active" id="tab-overview">
    <div class="ov-kpis" id="kpi-card">
      <div class="ov-kpi-grid" id="kpis"></div>
      <div class="ov-note" id="coverage-note"></div>
    </div>

    <!-- ردیف ۱: روند (مقایسه‌ای با سال قبل) + وضعیت + جزئیات وضعیت -->
    <div class="ov-row ov-row-trend">
      <div class="card trend-card">
        <div class="toolbar" style="margin-bottom:6px">
          <h3 style="margin:0;border:0;padding:0">روند اخطارها <span class="hint" id="trend-hint">مقایسه با سال قبل</span></h3>
          <div class="right">
            <div class="seg" id="bars-compare" title="همان میله‌ها با سال قبل مقایسه شوند؛ میلهٔ خاکستری = سال قبل">
              <button data-barscompare="on">میله‌ها: با سال قبل</button><button data-barscompare="off" class="active">میله‌ها: سال جاری</button>
            </div>
            <div class="seg" id="trend-toggle">
              <button data-mode="month" class="active">ماهانه</button><button data-mode="year">سالانه</button>
            </div>
            <div class="seg" id="trend-compare">
              <button data-compare="yoy" class="active">با سال قبل</button><button data-compare="off">بدون مقایسه</button>
            </div>
          </div>
        </div>
        <div id="trend-kpis" class="trend-kpis"></div>
        <div class="trend-canvas">
          <div class="trend-legend" id="trend-legend"></div>
          <div class="trend-wrap" id="trend"></div>
        </div>
        <details class="trend-details" id="trend-details">
          <summary>جدول مقایسهٔ ماه‌به‌ماه با سال قبل</summary>
          <div id="trend-table"></div>
        </details>
      </div>
      <div class="ov-col">
        <div class="card">
          <h3>وضعیت اخطارهای کیفی <span class="hint" id="status-total"></span></h3>
          <div id="status-donut"></div>
        </div>
        <div class="card">
          <h3>جزئیات وضعیت <span class="hint">مراحل اقدام</span></h3>
          <div id="status-detail"></div>
        </div>
      </div>
    </div>

    <div class="bar-legend" id="bars-legend"></div>

    <!-- ردیف ۲: ریشه، قطعه، ایراد اعلام‌شده، واحد مسئول -->
    <div class="ov-row ov-row-four">
      <div class="card">
        <h3>ریشهٔ ایراد <span class="hint">کلیک = ریزش اطلاعات</span></h3>
        <div class="bars" id="root-bars"></div>
        <div class="muted tiny" id="root-note" style="margin-top:6px"></div>
      </div>
      <div class="card">
        <h3>قطعهٔ معیوب <span class="hint">از «آنالیز علت ایراد»</span></h3>
        <div class="bars" id="rootpart-bars"></div>
        <div class="muted tiny" id="pareto-note" style="margin-top:6px"></div>
      </div>
      <div class="card">
        <h3>ایراد اعلام‌شده <span class="hint">متن مشتری</span></h3>
        <div class="bars" id="ov-defect-bars"></div>
      </div>
      <div class="card">
        <h3>واحد مسئول <span class="hint">فرآیند از برگهٔ بررسی (C-Plus)</span></h3>
        <div class="bars" id="ov-make-bars"></div>
        <div class="muted tiny" id="ov-process-note" style="margin-top:6px"></div>
      </div>
    </div>

    <!-- ردیف ۳: ۶M + ایرادهای تکراردار -->
    <div class="ov-row ov-row-two">
      <div class="card">
        <h3>علت‌ها بر پایهٔ ۶M <span class="hint">از برگهٔ بررسی</span></h3>
        <div class="bars" id="ov-m6-bars"></div>
        <div class="muted tiny" id="ov-m6-note" style="margin-top:6px"></div>
      </div>
      <div class="card">
        <h3>ایرادهای تکراردار <span class="hint">همان ایراد در یک محصول</span></h3>
        <div class="table-wrap" style="max-height:250px"><table id="repeat-table"></table></div>
      </div>
    </div>

    <!-- ردیف ۴: گروه‌ها + خانواده‌ها + محصولات -->
    <div class="ov-row ov-row-three">
      <div class="card"><h3>سهم گروه‌های محصول <span class="hint">تعداد اخطار</span></h3><div id="donut"></div></div>
      <div class="card"><h3>پرتکرارترین خانواده‌ها <span class="hint">۱۲ خانواده</span></h3><div class="bars" id="family-bars"></div></div>
      <div class="card"><h3>پرتکرارترین محصولات <span class="hint">۱۰ محصول</span></h3><div class="bars" id="product-bars"></div></div>
    </div>

    <div class="card" style="margin-bottom:10px">
      <div class="toolbar">
        <h3 style="margin:0;border:0;padding:0">پارتو قطعه در تحلیل <span class="hint" id="pareto-count"></span></h3>
        <div class="right"><div class="search-mini"><input id="pareto-search" placeholder="جستجوی قطعه در تحلیل"></div></div>
      </div>
      <div class="table-wrap" style="max-height:360px"><table id="pareto-table"></table></div>
    </div>

    <div class="card">
      <h3>خلاصه گروه‌ها <span class="hint">کلیک روی ردیف = فیلتر گروه</span></h3>
      <div class="table-wrap" style="max-height:420px"><table id="group-table"></table></div>
    </div>
  </section>

  <section class="tab-panel" id="tab-groups">
    <div class="grid-2">
      <div class="card"><h3>توزیع اخطار در گروه‌ها</h3><div id="groups-donut"></div></div>
      <div class="card"><h3>قطعات معیوب در گروه‌ها</h3><div class="bars" id="groups-qty"></div></div>
    </div>
    <div class="card"><h3>جدول کامل گروه‌ها</h3><div class="table-wrap"><table id="groups-full"></table></div></div>
  </section>

  <section class="tab-panel" id="tab-families">
    <div class="grid-2">
      <div class="card"><h3>خانواده‌های پرتکرار</h3><div class="bars" id="families-bars"></div></div>
      <div class="card"><h3>سهم قطعات معیوب خانواده‌ها</h3><div class="bars" id="families-qty"></div></div>
    </div>
    <div class="card"><h3>جدول خانواده‌ها</h3><div class="table-wrap"><table id="families-table"></table></div></div>
  </section>

  <section class="tab-panel" id="tab-products">
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">محصولات <span class="hint" id="products-count"></span></h3>
        <div class="right"><div class="search-mini"><input id="product-search" placeholder="جستجوی محصول/خانواده/کد"></div></div>
      </div>
      <div class="table-wrap"><table id="products-table"></table></div>
      <div class="pager" id="products-pager"></div>
    </div>
  </section>

  <section class="tab-panel" id="tab-warnings">
    <div class="quality-note" id="priority-note" style="margin:0 0 12px"></div>
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">فهرست اخطارها <span class="hint" id="warnings-count"></span></h3>
        <div class="right">
          <select id="warning-sort" class="btn" style="padding:8px 10px"><option value="priority">ترتیب: اولویت، سپس جدیدترین</option><option value="date">ترتیب: فقط جدیدترین</option></select>
          <div class="search-mini"><input id="warning-search" placeholder="جستجو در شرح قطعه/شماره فنی/سریال"></div>
          <select id="page-size" class="btn" style="padding:8px 10px"><option value="25">۲۵ ردیف</option><option value="50">۵۰ ردیف</option><option value="100">۱۰۰ ردیف</option></select>
        </div>
      </div>
      <div class="fchips" id="warnings-active-filters"></div>
      <div class="table-wrap"><table id="warnings-table"></table></div>
      <div class="pager" id="warnings-pager"></div>
    </div>
  </section>

  <section class="tab-panel" id="tab-reviews">
    <div class="quality-note" id="review-link-note" style="margin:0 0 12px"></div>
    <div class="kpi-grid" id="review-kpis" style="grid-template-columns:repeat(4,1fr)"></div>
    <div class="grid-2">
      <div class="card"><h3>منشا ایراد <span class="hint">بر اساس برگه‌های بررسی</span></h3><div class="bars" id="origin-bars"></div></div>
      <div class="card"><h3>دسته محصول اعلامی مشتری <span class="hint">مقایسه با گروه‌بندی داخلی</span></h3><div class="bars" id="category-bars"></div></div>
    </div>
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">برگه‌های بررسی مشتری <span class="hint" id="review-count"></span></h3>
        <div class="right">
          <div class="search-mini"><input id="review-search" placeholder="جستجو در علت ایراد/اقدام/شماره اخطار"></div>
          <button class="btn" id="review-export">خروجی CSV بررسی‌ها</button>
        </div>
      </div>
      <div class="table-wrap"><table id="reviews-table"></table></div>
      <div class="pager" id="reviews-pager"></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>راهنمای فرم 8D</h3>
      <div class="quality-note">برای هر اخطار بررسی‌شده و هر اخطار باز، یک فرم 8D با شماره <b>8D-سال-سریال</b> ساخته شده است. فایل ورد همهٔ فرم‌ها با عنوان «فرم 8D اخطارها.docx» در پوشهٔ خروجی است و ردیف‌های آماده (دارای علت و اقدام) در شیت «فرم 8D» گزارش اکسل فهرست شده‌اند. در جزئیات هر اخطار، شماره فرم و متن علت/اقدام نمایش داده می‌شود.</div>
    </div>
  </section>

  <section class="tab-panel" id="tab-defects">
    <div class="quality-note" style="margin:0 0 12px">
      <b>ایراد مشتری</b> متن واقعی ایراد است که از «توضیحات» استخراج می‌شود؛ نمونه: اخطار ۲۳۵۹۱۱ ← «عدم عملکرد نشانگر درب‌ها».
      <b>دسته‌بندی ایراد</b> جداگانه و فقط <b>عملکردی</b> یا <b>ظاهری</b> است. ستون «گروه فنی» فقط یک لایهٔ کمکی برای گزارش است و جای توصیف ایراد را نمی‌گیرد.
    </div>
    <div class="quality-note" id="pattern-note" style="margin:0 0 12px" hidden></div>
    <div class="kpi-grid" id="defect-kpis" style="grid-template-columns:repeat(4,1fr)"></div>
    <div class="grid-2">
      <div class="card"><h3>پرتکرارترین ایرادهای مشتری <span class="hint">توصیف واقعی استخراج‌شده از «توضیحات»</span></h3><div class="bars" id="defect-bars"></div></div>
      <div class="card"><h3>گروه ۶M علت‌ها <span class="hint">نیروی انسانی / تجهیزات / مواد / روش / اندازه‌گیری / محیط</span></h3><div class="bars" id="m6-bars"></div></div>
    </div>
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">ایرادهای مشتری <span class="hint" id="defect-count"></span></h3>
        <div class="right">
          <div class="seg" id="defect-cat" style="margin-bottom:0"><button data-cat="all" class="active">همه</button><button data-cat="عملکردی">عملکردی</button><button data-cat="ظاهری">ظاهری</button></div>
          <div class="search-mini"><input id="defect-search" placeholder="جستجو در ایراد / دسته‌بندی / گروه"></div>
          <button class="btn" id="defect-export">خروجی CSV</button>
        </div>
      </div>
      <div class="table-wrap"><table id="defects-table"></table></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>علت‌های استاندارد <span class="hint">یکسان‌سازی «آنالیز علت ایراد» برگه‌های بررسی</span></h3>
      <div class="table-wrap"><table id="causes-table"></table></div>
    </div>
  </section>

  <section class="tab-panel" id="tab-forms8d">
    <div class="kpi-grid" id="form-kpis" style="grid-template-columns:repeat(4,1fr)"></div>
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">فرم‌های 8D <span class="hint" id="form-count"></span></h3>
        <div class="right">
          <span class="store-badge local" id="store-badge">حالت مرورگر</span>
          <div class="search-mini"><input id="form-search" placeholder="جستجو در سریال / قطعه / مسئول"></div>
          <select id="form-scope" class="btn" style="padding:8px 10px">
            <option value="working">باز یا دارای برگه بررسی</option>
            <option value="open">فقط اخطارهای باز</option>
            <option value="review">فقط دارای برگه بررسی</option>
            <option value="all">همهٔ اخطارها</option>
          </select>
          <select id="form-status-filter" class="btn" style="padding:8px 10px"></select>
          <button class="btn" id="form-export">خروجی CSV</button>
          <button class="btn" id="form-export-json">پشتیبان JSON</button>
        </div>
      </div>
      <div class="table-wrap"><table id="forms-table"></table></div>
      <div class="pager" id="forms-pager"></div>
      <div class="quality-note">فرم‌ها را با کلیک روی هر ردیف باز کنید، بخش‌های D1 تا D8 را پر کنید و «ذخیره» بزنید. برای ذخیرهٔ دائمی روی سرور، برنامه را با <b>python serve.py</b> اجرا کنید؛ در حالت فایل، داده‌ها در مرورگر همان رایانه نگه داشته می‌شوند و با «پشتیبان JSON» قابل انتقال‌اند.</div>
    </div>
  </section>

  <section class="tab-panel" id="tab-quality">
    <div class="kpi-grid" id="quality-kpis" style="grid-template-columns:repeat(4,1fr)"></div>
    <div class="grid-2">
      <div class="card"><h3>روش تطبیق</h3><div class="bars" id="method-bars"></div></div>
      <div class="card"><h3>دسته‌های خارج از دامنه</h3><div class="bars" id="out-bars"></div></div>
    </div>
    <div class="card"><h3>موارد نیازمند بازبینی <span class="hint">حداکثر ۲۰۰ ردیف</span></h3><div class="table-wrap"><table id="review-table"></table></div></div>
    <div class="card" style="margin-top:14px">
      <h3>کنترل گروه‌بندی <span class="hint">ردیف‌هایی که دستهٔ اعلامی مشتری با گروه‌بندی داخلی هم‌خوان نیست</span></h3>
      <div class="table-wrap"><table id="checks-table"></table></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>برگه‌های بررسی بدون اخطار متناظر <span class="hint">سریال‌هایی که در فایل اخطارها نیستند</span></h3>
      <div class="table-wrap"><table id="unmatched-table"></table></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>راهنمای تفسیر</h3>
      <div class="quality-note">
        «در دامنه» یعنی گروه محصول یکی از گروه‌های فایل گروه‌بندی است. «در فایل گروه‌بندی» یعنی خود محصول/خانواده در فایل پیدا شده است. اختلاف این دو، شکاف کاتالوگ را نشان می‌دهد: محصولاتی که گروه آن‌ها مشخص است ولی هنوز در فایل گروه‌بندی تعریف نشده‌اند. ستون «نیاز به بازبینی» برای تطبیق‌های کم‌اطمینان یا مبتنی بر نام است.
      </div>
    </div>
  </section>
</main>
<footer id="footer"></footer>

<div class="update-banner" id="update-banner">
  <span id="update-banner-text">نسخهٔ تازهٔ گزارش آماده است</span>
  <button class="btn primary" id="update-banner-apply" style="padding:6px 10px">بارگذاری</button>
  <button class="btn" id="update-banner-later" style="padding:6px 10px">بعداً</button>
</div>

<div class="modal hidden" id="modal">
  <div class="modal-box">
    <div class="modal-head"><h2 id="modal-title">جزئیات</h2><button class="btn" id="modal-close">بستن</button></div>
    <div class="modal-body" id="modal-body"></div>
    <div class="modal-foot" id="modal-foot"></div>
  </div>
</div>

__DATA_SCRIPT__
<script>
const DATA = window.DASHBOARD_DATA;
if(!DATA){
  document.body.insertAdjacentHTML("afterbegin",'<div style="padding:40px;text-align:center;font-family:Tahoma;direction:rtl">دادهٔ داشبورد بارگذاری نشد. فایل داده (dashboard-data.js) باید کنار همین فایل HTML باشد.</div>');
  throw new Error("dashboard data missing");
}
const GROUP_COLORS = {
  "Cluster Instrument":"#0e7f9a",
  "Nodes":"#3b6fe0",
  "EMS-توسعه و نگاشت موتور":"#7255d8",
  "TP-قطعات جانبی قوای محرکه":"#c9820f",
  "SBS-سیستم های ایمنی ترمز":"#d4485f",
  "Switch":"#0e8ea6",
  "Display Unit":"#5f9a33",
  "خارج از دامنه گروه‌بندی":"#9aa8b8",
  "سایر":"#9b6bd4",
  "درایو کولر":"#dd9427"
};
const GROUP_SHORT = {
  "EMS-توسعه و نگاشت موتور":"EMS — موتور",
  "TP-قطعات جانبی قوای محرکه":"TP — قطعات جانبی",
  "SBS-سیستم های ایمنی ترمز":"SBS — ایمنی ترمز",
  "خارج از دامنه گروه‌بندی":"خارج از دامنه"
};
const $ = (s, el=document)=>el.querySelector(s);
const $$ = (s, el=document)=>Array.from(el.querySelectorAll(s));
const fmt = n => new Intl.NumberFormat("fa-IR").format(Number(n||0));
const pct = x => (Number(x||0)*100).toLocaleString("fa-IR",{maximumFractionDigits:1})+"٪";
const faDigits = s => String(s??"").replace(/\d/g,d=>"۰۱۲۳۴۵۶۷۸۹"[d]);
const esc = s => String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const color = g => GROUP_COLORS[g] || "#64748b";
const gLabel = g => GROUP_SHORT[g] || g;
const statusBadge = r => {
  if(r.autoClosed) return `<span class="badge violet" title="وضعیت ثبت‌شده: ${esc(r.rawStatus||"—")}">خاتمهٔ خودکار</span>`;
  return r.open ? '<span class="badge amber">باز</span>' : `<span class="badge green" title="وضعیت ثبت‌شده: ${esc(r.rawStatus||"—")}">خاتمه</span>`;
};
const priorityBadge = r => {
  const cls={1:"red",2:"amber",3:"slate",4:"violet",5:"green"}[r.priority]||"slate";
  return `<span class="badge ${cls}">${esc(r.priorityLabel||"—")}</span>`;
};
const confBadge = c => {
  const cls = c==="قطعی"||c==="بالا" ? "green" : c==="متوسط" ? "amber" : c==="پایین" ? "red" : "slate";
  return `<span class="badge ${cls}">${esc(c||"—")}</span>`;
};
const reviewBadge = r => r.review ? '<span class="badge red">بازبینی</span>' : "";
const catalogBadge = r => r.inCatalog ? '<span class="badge green">کاتالوگ</span>' : (r.inScope ? '<span class="badge slate">سایر</span>' : '<span class="badge slate">خارج</span>');

const state = {group:"",family:"",product:"",car:"",grade:"",status:"",priority:"",year:"",from:"",to:"",q:"",m6:"",make:"",process:"",tab:"overview",warningSort:"priority",
  review:"",branch:"",defect:"",root:"",rootPart:"",quickFilter:"",defectCat:"all",productQ:"",warningQ:"",reviewQ:"",defectQ:"",formQ:"",formStatus:"",formScope:"working",paretoQ:"",
  page:1,pageSize:25,productSort:{key:"warnings",dir:-1},trendMode:"month",trendCompare:true,barsCompare:false};
let currentProducts = [];
let currentWarnings = [];
let currentReviews = [];
let FORM_DIRTY = false;      // ویرایش ذخیره‌نشده در فرم 8D
let PAGE_BUILD = null;       // شناسهٔ نسخهٔ بارگذاری‌شده
let SERVER_WATCH = null;     // وضعیت به‌روزرسانی خودکار روی سرور

function monthKey(r){ return r.monthKey || 0; }
function byPriority(a,b){
  return (a.priority||9)-(b.priority||9) || (b.dateKey||0)-(a.dateKey||0) || (b.id||0)-(a.id||0);
}
function byNewest(a,b){
  return (b.dateKey||0)-(a.dateKey||0) || (a.priority||9)-(b.priority||9) || (b.id||0)-(a.id||0);
}
function haystack(r){
  return [r.part,r.origin,r.tech,r.code,r.rahkaran,r.product,r.family,r.group,r.branch,r.car,r.id,r.error,r.type,r.cause,r.causeStd,r.m6,r.defect,r.defectCat,r.defectGroup,r.action].join(" ").toLowerCase();
}
function applyFilters(opts){
  opts=opts||{};
  const q = state.q.trim().toLowerCase();
  return DATA.warnings.filter(r=>{
    if(state.group && r.group!==state.group) return false;
    if(state.family && r.family!==state.family) return false;
    if(state.product && r.product!==state.product) return false;
    if(state.branch && r.branch!==state.branch) return false;
    if(state.defect && r.defect!==state.defect) return false;
    if(state.root && r.rootCause!==state.root) return false;
    if(state.rootPart && r.analysisPart!==state.rootPart) return false;
    if(state.m6 && (r.m6||"نامشخص")!==state.m6) return false;
    if(state.make && r.make!==state.make) return false;
    if(state.process && r.process!==state.process) return false;
    if(state.quickFilter==="notreceived" && !isNotReceived(r)) return false;
    if(state.car && r.car!==state.car) return false;
    if(state.grade && r.grade!==state.grade) return false;
    if(state.status==="open" && !r.open) return false;
    if(state.status==="closed" && r.open) return false;
    if(state.priority && String(r.priority)!==state.priority) return false;
    if(state.review==="yes" && !r.hasReview) return false;
    if(state.review==="no" && r.hasReview) return false;
    if(!opts.skipYear){
      if(state.year && String(r.year)!==state.year) return false;
      if(state.from && monthKey(r) && monthKey(r)<Number(state.from)) return false;
      if(state.to && monthKey(r) && monthKey(r)>Number(state.to)) return false;
    }
    if(q && !haystack(r).includes(q)) return false;
    return true;
  });
}
function monthsOfYear(year){
  const set = new Map();
  DATA.warnings.forEach(r=>{
    if(!r.monthKey) return;
    if(year && String(r.year)!==String(year)) return;
    if(!set.has(r.monthKey)) set.set(r.monthKey, r.month);
  });
  return Array.from(set.entries()).sort((a,b)=>a[0]-b[0]).map(([key,label])=>({key:String(key),label}));
}
function sum(rows,key){ return rows.reduce((a,r)=>a+Number(r[key]||0),0); }
function uniq(rows,key){ return new Set(rows.map(r=>r[key]).filter(Boolean)).size; }
function groupAgg(rows,key){
  const map = new Map();
  rows.forEach(r=>{
    const k = r[key] || "نامشخص";
    if(!map.has(k)) map.set(k,{name:k,warnings:0,qty:0,score:0,products:new Set(),families:new Set(),open:0,gradeA:0});
    const o=map.get(k); o.warnings++; o.qty+=r.qty||0; o.score+=r.score||0; o.products.add(r.product); o.families.add(r.family);
    if(r.open) o.open++; if(r.grade==="A") o.gradeA++;
  });
  return Array.from(map.values()).map(o=>({...o,products:o.products.size,families:o.families.size})).sort((a,b)=>b.warnings-a.warnings);
}
function topN(rows,key,n,value="warnings"){
  return groupAgg(rows,key).sort((a,b)=>b[value]-a[value]).slice(0,n);
}
function empty(el,text="داده‌ای برای نمایش نیست"){ el.innerHTML=`<div class="empty">${text}</div>`; }

function renderMeta(){
  const k=DATA.kpis;
  $("#meta").innerHTML = `<div>منابع: <b>${esc(DATA.meta.sources.warnings||"اخطار کیفی")}</b> · <b>${esc(DATA.meta.sources.listdata||"ListData")}</b> · <b>${esc(DATA.meta.sources.catalog||"گروه‌بندی")}</b></div>
  <div>تولید گزارش: ${esc(faDigits(DATA.meta.generated))}</div>`;
  $("#footer").innerHTML = `داشبورد تولیدشده از ${fmt(k.warnings)} ردیف اخطار · ${fmt(k.tech)} شماره فنی یکتا · ${fmt(k.products)} محصول · ${pct(k.in_scope_pct)} در دامنه گروه‌بندی`;
}

function renderPriorityNote(){
  const el=$("#priority-note"); if(!el) return;
  const rule=DATA.statusRule||{}, counts=rule.counts||{};
  const n=key=>fmt(counts[key]||0);
  const auto=(rule.autoClosed||[]).map(item=>item["سریال اخطار"]);
  el.innerHTML=`<b>ترتیب پیش‌فرض:</b> اولویت اخطار، سپس جدیدترین تاریخ. `+
    `<b>${n("باز — سال جاری")}</b> اخطار باز سال ${faDigits(rule.currentYear||"")} در اولویت اول · `+
    `<b>${n("باز — یک‌سال گذشته")}</b> اخطار باز یک‌سال گذشته (مرز ${faDigits(rule.cutoff||"—")}) · `+
    `<b>${n("باز — بدون تاریخ")}</b> اخطار باز بدون تاریخ · `+
    `<b>${n("خاتمهٔ خودکار")}</b> اخطار قدیمی‌تر خودکار خاتمه‌یافته${auto.length?` (سریال ${auto.map(value=>esc(value)).join("، ")})`:""}. `+
    `<span class="muted tiny">مبنا: امروز ${faDigits(rule.today||"—")} · برای دیدن هر گروه از فیلتر «اولویت اخطار» استفاده کنید.</span>`;
}

/* «عدم دریافت قطعه»: «آنالیز علت ایراد» برگهٔ بررسی این عبارت را دارد (فایل C-Plus). */
const isNotReceived=r=>r.statusGroup?r.statusGroup==="عدم دریافت قطعه":(r.cause||"").replace(/ي/g,"ی").indexOf("عدم دریافت قطعه")>=0;
/* سه گروه وضعیت، افراز کامل: خاتمه‌یافته + در حال بررسی + عدم دریافت قطعه = کل */
const hasRootCause=r=>r.hasRoot===true || !!(r.process && r.process!=="نامشخص");
const isInReview=r=>r.statusGroup?r.statusGroup==="در حال بررسی":!isNotReceived(r)&&((r.hasReview&&!hasRootCause(r))||!!r.open);
const isClosed=r=>r.statusGroup?r.statusGroup==="خاتمه‌یافته":(!isNotReceived(r)&&!isInReview(r));
const STATUS_GROUPS=["خاتمه‌یافته","در حال بررسی","عدم دریافت قطعه"];
const statusOf=r=>isNotReceived(r)?"عدم دریافت قطعه":(isInReview(r)?"در حال بررسی":"خاتمه‌یافته");
const statusCounts=rows=>({
  closed:rows.filter(isClosed).length,
  inReview:rows.filter(isInReview).length,
  notReceived:rows.filter(isNotReceived).length
});
const PROC_ORDER=["تولید","مواد اولیه","تامین‌کننده","طراحی مهندسی","مشتری"];
/* میله‌های «واحد مسئول»: جمع همه = تعداد اخطارها (هیچ ردیفی گم نمی‌شود) */
function makeProcessItems(rows){
  const items=PROC_ORDER.map(name=>({name,warnings:rows.filter(r=>hasRootCause(r)&&!isNotReceived(r)&&r.process===name).length}));
  items.push({name:"عدم دریافت قطعه",warnings:rows.filter(isNotReceived).length});
  const known=PROC_ORDER.reduce((a,name)=>a+rows.filter(r=>hasRootCause(r)&&!isNotReceived(r)&&r.process===name).length,0);
  items.push({name:"در حال بررسی",warnings:rows.length-known-rows.filter(isNotReceived).length});
  return items.filter(i=>i.warnings>0);
}
const HIDDEN_ROOTS=["اعلام نشده","عدم دریافت قطعه"];
const isHiddenRoot=name=>HIDDEN_ROOTS.indexOf(name)>=0;
function rootText(r){
  const name=r.rootCause||"";
  if(!name||isHiddenRoot(name)) return "—";
  return name;
}
function renderCoverage(rows){
  const el=$("#kpis"); if(!el) return;
  const total=rows.length;
  const sc=statusCounts(rows);
  const qty=sum(rows,"qty");
  const base=total||1;
  const products=uniq(rows,"product");
  const cctx=compareContext();
  const curYear=cctx.cur;
  const vs=(cur,prev)=>(curYear && cctx.prevRows.length)
    ? `<div class="vs">${deltaHtml(cur,prev,true)} <span class="muted">نسبت به ${faDigits(curYear-1)}</span></div>` : "";
  const vsRows=pred=>vs(cctx.curRows.filter(pred).length, cctx.prevRows.filter(pred).length);
  const items=[
    {name:"اخطار کیفی", value:fmt(total), sub:curYear?`سال ${faDigits(curYear)}: ${fmt(cctx.curRows.length)}`:"ردیف انتخاب‌شده", color:"#0b64c8", accent:"blue",
     extra:vs(cctx.curRows.length, cctx.prevRows.length), list:()=>rows, apply:null, title:"اخطارهای کیفی"},
    {name:"خاتمه‌یافته", value:fmt(sc.closed), sub:`${pct(sc.closed/base)} از کل`, color:"#0f9f8f", accent:"teal",
     extra:vsRows(isClosed), list:()=>rows.filter(isClosed), apply:()=>{state.status="closed";state.quickFilter="";}, title:"خاتمه‌یافته"},
    {name:"در حال بررسی", value:fmt(sc.inReview), sub:`${pct(sc.inReview/base)} از کل · ریشهٔ ثبت‌نشده`, color:"#c47f0a", accent:"amber",
     extra:vsRows(isInReview), list:()=>rows.filter(isInReview), apply:()=>{state.status="";state.quickFilter="";}, title:"در حال بررسی"},
    {name:"عدم دریافت قطعه", value:fmt(sc.notReceived), sub:`${pct(sc.notReceived/base)} از کل · از C-Plus`, color:"#7c3aed", accent:"violet",
     extra:vsRows(isNotReceived), list:()=>rows.filter(isNotReceived), apply:()=>{state.status="";state.quickFilter="notreceived";}, title:"عدم دریافت قطعه"},
    {name:"قطعات کلیم‌شده", value:fmt(qty), sub:`${fmt(products)} محصول · جمع تعداد قطعات`, color:"#0284c7", accent:"blue",
     extra:vs(sum(cctx.curRows,"qty"), sum(cctx.prevRows,"qty")), list:()=>rows, apply:null, title:"قطعات کلیم‌شده"}
  ];
  el.innerHTML=items.map((item,index)=>`<div class="kpi ${item.accent}" data-kpi="${index}" role="button" tabindex="0" title="نمایش ریزش اطلاعات ${esc(item.name)}">
    <div class="label"><span class="cdot" style="background:${item.color}"></span>${esc(item.name)}</div>
    <div class="value">${item.value}</div>
    <div class="sub">${esc(item.sub)}</div>
    ${item.extra}
  </div>`).join("");
  $$("#kpis [data-kpi]").forEach(card=>{
    const item=items[Number(card.dataset.kpi)];
    const fire=()=>openBreakdown(item.title,item.sub,item.list(),{apply:item.apply||undefined});
    card.addEventListener("click",fire);
    card.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();fire();}});
  });
  const note=$("#coverage-note");
  if(note) note.innerHTML=`سه گروه بدون هم‌پوشانی: <b>خاتمه‌یافته ${fmt(sc.closed)}</b> + <b>در حال بررسی ${fmt(sc.inReview)}</b> + <b>عدم دریافت قطعه ${fmt(sc.notReceived)}</b> = <b>${fmt(total)}</b> اخطار · روی هر کاشی بزنید تا ریزش اطلاعات همان گروه باز شود.`;
}
function rootRows(rows){
  const map=new Map();
  rows.forEach(r=>{
    const name=r.rootCause||"اعلام نشده";
    if(!map.has(name)) map.set(name,{name,warnings:0,products:new Set(),open:0,qty:0});
    const item=map.get(name);
    item.warnings+=1; item.open+=r.open?1:0; item.qty+=Number(r.qty||0); item.products.add(r.product);
  });
  return Array.from(map.values()).map(i=>({...i,products:i.products.size})).sort((a,b)=>b.warnings-a.warnings);
}
function paretoRows(rows){
  const map=new Map();
  rows.forEach(r=>{
    const name=r.analysisPart||"نامشخص";
    if(!map.has(name)) map.set(name,{name,warnings:0,products:new Set(),groups:new Set(),open:0});
    const item=map.get(name);
    item.warnings+=1; item.open+=r.open?1:0;
    item.products.add(r.product);
    if(r.groupPath) item.groups.add(r.groupPath.split(" / ")[0]);
  });
  const total=rows.length||1;
  let cumulative=0;
  return Array.from(map.values()).map(i=>({...i,products:i.products.size,groups:i.groups.size}))
    .sort((a,b)=>b.warnings-a.warnings || a.name.localeCompare(b.name,"fa"))
    .map((item,index)=>{
      cumulative+=item.warnings;
      return {...item,rank:index+1,share:item.warnings/total,cum:cumulative/total};
    });
}
function repeatRows(rows){
  const map=new Map();
  rows.forEach(r=>{
    if(Number(r.defectRepeat||0)<2) return;
    const name=r.defect||"نامشخص";
    if(!map.has(name)) map.set(name,{name,warnings:0,maxRepeat:0,products:new Set(),open:0});
    const item=map.get(name);
    item.warnings+=1; item.open+=r.open?1:0;
    item.maxRepeat=Math.max(item.maxRepeat,Number(r.defectRepeat||0));
    item.products.add(r.product);
  });
  return Array.from(map.values()).map(i=>({...i,products:i.products.size}))
    .sort((a,b)=>b.maxRepeat-a.maxRepeat || b.warnings-a.warnings);
}
const shorten=(v,n)=>{const t=String(v==null?"":v);return t.length>n?t.slice(0,n)+"…":t;};
function drillBars(items,color,valueKey="warnings"){
  if(!items||!items.length) return '<div class="drill-empty">داده‌ای برای نمایش نیست</div>';
  const max=Math.max(1,...items.map(i=>Number(i[valueKey]||0)));
  return items.map(i=>`<div class="bar-row"><div class="label" title="${esc(i.name)}">${esc(i.name)}</div>
    <div class="track"><div class="fill" style="width:${Number(i[valueKey]||0)/max*100}%;background:${color}"></div></div>
    <div class="val">${fmt(i[valueKey]||0)}</div></div>`).join("");
}
function openBreakdown(title,subtitle,rows,opts){
  opts=opts||{};
  rows=rows||[];
  const box=$(".modal-box"); if(box) box.scrollTop=0;
  const total=rows.length;
  const sc=statusCounts(rows);
  const qty=sum(rows,"qty");
  const products=new Set(rows.map(r=>r.product)).size;
  const roots=rootRows(rows).filter(i=>!isHiddenRoot(i.name)).slice(0,7);
  const isPartMode=opts.mode==="part";
  const parts=isPartMode
    ? groupAgg(rows.map(r=>({...r,partGroup:(r.groupPath||"نامشخص").split(" / ")[0]})),"partGroup").slice(0,7)
    : paretoRows(rows).filter(i=>i.name!=="نامشخص").slice(0,7);
  const defects=defectRows(rows).slice(0,7);
  const list=rows.slice().sort(byPriority).slice(0,40);
  $("#modal-title").textContent=title;
  $("#modal-body").innerHTML=`
    <div class="drill-hero">
      <div class="drill-kicker">ریزش اطلاعات</div>
      <div class="drill-title">${esc(title)}</div>
      <div class="drill-sub">${esc(subtitle||"")}</div>
      <div class="drill-stats">
        ${[["اخطار",fmt(total)],["خاتمه‌یافته",fmt(sc.closed)],["در حال بررسی",fmt(sc.inReview)],["عدم دریافت قطعه",fmt(sc.notReceived)],["قطعات کلیم‌شده",fmt(qty)]]
          .map(([l,v])=>`<div class="drill-stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("")}
      </div>
    </div>
    <div class="drill-grid">
      <div class="drill-card"><h4>ریشهٔ ایراد</h4>${drillBars(roots,"#0b64c8")}</div>
      <div class="drill-card"><h4>${isPartMode?"گروه محصول این قطعه":"قطعه در تحلیل (پارتو)"}</h4>${drillBars(parts,"#0f9f8f",isPartMode?"warnings":"warnings")}</div>
    </div>
    <div class="drill-grid">
      <div class="drill-card"><h4>پرتکرارترین ایراد مشتری</h4>${drillBars(defects,"#d92d5c")}</div>
      <div class="drill-card"><h4>وضعیت اخطارها</h4>${drillBars([
        {name:"خاتمه‌یافته",warnings:sc.closed},
        {name:"در حال بررسی",warnings:sc.inReview},
        {name:"عدم دریافت قطعه",warnings:sc.notReceived}
      ].filter(i=>i.warnings>0),"#7c3aed")}</div>
    </div>
    <div class="drill-card">
      <h4>ردیف‌های همین گروه (${fmt(Math.min(40,total))} از ${fmt(total)}) — برای دیدن پروندهٔ اخطار کلیک کنید</h4>
      ${list.length?`<div class="table-wrap drill-table" style="max-height:360px"><table><thead><tr>
        <th>سریال</th><th>تاریخ</th><th>شرح قطعه</th><th>ایراد مشتری</th><th>ریشه</th><th>وضعیت</th></tr></thead>
        <tbody>${list.map(r=>`<tr data-drill-id="${r.id}">
          <td class="num">${esc(faDigits(r.id))}</td><td class="tiny muted">${esc(faDigits(r.date))}</td>
          <td class="tiny" title="${esc(r.part)}">${esc(shorten(r.part,34))}</td>
          <td class="tiny" title="${esc(r.defect)}">${esc(shorten(r.defect,38)||"—")}</td>
          <td class="tiny">${rootText(r)==="—"?'<span class="muted">—</span>':`<span class="badge amber">${esc(rootText(r))}</span>`}</td>
          <td>${statusBadge(r)}</td></tr>`).join("")}</tbody></table></div>`:'<div class="drill-empty">ردیفی در این گروه نیست.</div>'}
    </div>`;
  $$("#modal-body [data-drill-id]").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.drillId))));
  const foot=$("#modal-foot");
  if(foot) foot.innerHTML=`<div class="muted tiny">${fmt(total)} اخطار در این گروه</div>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="btn primary" id="drill-list">نمایش در فهرست اخطارها</button>
      <button class="btn" id="drill-close">بستن</button>
    </div>`;
  const closeBtn=$("#drill-close");
  if(closeBtn) closeBtn.addEventListener("click",()=>$("#modal").classList.add("hidden"));
  const go=$("#drill-list");
  if(go) go.addEventListener("click",()=>{
    if(typeof opts.apply==="function") opts.apply();
    const statusSel=$("#f-status"); if(statusSel) statusSel.value=state.status||"";
    state.page=1; switchTab("warnings"); render();
    $("#modal").classList.add("hidden");
  });
  $("#modal").classList.remove("hidden");
}
/* ─────────────────── ریزش اطلاعات هر گروه (۶M، واحد، ایراد، …) ───────────────────
   برای هر میله در نمای کلی: پنجرهٔ ریزش با آمار، مقایسهٔ سال جاری/قبل،
   ترکیب وضعیت، قطعهٔ معیوب و فهرست همان اخطارها. */
/* مجموعهٔ مقایسه: همان فیلترها ولی بدون قید سال، تا وقتی «سال» فیلتر شده
   هم بتوانیم سال قبل را کنارش بگذاریم. اگر ماه هم فیلتر شده باشد، همان
   بازهٔ ماهانه در سال قبل اعمال می‌شود. */
function compareContext(){
  const all=applyFilters({skipYear:true});
  const counts=new Map();
  DATA.warnings.forEach(r=>{ const y=Number(r.year)||0; if(y) counts.set(y,(counts.get(y)||0)+1); });
  const years=Array.from(counts.keys()).sort((a,b)=>a-b);
  const cur=state.year?Number(state.year):(years[years.length-1]||0);
  const prev=cur?cur-1:0;
  const fromM=state.from?Number(state.from)%100:0;
  const toM=state.to?Number(state.to)%100:0;
  const inRange=r=>{
    if(!fromM&&!toM) return true;
    const m=Number(r.monthKey||0)%100;
    if(!m) return true;
    if(fromM&&m<fromM) return false;
    if(toM&&m>toM) return false;
    return true;
  };
  const curRows=all.filter(r=>Number(r.year)===cur && inRange(r));
  const prevRows=prev?all.filter(r=>Number(r.year)===prev && inRange(r)):[];
  return {cur, prev, all, curRows, prevRows, inRange};
}
function compareYears(){
  const counts=new Map();
  DATA.warnings.forEach(r=>{ const y=Number(r.year)||0; if(y) counts.set(y,(counts.get(y)||0)+1); });
  const years=Array.from(counts.keys()).sort((a,b)=>a-b);
  const cur=state.year?Number(state.year):(years[years.length-1]||0);
  return {cur, prev:cur?cur-1:0};
}
/* کارت مقایسهٔ سال جاری/سال قبل داخل ریزش؛ مستقل از فیلتر سال محاسبه می‌شود
   تا وقتی «سال» فیلتر شده هم سال قبل کنارش دیده شود. */
function drillCompareCard(match){
  const ctx=compareContext();
  if(!ctx.cur) return "";
  const curCount=ctx.curRows.filter(match).length;
  const prevCount=ctx.prevRows.filter(match).length;
  const max=Math.max(1,curCount,prevCount);
  const shareCur=ctx.curRows.length?curCount/ctx.curRows.length:0;
  const sharePrev=ctx.prevRows.length?prevCount/ctx.prevRows.length:0;
  return `<div class="drill-card" style="margin-bottom:12px">
    <h4>مقایسه با سال قبل ${state.year?`(سال ${faDigits(ctx.cur)} در برابر ${faDigits(ctx.prev)})`:""}</h4>
    <div class="cmp">
      <div class="cmp-side">
        <div class="cmp-l">سال ${faDigits(ctx.cur)}</div>
        <div class="cmp-v">${fmt(curCount)}</div>
        <div class="cmp-s">${pct(shareCur)} از ${fmt(ctx.curRows.length)} اخطار سال</div>
        <div class="track"><div class="fill" style="width:${curCount/max*100}%;background:#0b64c8"></div></div>
      </div>
      <div class="cmp-side">
        <div class="cmp-l">سال ${faDigits(ctx.prev)}</div>
        <div class="cmp-v">${fmt(prevCount)}</div>
        <div class="cmp-s">${pct(sharePrev)} از ${fmt(ctx.prevRows.length)} اخطار سال</div>
        <div class="track"><div class="fill" style="width:${prevCount/max*100}%;background:#9fb3c8"></div></div>
      </div>
    </div>
    <div class="cmp-delta">${deltaHtml(curCount,prevCount,true)} <span class="muted tiny">تغییر تعداد این گروه نسبت به سال قبل</span></div>
  </div>`;
}
function openGroupDrill(name,cfg){
  cfg=cfg||{};
  const base=applyFilters();
  const field=cfg.field||"m6";
  const value=cfg.value||name;
  const virtual={inreview:isInReview,notreceived:isNotReceived,noreview:r=>!r.hasReview};
  const match=virtual[field]?virtual[field]:r=>(r[field]||"نامشخص")===value;
  const rows=base.filter(match);
  const sc=statusCounts(rows);
  const qty=sum(rows,"qty");
  const products=new Set(rows.map(r=>r.product)).size;
  const roots=rootRows(rows).filter(i=>!isHiddenRoot(i.name)).slice(0,7);
  const parts=paretoRows(rows.filter(r=>!!r.analysisPart)).slice(0,7);
  const defects=defectRows(rows).slice(0,7);
  const statusItems=[
    {name:"خاتمه‌یافته",warnings:sc.closed},
    {name:"در حال بررسی",warnings:sc.inReview},
    {name:"عدم دریافت قطعه",warnings:sc.notReceived}
  ].filter(i=>i.warnings>0);
  const list=rows.slice().sort(byPriority).slice(0,40);
  $("#modal-title").textContent=cfg.title?`${cfg.title}: ${name}`:`ریزش اطلاعات: ${name}`;
  $("#modal-body").innerHTML=`
    <div class="drill-hero">
      <div class="drill-kicker">${esc(cfg.kicker||"ریزش اطلاعات")}</div>
      <div class="drill-title">${esc(name)}</div>
      <div class="drill-sub">${esc(cfg.subtitle||"")}${state.year?` · سال ${faDigits(state.year)}`:""}</div>
      <div class="drill-stats">
        ${[["اخطار",fmt(rows.length)],["خاتمه‌یافته",fmt(sc.closed)],["در حال بررسی",fmt(sc.inReview)],["عدم دریافت قطعه",fmt(sc.notReceived)],["قطعه معیوب",fmt(qty)]]
          .map(([l,v])=>`<div class="drill-stat"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("")}
      </div>
    </div>
    ${drillCompareCard(match)}
    <div class="drill-grid">
      <div class="drill-card"><h4>ریشهٔ ایراد</h4>${drillBars(roots,"#0b64c8")}</div>
      <div class="drill-card"><h4>قطعه در تحلیل (پارتو)</h4>${drillBars(parts,"#0e7f9a")}</div>
    </div>
    <div class="drill-grid">
      <div class="drill-card"><h4>پرتکرارترین ایراد مشتری</h4>${drillBars(defects,"#d92d5c")}</div>
      <div class="drill-card"><h4>وضعیت اخطارها</h4>${drillBars(statusItems,"#1e4fd8")}</div>
    </div>
    <div class="drill-card">
      <h4>ردیف‌های همین گروه (${fmt(Math.min(40,rows.length))} از ${fmt(rows.length)}) — برای پروندهٔ اخطار کلیک کنید</h4>
      ${list.length?`<div class="table-wrap drill-table" style="max-height:340px"><table><thead><tr>
        <th>سریال</th><th>تاریخ</th><th>شرح قطعه</th><th>ایراد مشتری</th><th>ریشه</th><th>وضعیت</th></tr></thead>
        <tbody>${list.map(r=>`<tr data-drill-id="${r.id}">
          <td class="num">${esc(faDigits(r.id))}</td><td class="tiny muted">${esc(faDigits(r.date))}</td>
          <td class="tiny" title="${esc(r.part)}">${esc(shorten(r.part,32))}</td>
          <td class="tiny" title="${esc(r.defect)}">${esc(shorten(r.defect,34)||"—")}</td>
          <td class="tiny">${rootText(r)==="—"?'<span class="muted">—</span>':`<span class="badge amber">${esc(rootText(r))}</span>`}</td>
          <td>${statusBadge(r)}</td></tr>`).join("")}</tbody></table></div>`:'<div class="drill-empty">ردیفی در این گروه نیست.</div>'}
    </div>`;
  $$("#modal-body [data-drill-id]").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.drillId))));
  const foot=$("#modal-foot");
  if(foot) foot.innerHTML=`<div class="muted tiny">${fmt(rows.length)} اخطار · ${cfg.unit||""}</div>
    <div style="display:flex;gap:8px;align-items:center">
      ${cfg.apply?'<button class="btn primary" id="drill-list">نمایش در فهرست اخطارها</button>':""}
      <button class="btn" id="drill-close">بستن</button>
    </div>`;
  const closeBtn=$("#drill-close");
  if(closeBtn) closeBtn.addEventListener("click",()=>$("#modal").classList.add("hidden"));
  const go=$("#drill-list");
  if(go) go.addEventListener("click",()=>{
    cfg.apply();
    state.page=1; switchTab("warnings"); render();
    $("#modal").classList.add("hidden");
  });
  $("#modal").classList.remove("hidden");
}
/* گزینه‌های ریزش برای هر میلهٔ نمای کلی */
const BAR_DRILL = {
  root:  {title:"ریشهٔ ایراد", field:"rootCause", kicker:"ریزش اطلاعات · ریشهٔ ایراد",
          subtitle:"همهٔ اخطارهایی که متنشان این ریشه را نشان می‌دهد",
          apply:name=>{state.root=name; const sel=$("#f-root"); if(sel) sel.value=name;}},
  part:  {title:"قطعه در تحلیل", field:"analysisPart", kicker:"ریزش اطلاعات · قطعهٔ معیوب",
          subtitle:"قطعه‌ای که در «آنالیز علت ایراد» برگهٔ بررسی نام برده شده است",
          apply:name=>{state.rootPart=name; const sel=$("#f-rootpart"); if(sel) sel.value=name;}},
  defect:{title:"ایراد اعلام‌شده", field:"defectGroup", kicker:"ریزش اطلاعات · ایراد مشتری",
          subtitle:"گروه ایرادی که مشتری در «توضیحات» اعلام کرده است"},
  make:  {title:"واحد مسئول", field:"make", kicker:"ریزش اطلاعات · واحد مسئول",
          subtitle:"گروه ساخت (واحد سازنده/مسئول) همین اخطارها", apply:name=>{state.make=name;}},
  process:{title:"فرآیند مسئول", field:"process", kicker:"ریزش اطلاعات · فرآیند مسئول",
          subtitle:"از ستون «منشاء ایراد» برگهٔ بررسی (C-Plus)", apply:name=>{state.process=name;}},
  inreview:{title:"در حال بررسی", field:"__status", kicker:"ریزش اطلاعات · در حال بررسی",
          subtitle:"ریشهٔ ایراد (منشاء ایراد برگهٔ بررسی) برایشان ثبت نشده است"},
  notreceived:{title:"عدم دریافت قطعه", field:"__status", kicker:"ریزش اطلاعات · عدم دریافت قطعه",
          subtitle:"«آنالیز علت ایراد» برگهٔ بررسی = عدم دریافت قطعه"},
  noreview:{title:"بدون برگهٔ بررسی", field:"__status", kicker:"ریزش اطلاعات · بدون برگهٔ بررسی",
          subtitle:"این اخطارها در فایل C-Plus ردیف متناظر ندارند"},
  m6:    {title:"علت‌ها بر پایهٔ ۶M", field:"m6", kicker:"ریزش اطلاعات · ۶M",
          subtitle:"دستهٔ علت (مواد، روش، تجهیزات، نیروی انسانی، محیط، اندازه‌گیری) از برگهٔ بررسی",
          apply:name=>{state.m6=name;}}, 
  group: {title:"گروه محصول", field:"group", kicker:"ریزش اطلاعات · گروه محصول",
          subtitle:"همهٔ اخطارهای همین گروه محصول", apply:name=>{state.group=name; state.family=""; state.product="";}},
  family:{title:"خانواده محصول", field:"family", kicker:"ریزش اطلاعات · خانواده محصول",
          subtitle:"همهٔ اخطارهای همین خانواده", apply:name=>{state.family=name;}},
  product:{title:"محصول", field:"product", kicker:"ریزش اطلاعات · محصول",
          subtitle:"همهٔ اخطارهای همین محصول", apply:name=>{state.product=name;}}
};
function barClick(kind){
  return name=>{
    const base=BAR_DRILL[kind]||{title:kind,field:kind};
    const cfg=Object.assign({}, base);
    if(base.apply) cfg.apply=()=>base.apply(name);
    openGroupDrill(name,cfg);
  };
}
function goRoot(name){
  openGroupDrill(name, {title:"ریشهٔ ایراد", field:"rootCause", kicker:"ریزش اطلاعات · ریشهٔ ایراد",
    subtitle:"همهٔ اخطارهایی که متنشان این ریشه را نشان می‌دهد",
    apply:()=>{state.root=name;state.page=1;const sel=$("#f-root");if(sel)sel.value=name;}});
}
function goRootPart(name){
  openGroupDrill(name, {title:"قطعه در تحلیل", field:"analysisPart", kicker:"ریزش اطلاعات · قطعهٔ معیوب",
    subtitle:"قطعه‌ای که در «آنالیز علت ایراد» همین اخطارها نام برده شده است", mode:"part",
    apply:()=>{state.rootPart=name;state.page=1;const sel=$("#f-rootpart");if(sel)sel.value=name;}});
}
function goDefect(name){
  openGroupDrill(name, {title:"ایراد مشتری", field:"defect", kicker:"ریزش اطلاعات · ایراد مشتری",
    subtitle:"همهٔ اخطارهایی که همین ایراد برایشان ثبت شده است",
    apply:()=>{state.defect=name;state.page=1;}});
}
function goGroup(name){
  openGroupDrill(name, {title:"گروه محصول", field:"group", kicker:"ریزش اطلاعات · گروه محصول",
    subtitle:"همهٔ اخطارهای همین گروه محصول",
    apply:()=>{state.group=name;state.family="";state.product="";state.page=1;syncSelects();}});
}
function renderRootPanel(rows){
  const all=rootRows(rows);
  const known=all.filter(i=>!isHiddenRoot(i.name));
  const el=$("#root-bars");
  if(!el) return;
  if(!known.length){ empty(el,"ریشه‌ای در متن اخطارها پیدا نشد"); }
  else{
    const top=known.slice(0,9);
    const max=Math.max(1,...top.map(i=>i.warnings));
    el.innerHTML=top.map(i=>`<div class="bar-row clickable" data-root="${esc(i.name)}" title="نمایش اخطارهای ریشهٔ «${esc(i.name)}»">
      <div class="label">${esc(i.name)}</div><div class="track"><div class="fill" style="width:${i.warnings/max*100}%;background:#0e7f9a"></div></div><div class="val">${fmt(i.warnings)}</div></div>`).join("");
    $$("#root-bars [data-root]").forEach(row=>row.addEventListener("click",()=>goRoot(row.dataset.root)));
  }
  const note=$("#root-note");
  if(note) note.innerHTML=known.length
    ? `«علت اعلام‌نشده» و «قطعه دریافت‌نشده» در نمودار نیامده‌اند؛ شمارشان فقط یک‌بار در نوار بالای صفحه آمده است.`
    : `متن اخطارها علت مشخصی ندارد؛ ریشه فقط از «توضیحات»/«شرح منشا»/«آنالیز علت» خوانده می‌شود.`;
}
function renderPareto(rows){
  const items=paretoRows(rows.filter(r=>!!r.analysisPart));
  const el=$("#rootpart-bars");
  if(!el) return;
  if(!items.length){ empty(el,"قطعهٔ ریزی برای پارتو پیدا نشد"); }
  else{
    const top=items.slice(0,9);
    const max=Math.max(1,...top.map(i=>i.warnings));
    el.innerHTML=top.map(i=>`<div class="bar-row clickable" data-part="${esc(i.name)}" title="نمایش اخطارهای قطعهٔ «${esc(i.name)}»">
      <div class="label" title="${esc(i.name)}">${esc(i.name)}</div><div class="track"><div class="fill" style="width:${i.warnings/max*100}%;background:#0891b2"></div></div><div class="val">${fmt(i.warnings)}</div></div>`).join("");
    $$("#rootpart-bars [data-part]").forEach(row=>row.addEventListener("click",()=>goRootPart(row.dataset.part)));
    const eighty=items.find(i=>i.cum>=0.8);
    const note=$("#pareto-note");
    const reviewedNamed=rows.filter(r=>!!r.analysisPart).length;
    if(note) note.innerHTML=`از ${fmt(reviewedNamed)} اخطار با «آنالیز علت ایراد»، ${fmt(items.length)} قطعه نام برده شده · ${eighty?`${fmt(eighty.rank)} قطعهٔ اول، ${pct(eighty.cum)} این تحلیل‌ها را می‌سازند`:`همهٔ قطعه‌ها`}`;
  }
  const q=(state.paretoQ||"").trim().toLowerCase();
  const list=q?items.filter(i=>i.name.toLowerCase().includes(q)):items;
  $("#pareto-count").textContent=`${fmt(Math.min(60,list.length))} از ${fmt(items.length)} قطعه · ${fmt(rows.length)} اخطار`;
  $("#pareto-table").innerHTML=`<thead><tr><th>#</th><th>قطعه در تحلیل</th><th>اخطار</th><th>سهم</th><th>سهم تجمعی</th><th>گروه‌ها</th><th>محصولات</th><th>باز</th><th></th></tr></thead>
    <tbody>${list.slice(0,60).map(i=>`<tr class="clickable" data-part="${esc(i.name)}">
      <td class="num muted">${fmt(i.rank)}</td><td><b>${esc(i.name)}</b></td>
      <td class="num">${fmt(i.warnings)}</td><td class="num muted">${pct(i.share)}</td>
      <td class="num">${pct(i.cum)}</td><td class="num">${fmt(i.groups)}</td>
      <td class="num">${fmt(i.products)}</td><td class="num">${fmt(i.open)}</td>
      <td><button class="btn" data-open-part="${esc(i.name)}" style="padding:4px 9px">اخطارها</button></td></tr>`).join("")}</tbody>`;
  $$("#pareto-table [data-part]").forEach(row=>row.addEventListener("click",()=>goRootPart(row.dataset.part)));
}
function renderRepeatPanel(rows){
  const items=repeatRows(rows);
  const el=$("#repeat-table");
  if(!el) return;
  if(!items.length){ el.innerHTML='<tbody><tr><td class="muted tiny">ایراد تکراردار (بیش از یک بار در یک محصول) در این فیلتر نیست.</td></tr></tbody>'; return; }
  el.innerHTML=`<thead><tr><th>ایراد مشتری</th><th>بیشترین تکرار</th><th>اخطار</th></tr></thead>
    <tbody>${items.slice(0,25).map(i=>`<tr class="clickable" data-defect="${esc(i.name)}" title="نمایش اخطارهای «${esc(i.name)}»">
      <td class="tiny">${esc(i.name)}</td><td class="num"><span class="badge red">×${fmt(i.maxRepeat)}</span></td><td class="num">${fmt(i.warnings)}</td></tr>`).join("")}</tbody>`;
  $$("#repeat-table [data-defect]").forEach(row=>row.addEventListener("click",()=>goDefect(row.dataset.defect)));
}
function renderActiveFilters(){
  const el=$("#warnings-active-filters"); if(!el) return;
  const chips=[];
  if(state.root) chips.push(`<span class="fchip">ریشه: ${esc(state.root)}<button data-clear="root" title="حذف فیلتر">×</button></span>`);
  if(state.rootPart) chips.push(`<span class="fchip">قطعهٔ تحلیل: ${esc(state.rootPart)}<button data-clear="rootPart" title="حذف فیلتر">×</button></span>`);
  if(state.defect) chips.push(`<span class="fchip">ایراد مشتری: ${esc(state.defect)}<button data-clear="defect" title="حذف فیلتر">×</button></span>`);
  if(state.m6) chips.push(`<span class="fchip">۶M: ${esc(state.m6)}<button data-clear="m6" title="حذف فیلتر">×</button></span>`);
  if(state.make) chips.push(`<span class="fchip">واحد مسئول: ${esc(state.make)}<button data-clear="make" title="حذف فیلتر">×</button></span>`);
  if(state.process) chips.push(`<span class="fchip">فرآیند مسئول: ${esc(state.process)}<button data-clear="process" title="حذف فیلتر">×</button></span>`);
  if(state.quickFilter==="notreceived") chips.push(`<span class="fchip">فقط «عدم دریافت قطعه»<button data-clear="quickFilter" title="حذف فیلتر">×</button></span>`);
  if(!chips.length){ el.innerHTML=""; return; }
  el.innerHTML=chips.join("")+`<button class="fchip clear" id="clear-linked" style="cursor:pointer">پاک‌کردن فیلترهای لینک‌شده</button>`;
  $$("#warnings-active-filters [data-clear]").forEach(btn=>btn.addEventListener("click",()=>{
    const key=btn.dataset.clear;
    state[key]="";
    const map={root:"#f-root",rootPart:"#f-rootpart"};
    if(map[key]){ const sel=$(map[key]); if(sel) sel.value=""; }
    if(key==="quickFilter"){ state.status=""; const s=$("#f-status"); if(s) s.value=""; }
    state.page=1; render();
  }));
  const clear=$("#clear-linked");
  if(clear) clear.addEventListener("click",()=>{
    state.root=""; state.rootPart=""; state.defect=""; state.quickFilter=""; state.status=""; state.page=1;
    $("#f-root").value=""; $("#f-rootpart").value=""; $("#f-status").value="";
    render();
  });
}
function renderQualityKpis(rows){
  const total=rows.length||1;
  const inScope=rows.filter(r=>r.inScope).length, inCatalog=rows.filter(r=>r.inCatalog).length;
  const review=rows.filter(r=>r.review).length, noMatch=rows.filter(r=>r.method==="بدون تطابق").length;
  const invalid=rows.filter(r=>!r.monthKey).length, mismatch=rows.filter(r=>r.mismatch).length;
  const cards=[
    ["در دامنه گروه‌بندی",pct(inScope/total),`${fmt(inScope)} ردیف`,""],
    ["در فایل گروه‌بندی",pct(inCatalog/total),`${fmt(inCatalog)} ردیف`,"blue"],
    ["نیاز به بازبینی",pct(review/total),`${fmt(review)} ردیف`,"amber"],
    ["بدون تطبیق",pct(noMatch/total),`${fmt(noMatch)} ردیف`,"rose"],
    ["تاریخ نامعتبر",fmt(invalid),"ردیف","slate"],
    ["قطعات معیوب > ۱۰۰۰",fmt(rows.filter(r=>r.qty>1000).length),"ردیف","amber"],
    ["مغایرت خودرو",fmt(mismatch),"ردیف","violet"],
    ["شماره فنی یکتا",fmt(uniq(rows,"tech")),"شماره",""],
    ["محصولات",fmt(uniq(rows,"product")),"محصول","blue"]
  ];
  $("#quality-kpis").innerHTML=cards.map(([l,v,s,c])=>`<div class="kpi ${c}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");
}

function renderDonut(el,rows){
  const items=groupAgg(rows,"group");
  if(!items.length){ empty(el); return; }
  const total=items.reduce((a,b)=>a+b.warnings,0);
  const size=220, r=82, c=110, stroke=24, circ=2*Math.PI*r;
  let offset=0;
  let arcs="";
  items.forEach(item=>{
    const frac=item.warnings/total;
    const len=circ*frac;
    arcs+=`<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${color(item.name)}" stroke-width="${stroke}" stroke-dasharray="${len} ${circ-len}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${c} ${c})"><title>${esc(gLabel(item.name))}: ${fmt(item.warnings)} اخطار (${pct(frac)})</title></circle>`;
    offset+=len;
  });
  const legend=items.map(item=>`<div class="legend-item" data-group="${esc(item.name)}"><span class="dot" style="background:${color(item.name)}"></span><span class="name" title="${esc(item.name)}">${esc(gLabel(item.name))}</span><span class="num">${fmt(item.warnings)} · ${pct(item.warnings/total)}</span></div>`).join("");
  el.innerHTML=`<div class="donut-wrap"><svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">
    <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="#eef2f7" stroke-width="${stroke}"></circle>${arcs}
    <text x="${c}" y="${c-6}" text-anchor="middle" font-size="22" font-weight="800" fill="#0f172a">${fmt(total)}</text>
    <text x="${c}" y="${c+16}" text-anchor="middle" font-size="10" fill="#64748b">اخطار</text>
  </svg><div class="donut-legend">${legend}</div></div>`;
  $$(".legend-item",el).forEach(item=>item.addEventListener("click",()=>goGroup(item.dataset.group)));
}

/* ───────────────────────── روند اخطارها با مقایسهٔ سال قبل ─────────────────────────
   حالت «ماهانه»: ۱۲ ماه سال جاری در برابر همان ماه‌های سال قبل (خط چین).
   حالت «سالانه»: همهٔ سال‌ها به‌صورت ستون/خط + ستون‌های سال قبل.
   مبنای مقایسه، ردیف‌های همان فیلترهاست (نه کل داده). */
function trendYears(rows){
  const years=Array.from(new Set(rows.map(r=>Number(r.year)||0).filter(Boolean))).sort((a,b)=>a-b);
  return years;
}
function trendMonthCounts(rows,year){
  const out=new Array(12).fill(0);
  rows.forEach(r=>{ if(Number(r.year)===Number(year) && r.monthKey){ const m=Number(r.monthKey)%100; if(m>=1&&m<=12) out[m-1]+=1; } });
  return out;
}
function trendSum(arr){ return arr.reduce((a,b)=>a+b,0); }
function deltaHtml(cur,prev,invert){
  if(prev===null||prev===undefined) return `<span class="flat">—</span>`;
  if(!prev) return cur? `<span class="${invert?"down":"up"}">جدید</span>` : `<span class="flat">۰</span>`;
  const d=(cur-prev)/prev*100;
  if(Math.abs(d)<0.5) return `<span class="flat">۰٪</span>`;
  const up=d>0, cls=invert?(up?"down":"up"):(up?"up":"down");
  const shown = Math.abs(d).toLocaleString("fa-IR",{maximumFractionDigits:1});
  return `<span class="${cls}">${up?"▲":"▼"} ${shown}٪</span>`;
}
function renderTrendLegacy(el,rows){ /* نگه‌داشته‌شده برای سازگاری؛ استفاده نمی‌شود */ }
function renderTrend(el,rows){
  const mode=state.trendMode||"month";
  const compare=state.trendCompare!==false;
  const ctx=compareContext();
  const curYear=ctx.cur, prevYear=ctx.prev;
  const names=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
  if(!rows.length){
    empty(el,"در بازهٔ انتخاب‌شده اخطاری وجود ندارد");
    if($("#trend-legend")) $("#trend-legend").innerHTML="";
    if($("#trend-table")) $("#trend-table").innerHTML="";
    if($("#trend-kpis")) $("#trend-kpis").innerHTML="";
    return;
  }

  if(mode==="month"){
    const cur=trendMonthCounts(ctx.curRows,curYear);
    const prev=compare?trendMonthCounts(ctx.prevRows,prevYear):null;
    const W=880,H=280,pad={l:44,r:16,t:16,b:40};
    const iw=W-pad.l-pad.r, ih=H-pad.t-pad.b;
    const max=Math.max(1,...cur,...(prev||[0]));
    const x=i=>pad.l+(iw/(12-1))*i;
    const y=v=>pad.t+ih-(v/max)*ih;
    let grid="",labels="";
    for(let g=0;g<=4;g++){
      const yy=pad.t+ih-(g/4)*ih;
      grid+=`<line x1="${pad.l}" y1="${yy}" x2="${W-pad.r}" y2="${yy}" stroke="#eef3f9" stroke-width="1"/>`;
      grid+=`<text x="${pad.l-6}" y="${yy+4}" text-anchor="end" font-size="9" fill="#94a3b8">${fmt(Math.round(max*g/4))}</text>`;
    }
    names.forEach((n,i)=>labels+=`<text x="${x(i)}" y="${H-16}" text-anchor="middle" font-size="9" fill="#64748b">${esc(n)}</text>`);
    const curPts=cur.map((v,i)=>`${x(i)},${y(v)}`).join(" ");
    const prevPts=prev?prev.map((v,i)=>`${x(i)},${y(v)}`).join(" "):"";
    const curDots=cur.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="3.4" fill="#0b64c8"><title>${names[i]} ${faDigits(curYear)}: ${fmt(v)} اخطار</title></circle>`).join("");
    const prevDots=prev?prev.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="#fff" stroke="#8aa4c0" stroke-width="1.6"><title>${names[i]} ${faDigits(prevYear)}: ${fmt(v)} اخطار</title></circle>`).join(""):"";
    const curVals=cur.map((v,i)=>v?`<text x="${x(i)}" y="${y(v)-8}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0b64c8">${fmt(v)}</text>`:"").join("");
    el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img">
      <defs><linearGradient id="gradCur" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#0b64c8" stop-opacity=".16"/><stop offset="1" stop-color="#0b64c8" stop-opacity="0"/></linearGradient></defs>
      ${grid}
      ${prev?`<polyline points="${prevPts}" fill="none" stroke="#9fb3c8" stroke-width="2" stroke-dasharray="5 4"/>`:""}
      <polygon points="${pad.l},${pad.t+ih} ${curPts} ${x(11)},${pad.t+ih}" fill="url(#gradCur)"/>
      <polyline points="${curPts}" fill="none" stroke="#0b64c8" stroke-width="2.6"/>
      ${prevDots}${curDots}${curVals}${labels}
    </svg>`;
    const curTotal=trendSum(cur), prevTotal=prev?trendSum(prev):null;
    const lastMonth=cur.reduce((acc,v,i)=>v?i+1:acc,0)||12;
    const curUpto=trendSum(cur.slice(0,lastMonth));
    const prevUpto=prev?trendSum(prev.slice(0,lastMonth)):null;
    const legend=$("#trend-legend");
    if(legend){
      legend.innerHTML=`<span class="k"><span class="sw" style="background:#0b64c8"></span>سال ${faDigits(curYear)}${state.year?" (فیلتر سال)":""}</span>`+
        (compare?`<span class="k"><span class="sw dash"></span>سال ${faDigits(prevYear)}${state.year?" (سال قبل فیلتر)":""}</span>`:`<span class="muted">مقایسه خاموش است</span>`)+
        `<span class="muted tiny">مقایسه تا پایان ${esc(names[lastMonth-1]||"")}</span>`;
    }
    const kpiBox=$("#trend-kpis");
    if(kpiBox) kpiBox.innerHTML=`
        <div class="trend-kpi"><div class="l">اخطار سال ${faDigits(curYear)}</div><div class="v">${fmt(curTotal)}</div><div class="d">${deltaHtml(curTotal,prevTotal,true)} نسبت به سال قبل</div></div>
        <div class="trend-kpi"><div class="l">سال ${faDigits(prevYear)}</div><div class="v">${prevTotal===null?"—":fmt(prevTotal)}</div><div class="d flat">کل سال</div></div>
        <div class="trend-kpi"><div class="l">هم‌بازه تا ${esc(names[lastMonth-1]||"")}</div><div class="v">${fmt(curUpto)} <span class="muted tiny">/ ${prevUpto===null?"—":fmt(prevUpto)}</span></div><div class="d">${deltaHtml(curUpto,prevUpto,true)}</div></div>
        <div class="trend-kpi"><div class="l">اختلاف تا امروز</div><div class="v">${prevUpto===null?"—":fmt(curUpto-prevUpto)}</div><div class="d flat">اخطار</div></div>`;
    const table=$("#trend-table");
    if(table){
      const head=names.map(n=>`<th>${esc(n)}</th>`).join("");
      const rowCur=cur.map(v=>`<td>${fmt(v)}</td>`).join("");
      const rowPrev=prev?prev.map(v=>`<td>${fmt(v)}</td>`).join(""):"";
      const rowDiff=prev?cur.map((v,i)=>`<td>${v-(prev[i]||0)>0?"+":""}${fmt(v-(prev[i]||0))}</td>`).join(""):"";
      table.innerHTML=compare?`<table class="trend-table"><thead><tr><th class="lbl">ماه / سال</th>${head}<th>جمع</th></tr></thead><tbody>
          <tr class="cur"><td class="lbl">${faDigits(curYear)}</td>${rowCur}<td><b>${fmt(curTotal)}</b></td></tr>
          <tr class="prev"><td class="lbl">${faDigits(prevYear)}</td>${rowPrev}<td><b>${fmt(prevTotal||0)}</b></td></tr>
          <tr><td class="lbl">اختلاف</td>${rowDiff}<td><b>${fmt(curTotal-(prevTotal||0))}</b></td></tr>
        </tbody></table>`:"";
    }
    return;
  }

  // ── حالت سالانه: همهٔ سال‌ها از مجموعهٔ فیلترشده (بدون قید سال)
  const allRows=ctx.all;
  const years=trendYears(allRows);
  const counts=years.map(y=>allRows.filter(r=>Number(r.year)===y).length);
  const W=880,H=270,pad={l:46,r:16,t:16,b:38};
  const iw=W-pad.l-pad.r, ih=H-pad.t-pad.b;
  const max=Math.max(1,...counts);
  const step=years.length>1?iw/(years.length-1):0;
  const x=i=>pad.l+i*step;
  const y=v=>pad.t+ih-(v/max)*ih;
  let grid="",labels="";
  for(let g=0;g<=4;g++){
    const yy=pad.t+ih-(g/4)*ih;
    grid+=`<line x1="${pad.l}" y1="${yy}" x2="${W-pad.r}" y2="${yy}" stroke="#eef3f9"/>`;
    grid+=`<text x="${pad.l-6}" y="${yy+4}" text-anchor="end" font-size="9" fill="#94a3b8">${fmt(Math.round(max*g/4))}</text>`;
  }
  const stepLbl=Math.ceil(years.length/12);
  years.forEach((yr,i)=>{ if(i%stepLbl===0||i===years.length-1) labels+=`<text x="${x(i)}" y="${H-14}" text-anchor="middle" font-size="9" fill="#64748b">${faDigits(yr)}</text>`; });
  const bars=years.map((yr,i)=>{
    const bw=Math.max(6,Math.min(30,step*0.55));
    const isCur=yr===curYear;
    return `<rect x="${x(i)-bw/2}" y="${y(counts[i])}" width="${bw}" height="${pad.t+ih-y(counts[i])}" rx="2" fill="${isCur?"#0b64c8":"#9cc3e8"}"><title>${faDigits(yr)}: ${fmt(counts[i])} اخطار</title></rect>`;
  }).join("");
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img">${grid}${bars}${labels}</svg>`;
  const legend=$("#trend-legend");
  if(legend) legend.innerHTML=`<span class="k"><span class="sw" style="background:#0b64c8"></span>سال مبنا (${faDigits(curYear)})</span><span class="k"><span class="sw" style="background:#9cc3e8"></span>سال‌های دیگر</span>`;
  const thisYearCount=allRows.filter(r=>Number(r.year)===curYear).length;
  const lastYearCount=allRows.filter(r=>Number(r.year)===prevYear).length;
  const kpiBox=$("#trend-kpis");
  if(kpiBox) kpiBox.innerHTML=`
      <div class="trend-kpi"><div class="l">اخطار سال ${faDigits(curYear)}</div><div class="v">${fmt(thisYearCount)}</div><div class="d">${deltaHtml(thisYearCount,lastYearCount,true)} نسبت به سال قبل</div></div>
      <div class="trend-kpi"><div class="l">سال ${faDigits(prevYear)}</div><div class="v">${fmt(lastYearCount)}</div><div class="d flat">کل سال</div></div>
      <div class="trend-kpi"><div class="l">بیشترین سال</div><div class="v">${faDigits(years[counts.indexOf(Math.max(...counts))]||"—")}</div><div class="d flat">${fmt(Math.max(...counts))} اخطار</div></div>
      <div class="trend-kpi"><div class="l">میانگین سالانه</div><div class="v">${fmt(Math.round(counts.reduce((a,b)=>a+b,0)/counts.length))}</div><div class="d flat">${faDigits(years.length)} سال</div></div>`;
  const order=years.slice().reverse().slice(0,10);
  const table=$("#trend-table");
  if(table) table.innerHTML=`<table class="trend-table"><thead><tr><th class="lbl">سال</th>${order.map(yy=>`<th>${faDigits(yy)}</th>`).join("")}</tr></thead>
    <tbody><tr class="cur"><td class="lbl">اخطار</td>${order.map(yy=>`<td>${fmt(allRows.filter(r=>Number(r.year)===yy).length)}</td>`).join("")}</tr>
    <tr><td class="lbl">تغییر</td>${order.map((yy,i)=>{ if(i===order.length-1) return `<td>—</td>`; const now=allRows.filter(r=>Number(r.year)===yy).length, before=allRows.filter(r=>Number(r.year)===order[i+1]).length; return `<td>${deltaHtml(now,before,true)}</td>`; }).join("")}</tr></tbody></table>`;
}

function monthLabel(key){
  const m = DATA.warnings.find(r=>String(r.monthKey)===String(key));
  if(m) return m.month;
  const k = Number(key); const month = k%100; const year = Math.floor(k/100);
  const names = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
  return `${names[month-1]||""} ${year}`;
}

/* میله‌های افقی؛ با opts.click = «ریزش اطلاعات» همان گروه باز می‌شود و
   با opts.compare = تعداد سال قبل (خط‌چین پشت میله) و درصد تغییر نمایش داده می‌شود. */
function renderBars(el,items,valueKey="warnings",colorFn=null,labelFn=null,opts){
  opts=opts||{};
  if(!items||!items.length){ empty(el); return; }
  const max=Math.max(1,...items.map(i=>Math.max(Number(i[valueKey]||0), Number(i.prev||0))));
  el.innerHTML=items.map(item=>{
    const val=Number(item[valueKey]||0);
    const p=val/max*100;
    const pPrev=Math.max(0,Math.min(100,(Number(item.prev||0)/max)*100));
    const col=colorFn?colorFn(item):"#0e7f9a";
    const label=labelFn?labelFn(item):item.name;
    const clickable=typeof opts.click==="function";
    const prevBar=opts.compare?`<div class="fill prev" style="width:${pPrev}%" title="سال قبل: ${fmt(item.prev||0)}"></div>`:"";
    const delta=opts.compare&&item.prev!==undefined?`<span class="bar-delta">${deltaHtml(val,item.prev,true)}</span>`:"";
    return `<div class="bar-row${clickable?" clickable":""}" ${clickable?`data-bar="${esc(item.name)}" role="button" tabindex="0" title="ریزش اطلاعات ${esc(label)}"`:""}>
      <div class="label" title="${esc(label)}">${esc(label)}</div>
      <div class="track">${prevBar}<div class="fill" style="width:${p}%;background:${col}"></div></div>
      <div class="val">${fmt(val)}${delta}</div></div>`;
  }).join("");
  if(typeof opts.click==="function"){
    $$("[data-bar]",el).forEach(row=>{
      const fire=()=>opts.click(row.dataset.bar);
      row.addEventListener("click",fire);
      row.addEventListener("keydown",e=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); fire(); } });
    });
  }
}

const STAGE_COLORS = {
  "خاتمه يافته":"#0e7f9a",
  "اقدام ميان مدت":"#c47f0a",
  "اقدام كوتاه مدت":"#d92d5c",
  "تنظيم":"#7c3aed"
};
function stageName(s){ return s==="خاتمه يافته" ? "خاتمه‌یافته" : s || "نامشخص"; }

function renderStatusDonut(el, rows){
  if(!rows.length){ empty(el); return; }
  const sc=statusCounts(rows);
  const total = rows.length || 1;
  const groups=[
    ["خاتمه‌یافته",sc.closed,"#0e7f9a"],
    ["در حال بررسی",sc.inReview,"#c47f0a"],
    ["عدم دریافت قطعه",sc.notReceived,"#d92d5c"]
  ].filter(g=>g[1]>0);
  const size=190, r0=68, c=95, stroke=22, circ=2*Math.PI*r0;
  let offset=0;
  const arcs=groups.map(([name,value,color])=>{
    const len=circ*(value/total);
    const seg=`<circle cx="${c}" cy="${c}" r="${r0}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-dasharray="${len} ${circ-len}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${c} ${c})"><title>${esc(name)}: ${fmt(value)}</title></circle>`;
    offset+=len;
    return seg;
  }).join("");
  const legend = groups.map(([name,value,color])=>`<div class="legend-item" data-stage="${esc(name)}">
      <span class="dot" style="background:${color}"></span>
      <span class="name">${esc(name)}</span><span class="num">${fmt(value)} · ${pct(value/total)}</span></div>`).join("");
  el.innerHTML=`<div class="donut-wrap"><svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${c}" cy="${c}" r="${r0}" fill="none" stroke="#eef2f7" stroke-width="${stroke}"></circle>${arcs}
    <text x="${c}" y="${c-4}" text-anchor="middle" font-size="20" font-weight="800" fill="#0f172a">${fmt(total)}</text>
    <text x="${c}" y="${c+14}" text-anchor="middle" font-size="10" fill="#64748b">اخطار</text>
  </svg><div class="donut-legend">${legend}</div></div>`;
}

/* جزئیات وضعیت: سه گروه — خاتمه‌یافته، باز، عدم دریافت قطعه */
/* کارت ۶M در نمای کلی: اگر سال انتخاب‌شده علت ۶M ثبت‌شده نداشته باشد، جای
   نمودار خالی، وضعیت و پوشش داده توضیح داده می‌شود (بدون اختراع عدد). */
function renderM6Overview(rows, items, opts){
  const el=$("#ov-m6-bars");
  const note=$("#ov-m6-note");
  const total=rows.length||1;
  const unknown=rows.filter(r=>!r.m6 || r.m6==="نامشخص").length;
  if(items && items.length){
    renderBars(el, items, "warnings", ()=> "#1e4fd8", null, opts);
    if(note) note.innerHTML=`${fmt(total-unknown)} از ${fmt(total)} اخطار (${pct((total-unknown)/total)}) علت ۶M ثبت‌شده دارند · ${fmt(unknown)} نامشخص (در نمودار نیامده)`;
    return;
  }
  el.innerHTML=`<div class="ov-empty">برای ${fmt(unknown)} اخطار این بازه، علت ۶M در برگهٔ بررسی ثبت نشده است.
    <div style="margin-top:8px"><button class="btn sm" id="m6-clear-year">نمایش ۶M در همهٔ سال‌ها</button></div></div>`;
  if(note) note.innerHTML=`۶M فقط برای اخطارهای دارای برگهٔ بررسی ثبت می‌شود؛ با برداشتن فیلتر سال، ۱۴۰۴ و ۱۴۰۵ دیده می‌شوند.`;
  const b=$("#m6-clear-year");
  if(b) b.addEventListener("click",()=>{
    state.year=""; state.from=""; state.to="";
    const sel=$("#f-year"); if(sel) sel.value="";
    refreshMonthSelects(); setTrendMode("year"); render();
  });
}

function renderStatusDetail(rows){
  const el=$("#status-detail"), total=$("#status-total");
  if(!el) return;
  const n=rows.length||1;
  const sc=statusCounts(rows);
  const closed=sc.closed, inReview=sc.inReview, notReceived=sc.notReceived;
  if(total) total.textContent=`${fmt(rows.length)} اخطار · ${fmt(closed)}+${fmt(inReview)}+${fmt(notReceived)}`;
  const items=[
    {name:"خاتمه‌یافته", value:closed, color:"#0e7f9a", hint:"رسیدگی تمام شده"},
    {name:"در حال بررسی", value:inReview, color:"#c47f0a", hint:"ریشهٔ ایراد ثبت نشده"},
    {name:"عدم دریافت قطعه", value:notReceived, color:"#7c3aed", hint:"از برگهٔ بررسی"}
  ];
  const max=Math.max(1,...items.map(i=>i.value));
  const bars=items.map(i=>`<div class="bar-row clickable" style="cursor:pointer" data-status="${esc(i.name)}" role="button" tabindex="0" title="ریزش اطلاعات ${esc(i.name)}">
      <div class="label">${esc(i.name)}<span class="muted tiny"> ${esc(i.hint)}</span></div>
      <div class="track"><div class="fill" style="width:${i.value/max*100}%;background:${i.color}"></div></div>
      <div class="val">${fmt(i.value)} · ${pct(i.value/n)}</div></div>`).join("");
  el.innerHTML=bars;
  $$("[data-status]",el).forEach(row=>{
    const openIt=()=>{
      const key=row.dataset.status;
      const base=applyFilters();
      if(key==="در حال بررسی"){
        openBreakdown("در حال بررسی","اخطارهایی که ریشهٔ ایراد (منشاء ایراد برگهٔ بررسی) برایشان ثبت نشده",base.filter(isInReview),
          {apply:()=>{state.quickFilter="";state.page=1;}});
        return;
      }
      if(key==="عدم دریافت قطعه"){
        openBreakdown("عدم دریافت قطعه","اخطارهایی که در «آنالیز علت ایراد» برگهٔ بررسی، عدم دریافت قطعه ثبت شده",base.filter(isNotReceived),
          {apply:()=>{state.quickFilter="notreceived";state.page=1;}});
        return;
      }
      openBreakdown("خاتمه‌یافته","اخطارهای رسیدگی‌شده",base.filter(isClosed),
        {apply:()=>{state.quickFilter="";state.status="closed";state.page=1;}});
    };
    row.addEventListener("click",openIt);
    row.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openIt();}});
  });
}

function renderActionBars(rows){
  // مراحل اقدام داخل کارت «جزئیات وضعیت» رسم می‌شوند؛ اگر کارت‌های مستقل وجود
  // داشتند (نسخه‌های قدیمی قالب) همان‌ها هم پر می‌شوند.
  const stItems = groupAgg(rows,"stAction").sort((a,b)=>b.warnings-a.warnings);
  const mtItems = groupAgg(rows,"mtAction").sort((a,b)=>b.warnings-a.warnings);
  const stCount=$("#st-count"), mtCount=$("#mt-count");
  if(stCount) stCount.textContent = `${fmt(rows.filter(r=>r.status==="اقدام كوتاه مدت").length)} اخطار در این مرحله`;
  if(mtCount) mtCount.textContent = `${fmt(rows.filter(r=>r.status==="اقدام ميان مدت").length)} اخطار در این مرحله`;
  const accentOk="#0e7f9a";
  if($("#st-bars")) renderBars($("#st-bars"), stItems.slice(0,6), "warnings", i=>i.name==="تاييد مشتري" ? accentOk : "#d92d5c");
  if($("#mt-bars")) renderBars($("#mt-bars"), mtItems.slice(0,6), "warnings", i=>i.name==="تاييد مشتري" ? accentOk : (i.name==="غيرضروري" ? "#94a3b8" : "#c47f0a"));
}

function renderReviewKpis(rows){
  const reviewed = rows.filter(r=>r.hasReview);
  const ready = reviewed.filter(r=>r.cause).length;
  const withAction = reviewed.filter(r=>r.action).length;
  const cards=[
    ["برگه بررسی", fmt(reviewed.length), `از ${fmt(rows.length)} اخطار`, ""],
    ["پوشش بررسی", pct(rows.length?reviewed.length/rows.length:0), "درصد اخطارهای بررسی‌شده", "blue"],
    ["دارای آنالیز علت", fmt(ready), "برگهٔ آمادهٔ تأیید", "amber"],
    ["دارای اقدام اصلاحی", fmt(withAction), "برگه با اقدام ثبت‌شده", "violet"]
  ];
  $("#review-kpis").innerHTML=cards.map(([l,v,s,c])=>`<div class="kpi ${c}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");
}

function reviewRows(rows){
  const q = state.reviewQ.trim().toLowerCase();
  let items = rows.filter(r=>r.hasReview);
  if(q) items = items.filter(r=>[r.id,r.part,r.cause,r.action,r.reviewOrigin,r.product,r.claimNo].join(" ").toLowerCase().includes(q));
  return items;
}

function renderReviewLinkNote(rows){
  const el=$("#review-link-note"); if(!el) return;
  const sources=DATA.meta.sources||{};
  const reviewed=rows.filter(r=>r.hasReview).length;
  const total=rows.length||1;
  const unmatched=(DATA.unmatchedReview||[]).length;
  el.innerHTML=`<b>برگهٔ بررسی، بخشی از خود اخطار است:</b> هر برگه از فایل <b>${esc(sources.review||"C_Plus")}</b> با کلید <b>شماره اخطار</b> به همان ردیف فهرست اخطارها متصل شده است؛ دادهٔ جداگانه‌ای نیست.
    از <b>${fmt(total)}</b> اخطار فیلترشده، <b>${fmt(reviewed)}</b> برگهٔ بررسی متصل دارند (${pct(reviewed/total)}).
    ${unmatched?`<span class="muted tiny">${fmt(unmatched)} برگه در فایل مشتری شماره اخطار متناظر ندارد و در «کیفیت تطبیق» فهرست شده است.</span>`:""}
    <div style="margin-top:8px;display:flex;gap:14px;flex-wrap:wrap;align-items:center">
      <button class="wm-link" id="review-to-warnings">نمایش همین اخطارها در فهرست اخطارها ←</button>
      <span class="muted tiny">روی هر ردیف کلیک کنید تا پروندهٔ همان اخطار با بخش «برگهٔ بررسی مشتری» باز شود.</span>
    </div>`;
  const jump=$("#review-to-warnings");
  if(jump) jump.addEventListener("click",()=>{
    state.review="yes"; state.page=1;
    const sel=$("#f-review"); if(sel) sel.value="yes";
    switchTab("warnings"); render();
  });
}
function renderReviews(rows){
  renderReviewKpis(rows);
  renderReviewLinkNote(rows);
  const reviewed = rows.filter(r=>r.hasReview);
  const origins = groupAgg(reviewed,"reviewOrigin").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#origin-bars"), origins.slice(0,10), "warnings", ()=>"#7c3aed", i=>i.name||"ثبت نشده");
  const cats = groupAgg(reviewed,"reviewCategory").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#category-bars"), cats.slice(0,10), "warnings", ()=>"#0891b2", i=>i.name||"ثبت نشده");

  const items = reviewRows(rows);
  currentReviews = items;
  $("#review-count").textContent = `${fmt(items.length)} برگه`;
  const pages = Math.max(1, Math.ceil(items.length/state.pageSize));
  if(state.page>pages) state.page=pages;
  const start=(state.page-1)*state.pageSize;
  const page = items.slice(start, start+state.pageSize);
  $("#reviews-table").innerHTML=`<thead><tr>
    <th>شماره اخطار</th><th>تاریخ</th><th>خودرو</th><th>شرح قطعه</th><th>محصول</th><th>آنالیز علت ایراد</th><th>اقدام اصلاحی</th><th>منشاء</th><th>کلیم</th><th>فرم 8D</th><th>وضعیت</th><th></th></tr></thead>
    <tbody>${page.map(r=>`<tr class="clickable" data-id="${r.id}">
      <td class="num"><b>${esc(faDigits(r.id))}</b></td><td class="tiny">${esc(faDigits(r.date))}</td><td class="tiny">${esc(r.car)}</td>
      <td class="tiny" title="${esc(r.part)}">${esc(r.part.length>40?r.part.slice(0,40)+"…":r.part)}</td>
      <td class="tiny">${esc(r.product)}</td>
      <td class="tiny" title="${esc(r.cause)}">${esc(r.cause? (r.cause.length>44?r.cause.slice(0,44)+"…":r.cause) : "—")}</td>
      <td class="tiny" title="${esc(r.action)}">${esc(r.action? (r.action.length>34?r.action.slice(0,34)+"…":r.action) : "—")}</td>
      <td class="tiny">${esc(r.reviewOrigin||"—")}</td>
      <td class="num tiny">${esc(r.claimNo||"—")}</td>
      <td class="tiny">${esc(r.form8d)}</td>
      <td>${statusBadge(r)}</td>
      <td><button class="btn" style="padding:5px 9px">اخطار</button></td></tr>`).join("")}</tbody>`;
  $$("#reviews-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id),"review")));
  renderPager($("#reviews-pager"),items.length,state.page,state.pageSize,p=>{state.page=p;renderReviews(applyFilters());});
}

function renderGroupTable(rows){
  const items=groupAgg(rows,"group");
  const total=items.reduce((a,b)=>a+b.warnings,0)||1;
  const defTotal=items.reduce((a,b)=>a+b.qty,0)||1;
  $("#group-table").innerHTML=`<thead><tr>
    <th>گروه محصول</th><th>اخطار</th><th>سهم</th><th>قطعات معیوب</th><th>سهم قطعات</th><th>نمره منفی</th><th>محصولات</th><th>اخطار باز</th><th>گرید A</th></tr></thead>
    <tbody>${items.map(i=>`<tr class="clickable" data-group="${esc(i.name)}">
      <td><span class="group-pill"><span class="dot" style="background:${color(i.name)}"></span>${esc(gLabel(i.name))}</span></td>
      <td class="num">${fmt(i.warnings)}</td><td class="num muted">${pct(i.warnings/total)}</td>
      <td class="num">${fmt(i.qty)}</td><td class="num muted">${pct(i.qty/defTotal)}</td>
      <td class="num">${fmt(i.score)}</td><td class="num">${fmt(i.products)}</td>
      <td class="num">${fmt(i.open)}</td><td class="num">${fmt(i.gradeA)}</td></tr>`).join("")}</tbody>`;
  $$("#group-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>goGroup(tr.dataset.group)));
}
function renderGroupsTab(rows){
  renderDonut($("#groups-donut"),rows);
  renderBars($("#groups-qty"),groupAgg(rows,"group").sort((a,b)=>b.qty-a.qty).slice(0,12),"qty",i=>color(i.name),i=>gLabel(i.name));
  const items=groupAgg(rows,"group"); const total=items.reduce((a,b)=>a+b.warnings,0)||1; const defTotal=items.reduce((a,b)=>a+b.qty,0)||1;
  $("#groups-full").innerHTML=`<thead><tr><th>گروه محصول</th><th>اخطار</th><th>سهم اخطار</th><th>قطعات معیوب</th><th>سهم قطعات</th><th>نمره منفی</th><th>خانواده‌ها</th><th>محصولات</th><th>اخطار باز</th><th>گرید A</th></tr></thead>
  <tbody>${items.map(i=>`<tr><td><span class="group-pill"><span class="dot" style="background:${color(i.name)}"></span>${esc(gLabel(i.name))}</span></td>
    <td class="num">${fmt(i.warnings)}</td><td class="num muted">${pct(i.warnings/total)}</td><td class="num">${fmt(i.qty)}</td><td class="num muted">${pct(i.qty/defTotal)}</td>
    <td class="num">${fmt(i.score)}</td><td class="num">${fmt(i.families)}</td><td class="num">${fmt(i.products)}</td><td class="num">${fmt(i.open)}</td><td class="num">${fmt(i.gradeA)}</td></tr>`).join("")}</tbody>`;
}
function renderFamiliesTab(rows){
  const items=groupAgg(rows,"family").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#families-bars"),items.slice(0,14),"warnings",()=>"#0e7f9a",i=>i.name);
  renderBars($("#families-qty"),items.slice().sort((a,b)=>b.qty-a.qty).slice(0,14),"qty",()=>"#0891b2",i=>i.name);
  $("#families-table").innerHTML=`<thead><tr><th>خانواده محصول</th><th>گروه محصول</th><th>اخطار</th><th>قطعات معیوب</th><th>نمره منفی</th><th>محصولات</th><th>اخطار باز</th><th>نیاز به بازبینی</th></tr></thead>
  <tbody>${items.map(i=>{
    const sample=rows.find(r=>r.family===i.name)||{};
    return `<tr><td>${esc(i.name)}</td><td class="muted">${esc(gLabel(sample.group||""))}</td><td class="num">${fmt(i.warnings)}</td><td class="num">${fmt(i.qty)}</td><td class="num">${fmt(i.score)}</td><td class="num">${fmt(i.products)}</td><td class="num">${fmt(i.open)}</td><td class="num">${fmt(rows.filter(r=>r.family===i.name&&r.review).length)}</td></tr>`;
  }).join("")}</tbody>`;
}
function renderProductBars(rows){
  renderBars($("#product-bars"),groupAgg(rows,"product").sort((a,b)=>b.warnings-a.warnings).slice(0,10),"warnings",i=>color((rows.find(r=>r.product===i.name)||{}).group||"#0e7f9a"),i=>i.name);
}

function productRows(rows){
  const q=state.productQ.trim().toLowerCase();
  let items=groupAgg(rows,"product");
  items=items.map(i=>{
    const sample=rows.find(r=>r.product===i.name)||{};
    const month=DATA.products.find(p=>p["محصول"]===i.name && p["آخرین ماه"])?.["آخرین ماه"]||"";
    const inCatalog=rows.some(r=>r.product===i.name&&r.inCatalog);
    const inScope=rows.some(r=>r.product===i.name&&r.inScope);
    return {...i,group:sample.group,family:sample.family,inCatalog,inScope,catalogCode:sample.catalogCode||"",lastMonth:month,
      review:rows.filter(r=>r.product===i.name&&r.review).length};
  });
  if(q) items=items.filter(i=>[i.name,i.family,i.group,i.catalogCode].join(" ").toLowerCase().includes(q));
  const key=state.productSort.key, dir=state.productSort.dir;
  items.sort((a,b)=>(a[key]>b[key]?1:a[key]<b[key]?-1:0)*dir);
  return items;
}
function renderProductsTab(rows){
  const items=productRows(rows);
  currentProducts=items;
  $("#products-count").textContent=`${fmt(items.length)} محصول`;
  const pages=Math.max(1,Math.ceil(items.length/state.pageSize));
  if(state.page>pages) state.page=pages;
  const start=(state.page-1)*state.pageSize;
  const page=items.slice(start,start+state.pageSize);
  const arrow=k=>state.productSort.key===k?`<span class="muted">${state.productSort.dir<0?"▼":"▲"}</span>`:"";
  $("#products-table").innerHTML=`<thead><tr>
    <th class="sortable" data-sort="name">محصول ${arrow("name")}</th><th>خانواده</th><th>گروه</th><th>کد گروه</th><th>وضعیت</th>
    <th class="sortable" data-sort="warnings">اخطار ${arrow("warnings")}</th>
    <th class="sortable" data-sort="qty">قطعات معیوب ${arrow("qty")}</th>
    <th class="sortable" data-sort="score">نمره منفی ${arrow("score")}</th>
    <th>آخرین ماه</th><th>بازبینی</th></tr></thead>
    <tbody>${page.map(i=>`<tr class="clickable" data-product="${esc(i.name)}">
      <td><b>${esc(i.name)}</b></td><td class="muted">${esc(i.family)}</td>
      <td><span class="group-pill"><span class="dot" style="background:${color(i.group)}"></span>${esc(gLabel(i.group))}</span></td>
      <td class="muted tiny">${esc(i.catalogCode||"—")}</td><td>${i.inCatalog?'<span class="badge green">کاتالوگ</span>':(i.inScope?'<span class="badge slate">سایر</span>':'<span class="badge slate">خارج</span>')}</td>
      <td class="num">${fmt(i.warnings)}</td><td class="num">${fmt(i.qty)}</td><td class="num">${fmt(i.score)}</td>
      <td class="muted tiny">${esc(faDigits(i.lastMonth||"—"))}</td><td class="num">${i.review?`<span class="badge red">${fmt(i.review)}</span>`:""}</td></tr>`).join("")}</tbody>`;
  $$("#products-table th.sortable").forEach(th=>th.addEventListener("click",()=>{
    const key=th.dataset.sort; state.productSort={key,dir:state.productSort.key===key?-state.productSort.dir:-1}; renderProductsTab(applyFilters());
  }));
  $$("#products-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openProduct(tr.dataset.product)));
  renderPager($("#products-pager"),items.length,state.page,state.pageSize,p=>{state.page=p;renderProductsTab(applyFilters());});
}
function renderWarningsTab(rows){
  const q=state.warningQ.trim().toLowerCase();
  let items=(rows||[]).slice().sort(state.warningSort==="date"?byNewest:byPriority);
  if(q) items=items.filter(r=>haystack(r).includes(q));
  currentWarnings=items;
  renderPriorityNote();
  renderActiveFilters();
  const total=items.length, pages=Math.max(1,Math.ceil(total/state.pageSize));
  if(state.page>pages) state.page=pages;
  const start=(state.page-1)*state.pageSize;
  const page=items.slice(start,start+state.pageSize);
  $("#warnings-count").textContent=`${fmt(total)} ردیف · نمایش ${fmt(page.length)} ردیف`;
  $("#warnings-table").innerHTML=`<thead><tr>
    <th>سریال</th><th>تاریخ</th><th>خودرو</th><th>قطعه (گروه‌بندی)</th><th>ایراد مشتری</th><th>ریشه</th><th>شماره فنی</th><th>محصول راهکاران</th><th>خانواده</th><th>محصول</th><th>گروه</th><th>برنچ</th><th>گرید</th><th>وضعیت</th><th>اولویت</th><th>قطعات</th><th>نمره</th><th>تطبیق</th></tr></thead>
    <tbody>${page.map(r=>`<tr class="clickable" data-id="${r.id}">
      <td class="num">${esc(r.id)}</td><td class="muted tiny">${esc(faDigits(r.date))}</td><td class="tiny">${esc(r.car)}</td>
      <td class="tiny" title="شرح قطعه (مشتری): ${esc(r.part)}">
        <div style="font-weight:700;color:#1e293b">${esc(r.product||"—")}</div>
        <div class="muted" style="font-size:10px">${esc([r.family,r.group?gLabel(r.group):""].filter(Boolean).join(" · ")||"—")}</div>
      </td>
      <td class="tiny" title="${esc(r.defect)}">${esc(r.defect||"—")} ${r.defectRepeat>1?`<span class="badge red">×${fmt(r.defectRepeat)}</span>`:""}</td>
      <td class="tiny">${rootText(r)==="—"?'<span class="muted">—</span>':`<span class="badge amber">${esc(rootText(r))}</span>`}</td>
      <td class="tiny">${esc(r.tech||"—")}</td><td class="tiny" title="${esc(r.rahkaran)}">${esc(r.rahkaran.length>34?r.rahkaran.slice(0,34)+"…":r.rahkaran||"—")}</td>
      <td class="tiny">${esc(r.family)}</td><td class="tiny">${esc(r.product)}</td>
      <td class="tiny"><span class="group-pill"><span class="dot" style="background:${color(r.group)}"></span>${esc(gLabel(r.group))}</span></td>
      <td class="tiny">${esc(r.branch||"—")}</td>
      <td class="num">${esc(r.grade)}</td><td>${statusBadge(r)}</td><td class="tiny">${priorityBadge(r)}</td><td class="num">${fmt(r.qty)}</td><td class="num">${fmt(r.score)}</td>
      <td>${confBadge(r.confidence)} ${r.hasReview?`<button class="wm-link" data-review="${r.id}" title="باز کردن برگهٔ بررسی متصل به این اخطار">برگهٔ بررسی</button>`:reviewBadge(r)}</td></tr>`).join("")}</tbody>`;
  $$("#warnings-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id))));
  $$("#warnings-table [data-review]").forEach(btn=>btn.addEventListener("click",event=>{
    event.stopPropagation(); openWarning(Number(btn.dataset.review),"review");
  }));
  renderPager($("#warnings-pager"),total,state.page,state.pageSize,p=>{state.page=p;renderWarningsTab(applyFilters());});
}
function renderGroupingChecks(){
  const rows = DATA.groupingChecks || [];
  if(!rows.length){ empty($("#checks-table"),"همهٔ ردیف‌های بررسی‌شده با دستهٔ اعلامی مشتری هم‌خوان هستند"); return; }
  $("#checks-table").innerHTML=`<thead><tr><th>سریال</th><th>دسته اعلامی مشتری</th><th>شرح قطعه</th><th>خانواده فعلی</th><th>محصول فعلی</th><th>روش تطبیق</th></tr></thead>
    <tbody>${rows.map(r=>`<tr class="clickable" data-id="${esc(r["سریال اخطار"])}">
      <td class="num">${esc(r["سریال اخطار"])}</td><td>${esc(r["دسته اعلامی مشتری"])}</td>
      <td class="tiny">${esc(r["شرح قطعه"])}</td><td class="tiny">${esc(r["خانواده فعلی"])}</td>
      <td class="tiny">${esc(r["محصول فعلی"])}</td><td class="tiny">${esc(r["روش تطبیق"])}</td></tr>`).join("")}</tbody>`;
  $$("#checks-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id))));
}

function renderUnmatched(){
  const rows = DATA.unmatchedReview || [];
  if(!rows.length){ empty($("#unmatched-table"),"موردی نیست"); return; }
  $("#unmatched-table").innerHTML=`<thead><tr><th>سریال</th><th>شرح قطعه (بررسی)</th><th>دسته محصول</th><th>آنالیز علت ایراد</th></tr></thead>
    <tbody>${rows.map(r=>`<tr><td class="num">${esc(r["سریال اخطار"])}</td>
      <td class="tiny">${esc(r["شرح قطعه (بررسی)"]||"—")}</td><td class="tiny">${esc(r["دسته محصول (بررسی)"]||"—")}</td>
      <td class="tiny">${esc(r["آنالیز علت ایراد"]||"—")}</td></tr>`).join("")}</tbody>`;
}

function renderQuality(rows){
  renderGroupingChecks();
  renderUnmatched();
  renderQualityKpis(rows);
  const methods=groupAgg(rows,"method").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#method-bars"),methods.slice(0,10),"warnings",()=>"#0e7f9a",i=>i.name);
  const out=groupAgg(rows.filter(r=>!r.inScope),"family").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#out-bars"),out.slice(0,10),"warnings",()=>"#94a3b8",i=>i.name.replace("خارج از دامنه - ",""));
  const reviews=rows.filter(r=>r.review).slice(0,200);
  $("#review-table").innerHTML=`<thead><tr><th>سریال</th><th>شرح قطعه</th><th>شماره فنی</th><th>محصول</th><th>خانواده</th><th>روش</th><th>اطمینان</th><th>کاندید</th><th>مغایرت خودرو</th></tr></thead>
    <tbody>${reviews.map(r=>`<tr class="clickable" data-id="${r.id}"><td class="num">${esc(r.id)}</td><td class="tiny">${esc(r.part)}</td><td class="tiny">${esc(r.tech||"—")}</td><td class="tiny">${esc(r.product)}</td><td class="tiny">${esc(r.family)}</td><td class="tiny">${esc(r.method)}</td><td>${confBadge(r.confidence)}</td><td class="num">${fmt(r.candidates)}</td><td>${r.mismatch?'<span class="badge amber">بله</span>':""}</td></tr>`).join("")}</tbody>`;
  $$("#review-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id))));
}

function renderPager(el,total,page,size,onChange){
  const pages=Math.max(1,Math.ceil(total/size));
  if(pages<=1){ el.innerHTML=""; return; }
  let html=`<button ${page<=1?"disabled":""} data-p="${page-1}">قبلی</button>`;
  const start=Math.max(1,page-2), end=Math.min(pages,page+2);
  if(start>1) html+=`<button data-p="1">۱</button>`;
  for(let p=start;p<=end;p++) html+=`<button class="${p===page?"active":""}" data-p="${p}">${fmt(p)}</button>`;
  if(end<pages) html+=`<button data-p="${pages}">${fmt(pages)}</button>`;
  html+=`<button ${page>=pages?"disabled":""} data-p="${page+1}">بعدی</button>`;
  el.innerHTML=html;
  $$("button",el).forEach(b=>b.addEventListener("click",()=>{ if(!b.disabled) onChange(Number(b.dataset.p)); }));
}


/* ------------------------------------------------------------ ایرادهای مشتری */
function defectCatBadge(cat){
  const cls=cat==="ظاهری"?"violet":"amber";
  return cat?`<span class="badge ${cls}">${esc(cat)}</span>`:"";
}
function defectRows(rows){
  const map=new Map();
  rows.forEach(r=>{
    const name=r.defect||"نامشخص";
    const cat=r.defectCat||"عملکردی";
    const key=name+"|"+cat;
    if(!map.has(key)) map.set(key,{name,cat,group:r.defectGroup||"نامشخص",warnings:0,qty:0,products:new Set(),families:new Set(),open:0,maxRepeat:0});
    const item=map.get(key);
    item.warnings+=1; item.qty+=Number(r.qty||0); item.open+=r.open?1:0;
    item.products.add(r.product); item.families.add(r.family);
    item.maxRepeat=Math.max(item.maxRepeat,Number(r.defectRepeat||0));
  });
  return Array.from(map.values()).map(i=>({...i,products:i.products.size,families:i.families.size}))
    .sort((a,b)=>b.warnings-a.warnings);
}
function renderDefectsTab(rows){
  const scoped=rows.filter(r=>state.defectCat==="all"||r.defectCat===state.defectCat);
  const items=defectRows(scoped);
  const top=items[0];
  const patternNote=$("#pattern-note");
  if(patternNote){
    const manual=rows.filter(r=>(r.defectSrc||"").indexOf("الگوی دستی")===0).length;
    patternNote.hidden=!manual;
    if(manual) patternNote.innerHTML=`<b>الگوی دستی</b> از «فرم ثبت محصولات برگشتی» یاد گرفته شده است: ${fmt(manual)} اخطار (${pct(manual/(rows.length||1))}) به همان عبارت یکتای دستی یکسان شده و بقیه متن استخراج خودکار را دارند. در جزئیات هر اخطار، منبع متن کنار «ایراد مشتری» نشان داده می‌شود.`;
  }
  const functional=rows.filter(r=>r.defectCat==="عملکردی").length;
  const visual=rows.filter(r=>r.defectCat==="ظاهری").length;
  const empty=rows.length-functional-visual;
  const unique=new Set(scoped.map(r=>r.defect||"نامشخص")).size;
  const cards=[
    ["ایراد یکتا",fmt(unique),`از ${fmt(scoped.length)} اخطار · ${fmt(items.length)} ردیف`,""],
    ["عملکردی",fmt(functional),"ایراد در کارکرد قطعه","amber"],
    ["ظاهری",fmt(visual),"ایراد در ظاهر/شکل قطعه","violet"],
    ["پرتکرارترین ایراد",top?esc(top.name):"—",top?`${fmt(top.warnings)} اخطار · ${esc(top.cat)}`:"","rose"]
  ];
  if(empty) cards[0][2]=`از ${fmt(scoped.length)} اخطار · بدون دسته: ${fmt(empty)}`;
  $("#defect-kpis").innerHTML=cards.map(([l,v,s,c])=>`<div class="kpi ${c}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");
  renderBars($("#defect-bars"),items.slice(0,10),"warnings",()=>"#d92d5c",i=>i.name);
  const m6=groupAgg(rows.filter(r=>r.m6&&r.m6!=="نامشخص"),"m6").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#m6-bars"),m6,"warnings",i=>i.name==="تجهیزات"?"#0e7f9a":"#c47f0a",i=>i.name);

  const q=state.defectQ.trim().toLowerCase();
  let list=items.filter(i=>!q || (i.name+" "+i.group+" "+i.cat).toLowerCase().includes(q));
  $("#defect-count").textContent=`${fmt(list.length)} ردیف · ${fmt(new Set(list.map(i=>i.name)).size)} توصیف یکتا`;
  const total=scoped.length||1;
  $("#defects-table").innerHTML=`<thead><tr><th>ایراد مشتری (توصیف واقعی)</th><th>دسته‌بندی</th><th>گروه فنی</th><th>اخطار</th><th>سهم</th><th>محصول</th><th>خانواده</th><th>قطعات معیوب</th><th>بیشترین تکرار</th><th>باز</th><th></th></tr></thead>
    <tbody>${list.map(i=>`<tr>
      <td><b>${esc(i.name)}</b></td><td>${defectCatBadge(i.cat)}</td><td class="tiny">${esc(i.group)}</td>
      <td class="num">${fmt(i.warnings)}</td><td class="num muted">${pct(i.warnings/total)}</td>
      <td class="num">${fmt(i.products)}</td><td class="num">${fmt(i.families)}</td>
      <td class="num">${fmt(i.qty)}</td><td class="num">${i.maxRepeat>1?`<span class="badge red">×${fmt(i.maxRepeat)}</span>`:fmt(1)}</td>
      <td class="num">${fmt(i.open)}</td>
      <td><button class="btn" data-defect="${esc(i.name)}" style="padding:5px 9px">اخطارها</button></td></tr>`).join("")}</tbody>`;
  $$("#defects-table [data-defect]").forEach(btn=>btn.addEventListener("click",()=>{
    state.defect=btn.dataset.defect; state.page=1; switchTab("warnings"); render();
  }));

  // علت‌های استاندارد
  const causes=new Map();
  rows.filter(r=>r.hasReview).forEach(r=>{
    const key=r.causeStd||"ثبت نشده";
    if(!causes.has(key)) causes.set(key,{name:key,group:r.causeGroup||"نامشخص",m6:r.m6||"نامشخص",warnings:0,products:new Set()});
    const item=causes.get(key); item.warnings+=1; item.products.add(r.product);
  });
  const causeList=Array.from(causes.values()).map(i=>({...i,products:i.products.size})).sort((a,b)=>b.warnings-a.warnings).slice(0,40);
  $("#causes-table").innerHTML=`<thead><tr><th>علت استاندارد</th><th>گروه علت</th><th>گروه ۶M</th><th>اخطار</th><th>محصول</th></tr></thead>
    <tbody>${causeList.map(i=>`<tr><td><b>${esc(i.name)}</b></td><td class="tiny">${esc(i.group)}</td><td class="tiny">${esc(i.m6)}</td><td class="num">${fmt(i.warnings)}</td><td class="num">${fmt(i.products)}</td></tr>`).join("")}</tbody>`;
}
function exportDefectCsv(){
  const rows=defectRows(applyFilters().filter(r=>state.defectCat==="all"||r.defectCat===state.defectCat));
  const head=["ایراد مشتری","دسته‌بندی ایراد","گروه فنی (کمکی)","تعداد اخطار","تعداد محصول","تعداد خانواده","قطعات معیوب","بیشترین تکرار","اخطار باز"];
  const body=rows.map(i=>[i.name,i.cat,i.group,i.warnings,i.products,i.families,i.qty,i.maxRepeat,i.open].map(v=>`"${String(v).replace(/"/g,'""')}"`).join(","));
  downloadCsv("\ufeff"+head.join(",")+"\n"+body.join("\n"),"ekhtar-defects.csv");
}

/* ------------------------------------------------------------ فرم‌های 8D */
const FORM_CORE=["team","containment","root_cause","corrective","verification","prevention","lesson"];
const formPercentOf=e=>e?Math.round(FORM_CORE.filter(k=>String(e[k]||"").trim()).length/FORM_CORE.length*100):0;
function formStatusOf(e){
  if(!e) return "شروع نشده";
  if(String(e.status||"")==="بسته شده") return "بسته شده";
  const p=formPercentOf(e);
  if(p>=100) return "آماده تأیید";
  if(p>0) return "در جریان";
  return "شروع نشده";
}
const formBadge=s=>{
  const cls=s==="بسته شده"?"green":s==="آماده تأیید"?"blue":s==="در جریان"?"amber":"slate";
  return `<span class="badge ${cls}">${esc(s)}</span>`;
};
function formRows(rows){
  const scope=state.formScope||"working";
  return rows.filter(r=>{
    if(!r.form8d || r.form8d==="—") return false;
    if(scope==="open") return !!r.open;
    if(scope==="review") return !!r.hasReview;
    if(scope==="all") return true;
    return r.open || r.hasReview;
  });
}
const FORM_STORE={
  mode:"local",
  data:{},
  async init(){
    try{
      const r=await fetch("api/8d",{cache:"no-store",headers:{"Accept":"application/json"}});
      if(r.ok){
        const payload=await r.json();
        if(payload && payload.entries){
          this.mode="server"; this.data=payload.entries; this.stats=payload.stats;
          this.apply(); this.badge(); return;
        }
      }
    }catch(e){}
    this.mode="local";
    try{ this.data=JSON.parse(localStorage.getItem("ekhtar8d")||"{}")||{}; }catch(e){ this.data={}; }
    this.apply(); this.badge();
  },
  badge(){
    const el=$("#store-badge"); if(!el) return;
    if(this.mode==="server"){
      el.className="store-badge server";
      el.textContent="حالت ویرایش — ذخیره روی سرور";
      el.title="داده‌ها در output/8d-forms.json ذخیره می‌شوند";
    }else{
      el.className="store-badge local";
      el.textContent="حالت فایل — ذخیره در مرورگر";
      el.title="برای ذخیرهٔ دائمی، python serve.py را اجرا کنید";
    }
  },
  apply(){
    Object.entries(this.data||{}).forEach(([k,v])=>{
      const r=DATA.warnings.find(x=>String(x.id)===String(k));
      if(r){ r.form=v; r.formStatus=formStatusOf(v); r.formPercent=formPercentOf(v); }
    });
  },
  saveLocal(){
    try{ localStorage.setItem("ekhtar8d",JSON.stringify(this.data)); return true; }catch(e){ return false; }
  },
  async save(serial,values,number){
    const key=String(serial);
    if(this.mode==="server"){
      try{
        const r=await fetch("api/8d",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({serial:key,values,number})});
        const payload=await r.json();
        if(!r.ok) return {ok:false,error:payload.error||"خطای سرور"};
        this.data[key]=payload.entry; this.stats=payload.stats;
        return {ok:true,entry:payload.entry};
      }catch(e){ return {ok:false,error:"ارتباط با سرور قطع است"}; }
    }
    this.data[key]={...(this.data[key]||{}),...values,updated:new Date().toISOString().slice(0,16).replace("T"," ")};
    const ok=this.saveLocal();
    return ok?{ok:true,entry:this.data[key]}:{ok:false,error:"ذخیره در مرورگر ممکن نشد"};
  }
};
function toast(message){
  let el=$("#toast");
  if(!el){ el=document.createElement("div"); el.id="toast"; el.className="toast"; document.body.appendChild(el); }
  el.textContent=message; el.classList.add("show");
  clearTimeout(el._timer); el._timer=setTimeout(()=>el.classList.remove("show"),2600);
}

function formEditorHtml(r){
  const form=r.form||{};
  const labels=DATA.formFields||{};
  const skip=new Set(["owner","due"]);
  const fields=Object.entries(labels).filter(([k])=>!skip.has(k));
  const suggestions={
    problem:[r.part?`شرح قطعه: ${r.part}`:"",r.error?`شرح خطا: ${r.error}`:"",r.car?`خودرو: ${r.car}`:""].filter(Boolean).join("\n"),
    root_cause:[r.causeStd?`علت استاندارد: ${r.causeStd}`:"",r.cause?`آنالیز علت: ${r.cause}`:"",r.reviewOrigin?`منشاء: ${r.reviewOrigin}`:""].filter(Boolean).join("\n"),
    containment:r.action||"",
    corrective:r.action||""
  };
  const percent=formPercentOf(form);
  return `<div style="margin-top:18px;border-top:1px solid #e2e8f0;padding-top:14px">
    <div class="toolbar" style="margin-bottom:6px">
      <h3 style="margin:0">فرم 8D — <span class="num">${esc(r.form8d||"—")}</span></h3>
      <div class="right"><span id="form-chip">${formBadge(formStatusOf(form))}</span>
        <span class="muted tiny" id="form-percent">${fmt(percent)}٪ تکمیل</span></div>
    </div>
    <div class="progress" style="margin-bottom:10px"><div class="fill" id="form-progress" style="width:${percent}%"></div></div>
    <div class="form-grid">
      <div class="field"><label>مسئول پیگیری</label><input data-f="owner" value="${esc(form.owner||"")}" placeholder="نام مسئول"></div>
      <div class="field"><label>تاریخ تکمیل</label><input data-f="due" value="${esc(form.due||"")}" placeholder="۱۴۰۵/۰۸/۱۵"></div>
      <div class="field"><label>وضعیت فرم</label><select data-f="status">${(DATA.formStatuses||[]).map(s=>`<option value="${esc(s)}" ${((form.status||"")===s)?"selected":""}>${esc(s)}</option>`).join("")}</select></div>
      <div class="field"><label>&nbsp;</label><button class="btn" id="fill-suggest">پر کردن از داده‌های اخطار</button></div>
      ${fields.map(([k,label])=>`<div class="field full"><label>${esc(label)}</label>
        <textarea data-f="${k}" placeholder="${esc(suggestions[k]||"")}">${esc(form[k]||"")}</textarea></div>`).join("")}
    </div>
    <div class="form-actions">
      <button class="btn primary" id="save-form">ذخیرهٔ فرم</button>
      <button class="btn" id="reload-form">بازخوانی</button>
      <span class="form-state" id="form-state">${FORM_STORE.mode==="server"?"ذخیره روی سرور فعال است":"ذخیره در حافظهٔ مرورگر"}</span>
    </div>
  </div>`;
}
function bindFormEditor(r){
  FORM_DIRTY = false;
  $$("[data-f]").forEach(el=>el.addEventListener("input",()=>{ FORM_DIRTY = true; }));
  const fill=$("#fill-suggest");
  if(fill) fill.addEventListener("click",()=>{
    const map={
      problem:[r.part?`شرح قطعه: ${r.part}`:"",r.error?`شرح خطا: ${r.error}`:"",r.car?`خودرو: ${r.car}`:""].filter(Boolean).join("\n"),
      root_cause:[r.causeStd?`علت استاندارد: ${r.causeStd}`:"",r.cause?`آنالیز علت: ${r.cause}`:"",r.reviewOrigin?`منشاء: ${r.reviewOrigin}`:""].filter(Boolean).join("\n"),
      containment:r.action||"",
      corrective:r.action||""
    };
    Object.entries(map).forEach(([k,v])=>{
      const el=$(`[data-f="${k}"]`); if(el && !el.value.trim() && v) el.value=v;
    });
  });
  const reload=$("#reload-form");
  if(reload) reload.addEventListener("click",()=>{ openWarning(r.id); });
  const save=$("#save-form");
  if(save) save.addEventListener("click",async()=>{
    const values={};
    $$("[data-f]").forEach(el=>{ if(el.closest("#form8d-editor")) values[el.dataset.f]=el.value.trim(); });
    save.disabled=true; save.textContent="در حال ذخیره…";
    const result=await FORM_STORE.save(r.id,values,r.form8d);
    save.disabled=false; save.textContent="ذخیرهٔ فرم";
    if(result.ok){
      FORM_DIRTY = false;
      r.form={...values};
      r.formStatus=formStatusOf(values); r.formPercent=formPercentOf(values);
      const stateEl=$("#form-state");
      if(stateEl) stateEl.textContent="ذخیره شد ✓ "+new Date().toLocaleTimeString("fa-IR");
      const chip=$("#form-chip"); if(chip) chip.innerHTML=formBadge(r.formStatus);
      const pr=$("#form-percent"); if(pr) pr.textContent=`${fmt(r.formPercent)}٪ تکمیل`;
      const bar=$("#form-progress"); if(bar) bar.style.width=`${r.formPercent}%`;
      toast("فرم ذخیره شد");
      renderFormsTab(applyFilters());
    }else{
      const stateEl=$("#form-state");
      if(stateEl) stateEl.textContent="ذخیره نشد: "+result.error;
      toast("ذخیره نشد: "+result.error);
    }
  });
}
function renderFormsTab(rows){
  const items=formRows(rows).sort((a,b)=>
    (Number(b.open)-Number(a.open)) || (Number(b.hasReview)-Number(a.hasReview)) ||
    ((b.formPercent||0)-(a.formPercent||0)) || String(a.id).localeCompare(String(b.id)));
  const done=items.filter(r=>r.formPercent>=100).length;
  const doing=items.filter(r=>r.formPercent>0&&r.formPercent<100).length;
  const cards=[
    ["فرم‌های 8D",fmt(items.length),"هر اخطار بررسی‌شده یا باز یک فرم",""],
    ["تکمیل‌شده",fmt(done),`${pct(items.length?done/items.length:0)} از فرم‌ها`,"blue"],
    ["در جریان",fmt(doing),"ناقص، در حال تکمیل","amber"],
    ["شروع نشده",fmt(items.length-done-doing),"بدون ورود اطلاعات","slate"]
  ];
  $("#form-kpis").innerHTML=cards.map(([l,v,s,c])=>`<div class="kpi ${c}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");

  const q=state.formQ.trim().toLowerCase();
  let list=items;
  if(q) list=list.filter(r=>[r.id,r.part,r.product,r.form8d,(r.form||{}).owner].join(" ").toLowerCase().includes(q));
  if(state.formStatus) list=list.filter(r=>r.formStatus===state.formStatus);
  $("#form-count").textContent=`${fmt(list.length)} فرم`;
  const pages=Math.max(1,Math.ceil(list.length/state.pageSize));
  if(state.page>pages) state.page=pages;
  const start=(state.page-1)*state.pageSize;
  const page=list.slice(start,start+state.pageSize);
  $("#forms-table").innerHTML=`<thead><tr><th>شماره فرم</th><th>سریال</th><th>شرح قطعه</th><th>محصول</th><th>وضعیت اخطار</th><th>مسئول</th><th>تاریخ تکمیل</th><th>درصد</th><th>وضعیت فرم</th><th>آخرین ذخیره</th></tr></thead>
    <tbody>${page.map(r=>`<tr class="clickable" data-id="${r.id}">
      <td class="num tiny">${esc(r.form8d)}</td><td class="num">${esc(r.id)}</td>
      <td class="tiny" title="${esc(r.part)}">${esc(r.part.length>38?r.part.slice(0,38)+"…":r.part)}</td>
      <td class="tiny">${esc(r.product)}</td><td class="tiny">${statusBadge(r)}</td>
      <td class="tiny">${esc((r.form||{}).owner||"—")}</td><td class="tiny">${esc(faDigits((r.form||{}).due||"—"))}</td>
      <td style="min-width:90px"><div class="progress" title="${fmt(r.formPercent)}٪"><div class="fill" style="width:${r.formPercent}%"></div></div><span class="muted tiny">${fmt(r.formPercent)}٪</span></td>
      <td>${formBadge(r.formStatus)}</td>
      <td class="tiny muted">${esc(faDigits(String((r.form||{}).updated||"—").replace("T"," ").slice(0,16)))}</td></tr>`).join("")}</tbody>`;
  $$("#forms-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id))));
  renderPager($("#forms-pager"),list.length,state.page,state.pageSize,p=>{state.page=p;renderFormsTab(applyFilters());});
}
function exportFormCsv(){
  const rows=formRows(applyFilters());
  const labels=DATA.formFields||{};
  const head=["شماره فرم 8D","سریال اخطار","شرح قطعه","محصول","وضعیت اخطار",...Object.values(labels),"وضعیت فرم","درصد تکمیل","آخرین به‌روزرسانی"];
  const body=rows.map(r=>{
    const f=r.form||{};
    return [r.form8d,r.id,r.part,r.product,r.status,...Object.keys(labels).map(k=>f[k]||""),r.formStatus,r.formPercent,f.updated||""]
      .map(v=>`"${String(v==null?"":v).replace(/"/g,'""')}"`).join(",");
  });
  downloadCsv("\ufeff"+head.join(",")+"\n"+body.join("\n"),"ekhtar-8d-forms.csv");
}
function exportFormJson(){
  const rows=formRows(applyFilters());
  const payload={generated:new Date().toISOString(),mode:FORM_STORE.mode,entries:{}};
  rows.forEach(r=>{ if(r.form && Object.keys(r.form).length) payload.entries[String(r.id)]={...(r.form),number:r.form8d}; });
  const text=JSON.stringify(payload,null,1);
  const blob=new Blob([text],{type:"application/json;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a"); a.href=url; a.download="ekhtar-8d-forms.json"; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),8000);
  toast(`پشتیبان ${fmt(Object.keys(payload.entries).length)} فرم دانلود شد`);
}

function wmRow(label, value){
  return `<div class="k">${label}</div><div class="v">${value||"—"}</div>`;
}
function wmShowPanel(name){
  $$("#modal-body .wm-tab").forEach(btn=>btn.classList.toggle("active", btn.dataset.wm===name));
  $$("#modal-body .wm-panel").forEach(panel=>panel.classList.toggle("active", panel.dataset.wmPanel===name));
  const body=$("#modal-body"); if(body && name!=="summary") body.scrollTop=0;
}
function summaryPanelHtml(r){
  const stage = esc(stageName(r.status));
  return `<div class="wm-grid">
    <div class="wm-card">
      <h4>ایراد و دسته‌بندی</h4>
      <div class="wm-rows">
        ${wmRow("ایراد مشتری", `<b>${esc(r.defect||"—")}</b>${r.defectSrc?`<span class="wm-tag ${r.defectSrc.indexOf("الگوی دستی")===0?"manual":""}">${esc(r.defectSrc)}</span>`:""}`)}
        ${wmRow("دسته‌بندی", `${defectCatBadge(r.defectCat)||'<span class="muted tiny">ثبت نشده</span>'}`)}
        ${wmRow("گروه فنی", esc(r.defectGroup))}
        ${wmRow("ریشهٔ ایراد", r.rootCause&&!isHiddenRoot(r.rootCause)?`<b>${esc(r.rootCause)}</b>`:`<span class="muted">${r.rootCause==="عدم دریافت قطعه"?"قطعه دریافت نشده":"در متن اخطار علتی ذکر نشده"}</span>`)}
        ${wmRow("قطعه در تحلیل", r.analysisPart?`<b>${esc(r.analysisPart)}</b> <span class="muted tiny">(از آنالیز علت)</span>`:`<span class="muted">در تحلیل نام برده نشده</span>`)}
        ${wmRow("تکرار در محصول", r.defectRepeat>1?`<span class="badge red">${fmt(r.defectRepeat)} بار در این محصول</span>`:"۱ بار")}
        ${wmRow("نوع / شرح خطا", `${esc(r.type||"—")} · ${esc(r.error||"—")}`)}
        ${wmRow("خودرو", `${esc(r.car||"—")}${r.make?` · ${esc(r.make)}`:""}`)}
      </div>
    </div>
    <div class="wm-card">
      <h4>قطعه و محصول</h4>
      <div class="wm-rows">
        ${wmRow("قطعه (گروه‌بندی)", `<b>${esc(r.product||"—")}</b> <span class="muted tiny">${esc([r.group?gLabel(r.group):"",r.family].filter(Boolean).join(" · "))}</span>`)}
        ${wmRow("شرح قطعه (مشتری)", esc(r.part))}
        ${wmRow("شرح منشا", esc(r.origin))}
        ${wmRow("شماره فنی", esc(r.tech))}
        ${wmRow("محصول راهکاران", `${esc(r.rahkaran||"—")} ${r.code?`<span class="muted tiny">(${esc(r.code)})</span>`:""}`)}
        ${wmRow("گروه / خانواده", `${esc(r.group||"—")} · ${esc(r.family||"—")}`)}
        ${wmRow("محصول", `<b>${esc(r.product||"—")}</b>`)}
        ${wmRow("کد گروه / برنچ", `${esc(r.catalogCode||"—")} · ${esc(r.branch||"نامشخص")}`)}
      </div>
    </div>
    <div class="wm-card full">
      <h4>وضعیت، اقدام و کیفیت تطبیق</h4>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="wm-rows">
          ${wmRow("وضعیت مؤثر", statusBadge(r))}
          ${wmRow("وضعیت ثبت‌شده", esc(r.rawStatus||r.status))}
          ${wmRow("اولویت", priorityBadge(r))}
          ${wmRow("وضعیت اقدام", stage)}
          ${wmRow("اقدام کوتاه‌مدت", esc(r.stAction))}
          ${wmRow("اقدام میان‌مدت", esc(r.mtAction))}
          ${wmRow("شماره فرم 8D", `<b>${esc(r.form8d||"—")}</b>`)}
        </div>
        <div class="wm-rows">
          ${wmRow("روش تطبیق", `${esc(r.method||"—")} ${confBadge(r.confidence)}`)}
          ${wmRow("کاندید شماره فنی", `${fmt(r.candidates)} ${r.mismatch?'<span class="badge amber">مغایرت خودرو</span>':""} ${r.review?'<span class="badge red">نیاز به بازبینی</span>':""}`)}
          ${wmRow("محل صدور", esc(r.location))}
          ${wmRow("گرید", esc(r.grade))}
          ${wmRow("قطعات معیوب", fmt(r.qty))}
          ${wmRow("نمره منفی", `${fmt(r.score)} <span class="muted tiny">(سازنده ${fmt(r.scoreMaker)})</span>`)}
          ${wmRow("برگهٔ بررسی", r.hasReview?'<span class="badge green">متصل</span>':(r.autoClosed?'<span class="badge violet">خودکار خاتمه</span>':'<span class="badge slate">ندارد</span>'))}
        </div>
      </div>
      ${r.autoClosed?`<div class="wm-text" style="margin-top:10px;border-color:#ddd6fe;background:#f5f3ff;color:#5b21b6">این اخطار در فایل مشتری با وضعیت «${esc(r.rawStatus)}» ثبت شده بود؛ چون تاریخ تایید آن قدیمی‌تر از یک سال است، خودکار خاتمه‌یافته در نظر گرفته شده است.</div>`:""}
      ${r.notes?`<div class="wm-card full" style="border:0;padding:10px 0 0"><h4>توضیحات ثبت‌شدهٔ مشتری</h4><div class="wm-text">${esc(r.notes)}</div></div>`:""}
    </div>
  </div>`;
}
function reviewPanelHtml(r){
  const sources=DATA.meta.sources||{};
  const file=esc(sources.review||"C_Plus");
  if(!r.hasReview){
    return `<div class="wm-empty">
      <div style="font-size:24px;margin-bottom:4px">🗂️</div>
      برای اخطار <b>${esc(faDigits(r.id))}</b> در فایل <b>${file}</b> برگهٔ بررسی ثبت نشده است.<br>
      <span class="tiny">کلید اتصال، «شماره اخطار» است؛ به‌محض اضافه شدن برگه با همین شماره، این بخش در ساخت بعدی خودکار پر می‌شود.</span>
      <div style="margin-top:12px"><button class="btn" data-wm-jump="form">رفتن به فرم 8D</button></div>
    </div>`;
  }
  return `<div class="wm-source">
      🔗 این برگه از فایل <b>${file}</b>، شیت «اخطار»، با کلید <b>شماره اخطار ${esc(faDigits(r.id))}</b> به همین اخطار متصل شده است.
    </div>
    <div class="wm-grid">
      <div class="wm-card full"><h4>آنالیز علت ایراد</h4>
        <div class="wm-rows" style="margin-bottom:8px">${wmRow("قطعه در تحلیل", r.analysisPart?`<b>${esc(r.analysisPart)}</b>`:`<span class="muted">در متن تحلیل نام برده نشده</span>`)}</div>
        <div class="wm-text">${esc(r.cause||"—")}</div></div>
      <div class="wm-card full"><h4>شرح اقدام اصلاحی</h4><div class="wm-text">${esc(r.action||"—")}</div></div>
      <div class="wm-card"><h4>دسته‌بندی مشتری</h4><div class="wm-rows">
        ${wmRow("منشاء ایراد", esc(r.reviewOrigin))}
        ${wmRow("دسته اعلامی", esc(r.reviewCategory))}
        ${wmRow("گروه بازرگانی", esc(r.reviewDealGroup))}
        ${wmRow("تامین‌کننده", esc(r.supplier))}
        ${wmRow("دوره", esc(r.reviewPeriod))}
      </div></div>
      <div class="wm-card"><h4>کلیم و پیگیری</h4><div class="wm-rows">
        ${wmRow("شماره کلیم", esc(r.claimNo))}
        ${wmRow("کارت نارنجی", esc(r.orangeCard))}
        ${wmRow("کلیم شماره فنی", `${fmt(r.claims)} <span class="muted tiny">(پذیرفته ${fmt(r.claimsAccepted)})</span>`)}
        ${wmRow("علت استاندارد", `${esc(r.causeStd||"—")} ${r.m6&&r.m6!=="نامشخص"?`<span class="badge violet">${esc(r.m6)}</span>`:""}`)}
        ${wmRow("گروه علت", esc(r.causeGroup))}
      </div></div>
      ${r.reviewNotes?`<div class="wm-card full"><h4>توضیحات برگهٔ بررسی</h4><div class="wm-text">${esc(r.reviewNotes)}</div></div>`:""}
    </div>`;
}
function formPanelHtml(r){
  if(!r.form8d || r.form8d==="—"){
    return `<div class="wm-empty">برای این اخطار فرم 8D تعریف نشده است.</div>`;
  }
  return `<div id="form8d-editor">${formEditorHtml(r)}</div>`;
}
function renderModalFooter(r){
  const foot=$("#modal-foot"); if(!foot) return;
  const list=(currentWarnings&&currentWarnings.length)?currentWarnings:DATA.warnings;
  const idx=list.findIndex(x=>x.id===r.id);
  const prev=idx>0?list[idx-1]:null, next=idx>=0&&idx<list.length-1?list[idx+1]:null;
  foot.innerHTML=`<span>${idx>=0?`اخطار ${fmt(idx+1)} از ${fmt(list.length)} در فهرست فعلی`:"جزئیات اخطار"}</span>
    <span style="display:flex;gap:8px">
      <button class="btn" id="wm-prev" ${prev?"":"disabled"}>‹ قبلی</button>
      <button class="btn" id="wm-next" ${next?"":"disabled"}>بعدی ›</button>
    </span>`;
  const prevBtn=$("#wm-prev"), nextBtn=$("#wm-next");
  if(prevBtn&&prev) prevBtn.addEventListener("click",()=>openWarning(prev.id));
  if(nextBtn&&next) nextBtn.addEventListener("click",()=>openWarning(next.id));
}
function openWarning(id, panel){
  const r=DATA.warnings.find(x=>x.id===id); if(!r) return;
  $(".modal-box") && ($(".modal-box").scrollTop=0);
  $("#modal-title").textContent=`پروندهٔ اخطار کیفی · ${faDigits(r.id)}`;
  $("#modal-body").innerHTML=`
    <div class="wm-hero">
      <div class="wm-top">
        <div>
          <div class="wm-serial">شماره اخطار <b>${esc(faDigits(r.id))}</b></div>
          <div class="wm-meta">تاریخ تایید ${esc(faDigits(r.date))} · ${esc(r.car||"—")}${r.make?` · ${esc(r.make)}`:""}</div>
        </div>
        <div class="wm-badges">
          ${statusBadge(r)}
          ${priorityBadge(r)}
          ${r.grade?`<span class="badge slate">گرید ${esc(r.grade)}</span>`:""}
          ${r.branch?`<span class="badge blue">${esc(r.branch)}</span>`:""}
          ${r.hasReview?'<span class="badge green">برگهٔ بررسی متصل</span>':'<span class="badge amber">بدون برگهٔ بررسی</span>'}
        </div>
      </div>
      <div class="wm-defect">${esc(r.defect||r.part||"—")}</div>
      <div class="wm-part">${esc(r.part)}${r.defectCat?` · ${esc(r.defectCat)}`:""}${r.product?` · ${esc(r.product)}`:""}</div>
      <div class="wm-stats">
        ${[["قطعات معیوب",fmt(r.qty)],["نمره منفی",fmt(r.score)],["تکرار ایراد",fmt(r.defectRepeat||1)],["شماره فنی",r.tech||"—"]]
          .map(([l,v])=>`<div class="wm-stat"><div class="l">${l}</div><div class="v" title="${esc(v)}">${esc(v)}</div></div>`).join("")}
      </div>
    </div>
    <div class="wm-tabs">
      <button class="wm-tab" data-wm="summary">خلاصه</button>
      <button class="wm-tab" data-wm="review">برگهٔ بررسی مشتری ${r.hasReview?'<span class="badge green">متصل</span>':'<span class="badge slate">ندارد</span>'}</button>
      <button class="wm-tab" data-wm="form">فرم 8D</button>
    </div>
    <div class="wm-panel" data-wm-panel="summary">${summaryPanelHtml(r)}</div>
    <div class="wm-panel" data-wm-panel="review">${reviewPanelHtml(r)}</div>
    <div class="wm-panel" data-wm-panel="form">${formPanelHtml(r)}</div>`;
  $$("#modal-body .wm-tab").forEach(btn=>btn.addEventListener("click",()=>wmShowPanel(btn.dataset.wm)));
  $$("#modal-body [data-wm-jump]").forEach(btn=>btn.addEventListener("click",()=>wmShowPanel(btn.dataset.wmJump)));
  renderModalFooter(r);
  $("#modal").classList.remove("hidden");
  wmShowPanel(panel||"summary");
  bindFormEditor(r);
}
function openProduct(product){
  const saved=state.product; state.product="";
  const rows=applyFilters().filter(r=>r.product===product);
  state.product=saved;
  if(!rows.length) return;
  const qty=sum(rows,"qty"), score=sum(rows,"score");
  const first=rows[0];
  $("#modal-title").textContent=`محصول ${product}`;
  $("#modal-body").innerHTML=`<div class="kv">
    <div class="k">گروه محصول</div><div class="v">${esc(first.group)}</div>
    <div class="k">خانواده</div><div class="v">${esc(first.family)}</div>
    <div class="k">کد گروه</div><div class="v">${esc(first.catalogCode||"—")}</div>
    <div class="k">تعداد اخطار</div><div class="v">${fmt(rows.length)}</div>
    <div class="k">قطعات معیوب</div><div class="v">${fmt(qty)}</div>
    <div class="k">نمره منفی</div><div class="v">${fmt(score)}</div>
  </div>
  <div class="toolbar" style="margin-top:14px"><div class="hint muted">۱۰ ردیف آخر</div><button class="btn primary" id="go-product-warnings">مشاهده همه اخطارهای این محصول</button></div>
  <div class="table-wrap"><table><thead><tr><th>سریال</th><th>تاریخ</th><th>خودرو</th><th>شرح قطعه</th><th>شماره فنی</th><th>قطعات</th></tr></thead><tbody>
  ${rows.slice(0,10).map(r=>`<tr><td class="num">${esc(r.id)}</td><td class="tiny">${esc(faDigits(r.date))}</td><td class="tiny">${esc(r.car)}</td><td class="tiny">${esc(r.part)}</td><td class="tiny">${esc(r.tech||"—")}</td><td class="num">${fmt(r.qty)}</td></tr>`).join("")}
  </tbody></table></div>`;
  const foot=$("#modal-foot"); if(foot) foot.innerHTML="";
  $("#modal").classList.remove("hidden");
  $("#go-product-warnings").addEventListener("click",()=>{
    state.product=product; state.page=1; syncSelects(); switchTab("warnings"); render(); $("#modal").classList.add("hidden");
  });
}

function fillSelect(el,values,current,allLabel="همه"){
  el.innerHTML=`<option value="">${allLabel}</option>`+values.map(v=>`<option value="${esc(v)}" ${v===current?"selected":""}>${esc(v)}</option>`).join("");
}
function syncSelects(){
  const groups=Array.from(new Set(DATA.warnings.map(r=>r.group))).sort();
  const families=Array.from(new Set(DATA.warnings.filter(r=>!state.group||r.group===state.group).map(r=>r.family))).sort();
  const products=Array.from(new Set(DATA.warnings.filter(r=>!state.group||r.group===state.group).filter(r=>!state.family||r.family===state.family).map(r=>r.product))).sort();
  fillSelect($("#f-group"),groups,state.group);
  fillSelect($("#f-family"),families,state.family);
  fillSelect($("#f-product"),products,state.product);
  if(state.product && !products.includes(state.product)) state.product="";
}
function refreshMonthSelects(){
  const months=monthsOfYear(state.year);
  const fromEl=$("#f-from"), toEl=$("#f-to");
  const fromVal=state.from, toVal=state.to;
  fromEl.innerHTML=`<option value="">از ابتدا</option>`+months.map(m=>`<option value="${m.key}">${faDigits(m.label)}</option>`).join("");
  toEl.innerHTML=`<option value="">تا انتها</option>`+months.map(m=>`<option value="${m.key}">${faDigits(m.label)}</option>`).join("");
  fromEl.value = months.some(m=>m.key===fromVal) ? fromVal : "";
  toEl.value = months.some(m=>m.key===toVal) ? toVal : "";
  if(!fromEl.value) state.from="";
  if(!toEl.value) state.to="";
}

function initFilters(){
  const groups=Array.from(new Set(DATA.warnings.map(r=>r.group))).sort();
  const cars=Array.from(new Set(DATA.warnings.map(r=>r.car))).sort();
  const grades=Array.from(new Set(DATA.warnings.map(r=>r.grade).filter(Boolean))).sort();
  const years=Array.from(new Set(DATA.warnings.map(r=>r.year).filter(Boolean))).sort();
  const branches=Array.from(new Set(DATA.warnings.map(r=>r.branch).filter(Boolean))).sort();
  fillSelect($("#f-group"),groups,state.group);
  fillSelect($("#f-branch"),branches,state.branch);
  fillSelect($("#f-car"),cars,state.car);
  fillSelect($("#f-grade"),grades,state.grade);
  $("#f-status").innerHTML=`<option value="">همه</option><option value="open">باز</option><option value="closed">خاتمه‌یافته</option>`;
  $("#f-review").innerHTML=`<option value="">همه</option><option value="yes">دارای برگه بررسی</option><option value="no">بدون برگه بررسی</option>`;
  const roots=Array.from(new Set(DATA.warnings.map(r=>r.rootCause).filter(Boolean).filter(v=>!isHiddenRoot(v)))).sort();
  fillSelect($("#f-root"),roots,state.root);
  const rootParts=Array.from(new Set(DATA.warnings.map(r=>r.analysisPart).filter(Boolean))).sort((a,b)=>a.localeCompare(b,"fa"));
  fillSelect($("#f-rootpart"),rootParts,state.rootPart);
  const processes=["تولید","مواد اولیه","تامین‌کننده","طراحی مهندسی","مشتری"];
  fillSelect($("#f-process"),processes,state.process);
  $("#f-priority").innerHTML=`<option value="">همه اولویت‌ها</option>`+
    [["1","باز — سال جاری"],["2","باز — یک‌سال گذشته"],["3","باز — بدون تاریخ"],["4","خاتمهٔ خودکار"],["5","خاتمه‌یافته"]]
      .map(([value,label])=>`<option value="${value}">${label}</option>`).join("");
  $("#f-year").innerHTML=`<option value="">همه سال‌ها</option>`+years.map(y=>`<option value="${y}">${faDigits(y)}</option>`).join("");
  refreshMonthSelects();
  syncSelects();
  $("#f-group").addEventListener("change",e=>{state.group=e.target.value;state.family="";state.product="";state.page=1;syncSelects();render();});
  $("#f-family").addEventListener("change",e=>{state.family=e.target.value;state.product="";state.page=1;syncSelects();render();});
  $("#f-product").addEventListener("change",e=>{state.product=e.target.value;state.page=1;render();});
  $("#f-branch").addEventListener("change",e=>{state.branch=e.target.value;state.page=1;render();});
  $("#f-car").addEventListener("change",e=>{state.car=e.target.value;state.page=1;render();});
  $("#f-grade").addEventListener("change",e=>{state.grade=e.target.value;state.page=1;render();});
  $("#f-status").addEventListener("change",e=>{state.status=e.target.value;state.page=1;render();});
  $("#f-priority").addEventListener("change",e=>{state.priority=e.target.value;state.page=1;render();});
  $("#f-review").addEventListener("change",e=>{state.review=e.target.value;state.page=1;render();});
  $("#f-root").addEventListener("change",e=>{state.root=e.target.value;state.page=1;render();});
  $("#f-rootpart").addEventListener("change",e=>{state.rootPart=e.target.value;state.page=1;render();});
  $("#f-process").addEventListener("change",e=>{state.process=e.target.value;state.page=1;render();});
  $("#f-year").addEventListener("change",e=>{
    state.year=e.target.value; state.from=""; state.to=""; state.page=1;
    refreshMonthSelects();
    setTrendMode(state.year ? "month" : "year");
    render();
  });
  $("#f-from").addEventListener("change",e=>{state.from=e.target.value;state.page=1;setTrendMode("month");render();});
  $("#f-to").addEventListener("change",e=>{state.to=e.target.value;state.page=1;setTrendMode("month");render();});
  let timer=null;
  $("#f-q").addEventListener("input",e=>{clearTimeout(timer);timer=setTimeout(()=>{state.q=e.target.value;state.page=1;render();},180);});
  $("#reset").addEventListener("click",()=>{
    Object.assign(state,{group:"",family:"",product:"",branch:"",defect:"",root:"",rootPart:"",quickFilter:"",car:"",grade:"",status:"",priority:"",year:"",from:"",to:"",q:"",review:"",productQ:"",warningQ:"",reviewQ:"",defectQ:"",formQ:"",formStatus:"",page:1,warningSort:"priority"});
    $("#f-q").value=""; $("#product-search").value=""; $("#warning-search").value=""; $("#review-search").value="";
    $("#defect-search").value=""; $("#form-search").value=""; $("#pareto-search").value=""; state.paretoQ=""; $("#form-status-filter").value=""; $("#f-branch").value=""; $("#form-scope").value="working";
    syncSelects(); refreshMonthSelects();
    $("#f-car").value="";$("#f-grade").value="";$("#f-status").value="";$("#f-priority").value="";$("#warning-sort").value="priority";$("#f-year").value="";$("#f-review").value="";$("#f-from").value="";$("#f-to").value="";$("#f-root").value="";$("#f-rootpart").value="";
    render();
  });
  $("#export").addEventListener("click",exportCsv);
  $("#print").addEventListener("click",()=>window.print());
  $("#page-size").addEventListener("change",e=>{state.pageSize=Number(e.target.value);state.page=1;render();});
  $("#product-search").addEventListener("input",e=>{state.productQ=e.target.value;state.page=1;renderProductsTab(applyFilters());});
  $("#warning-search").addEventListener("input",e=>{state.warningQ=e.target.value;state.page=1;renderWarningsTab(applyFilters());});
  $("#warning-sort").addEventListener("change",e=>{state.warningSort=e.target.value;state.page=1;renderWarningsTab(applyFilters());});
  $("#review-search").addEventListener("input",e=>{state.reviewQ=e.target.value;state.page=1;renderReviews(applyFilters());});
  const paretoSearch=$("#pareto-search");
  if(paretoSearch) paretoSearch.addEventListener("input",e=>{state.paretoQ=e.target.value;renderPareto(applyFilters());});
  $("#review-export").addEventListener("click",exportReviewCsv);
  $("#defect-search").addEventListener("input",e=>{state.defectQ=e.target.value;renderDefectsTab(applyFilters());});
  $$("#defect-cat button").forEach(btn=>btn.addEventListener("click",()=>{
    state.defectCat=btn.dataset.cat;
    $$("#defect-cat button").forEach(b=>b.classList.toggle("active",b===btn));
    renderDefectsTab(applyFilters());
  }));
  $("#defect-export").addEventListener("click",exportDefectCsv);
  $("#form-search").addEventListener("input",e=>{state.formQ=e.target.value;state.page=1;renderFormsTab(applyFilters());});
  $("#form-scope").addEventListener("change",e=>{state.formScope=e.target.value;state.page=1;renderFormsTab(applyFilters());});
  $("#form-status-filter").innerHTML=`<option value="">همه وضعیت‌ها</option>`+(DATA.formStatuses||[]).map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join("");
  $("#form-status-filter").addEventListener("change",e=>{state.formStatus=e.target.value;state.page=1;renderFormsTab(applyFilters());});
  $("#form-export").addEventListener("click",exportFormCsv);
  $("#form-export-json").addEventListener("click",exportFormJson);
  FORM_STORE.init().then(()=>{renderFormsTab(applyFilters());});
  $$("#tabs .tab").forEach(btn=>btn.addEventListener("click",()=>{
    // فیلتر سریع «عدم دریافت قطعه» فقط برای فهرست است؛ با برگشتن به
    // نمای کلی پاک می‌شود تا نوار جمع‌بندی همیشه کل اخطارهای فیلترشده را نشان دهد
    if(btn.dataset.tab==="overview" && state.quickFilter){ state.quickFilter=""; render(); }
    switchTab(btn.dataset.tab);
  }));
  $$("#trend-toggle button").forEach(btn=>btn.addEventListener("click",()=>{
    setTrendMode(btn.dataset.mode);
    renderTrend($("#trend"),applyFilters());
  }));
  $$("#bars-compare button").forEach(btn=>btn.addEventListener("click",()=>{
    state.barsCompare = btn.dataset.barscompare==="on";
    $$("#bars-compare button").forEach(b=>b.classList.toggle("active", b===btn));
    syncBarsCompareLegend();
    render();
  }));
  $$("#trend-compare button").forEach(btn=>btn.addEventListener("click",()=>{
    state.trendCompare = btn.dataset.compare!=="off";
    $$("#trend-compare button").forEach(b=>b.classList.toggle("active", b===btn));
    renderTrend($("#trend"),applyFilters());
  }));
  $("#modal-close").addEventListener("click",()=>$("#modal").classList.add("hidden"));
  $("#modal").addEventListener("click",e=>{if(e.target.id==="modal") $("#modal").classList.add("hidden");});
  document.addEventListener("keydown",e=>{if(e.key==="Escape") $("#modal").classList.add("hidden");});
}
function setTrendMode(mode){
  state.trendMode = mode;
  $$("#trend-toggle button").forEach(b=>b.classList.toggle("active", b.dataset.mode===mode));
  const hint = $("#trend-hint");
  if(hint) hint.textContent = mode==="year" ? "سال شمسی" : (state.trendCompare? "مقایسه با سال قبل" : "ماه شمسی");
}

function switchTab(tab){
  state.tab=tab;
  $$("#tabs .tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
  $$(".tab-panel").forEach(p=>p.classList.toggle("active",p.id===`tab-${tab}`));
  window.scrollTo({top:0,behavior:"smooth"});
}
function render(){
  const rows=applyFilters();
  syncSelects();
  renderCoverage(rows);
  renderRootPanel(rows);
  renderPareto(rows);
  renderRepeatPanel(rows);
  renderDonut($("#donut"),rows);
  renderStatusDonut($("#status-donut"),rows);
  renderStatusDetail(rows);
  renderActionBars(rows);
  renderTrend($("#trend"),rows);
  const barOpts=kind=>({click:barClick(kind), compare:state.barsCompare});
  // سال قبل از مجموعهٔ «بدون فیلتر سال» شمرده می‌شود؛ وگرنه همیشه صفر می‌شود
  const prevPool=applyFilters({skipYear:true});
  const withPrev=(items,field)=>{
    if(!state.barsCompare) return items;
    const {prev}=compareYears();
    return items.map(i=>Object.assign({},i,{prev: prevPool.filter(r=>Number(r.year)===prev && (r[field]||"نامشخص")===i.name).length}));
  };
  const defectItems=withPrev(groupAgg(rows,"defectGroup").sort((a,b)=>b.warnings-a.warnings).slice(0,8),"defectGroup");
  // «واحد مسئول» = فرآیند مسئول از ستون «منشاء ایراد» برگهٔ بررسی (C-Plus)
  // هر ردیف دقیقاً در یک میله می‌افتد: فرآیندهای پنج‌گانه، سپس «در حال بررسی»
  // (برگهٔ بررسی دارد ولی ریشه/منشاء ایراد ندارد) و «عدم دریافت قطعه».
  const makeItems=makeProcessItems(rows);
  const m6Items=withPrev(groupAgg(rows.filter(r=>r.m6 && r.m6!=="نامشخص"),"m6").sort((a,b)=>b.warnings-a.warnings).slice(0,7),"m6");
  syncBarsCompareLegend();
  renderBars($("#ov-defect-bars"), defectItems, "warnings", ()=> "#d92d5c", null, barOpts("defect"));
  const PROC_COLORS={"تولید":"#0b64c8","مواد اولیه":"#0e7f9a","تامین‌کننده":"#7c3aed",
    "طراحی مهندسی":"#1e4fd8","مشتری":"#0891b2","در حال بررسی":"#c47f0a",
    "عدم دریافت قطعه":"#d92d5c","بدون برگهٔ بررسی":"#94a3b8"};
  const procClick=name=>({inreview:"inreview",notreceived:"notreceived",noreview:"noreview"}[name]?barClick({inreview:"inreview",notreceived:"notreceived",noreview:"noreview"}[name]):barClick("process"))(name);
  renderBars($("#ov-make-bars"), makeItems, "warnings", i=>PROC_COLORS[i.name]||"#0b64c8", null, {click:procClick, compare:state.barsCompare});
  const procNote=$("#ov-process-note");
  if(procNote){
    const parts=makeProcessItems(rows);
    const sumParts=parts.reduce((a,i)=>a+i.warnings,0);
    procNote.innerHTML=`جمع میله‌ها = ${fmt(sumParts)} = کل اخطارها · هر اخطار دقیقاً در یک گروه`;
  }
  renderM6Overview(rows, m6Items, barOpts("m6"));
  renderBars($("#family-bars"), withPrev(groupAgg(rows,"family").sort((a,b)=>b.warnings-a.warnings).slice(0,12),"family"), "warnings",
    i=>color((rows.find(r=>r.family===i.name)||{}).group||"#0e7f9a"), i=>i.name, barOpts("family"));
  renderBars($("#product-bars"), withPrev(groupAgg(rows,"product").sort((a,b)=>b.warnings-a.warnings).slice(0,10),"product"), "warnings",
    i=>color((rows.find(r=>r.product===i.name)||{}).group||"#0e7f9a"), i=>i.name, barOpts("product"));
  renderGroupTable(rows);
  renderGroupsTab(rows);
  renderFamiliesTab(rows);
  renderProductsTab(rows);
  renderWarningsTab(rows);
  renderReviews(rows);
  renderDefectsTab(rows);
  renderFormsTab(rows);
  renderQuality(rows);
}
function toCsv(rows){
  const cols=[
    ["سریال","id"],["تاریخ","date"],["ماه","month"],["خودرو","car"],["گروه ساخت","make"],["شرح قطعه","part"],["شرح منشا","origin"],
    ["شماره فنی","tech"],["کد راهکاران","code"],["محصول راهکاران","rahkaran"],["گروه محصول","group"],["خانواده","family"],["محصول","product"],
    ["کد گروه محصول","catalogCode"],["در کاتالوگ","inCatalog"],["در دامنه","inScope"],["روش تطبیق","method"],["اطمینان","confidence"],
    ["قطعات معیوب","qty"],["نمره منفی","score"],["گرید","grade"],["وضعیت مؤثر","status"],["وضعیت ثبت‌شده","rawStatus"],["خاتمهٔ خودکار","autoClosed"],["اولویت اخطار","priorityLabel"],["نیاز به بازبینی","review"],
    ["وضعیت اقدام کوتاه مدت","stAction"],["وضعیت اقدام میان مدت","mtAction"],
    ["آنالیز علت ایراد","cause"],["شرح اقدام اصلاحی","action"],["منشاء ایراد","reviewOrigin"],["تامین‌کننده (بررسی)","supplier"],
    ["برنچ","branch"],["ایراد مشتری","defect"],["ریشهٔ ایراد","rootCause"],["قطعه در تحلیل","analysisPart"],["قطعه (گروه‌بندی)","groupPath"],["دسته‌بندی ایراد","defectCat"],["گروه فنی (کمکی)","defectGroup"],["تکرار ایراد در محصول","defectRepeat"],["علت استاندارد","causeStd"],["گروه ۶M","m6"],
    ["شماره کلیم","claimNo"],["شماره کارت نارنجی","orangeCard"],["شماره فرم 8D","form8d"],["وضعیت فرم 8D","formStatus"],["دارای برگه بررسی","hasReview"]
  ];
  const head=cols.map(c=>c[0]).join(",");
  const body=rows.map(r=>cols.map(([_,k])=>{
    let v=r[k]; if(typeof v==="boolean") v=v?"بله":"خیر"; if(v===null||v===undefined) v="";
    v=String(v).replace(/"/g,'""'); return `"${v}"`;
  }).join(",")).join("\n");
  return "\ufeff"+head+"\n"+body;
}
function exportReviewCsv(){
  const rows = reviewRows(applyFilters());
  const cols=[["سریال","id"],["تاریخ","date"],["خودرو","car"],["شرح قطعه","part"],["شماره فنی","tech"],
    ["محصول راهکاران","rahkaran"],["گروه محصول","group"],["خانواده","family"],["محصول","product"],
    ["دسته محصول (بررسی)","reviewCategory"],["آنالیز علت ایراد","cause"],["شرح اقدام اصلاحی","action"],
    ["منشاء ایراد","reviewOrigin"],["شماره کلیم","claimNo"],["شماره کارت نارنجی","orangeCard"],
    ["تعداد کلیم شماره فنی","claims"],["شماره فرم 8D","form8d"],["وضعیت","status"]];
  const head=cols.map(c=>c[0]).join(",");
  const body=rows.map(r=>cols.map(([_,k])=>{
    let v=r[k]; if(typeof v==="boolean") v=v?"بله":"خیر"; if(v===null||v===undefined) v="";
    return `"${String(v).replace(/"/g,'""')}"`;
  }).join(",")).join("\n");
  downloadCsv("\ufeff"+head+"\n"+body, "ekhtar-reviews.csv");
}

function downloadCsv(csv, filename){
  const blob=new Blob([csv],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const a=document.createElement("a");
  a.href=url; a.download=filename; a.rel="noopener";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),10000);
  const sandboxed = (()=>{ try { return window.self!==window.top; } catch(e){ return true; } })();
  if(sandboxed) showCsvFallback(csv,url,filename);
}

function exportCsv(){
  const rows=applyFilters().slice().sort(state.warningSort==="date"?byNewest:byPriority);
  downloadCsv(toCsv(rows), "ekhtar-grouped.csv");
}
function showCsvFallback(csv,url,filename="ekhtar-grouped.csv"){
  $("#modal-title").textContent="خروجی CSV";
  $("#modal-body").innerHTML=`<div class="note-box" style="margin-top:0">فایل CSV آماده است. اگر دانلود به‌صورت خودکار شروع نشد (محدودیت پیش‌نمایش)، روی دکمهٔ «دانلود» بزنید یا متن زیر را کپی کنید.</div>
    <div style="display:flex;gap:8px;margin:10px 0;flex-wrap:wrap">
      <a class="btn primary" href="${url}" download="${filename}" target="_blank" rel="noopener">دانلود فایل CSV</a>
      <button class="btn" id="copy-csv">کپی متن</button>
      <span class="muted tiny" id="copy-state"></span>
    </div>
    <textarea id="csv-text" readonly style="width:100%;height:240px;direction:ltr;text-align:left;font-family:ui-monospace,monospace;font-size:11px;border:1px solid #e2e8f0;border-radius:10px;padding:8px;background:#f8fafc"></textarea>`;
  $("#csv-text").value=csv;
  $("#modal").classList.remove("hidden");
  $("#copy-csv").addEventListener("click",async()=>{
    try{ await navigator.clipboard.writeText(csv); $("#copy-state").textContent="کپی شد ✓"; }
    catch(e){ $("#csv-text").select(); document.execCommand("copy"); $("#copy-state").textContent="کپی شد ✓"; }
  });
}
/* ------------------------------------------------- بارگذاری دادهٔ تازه ----
   هر فایل ورودی در فهرست زیر جداگانه انتخاب می‌شود؛ فایل همان‌جا روی سرور
   ذخیره می‌شود (نسخهٔ قبلی پشتیبان می‌ماند) و گزارش خودکار دوباره ساخته
   می‌شود. هیچ دادهٔ دستی (فرم 8D، اصلاح ایراد، اصلاح گروه‌بندی) پاک نمی‌شود. */
const UPLOAD_ACCEPT={
  warnings:".xlsx,.xlsm", listdata:".xlsx,.xlsm", catalog:".xlsx,.xlsm",
  review:".xlsx,.xlsm", template:".docx", manual:".xlsx,.xlsm"
};
const UPLOAD_HINTS={
  warnings:"فایل «گزارش اخطار کيفي» با شیت «گزارش اخطار کيفي» — خروجی اکسل سامانهٔ اخطارها",
  listdata:"خروجی ListData راهکاران (عنوان، کد، مشخصه فنی، ماهیت کالا)",
  catalog:"فایل گروه‌بندی محصولات (کد گروه، محصول، خانواده، گروه محصول نهایی، برنچ)",
  review:"فایل C_Plus با شیت‌های «اخطار» (برگهٔ بررسی) و «کلیم»",
  template:"قالب رسمی QA-DA-02-C با پسوند docx (برای ساخت فرم‌های 8D)",
  manual:"اختیاری: «فرم ثبت محصولات برگشتی» برای یادگیری الگوی متن ایراد"
};
let UPLOAD_STATE={inputs:[],busy:false};
function upItemHtml(item){
  const hasFile=item.exists;
  const when=item.uploaded?`بارگذاری‌شده در داشبورد`:`فایل اصلی پروژه`;
  return `<div class="up-item ${hasFile?"ok":"missing"}" data-key="${item.key}">
    <div class="up-head">
      <div class="up-title">${esc(item.label)}${item.key==="manual"?' <span class="wm-tag">اختیاری</span>':""}</div>
      <span class="badge ${hasFile?"green":"red"}">${hasFile?"موجود":"پیدا نشد"}</span>
    </div>
    <div class="up-meta">${hasFile
      ? `${esc(item.name)}<br><b>${fmt(item.sizeMB||0)} مگابایت</b> · آخرین تغییر ${esc(faDigits(item.modified||"—"))} · ${when}${item.versions?` · ${fmt(item.versions)} نسخهٔ ذخیره‌شده`:""}`
      : `فایل پیش‌فرض <b>${esc(item.defaultName)}</b> در پروژه نیست؛ نسخهٔ تازه را بارگذاری کنید.`}</div>
    <div class="up-meta">${esc(UPLOAD_HINTS[item.key]||"")}</div>
    <div class="up-actions">
      <input type="file" id="up-file-${item.key}" accept="${UPLOAD_ACCEPT[item.key]||""}">
      <button class="up-btn" data-pick="${item.key}" ${UPLOAD_STATE.busy?"disabled":""}>انتخاب و بارگذاری فایل</button>
      <span class="up-status" id="up-status-${item.key}"></span>
    </div>
    <div class="up-bar" id="up-bar-${item.key}"><i></i></div>
  </div>`;
}
function renderUploadSheet(){
  const body=$("#modal-body"); if(!body) return;
  const items=UPLOAD_STATE.inputs||[];
  $("#modal-title").textContent="به‌روزرسانی و بارگذاری دادهٔ تازه";
  body.innerHTML=`
    <div class="up-note">
      <b>دادهٔ تازه را جای فایل‌های قبلی بگذارید:</b> برای هر ردیف، فایل تازه را انتخاب کنید؛ همان لحظه به‌صورت یک نسخهٔ زمان‌دار
      در پوشهٔ <b>data/inputs</b> ذخیره می‌شود، نسخهٔ قبلی در <b>data/backups/inputs</b> می‌ماند و ساخت گزارش خودکار شروع می‌شود.
      ${location.protocol==="file:"?'<br><b>الان در حالت فایل باز است؛</b> برای بارگذاری باید داشبورد را با <b>python serve.py</b> باز کنید.':""}
      <br>در پایان، فهرست اخطارها و همهٔ نمودارها با دادهٔ جدید ساخته می‌شوند؛ <b>فرم‌های 8D، اصلاح ایرادها و اصلاح گروه‌بندی پاک نمی‌شوند.</b>
    </div>
    <div class="up-grid">${items.map(upItemHtml).join("")}</div>
    <div class="up-note" style="margin:12px 0 0">
      <b>چه فایل‌هایی لازم است؟</b>
      <ol class="up-steps" style="margin:6px 0 0">
        <li><b>گزارش اخطارهای کیفی</b> — هر بار دادهٔ جدید سامانه آمد، همین را جایگزین کنید.</li>
        <li><b>برگه‌های بررسی مشتری (C_Plus)</b> — با آن، «آنالیز علت ایراد»، «قطعه در تحلیل» و اقدام اصلاحی تازه می‌شود.</li>
        <li><b>ListData و گروه‌بندی محصولات</b> — فقط وقتی کاتالوگ راهکاران یا گروه‌بندی محصولات تغییر کرده است.</li>
        <li><b>فرم دستی برگشتی</b> (اختیاری) — اگر الگوی متن ایراد عوض شده، برای یادگیری دوباره.</li>
      </ol>
    </div>`;
  items.forEach(item=>{
    const pick=body.querySelector(`[data-pick="${item.key}"]`);
    const input=$(`#up-file-${item.key}`);
    if(!pick||!input) return;
    pick.addEventListener("click",()=>{
      if(location.protocol==="file:"){ toast("برای بارگذاری فایل، داشبورد را با python serve.py باز کنید"); return; }
      input.click();
    });
    input.addEventListener("change",()=>{ if(input.files&&input.files[0]) uploadInput(item.key,input.files[0]); });
  });
  const foot=$("#modal-foot");
  if(foot) foot.innerHTML=`<div class="muted tiny">نسخه‌های قبلی هر فایل در data/backups/inputs نگه داشته می‌شود</div>
    <div style="display:flex;gap:8px"><button class="btn primary" id="up-rebuild">⟳ ساخت دوبارهٔ گزارش با فایل‌های فعلی</button>
    <button class="btn" id="up-close">بستن</button></div>`;
  const close=$("#up-close"); if(close) close.addEventListener("click",()=>$("#modal").classList.add("hidden"));
  const rebuild=$("#up-rebuild"); if(rebuild) rebuild.addEventListener("click",()=>{ $("#modal").classList.add("hidden"); refreshDashboard(); });
  $("#modal").classList.remove("hidden");
}
async function openUploadSheet(){
  $("#modal-title").textContent="به‌روزرسانی و بارگذاری دادهٔ تازه";
  $("#modal-body").innerHTML='<div class="wm-empty">در حال خواندن وضعیت فایل‌های ورودی…</div>';
  $("#modal-foot").innerHTML="";
  $("#modal").classList.remove("hidden");
  try{
    const response=await fetch("/api/inputs",{cache:"no-store"});
    const payload=await response.json();
    UPLOAD_STATE.inputs=payload.inputs||[];
  }catch(error){
    UPLOAD_STATE.inputs=[];
  }
  if(!UPLOAD_STATE.inputs.length){
    $("#modal-body").innerHTML='<div class="wm-empty">وضعیت فایل‌های ورودی خوانده نشد. داشبورد را با <b>python serve.py</b> باز کنید.</div>';
    return;
  }
  renderUploadSheet();
}
function uploadInput(key,file){
  if(UPLOAD_STATE.busy) return;
  UPLOAD_STATE.busy=true;
  const status=$(`#up-status-${key}`), bar=$(`#up-bar-${key}`), fill=bar&&bar.querySelector("i");
  const fileName=file.name;
  const sizeMB=file.size/(1024*1024);
  if(sizeMB>60){
    if(status){ status.className="up-status fail"; status.textContent=`حجم فایل ${fmt(sizeMB)} مگابایت است؛ حداکثر ۶۰ مگابایت.`; }
    UPLOAD_STATE.busy=false; return;
  }
  if(status){ status.className="up-status busy"; status.textContent="در حال ارسال فایل…"; }
  if(bar){ bar.classList.add("show"); }
  $$(".up-btn").forEach(b=>b.disabled=true);
  const xhr=new XMLHttpRequest();
  xhr.open("POST","/api/inputs/upload");
  xhr.setRequestHeader("X-Input-Key",key);
  xhr.setRequestHeader("X-File-Name",encodeURIComponent(fileName));
  xhr.setRequestHeader("Content-Type","application/octet-stream");
  xhr.upload.onprogress=e=>{
    if(!e.lengthComputable||!fill||!status) return;
    const percent=Math.round(e.loaded/e.total*100);
    fill.style.width=percent+"%";
    status.textContent=`در حال ارسال فایل… ${faDigits(percent)}٪`;
  };
  xhr.onload=()=>{
    UPLOAD_STATE.busy=false;
    $$(".up-btn").forEach(b=>b.disabled=false);
    let payload={};
    try{ payload=JSON.parse(xhr.responseText||"{}"); }catch(error){ payload={}; }
    if(xhr.status>=200&&xhr.status<300&&payload.ok){
      if(status){ status.className="up-status done"; status.textContent=`${fileName} ذخیره شد ✓`; }
      if(fill){ fill.style.width="100%"; }
      if(payload.inputs) UPLOAD_STATE.inputs=payload.inputs;
      toast(`فایل ${fileName} بارگذاری شد — ساخت گزارش شروع شد`);
      waitForUploadBuild(fileName);
    }else{
      if(status){ status.className="up-status fail"; status.textContent=(payload.error||"بارگذاری ناموفق بود"); }
      if(bar){ bar.classList.remove("show"); }
      toast(payload.error||"بارگذاری فایل ناموفق بود");
    }
  };
  xhr.onerror=()=>{
    UPLOAD_STATE.busy=false;
    $$(".up-btn").forEach(b=>b.disabled=false);
    if(status){ status.className="up-status fail"; status.textContent="ارتباط با سرور قطع شد"; }
    toast("ارتباط با سرور قطع شد — دوباره تلاش کنید");
  };
  xhr.send(file);
}
async function waitForUploadBuild(fileName){
  const status=$("#modal-body .up-status.busy")||null;
  const banner=$("#update-banner-text");
  for(let i=0;i<900;i++){
    await new Promise(resolve=>setTimeout(resolve,1500));
    let snapshot=null;
    try{
      const response=await fetch("/api/status",{cache:"no-store"});
      snapshot=await response.json();
    }catch(error){ continue; }
    setAutoBadge(snapshot);
    if(banner) banner.textContent=`در حال ساخت گزارش با فایل‌های تازه… ${Math.floor(snapshot.elapsed||0)} ثانیه`;
    if(snapshot.state==="done"){
      toast("گزارش با دادهٔ تازه ساخته شد ✓");
      if(snapshot.buildId) PAGE_BUILD=snapshot.buildId;
      setTimeout(()=>reloadNewBuild(),900);
      return;
    }
    if(snapshot.state==="error"){
      toast("ساخت گزارش ناموفق بود: "+(snapshot.error||""));
      if(status){ status.className="up-status fail"; status.textContent="فایل ذخیره شد اما ساخت گزارش خطا داد"; }
      showUpdateBanner("فایل ذخیره شد؛ ساخت گزارش خطا داد — شرح در output/rebuild.log");
      return;
    }
  }
  toast("ساخت گزارش طول کشید؛ خودکار تازه می‌شود");
}
function syncBarsCompareLegend(){
  const legend=$("#bars-legend");
  if(!legend) return;
  if(!state.barsCompare){ legend.innerHTML=""; return; }
  const {cur,prev}=compareYears();
  legend.innerHTML=`<span><span class="sw" style="background:#0b64c8"></span>سال ${faDigits(cur)}</span>
    <span><span class="sw" style="background:#cbd8e6"></span>سال ${faDigits(prev)}</span>
    <span>درصد تغییر کنار عدد هر ردیف</span>`;
}
function showUpdateBanner(text){
  const banner=$("#update-banner"); if(!banner) return;
  const label=$("#update-banner-text"); if(label && text) label.textContent=text;
  banner.classList.add("show");
}
function hideUpdateBanner(){
  const banner=$("#update-banner"); if(banner) banner.classList.remove("show");
}
function reloadNewBuild(){
  FORM_DIRTY=false;
  location.replace("/?v="+Date.now());
}
function setAutoBadge(status){
  const badge=$("#auto-refresh-badge"), text=$("#auto-refresh-text"), dot=badge&&badge.querySelector(".dot-live");
  if(!badge) return;
  if(!status || status.watching===false){
    badge.style.display="none"; return;
  }
  badge.style.display="inline-flex";
  if(dot) dot.classList.toggle("off", status.state!=="running");
  if(text) text.textContent = status.state==="running"
    ? `در حال ساخت گزارش… ${Math.floor(status.elapsed||0)} ثانیه`
    : "به‌روزرسانی خودکار: روشن";
}
async function pollStatus(){
  if(location.protocol==="file:") return;
  try{
    const response=await fetch("/api/status",{cache:"no-store"});
    if(!response.ok) return;
    const status=await response.json();
    setAutoBadge(status);
    if(!status.buildId) return;
    if(PAGE_BUILD===null){ PAGE_BUILD=status.buildId; return; }
    if(status.buildId!==PAGE_BUILD){
      PAGE_BUILD=status.buildId;
      if(FORM_DIRTY){
        showUpdateBanner("نسخهٔ تازه آماده است — اول فرم 8D را ذخیره کنید");
      }else{
        reloadNewBuild();
      }
    }
  }catch(error){ /* سرور در دسترس نیست؛ صفحه ثابت می‌ماند */ }
}
async function refreshDashboard(){
  const btn=$("#refresh-data"); if(!btn) return;
  if(location.protocol==="file:"){
    toast("این دکمه در حالت سرور کار می‌کند؛ داشبورد را با «python serve.py» باز کنید");
    return;
  }
  if(FORM_DIRTY){
    showUpdateBanner("اول فرم 8D را ذخیره کنید، بعد به‌روزرسانی بزنید");
    toast("تغییرات ذخیره‌نشدهٔ فرم وجود دارد؛ اول «ذخیرهٔ فرم» را بزنید");
    return;
  }
  const original=btn.textContent;
  btn.disabled=true;
  btn.textContent="در حال ساخت گزارش…";
  try{
    const response=await fetch("/api/rebuild",{method:"POST",headers:{"Accept":"application/json"}});
    const started=await response.json().catch(()=>({}));
    if(!response.ok && response.status!==409) throw new Error(started.error||"شروع ساخت گزارش ناموفق بود");
    for(let i=0;i<900;i++){
      await new Promise(resolve=>setTimeout(resolve,1500));
      const statusResponse=await fetch("/api/status",{cache:"no-store"});
      const status=await statusResponse.json();
      setAutoBadge(status);
      if(status.state==="done"){
        if(status.buildId) PAGE_BUILD=status.buildId;
        btn.textContent="بارگذاری نسخهٔ جدید…";
        reloadNewBuild();
        return;
      }
      if(status.state==="error") throw new Error(status.error||"ساخت گزارش ناموفق بود");
      btn.textContent=`در حال ساخت گزارش… ${Math.floor(status.elapsed||0)} ثانیه`;
    }
    throw new Error("ساخت گزارش بیش از حد طول کشید");
  }catch(error){
    toast((error.message||"خطا در به‌روزرسانی")+" — می‌توانید python build_report.py را دستی اجرا کنید");
    btn.disabled=false; btn.textContent=original;
  }
}
$("#refresh-data").addEventListener("click", refreshDashboard);
const openUploadBtn=$("#open-upload");
if(openUploadBtn) openUploadBtn.addEventListener("click", openUploadSheet);
const applyBanner=$("#update-banner-apply");
if(applyBanner) applyBanner.addEventListener("click", reloadNewBuild);
const laterBanner=$("#update-banner-later");
if(laterBanner) laterBanner.addEventListener("click", ()=>hideUpdateBanner());
window.addEventListener("beforeunload", event=>{
  if(!FORM_DIRTY) return;
  event.preventDefault();
  event.returnValue = "";
});
renderMeta();
initFilters();
render();
pollStatus();
setInterval(pollStatus, 5000);
</script>
</body>
</html>
"""
