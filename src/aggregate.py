"""جدول‌های خلاصهٔ مشترک برای گزارش اکسل و داشبورد HTML."""

from __future__ import annotations

import pandas as pd

from .taxonomy import OUT_GROUP

WARNING_COUNT = "تعداد اخطار"
DEFECTIVE = "تعداد قطعات معیوب"
SCORE = "نمره منفی مرجع"
SCORE_MAKER = "نمره منفی سازنده"
OPEN = "اخطار باز"
GRADE_A = "گرید A"


def kpis(frame: pd.DataFrame) -> dict:
    total = len(frame)
    in_scope = int((frame["گروه محصول نهایی"] != OUT_GROUP).sum())
    in_catalog = int((frame["در فایل گروه‌بندی"] == "بله").sum())
    return {
        "warnings": total,
        "products": int(frame["محصول"].nunique()),
        "families": int(frame["خانواده محصول"].nunique()),
        "groups": int(frame.loc[frame["گروه محصول نهایی"] != OUT_GROUP, "گروه محصول نهایی"].nunique()),
        "defective": int(frame[DEFECTIVE].fillna(0).sum()),
        "score": int(frame[SCORE].fillna(0).sum()),
        "score_maker": int(frame[SCORE_MAKER].fillna(0).sum()),
        "open": int((frame["وضعیت اخطار"] != "خاتمه يافته").sum()),
        "grade_a": int((frame["گرید ایراد"] == "A").sum()),
        "in_scope": in_scope,
        "in_scope_pct": (in_scope / total if total else 0),
        "in_catalog": in_catalog,
        "in_catalog_pct": (in_catalog / total if total else 0),
        "review": int((frame["نیاز به بازبینی"] == "بله").sum()),
        "reviewed": int((frame["دارای برگه بررسی"] == "بله").sum()) if "دارای برگه بررسی" in frame.columns else 0,
        "claims": int(pd.to_numeric(frame.get("تعداد کلیم"), errors="coerce").fillna(0).sum()) if "تعداد کلیم" in frame.columns else 0,
        "short_term": int((frame["وضعیت اخطار"] == "اقدام كوتاه مدت").sum()),
        "medium_term": int((frame["وضعیت اخطار"] == "اقدام ميان مدت").sum()),
        "tech": int(frame["شماره فنی"].replace("", pd.NA).dropna().nunique()),
        "serial": int(frame["سریال اخطار"].nunique()),
    }


def stage_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """وضعیت اخطار: خاتمه‌یافته، در اقدام کوتاه‌مدت، در اقدام میان‌مدت، تنظیم."""
    table = summarize(frame, "وضعیت اخطار")
    total = table[WARNING_COUNT].sum() or 1
    table["سهم"] = table[WARNING_COUNT] / total
    return table


def action_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """وضعیت تایید اقدامات کوتاه‌مدت و میان‌مدت."""
    rows: list[dict] = []
    for label, column in (("اقدام کوتاه مدت", "وضعیت اقدام کوتاه مدت"), ("اقدام میان مدت", "وضعیت اقدام میان مدت")):
        if column not in frame.columns:
            continue
        counts = frame[column].fillna("ثبت نشده").replace("", "ثبت نشده").value_counts()
        for status, count in counts.items():
            rows.append(
                {
                    "نوع اقدام": label,
                    "وضعیت تایید": str(status),
                    WARNING_COUNT: int(count),
                    "سهم": float(count) / len(frame) if len(frame) else 0.0,
                }
            )
    return pd.DataFrame(rows)


def review_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """خلاصهٔ برگه‌های بررسی به تفکیک منشا ایراد و دسته اعلامی مشتری."""
    if "دارای برگه بررسی" not in frame.columns:
        return pd.DataFrame()
    reviewed = frame[frame["دارای برگه بررسی"] == "بله"]
    if reviewed.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for label, column in (
        ("منشاء ایراد", "منشاء ایراد"),
        ("دسته اعلامی مشتری", "دسته محصول (بررسی)"),
    ):
        if column not in reviewed.columns:
            continue
        counts = reviewed[column].fillna("ثبت نشده").replace("", "ثبت نشده").value_counts()
        for value, count in counts.items():
            rows.append({"نوع دسته‌بندی": label, "مقدار": str(value), WARNING_COUNT: int(count)})
    return pd.DataFrame(rows)


def summarize(frame: pd.DataFrame, by: str | list[str], with_latest: bool = False) -> pd.DataFrame:
    by_list = [by] if isinstance(by, str) else by
    grouped = (
        frame.groupby(by_list, dropna=False)
        .agg(
            **{
                "اخطار": ("سریال اخطار", "size"),
                "قطعات معیوب": (DEFECTIVE, "sum"),
                "نمره منفی": (SCORE, "sum"),
                "نمره منفی سازنده": (SCORE_MAKER, "sum"),
                "اخطار باز": ("وضعیت اخطار", lambda s: int((s != "خاتمه يافته").sum())),
                "گرید A": ("گرید ایراد", lambda s: int((s == "A").sum())),
                "محصولات": ("محصول", "nunique"),
                "خانواده‌ها": ("خانواده محصول", "nunique"),
                "نیاز به بازبینی": ("نیاز به بازبینی", lambda s: int((s == "بله").sum())),
            }
        )
        .reset_index()
        .rename(columns={"اخطار": WARNING_COUNT, "قطعات معیوب": DEFECTIVE, "نمره منفی": SCORE, "نمره منفی سازنده": SCORE_MAKER})
    )
    total_warn = grouped[WARNING_COUNT].sum() or 1
    total_def = grouped[DEFECTIVE].sum() or 1
    total_score = grouped[SCORE].sum() or 1
    grouped["سهم اخطار"] = grouped[WARNING_COUNT] / total_warn
    grouped["سهم قطعات معیوب"] = grouped[DEFECTIVE] / total_def
    grouped["سهم نمره منفی"] = grouped[SCORE] / total_score
    if with_latest:
        valid = frame.dropna(subset=["سال", "ماه"]).copy()
        if valid.empty:
            grouped["آخرین ماه"] = ""
        else:
            valid["_key"] = valid["سال"].astype(int) * 100 + valid["ماه"].astype(int)
            latest = valid.loc[valid.groupby(by_list)["_key"].idxmax(), by_list + ["ماه شمسی"]]
            latest = latest.rename(columns={"ماه شمسی": "آخرین ماه"})
            grouped = grouped.merge(latest, on=by_list, how="left")
            grouped["آخرین ماه"] = grouped["آخرین ماه"].fillna("")
    return grouped.sort_values([WARNING_COUNT, DEFECTIVE], ascending=False).reset_index(drop=True)


def group_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return summarize(frame, "گروه محصول نهایی")


def family_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return summarize(frame, ["گروه محصول نهایی", "خانواده محصول"])


def product_summary(frame: pd.DataFrame) -> pd.DataFrame:
    table = summarize(frame, ["گروه محصول نهایی", "خانواده محصول", "محصول"], with_latest=True)
    codes = (
        frame.groupby(["گروه محصول نهایی", "خانواده محصول", "محصول"])["کد گروه محصول"]
        .agg(lambda s: next((v for v in s if v), ""))
        .reset_index()
    )
    table = table.merge(codes, on=["گروه محصول نهایی", "خانواده محصول", "محصول"], how="left")
    in_catalog = (
        frame.groupby(["گروه محصول نهایی", "خانواده محصول", "محصول"])["در فایل گروه‌بندی"]
        .agg(lambda s: "بله" if (s == "بله").any() else "خیر")
        .reset_index()
    )
    table = table.merge(in_catalog, on=["گروه محصول نهایی", "خانواده محصول", "محصول"], how="left")
    order = ["گروه محصول نهایی", "خانواده محصول", "محصول", "کد گروه محصول", "در فایل گروه‌بندی"]
    rest = [col for col in table.columns if col not in order]
    return table[order + rest]


def vehicle_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return summarize(frame, "گروه خودرو")


def year_summary(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame.dropna(subset=["سال"]).copy()
    if valid.empty:
        return pd.DataFrame()
    valid["سال"] = valid["سال"].astype(int)
    grouped = (
        valid.groupby("سال", dropna=False)
        .agg(
            **{
                "اخطار": ("سریال اخطار", "size"),
                "قطعات معیوب": (DEFECTIVE, "sum"),
                "نمره منفی": (SCORE, "sum"),
                "اخطار باز": ("وضعیت اخطار", lambda s: int((s != "خاتمه يافته").sum())),
                "نیاز به بازبینی": ("نیاز به بازبینی", lambda s: int((s == "بله").sum())),
            }
        )
        .reset_index()
        .sort_values("سال")
    )
    return grouped


def month_summary(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame.dropna(subset=["سال", "ماه"]).copy()
    valid["سال"] = valid["سال"].astype(int)
    valid["ماه"] = valid["ماه"].astype(int)
    valid["کلید ماه"] = valid["سال"] * 100 + valid["ماه"]
    grouped = (
        valid.groupby(["کلید ماه", "سال", "ماه", "ماه شمسی"], dropna=False)
        .agg(
            **{
                "اخطار": ("سریال اخطار", "size"),
                "قطعات معیوب": (DEFECTIVE, "sum"),
                "نمره منفی": (SCORE, "sum"),
                "اخطار باز": ("وضعیت اخطار", lambda s: int((s != "خاتمه يافته").sum())),
            }
        )
        .reset_index()
        .sort_values("کلید ماه")
    )
    return grouped


def grade_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return summarize(frame, ["گرید ایراد", "وضعیت اخطار"])


def out_of_scope_summary(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[frame["گروه محصول نهایی"] == OUT_GROUP]
    if out.empty:
        return pd.DataFrame()
    return summarize(out, ["خانواده محصول", "محصول"])


def bucket_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """خانواده/محصولاتی که گروه آن‌ها مشخص است ولی در فایل گروه‌بندی نیستند."""
    buckets = frame[(frame["در دامنه گروه‌بندی"] == "بله") & (frame["در فایل گروه‌بندی"] == "خیر")]
    if buckets.empty:
        return pd.DataFrame()
    keys = ["گروه محصول نهایی", "خانواده محصول", "محصول"]
    table = summarize(buckets, keys)
    titles = (
        buckets.groupby(keys)["نام محصول راهکاران"]
        .agg(lambda s: (s[s != ""].mode().iloc[0] if (s != "").any() else ""))
        .reset_index()
        .rename(columns={"نام محصول راهکاران": "عنوان راهکاران (نمونه)"})
    )
    return table.merge(titles, on=keys, how="left")


def top_parts(frame: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    table = (
        frame.groupby("شرح قطعه", dropna=False)
        .agg(
            **{
                "اخطار": ("سریال اخطار", "size"),
                "قطعات معیوب": (DEFECTIVE, "sum"),
                "نمره منفی": (SCORE, "sum"),
                "محصول غالب": ("محصول", lambda s: s.mode().iloc[0] if not s.mode().empty else ""),
                "خانواده غالب": ("خانواده محصول", lambda s: s.mode().iloc[0] if not s.mode().empty else ""),
            }
        )
        .reset_index()
        .sort_values(["اخطار", "قطعات معیوب"], ascending=False)
        .head(limit)
    )
    return table


def tech_table(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame[frame["شماره فنی"] != ""].copy()
    if valid.empty:
        return pd.DataFrame()

    def mode_or_empty(series: pd.Series) -> str:
        mode = series.mode()
        return str(mode.iloc[0]) if not mode.empty else ""

    def first_value(series: pd.Series) -> str:
        return next((v for v in series if v), "")

    g = valid.groupby("شماره فنی")
    table = pd.DataFrame(
        {
            "اخطار": g["سریال اخطار"].size(),
            "قطعات معیوب": g[DEFECTIVE].sum(),
            "نمره منفی": g[SCORE].sum(),
            "شرح قطعه": g["شرح قطعه"].agg(mode_or_empty),
            "کد راهکاران": g["کد راهکاران"].agg(first_value),
            "نام محصول راهکاران": g["نام محصول راهکاران"].agg(mode_or_empty),
            "گروه محصول نهایی": g["گروه محصول نهایی"].agg(mode_or_empty),
            "خانواده محصول": g["خانواده محصول"].agg(mode_or_empty),
            "محصول": g["محصول"].agg(mode_or_empty),
            "روش تطبیق": g["روش تطبیق"].agg(mode_or_empty),
            "اطمینان": g["اطمینان"].agg(mode_or_empty),
            "کاندیدهای شماره فنی": g["تعداد کاندید شماره فنی"].max(),
        }
    ).reset_index()
    return table.sort_values(["اخطار", "قطعات معیوب"], ascending=False).reset_index(drop=True)


def date_quality(frame: pd.DataFrame) -> dict:
    return {
        "missing_dates": int((frame["ماه شمسی"] == "نامشخص").sum()),
        "start": int(frame.loc[frame["سال"].notna(), "سال"].min()) if frame["سال"].notna().any() else None,
        "end": int(frame.loc[frame["سال"].notna(), "سال"].max()) if frame["سال"].notna().any() else None,
    }


def branch_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """خلاصه بر اساس برنچ (ELE / EMS / POL)."""
    if "برنچ" not in frame.columns:
        return pd.DataFrame()
    table = summarize(frame, "برنچ")
    total = table[WARNING_COUNT].sum() or 1
    table["سهم"] = table[WARNING_COUNT] / total
    return table.sort_values(WARNING_COUNT, ascending=False).reset_index(drop=True)
