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
                "origin": _clean_text(row.get("منشاء ایراد", "")),
                "claimNo": _clean_text(row.get("شماره کلیم", "")),
                "orangeCard": _clean_text(row.get("شماره کارت نارنجی", "")),
                "reviewCategory": _clean_text(row.get("دسته محصول (بررسی)", "")),
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
  --bg:#f1f5f9; --card:#ffffff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0;
  --teal:#0f766e; --teal2:#14b8a6; --blue:#2563eb; --violet:#7c3aed; --amber:#d97706;
  --rose:#e11d48; --cyan:#0891b2; --lime:#65a30d; --slate:#64748b; --shadow:0 10px 30px rgba(15,23,42,.06);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"Vazirmatn","IRANSansX","IRANSans","Segoe UI",Tahoma,Arial,sans-serif;
  background:var(--bg); color:var(--ink); line-height:1.7; font-size:14px;
}
a{color:inherit}
.topbar{
  background:linear-gradient(135deg,#0b3b38 0%,#0f766e 55%,#0d9488 100%);
  color:#fff; padding:22px 28px; display:flex; gap:20px; align-items:center; justify-content:space-between;
  flex-wrap:wrap;
}
.brand{display:flex; gap:14px; align-items:center}
.logo{
  width:52px;height:52px;border-radius:16px;background:rgba(255,255,255,.14);
  display:grid;place-items:center;font-size:24px;font-weight:800;border:1px solid rgba(255,255,255,.25)
}
.brand h1{font-size:22px;margin:0 0 2px;font-weight:800;letter-spacing:-.2px}
.brand p{margin:0;color:#ccfbf1;font-size:12.5px}
.meta{font-size:12px;color:#ccfbf1;text-align:left;line-height:1.9}
.meta b{color:#fff;font-weight:700}
.tabs{
  position:sticky; top:0; z-index:30; background:rgba(255,255,255,.94); backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line); display:flex; gap:4px; padding:10px 22px; overflow-x:auto;
}
.tab{
  border:0;background:transparent;padding:9px 14px;border-radius:10px;font-family:inherit;font-size:13px;
  color:var(--muted);cursor:pointer;white-space:nowrap;font-weight:600;
}
.tab:hover{background:#f1f5f9;color:var(--ink)}
.tab.active{background:#ccfbf1;color:#0f766e}
.filters{
  padding:14px 22px; background:#fff; border-bottom:1px solid var(--line);
  display:grid; grid-template-columns:repeat(7,minmax(120px,1fr)); gap:10px; align-items:end;
}
.field label{display:block;font-size:11px;color:var(--muted);margin-bottom:4px;font-weight:600}
.field select,.field input{
  width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:#f8fafc;
  font-family:inherit;font-size:12.5px;color:var(--ink);outline:none;
}
.field select:focus,.field input:focus{border-color:var(--teal2);background:#fff;box-shadow:0 0 0 3px rgba(20,184,166,.12)}
.filter-actions{display:flex;gap:6px}
.btn{
  border:1px solid var(--line);background:#fff;border-radius:10px;padding:9px 12px;font-family:inherit;
  font-size:12.5px;cursor:pointer;color:var(--ink);font-weight:600;white-space:nowrap;
}
.btn:hover{background:#f8fafc}
.btn.primary{background:var(--teal);border-color:var(--teal);color:#fff}
.btn.primary:hover{background:#0d5f59}
.btn.ghost{background:transparent}
main{padding:20px 22px 40px;max-width:1560px;margin:0 auto}
.tab-panel{display:none}
.tab-panel.active{display:block;animation:fade .18s ease}
@keyframes fade{from{opacity:.4;transform:translateY(3px)}to{opacity:1;transform:none}}
.kpi-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.kpi:before{content:"";position:absolute;inset-inline-start:0;top:0;bottom:0;width:4px;background:var(--teal2)}
.kpi.blue:before{background:var(--blue)} .kpi.violet:before{background:var(--violet)}
.kpi.amber:before{background:var(--amber)} .kpi.rose:before{background:var(--rose)} .kpi.slate:before{background:var(--slate)}
.kpi .label{font-size:11.5px;color:var(--muted);font-weight:600}
.kpi .value{font-size:24px;font-weight:800;letter-spacing:-.5px;margin-top:2px}
.kpi .sub{font-size:11px;color:var(--muted)}
.grid-2{display:grid;grid-template-columns:1.05fr 1fr;gap:14px;margin-bottom:14px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:var(--shadow);min-width:0}
.card h3{margin:0 0 12px;font-size:14px;font-weight:800;display:flex;align-items:center;gap:8px}
.card h3 .hint{font-size:10.5px;color:var(--muted);font-weight:500}
.card .empty{color:var(--muted);font-size:12px;padding:24px;text-align:center}
.donut-wrap{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.donut-legend{display:flex;flex-direction:column;gap:7px;flex:1;min-width:200px}
.legend-item{display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;border-radius:8px;padding:3px 5px}
.legend-item:hover{background:#f8fafc}
.dot{width:9px;height:9px;border-radius:99px;flex:none}
.legend-item .name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.legend-item .num{color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.bars{display:flex;flex-direction:column;gap:9px}
.bar-row{display:grid;grid-template-columns:minmax(120px,1.3fr) 3fr auto;gap:10px;align-items:center;font-size:12px}
.bar-row .label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155}
.bar-row .track{height:10px;background:#eef2f7;border-radius:99px;overflow:hidden}
.bar-row .fill{height:100%;border-radius:99px;min-width:2px;transition:width .25s ease}
.bar-row .val{font-variant-numeric:tabular-nums;color:#475569;font-size:11.5px;min-width:52px;text-align:left}
.seg{display:inline-flex;background:#f1f5f9;border-radius:10px;padding:3px;gap:2px;margin-bottom:8px}
.seg button{border:0;background:transparent;padding:5px 12px;border-radius:8px;font-family:inherit;font-size:11.5px;font-weight:700;color:var(--muted);cursor:pointer}
.seg button.active{background:#fff;color:var(--teal);box-shadow:0 1px 4px rgba(15,23,42,.12)}
.trend-wrap{position:relative;width:100%;overflow:hidden}
.trend-wrap svg{width:100%;height:auto;display:block}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;max-height:640px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:12px}
thead th{
  position:sticky;top:0;z-index:2;background:#f8fafc;color:#334155;font-weight:700;text-align:right;
  padding:10px 9px;border-bottom:1px solid var(--line);white-space:nowrap;font-size:11.5px;
}
thead th.sortable{cursor:pointer;user-select:none}
thead th.sortable:hover{color:var(--teal)}
tbody td{padding:9px;border-bottom:1px solid #f1f5f9;vertical-align:middle}
tbody tr:hover{background:#f8fafc}
tbody tr.clickable{cursor:pointer}
tbody tr:last-child td{border-bottom:0}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.muted{color:var(--muted)}
.tiny{font-size:10.5px}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:10.5px;font-weight:700;white-space:nowrap}
.badge.green{background:#ccfbf1;color:#0f766e}
.badge.blue{background:#dbeafe;color:#1d4ed8}
.badge.amber{background:#fef3c7;color:#92400e}
.badge.red{background:#ffe4e6;color:#be123c}
.badge.slate{background:#e2e8f0;color:#475569}
.badge.violet{background:#ede9fe;color:#6d28d9}
.group-pill{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.group-pill .dot{width:7px;height:7px}
.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.toolbar .right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.search-mini{position:relative}
.search-mini input{padding:8px 30px 8px 10px;border:1px solid var(--line);border-radius:10px;font-family:inherit;font-size:12.5px;width:260px;background:#f8fafc}
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
.quality-note{background:#fffbeb;border:1px solid #fde68a;color:#92400e;border-radius:12px;padding:10px 12px;font-size:11.5px;margin-top:10px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px;margin-top:6px}
.form-grid .field{display:flex;flex-direction:column;gap:4px}
.form-grid .field.full{grid-column:1/-1}
.form-grid label{font-size:11px;font-weight:700;color:#334155}
.form-grid input,.form-grid textarea,.form-grid select{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:9px;font-family:inherit;font-size:12px;background:#f8fafc}
.form-grid textarea{min-height:52px;resize:vertical}
.form-actions{display:flex;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap}
.form-state{font-size:11px;color:var(--muted)}
.store-badge{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;padding:4px 10px;border-radius:99px}
.store-badge.server{background:#ccfbf1;color:#0f766e}
.store-badge.local{background:#fef3c7;color:#92400e}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#0f172a;color:#fff;padding:10px 18px;border-radius:12px;font-size:12.5px;z-index:200;opacity:0;transition:opacity .25s;pointer-events:none}
.toast.show{opacity:1}
.modal{position:fixed;inset:0;background:rgba(15,23,42,.55);display:grid;place-items:center;z-index:100;padding:18px}
.modal.hidden{display:none}
.modal-box{background:#fff;border-radius:18px;max-width:820px;width:100%;max-height:90vh;overflow:auto;box-shadow:0 30px 80px rgba(0,0,0,.3)}
.modal-head{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#fff;z-index:2}
.modal-head h2{margin:0;font-size:16px}
.modal-body{padding:18px 20px}
.kv{display:grid;grid-template-columns:140px 1fr;gap:8px 12px;font-size:12.5px}
.kv .k{color:var(--muted);font-weight:600}
.kv .v{color:var(--ink)}
.note-box{background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:10px 12px;font-size:12px;margin-top:12px;white-space:pre-wrap}
footer{padding:18px 22px;color:var(--muted);font-size:11px;text-align:center}
@media(max-width:1200px){.kpi-grid{grid-template-columns:repeat(3,1fr)}.filters{grid-template-columns:repeat(4,1fr)}.grid-3{grid-template-columns:1fr}}
@media(max-width:760px){
  .kpi-grid{grid-template-columns:repeat(2,1fr)} .filters{grid-template-columns:repeat(2,1fr)}
  .grid-2,.mini-grid{grid-template-columns:1fr} .topbar{padding:16px}
  main{padding:14px} .search-mini input{width:100%} .bar-row{grid-template-columns:minmax(90px,1.2fr) 2fr auto}
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
    <button class="btn" id="refresh-data" title="ساخت دوبارهٔ گزارش از فایل‌های ورودی (بدون دانلود مجدد پوشه)" style="background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.35);padding:9px 14px;white-space:nowrap">⟳ به‌روزرسانی داده‌ها</button>
  </div>
</header>
<nav class="tabs" id="tabs">
  <button class="tab active" data-tab="overview">نمای کلی</button>
  <button class="tab" data-tab="groups">گروه‌های محصول</button>
  <button class="tab" data-tab="families">خانواده‌ها</button>
  <button class="tab" data-tab="products">محصولات</button>
  <button class="tab" data-tab="warnings">فهرست اخطارها</button>
  <button class="tab" data-tab="reviews">بررسی اخطارها</button>
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
  <div class="filter-actions" style="grid-column:span 4">
    <button class="btn" id="reset">پاک‌کردن</button>
    <button class="btn primary" id="export">خروجی CSV</button>
    <button class="btn" id="print">چاپ</button>
  </div>
</div>
<main>
  <section class="tab-panel active" id="tab-overview">
    <div class="kpi-grid" id="kpis"></div>
    <div class="grid-2">
      <div class="card"><h3>سهم گروه‌های محصول <span class="hint">بر اساس تعداد اخطار</span></h3><div id="donut"></div></div>
      <div class="card"><h3 style="justify-content:space-between">روند اخطارها <span class="hint" id="trend-hint">سال شمسی</span></h3>
        <div class="seg" id="trend-toggle"><button data-mode="year" class="active">سالانه</button><button data-mode="month">ماهانه</button></div>
        <div class="trend-wrap" id="trend"></div></div>
    </div>
    <div class="grid-3">
      <div class="card"><h3>وضعیت اخطار <span class="hint">خاتمه‌یافته / باز</span></h3><div id="status-donut"></div></div>
      <div class="card"><h3>اقدام کوتاه مدت <span class="hint" id="st-count"></span></h3><div class="bars" id="st-bars"></div></div>
      <div class="card"><h3>اقدام میان مدت <span class="hint" id="mt-count"></span></h3><div class="bars" id="mt-bars"></div></div>
    </div>
    <div class="grid-2">
      <div class="card"><h3>پرتکرارترین خانواده‌ها <span class="hint">۱۲ خانواده اول</span></h3><div class="bars" id="family-bars"></div></div>
      <div class="card"><h3>پرتکرارترین محصولات <span class="hint">۱۰ محصول اول</span></h3><div class="bars" id="product-bars"></div></div>
    </div>
    <div class="card">
      <h3>خلاصه گروه‌ها <span class="hint">با کلیک روی هر ردیف، فیلتر گروه اعمال می‌شود</span></h3>
      <div class="table-wrap"><table id="group-table"></table></div>
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
      <div class="table-wrap"><table id="warnings-table"></table></div>
      <div class="pager" id="warnings-pager"></div>
    </div>
  </section>

  <section class="tab-panel" id="tab-reviews">
    <div class="kpi-grid" id="review-kpis" style="grid-template-columns:repeat(4,1fr)"></div>
    <div class="grid-2">
      <div class="card"><h3>منشا ایراد <span class="hint">بر اساس برگه‌های بررسی</span></h3><div class="bars" id="origin-bars"></div></div>
      <div class="card"><h3>دسته محصول اعلامی مشتری <span class="hint">مقایسه با گروه‌بندی داخلی</span></h3><div class="bars" id="category-bars"></div></div>
    </div>
    <div class="card">
      <div class="toolbar">
        <h3 style="margin:0">برگه‌های بررسی اخطار <span class="hint" id="review-count"></span></h3>
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

<div class="modal hidden" id="modal">
  <div class="modal-box">
    <div class="modal-head"><h2 id="modal-title">جزئیات</h2><button class="btn" id="modal-close">بستن</button></div>
    <div class="modal-body" id="modal-body"></div>
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
  "Cluster Instrument":"#0f766e",
  "Nodes":"#2563eb",
  "EMS-توسعه و نگاشت موتور":"#7c3aed",
  "TP-قطعات جانبی قوای محرکه":"#d97706",
  "SBS-سیستم های ایمنی ترمز":"#e11d48",
  "Switch":"#0891b2",
  "Display Unit":"#65a30d",
  "خارج از دامنه گروه‌بندی":"#94a3b8",
  "سایر":"#a855f7",
  "درایو کولر":"#f59e0b"
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

const state = {group:"",family:"",product:"",car:"",grade:"",status:"",priority:"",year:"",from:"",to:"",q:"",tab:"overview",warningSort:"priority",
  review:"",branch:"",defect:"",defectCat:"all",productQ:"",warningQ:"",reviewQ:"",defectQ:"",formQ:"",formStatus:"",formScope:"working",
  page:1,pageSize:25,productSort:{key:"warnings",dir:-1},trendMode:"year"};
let currentProducts = [];
let currentWarnings = [];
let currentReviews = [];

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
function applyFilters(){
  const q = state.q.trim().toLowerCase();
  return DATA.warnings.filter(r=>{
    if(state.group && r.group!==state.group) return false;
    if(state.family && r.family!==state.family) return false;
    if(state.product && r.product!==state.product) return false;
    if(state.branch && r.branch!==state.branch) return false;
    if(state.defect && r.defect!==state.defect) return false;
    if(state.car && r.car!==state.car) return false;
    if(state.grade && r.grade!==state.grade) return false;
    if(state.status==="open" && !r.open) return false;
    if(state.status==="closed" && r.open) return false;
    if(state.priority && String(r.priority)!==state.priority) return false;
    if(state.review==="yes" && !r.hasReview) return false;
    if(state.review==="no" && r.hasReview) return false;
    if(state.year && String(r.year)!==state.year) return false;
    if(state.from && monthKey(r) && monthKey(r)<Number(state.from)) return false;
    if(state.to && monthKey(r) && monthKey(r)>Number(state.to)) return false;
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

function renderKpis(rows){
  const total=rows.length, qty=sum(rows,"qty"), score=sum(rows,"score"), open=rows.filter(r=>r.open).length;
  const auto=rows.filter(r=>r.autoClosed).length;
  const inScope=rows.filter(r=>r.inScope).length, inCatalog=rows.filter(r=>r.inCatalog).length;
  const products=uniq(rows,"product"), review=rows.filter(r=>r.review).length;
  const reviewed=rows.filter(r=>r.hasReview).length;
  const cards=[
    ["اخطارهای کیفی",fmt(total),"ردیف انتخاب‌شده",""],
    ["قطعات معیوب",fmt(qty),"جمع تعداد قطعات","blue"],
    ["نمره منفی مرجع",fmt(score),"مجموع امتیاز","violet"],
    ["محصولات درگیر",fmt(products),"محصول متمایز","amber"],
    ["پوشش گروه‌بندی",pct(total?inScope/total:0),`${fmt(inScope)} ردیف در دامنه`,"rose"],
    ["اخطارهای باز",fmt(open),`${fmt(auto)} خودکار خاتمه · ${fmt(reviewed)} برگه بررسی (${pct(total?reviewed/total:0)})`,"slate"]
  ];
  $("#kpis").innerHTML=cards.map(([l,v,s,c])=>`<div class="kpi ${c}"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");
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
  $$(".legend-item",el).forEach(item=>item.addEventListener("click",()=>{
    state.group=item.dataset.group; state.family=""; state.product=""; syncSelects(); render();
  }));
}

function renderTrend(el,rows){
  const mode=state.trendMode;
  // فقط بازهٔ انتخاب‌شده (یا بازهٔ داده) رسم می‌شود؛ ماه‌های بدون اخطار در دو سر بازه حذف می‌شوند
  const counts=new Map();
  const monthLabels=new Map();
  rows.forEach(r=>{
    const k = mode==="year" ? String(r.year||"") : String(r.monthKey||"");
    if(!k || k==="0") return;
    counts.set(k,(counts.get(k)||0)+1);
    if(mode!=="year") monthLabels.set(k,r.month||"");
  });
  let keys = Array.from(counts.keys()).sort();
  if(!keys.length){ empty(el,"در بازهٔ انتخاب‌شده اخطاری وجود ندارد"); return; }
  // پر کردن ماه‌های خالی بین دو سر بازه تا نمودار پیوسته باشد
  if(mode==="month"){
    const allKeys = Array.from(new Set(DATA.warnings.map(r=>r.monthKey).filter(Boolean))).sort((a,b)=>a-b);
    const first = Number(keys[0]), last = Number(keys[keys.length-1]);
    keys = allKeys.filter(k=>Number(k)>=first && Number(k)<=last).map(String);
  }
  const data=keys.map(k=>({key:k,label: mode==="year" ? k : (monthLabels.get(k) || monthLabel(k)), value:counts.get(k)||0}));
  const max=Math.max(1,...data.map(d=>d.value));
  const W=820,H=270,pad={l:40,r:14,t:16,b:38};
  const iw=W-pad.l-pad.r, ih=H-pad.t-pad.b;
  const step=data.length>1?iw/(data.length-1):0;
  const x=i=>pad.l+i*step;
  const y=v=>pad.t+ih-(v/max)*ih;
  const pts=data.map((d,i)=>`${x(i)},${y(d.value)}`).join(" ");
  const area=`${pad.l},${pad.t+ih} ${pts} ${x(data.length-1)},${pad.t+ih}`;
  let grid="",labels="";
  for(let g=0;g<=4;g++){
    const val=max*g/4, yy=pad.t+ih-(g/4)*ih;
    grid+=`<line x1="${pad.l}" y1="${yy}" x2="${W-pad.r}" y2="${yy}" stroke="#eef2f7" stroke-width="1"/>`;
    grid+=`<text x="${pad.l-6}" y="${yy+4}" text-anchor="end" font-size="9" fill="#94a3b8">${fmt(Math.round(val))}</text>`;
  }
  const labelStep = mode==="year" ? Math.ceil(data.length/14) : Math.ceil(data.length/10);
  data.forEach((d,i)=>{ if(i%labelStep===0 || i===data.length-1){
    labels+=`<text x="${x(i)}" y="${H-14}" text-anchor="middle" font-size="9" fill="#64748b">${esc(faDigits(d.label))}</text>`;
  }});
  const dots=data.map((d,i)=>`<circle cx="${x(i)}" cy="${y(d.value)}" r="3" fill="#0f766e"><title>${esc(faDigits(d.label))}: ${fmt(d.value)} اخطار</title></circle>`).join("");
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img"><defs><linearGradient id="grad" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#14b8a6" stop-opacity=".35"/><stop offset="1" stop-color="#14b8a6" stop-opacity="0"/></linearGradient></defs>${grid}<polygon points="${area}" fill="url(#grad)"/><polyline points="${pts}" fill="none" stroke="#0f766e" stroke-width="2.5"/>${dots}${labels}</svg>`;
}

function monthLabel(key){
  const m = DATA.warnings.find(r=>String(r.monthKey)===String(key));
  if(m) return m.month;
  const k = Number(key); const month = k%100; const year = Math.floor(k/100);
  const names = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"];
  return `${names[month-1]||""} ${year}`;
}

function renderBars(el,items,valueKey="warnings",colorFn=null,labelFn=null){
  if(!items.length){ empty(el); return; }
  const max=Math.max(1,...items.map(i=>i[valueKey]||0));
  el.innerHTML=items.map(item=>{
    const p=(item[valueKey]||0)/max*100;
    const col=colorFn?colorFn(item):"#0f766e";
    const label=labelFn?labelFn(item):item.name;
    return `<div class="bar-row"><div class="label" title="${esc(label)}">${esc(label)}</div><div class="track"><div class="fill" style="width:${p}%;background:${col}"></div></div><div class="val">${fmt(item[valueKey]||0)}</div></div>`;
  }).join("");
}

const STAGE_COLORS = {
  "خاتمه يافته":"#0f766e",
  "اقدام ميان مدت":"#d97706",
  "اقدام كوتاه مدت":"#e11d48",
  "تنظيم":"#7c3aed"
};
function stageName(s){ return s==="خاتمه يافته" ? "خاتمه‌یافته" : s || "نامشخص"; }

function renderStatusDonut(el, rows){
  if(!rows.length){ empty(el); return; }
  const counts = {};
  rows.forEach(r=>{ const k=r.status||"نامشخص"; counts[k]=(counts[k]||0)+1; });
  const closed = rows.filter(r=>!r.open).length;
  const open = rows.length - closed;
  const total = rows.length || 1;
  const size=190, r0=68, c=95, stroke=22, circ=2*Math.PI*r0;
  const closedLen = circ*(closed/total);
  const arcs = `<circle cx="${c}" cy="${c}" r="${r0}" fill="none" stroke="#0f766e" stroke-width="${stroke}" stroke-dasharray="${closedLen} ${circ-closedLen}" stroke-dashoffset="0" transform="rotate(-90 ${c} ${c})"><title>خاتمه‌یافته: ${fmt(closed)}</title></circle>
    <circle cx="${c}" cy="${c}" r="${r0}" fill="none" stroke="#e11d48" stroke-width="${stroke}" stroke-dasharray="${circ-closedLen} ${circ-(circ-closedLen)}" stroke-dashoffset="${-closedLen}" transform="rotate(-90 ${c} ${c})"><title>باز: ${fmt(open)}</title></circle>`;
  const order = ["خاتمه يافته","اقدام ميان مدت","اقدام كوتاه مدت","تنظيم"];
  const legend = order.filter(k=>counts[k]).map(k=>`<div class="legend-item" data-stage="${esc(k)}">
      <span class="dot" style="background:${STAGE_COLORS[k]||"#94a3b8"}"></span>
      <span class="name">${esc(stageName(k))}</span><span class="num">${fmt(counts[k])} · ${pct(counts[k]/total)}</span></div>`).join("");
  el.innerHTML=`<div class="donut-wrap"><svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${c}" cy="${c}" r="${r0}" fill="none" stroke="#eef2f7" stroke-width="${stroke}"></circle>${arcs}
    <text x="${c}" y="${c-4}" text-anchor="middle" font-size="20" font-weight="800" fill="#0f172a">${fmt(open)}</text>
    <text x="${c}" y="${c+14}" text-anchor="middle" font-size="10" fill="#64748b">اخطار باز</text>
  </svg><div class="donut-legend">${legend}</div></div>`;
}

function renderActionBars(rows){
  const st = state.stActionCounts || {};
  const stItems = groupAgg(rows,"stAction").sort((a,b)=>b.warnings-a.warnings);
  const mtItems = groupAgg(rows,"mtAction").sort((a,b)=>b.warnings-a.warnings);
  $("#st-count").textContent = `${fmt(rows.filter(r=>r.status==="اقدام كوتاه مدت").length)} اخطار در این مرحله`;
  $("#mt-count").textContent = `${fmt(rows.filter(r=>r.status==="اقدام ميان مدت").length)} اخطار در این مرحله`;
  renderBars($("#st-bars"), stItems.slice(0,6), "warnings", i=>i.name==="تاييد مشتري" ? "#0f766e" : "#e11d48");
  renderBars($("#mt-bars"), mtItems.slice(0,6), "warnings", i=>i.name==="تاييد مشتري" ? "#0f766e" : (i.name==="غيرضروري" ? "#94a3b8" : "#d97706"));
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
  if(q) items = items.filter(r=>[r.id,r.part,r.cause,r.action,r.origin,r.product,r.claimNo].join(" ").toLowerCase().includes(q));
  return items;
}

function renderReviews(rows){
  renderReviewKpis(rows);
  const reviewed = rows.filter(r=>r.hasReview);
  const origins = groupAgg(reviewed,"origin").sort((a,b)=>b.warnings-a.warnings);
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
    <th>سریال</th><th>تاریخ</th><th>خودرو</th><th>شرح قطعه</th><th>محصول</th><th>آنالیز علت ایراد</th><th>اقدام اصلاحی</th><th>منشاء</th><th>کلیم</th><th>فرم 8D</th><th>وضعیت</th></tr></thead>
    <tbody>${page.map(r=>`<tr class="clickable" data-id="${r.id}">
      <td class="num">${esc(r.id)}</td><td class="tiny">${esc(faDigits(r.date))}</td><td class="tiny">${esc(r.car)}</td>
      <td class="tiny" title="${esc(r.part)}">${esc(r.part.length>40?r.part.slice(0,40)+"…":r.part)}</td>
      <td class="tiny">${esc(r.product)}</td>
      <td class="tiny" title="${esc(r.cause)}">${esc(r.cause? (r.cause.length>44?r.cause.slice(0,44)+"…":r.cause) : "—")}</td>
      <td class="tiny" title="${esc(r.action)}">${esc(r.action? (r.action.length>34?r.action.slice(0,34)+"…":r.action) : "—")}</td>
      <td class="tiny">${esc(r.origin||"—")}</td>
      <td class="num tiny">${esc(r.claimNo||"—")}</td>
      <td class="tiny">${esc(r.form8d)}</td>
      <td>${statusBadge(r)}</td></tr>`).join("")}</tbody>`;
  $$("#reviews-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id))));
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
  $$("#group-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>{ state.group=tr.dataset.group; state.family=""; state.product=""; syncSelects(); render(); }));
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
  renderBars($("#families-bars"),items.slice(0,14),"warnings",()=>"#0f766e",i=>i.name);
  renderBars($("#families-qty"),items.slice().sort((a,b)=>b.qty-a.qty).slice(0,14),"qty",()=>"#0891b2",i=>i.name);
  $("#families-table").innerHTML=`<thead><tr><th>خانواده محصول</th><th>گروه محصول</th><th>اخطار</th><th>قطعات معیوب</th><th>نمره منفی</th><th>محصولات</th><th>اخطار باز</th><th>نیاز به بازبینی</th></tr></thead>
  <tbody>${items.map(i=>{
    const sample=rows.find(r=>r.family===i.name)||{};
    return `<tr><td>${esc(i.name)}</td><td class="muted">${esc(gLabel(sample.group||""))}</td><td class="num">${fmt(i.warnings)}</td><td class="num">${fmt(i.qty)}</td><td class="num">${fmt(i.score)}</td><td class="num">${fmt(i.products)}</td><td class="num">${fmt(i.open)}</td><td class="num">${fmt(rows.filter(r=>r.family===i.name&&r.review).length)}</td></tr>`;
  }).join("")}</tbody>`;
}
function renderProductBars(rows){
  renderBars($("#product-bars"),groupAgg(rows,"product").sort((a,b)=>b.warnings-a.warnings).slice(0,10),"warnings",i=>color((rows.find(r=>r.product===i.name)||{}).group||"#0f766e"),i=>i.name);
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
  const total=items.length, pages=Math.max(1,Math.ceil(total/state.pageSize));
  if(state.page>pages) state.page=pages;
  const start=(state.page-1)*state.pageSize;
  const page=items.slice(start,start+state.pageSize);
  $("#warnings-count").textContent=`${fmt(total)} ردیف · نمایش ${fmt(page.length)} ردیف`;
  $("#warnings-table").innerHTML=`<thead><tr>
    <th>سریال</th><th>تاریخ</th><th>خودرو</th><th>شرح قطعه</th><th>ایراد مشتری</th><th>شماره فنی</th><th>محصول راهکاران</th><th>خانواده</th><th>محصول</th><th>گروه</th><th>برنچ</th><th>گرید</th><th>وضعیت</th><th>اولویت</th><th>قطعات</th><th>نمره</th><th>تطبیق</th></tr></thead>
    <tbody>${page.map(r=>`<tr class="clickable" data-id="${r.id}">
      <td class="num">${esc(r.id)}</td><td class="muted tiny">${esc(faDigits(r.date))}</td><td class="tiny">${esc(r.car)}</td>
      <td title="${esc(r.part)}">${esc(r.part.length>46?r.part.slice(0,46)+"…":r.part)}</td>
      <td class="tiny" title="${esc(r.defect)}">${esc(r.defect||"—")} ${r.defectRepeat>1?`<span class="badge red">×${fmt(r.defectRepeat)}</span>`:""}</td>
      <td class="tiny">${esc(r.tech||"—")}</td><td class="tiny" title="${esc(r.rahkaran)}">${esc(r.rahkaran.length>34?r.rahkaran.slice(0,34)+"…":r.rahkaran||"—")}</td>
      <td class="tiny">${esc(r.family)}</td><td class="tiny">${esc(r.product)}</td>
      <td class="tiny"><span class="group-pill"><span class="dot" style="background:${color(r.group)}"></span>${esc(gLabel(r.group))}</span></td>
      <td class="tiny">${esc(r.branch||"—")}</td>
      <td class="num">${esc(r.grade)}</td><td>${statusBadge(r)}</td><td class="tiny">${priorityBadge(r)}</td><td class="num">${fmt(r.qty)}</td><td class="num">${fmt(r.score)}</td>
      <td>${confBadge(r.confidence)} ${reviewBadge(r)}</td></tr>`).join("")}</tbody>`;
  $$("#warnings-table tbody tr").forEach(tr=>tr.addEventListener("click",()=>openWarning(Number(tr.dataset.id))));
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
  renderBars($("#method-bars"),methods.slice(0,10),"warnings",()=>"#0f766e",i=>i.name);
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
  renderBars($("#defect-bars"),items.slice(0,10),"warnings",()=>"#e11d48",i=>i.name);
  const m6=groupAgg(rows.filter(r=>r.m6&&r.m6!=="نامشخص"),"m6").sort((a,b)=>b.warnings-a.warnings);
  renderBars($("#m6-bars"),m6,"warnings",i=>i.name==="تجهیزات"?"#0f766e":"#d97706",i=>i.name);

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
    root_cause:[r.causeStd?`علت استاندارد: ${r.causeStd}`:"",r.cause?`آنالیز علت: ${r.cause}`:"",r.origin?`منشاء: ${r.origin}`:""].filter(Boolean).join("\n"),
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
  const fill=$("#fill-suggest");
  if(fill) fill.addEventListener("click",()=>{
    const map={
      problem:[r.part?`شرح قطعه: ${r.part}`:"",r.error?`شرح خطا: ${r.error}`:"",r.car?`خودرو: ${r.car}`:""].filter(Boolean).join("\n"),
      root_cause:[r.causeStd?`علت استاندارد: ${r.causeStd}`:"",r.cause?`آنالیز علت: ${r.cause}`:"",r.origin?`منشاء: ${r.origin}`:""].filter(Boolean).join("\n"),
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

function openWarning(id){
  const r=DATA.warnings.find(x=>x.id===id); if(!r) return;
  $("#modal-title").textContent=`اخطار ${r.id}`;
  $("#modal-body").innerHTML=`<div class="kv">
    <div class="k">تاریخ تایید</div><div class="v">${esc(faDigits(r.date))}</div>
    <div class="k">گروه خودرو</div><div class="v">${esc(r.car)} · ${esc(r.make)}</div>
    <div class="k">شرح قطعه</div><div class="v">${esc(r.part)}</div>
    <div class="k">شرح منشا</div><div class="v">${esc(r.origin||"—")}</div>
    <div class="k">شماره فنی</div><div class="v">${esc(r.tech||"—")}</div>
    <div class="k">محصول راهکاران</div><div class="v">${esc(r.rahkaran||"—")} ${r.code?`<span class="muted tiny">(${esc(r.code)})</span>`:""}</div>
    <div class="k">گروه محصول</div><div class="v"><span class="group-pill"><span class="dot" style="background:${color(r.group)}"></span>${esc(r.group)}</span></div>
    <div class="k">خانواده</div><div class="v">${esc(r.family)}</div>
    <div class="k">محصول</div><div class="v"><b>${esc(r.product)}</b></div>
    <div class="k">کد گروه محصول</div><div class="v">${esc(r.catalogCode||"—")}</div>
    <div class="k">روش تطبیق</div><div class="v">${esc(r.method)}</div>
    <div class="k">اطمینان</div><div class="v">${confBadge(r.confidence)} ${r.review?'<span class="badge red">نیاز به بازبینی</span>':""}</div>
    <div class="k">کاندیدهای شماره فنی</div><div class="v">${fmt(r.candidates)} ${r.mismatch?'<span class="badge amber">مغایرت خودرو</span>':""}</div>
    <div class="k">قطعات معیوب</div><div class="v">${fmt(r.qty)}</div>
    <div class="k">نمره منفی</div><div class="v">${fmt(r.score)} (سازنده: ${fmt(r.scoreMaker)})</div>
    <div class="k">گرید / وضعیت</div><div class="v">${esc(r.grade)} · ${statusBadge(r)}</div>
    <div class="k">اولویت اخطار</div><div class="v">${priorityBadge(r)} ${r.rawStatus&&r.rawStatus!==r.status?`<span class="muted tiny">ثبت‌شده: ${esc(r.rawStatus)}</span>`:""}</div>
    ${r.autoClosed?`<div class="k">خاتمهٔ خودکار</div><div class="v">این اخطار با وضعیت «${esc(r.rawStatus)}» ثبت شده بود؛ چون قدیمی‌تر از یک سال است، خودکار خاتمه‌یافته در نظر گرفته شد.</div>`:""}
    <div class="k">محل صدور</div><div class="v">${esc(r.location||"—")}</div>
    <div class="k">نوع ایراد / خطا</div><div class="v">${esc(r.type||"—")} · ${esc(r.error||"—")}</div>
    <div class="k">وضعیت اقدام</div><div class="v">${esc(stageName(r.status))} · کوتاه‌مدت: ${esc(r.stAction||"—")} · میان‌مدت: ${esc(r.mtAction||"—")}</div>
    <div class="k">شماره فرم 8D</div><div class="v"><b>${esc(r.form8d)}</b> ${r.hasReview?'<span class="badge green">برگه بررسی دارد</span>':'<span class="badge amber">بدون برگه بررسی</span>'}</div>
    <div class="k">برنچ</div><div class="v">${esc(r.branch||"—")} ${r.branchSource?`<span class="muted tiny">(${esc(r.branchSource)})</span>`:""}</div>
    <div class="k">ایراد مشتری</div><div class="v">${esc(r.defect||"—")} ${defectCatBadge(r.defectCat)} ${r.defectGroup?`<span class="muted tiny">گروه فنی: ${esc(r.defectGroup)}</span>`:""} ${r.defectRepeat>1?`<span class="badge red">${fmt(r.defectRepeat)} بار در این محصول</span>`:""}</div>
    <div class="k">علت استاندارد / ۶M</div><div class="v">${esc(r.causeStd||"—")} ${r.m6&&r.m6!=="نامشخص"?`· <span class="badge violet">${esc(r.m6)}</span>`:""}</div>
    <div class="k">شماره کلیم / کارت نارنجی</div><div class="v">${esc(r.claimNo||"—")} · ${esc(r.orangeCard||"—")}</div>
    <div class="k">تعداد کلیم شماره فنی</div><div class="v">${fmt(r.claims)} (پذیرفته‌شده: ${fmt(r.claimsAccepted)})</div>
  </div>
  ${(r.cause||r.action||r.origin)?`<div class="note-box"><b>آنالیز علت ایراد:</b> ${esc(r.cause||"—")}
<b>شرح اقدام اصلاحی:</b> ${esc(r.action||"—")}
<b>منشاء ایراد:</b> ${esc(r.origin||"—")} ${r.reviewCategory?` · <span class="muted">دسته اعلامی مشتری: ${esc(r.reviewCategory)}</span>`:""}</div>`:`<div class="note-box muted">برای این اخطار برگهٔ بررسی ثبت نشده است؛ فرم 8D با اطلاعات سرصفحه ساخته شده و بخش‌های علت/اقدام باید تکمیل شود.</div>`}
  ${r.notes?`<div class="note-box"><b>توضیحات:</b>\n${esc(r.notes)}</div>`:""}
  ${r.form8d && r.form8d!=="—" ? `<div id="form8d-editor">${formEditorHtml(r)}</div>` : '<div class="note-box muted">برای این اخطار فرم 8D تعریف نشده است.</div>'}`;
  $("#modal").classList.remove("hidden");
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
    Object.assign(state,{group:"",family:"",product:"",branch:"",defect:"",car:"",grade:"",status:"",priority:"",year:"",from:"",to:"",q:"",review:"",productQ:"",warningQ:"",reviewQ:"",defectQ:"",formQ:"",formStatus:"",page:1,warningSort:"priority"});
    $("#f-q").value=""; $("#product-search").value=""; $("#warning-search").value=""; $("#review-search").value="";
    $("#defect-search").value=""; $("#form-search").value=""; $("#form-status-filter").value=""; $("#f-branch").value=""; $("#form-scope").value="working";
    syncSelects(); refreshMonthSelects();
    $("#f-car").value="";$("#f-grade").value="";$("#f-status").value="";$("#f-priority").value="";$("#warning-sort").value="priority";$("#f-year").value="";$("#f-review").value="";$("#f-from").value="";$("#f-to").value="";
    render();
  });
  $("#export").addEventListener("click",exportCsv);
  $("#print").addEventListener("click",()=>window.print());
  $("#page-size").addEventListener("change",e=>{state.pageSize=Number(e.target.value);state.page=1;render();});
  $("#product-search").addEventListener("input",e=>{state.productQ=e.target.value;state.page=1;renderProductsTab(applyFilters());});
  $("#warning-search").addEventListener("input",e=>{state.warningQ=e.target.value;state.page=1;renderWarningsTab(applyFilters());});
  $("#warning-sort").addEventListener("change",e=>{state.warningSort=e.target.value;state.page=1;renderWarningsTab(applyFilters());});
  $("#review-search").addEventListener("input",e=>{state.reviewQ=e.target.value;state.page=1;renderReviews(applyFilters());});
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
  $$("#tabs .tab").forEach(btn=>btn.addEventListener("click",()=>switchTab(btn.dataset.tab)));
  $$("#trend-toggle button").forEach(btn=>btn.addEventListener("click",()=>{
    setTrendMode(btn.dataset.mode);
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
  if(hint) hint.textContent = mode==="year" ? "سال شمسی" : "ماه شمسی";
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
  renderKpis(rows);
  renderDonut($("#donut"),rows);
  renderStatusDonut($("#status-donut"),rows);
  renderActionBars(rows);
  renderTrend($("#trend"),rows);
  renderBars($("#family-bars"),groupAgg(rows,"family").sort((a,b)=>b.warnings-a.warnings).slice(0,12),"warnings",i=>color((rows.find(r=>r.family===i.name)||{}).group||"#0f766e"),i=>i.name);
  renderProductBars(rows);
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
    ["آنالیز علت ایراد","cause"],["شرح اقدام اصلاحی","action"],["منشاء ایراد","origin"],
    ["برنچ","branch"],["ایراد مشتری","defect"],["دسته‌بندی ایراد","defectCat"],["گروه فنی (کمکی)","defectGroup"],["تکرار ایراد در محصول","defectRepeat"],["علت استاندارد","causeStd"],["گروه ۶M","m6"],
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
    ["منشاء ایراد","origin"],["شماره کلیم","claimNo"],["شماره کارت نارنجی","orangeCard"],
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
async function refreshDashboard(){
  const btn=$("#refresh-data"); if(!btn) return;
  if(location.protocol==="file:"){
    toast("این دکمه در حالت سرور کار می‌کند؛ داشبورد را با «python serve.py» باز کنید");
    return;
  }
  const original=btn.innerHTML;
  btn.disabled=true;
  const label=text=>{btn.textContent=text;};
  label("در حال ساخت گزارش…");
  try{
    const response=await fetch("/api/rebuild",{method:"POST",headers:{"Accept":"application/json"}});
    const started=await response.json().catch(()=>({}));
    if(!response.ok && response.status!==409) throw new Error(started.error||"شروع ساخت گزارش ناموفق بود");
    for(let i=0;i<900;i++){
      await new Promise(resolve=>setTimeout(resolve,1500));
      const statusResponse=await fetch("/api/rebuild",{cache:"no-store"});
      const status=await statusResponse.json();
      if(status.state==="done"){
        label("بارگذاری نسخهٔ جدید…");
        location.replace("/?v="+Date.now());
        return;
      }
      if(status.state==="error") throw new Error(status.error||"ساخت گزارش ناموفق بود");
      label(`در حال ساخت گزارش… ${Math.floor(status.elapsed||0)} ثانیه`);
    }
    throw new Error("ساخت گزارش بیش از حد طول کشید");
  }catch(error){
    toast((error.message||"خطا در به‌روزرسانی")+" — می‌توانید python build_report.py را دستی اجرا کنید");
    btn.disabled=false; btn.innerHTML=original;
  }
}
$("#refresh-data").addEventListener("click", refreshDashboard);
renderMeta();
initFilters();
render();
</script>
</body>
</html>
"""
