"""تولید گزارش اکسل چندبرگی با قالب‌بندی فارسی و راست‌به‌چپ."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .aggregate import (
    DEFECTIVE,
    branch_summary,
    action_summary,
    SCORE,
    WARNING_COUNT,
    bucket_summary,
    date_quality,
    family_summary,
    group_summary,
    kpis,
    month_summary,
    out_of_scope_summary,
    product_summary,
    review_summary,
    stage_summary,
    tech_table,
    year_summary,
    top_parts,
    vehicle_summary,
)
from .defects import cause_summary, defect_summary, m6_summary, M6_UNKNOWN
from .taxonomy import OUT_GROUP

TITLE_COLOR = "0F3D3E"
HEADER_COLOR = "0F766E"
ACCENT_COLOR = "14B8A6"
LIGHT_ROW = "F0FDFA"
BORDER_COLOR = "CBD5E1"
PERSIAN_FONT = "Tahoma"

THIN = Side(style="thin", color=BORDER_COLOR)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _to_python(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # pragma: no cover
            return value
    return value


def _title(ws, row: int, columns: int, text: str, subtitle: str = "") -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=columns)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(name=PERSIAN_FONT, size=16, bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=TITLE_COLOR)
    cell.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[row].height = 32
    row += 1
    if subtitle:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=columns)
        cell = ws.cell(row=row, column=1, value=subtitle)
        cell.font = Font(name=PERSIAN_FONT, size=10, color="334155")
        cell.fill = PatternFill("solid", fgColor="E2E8F0")
        cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 24
        row += 1
    return row


def _header(ws, row: int, columns: int) -> None:
    for col in range(1, columns + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(name=PERSIAN_FONT, size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_COLOR)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[row].height = 34


def _widths(ws, columns: list[str], override: dict[str, int] | None = None) -> None:
    override = override or {}
    for index, name in enumerate(columns, start=1):
        width = override.get(name)
        if width is None:
            if any(key in name for key in ("توضیحات", "شرح", "نام محصول", "محصول (شرح")):
                width = 46
            elif any(key in name for key in ("گروه", "خانواده", "روش", "وضعیت", "محل", "سازنده", "صادر")):
                width = 26
            elif any(key in name for key in ("کد", "شماره", "سریال")):
                width = 16
            else:
                width = 16
        ws.column_dimensions[get_column_letter(index)].width = width


def _write_table(
    ws,
    frame: pd.DataFrame,
    start_row: int,
    title: str = "",
    subtitle: str = "",
    widths: dict[str, int] | None = None,
    number_formats: dict[str, str] | None = None,
    freeze: bool = True,
    max_rows: int | None = None,
) -> tuple[int, int]:
    columns = list(frame.columns)
    row = start_row
    if title:
        row = _title(ws, row, max(len(columns), 6), title, subtitle)
    header_row = row
    for index, name in enumerate(columns, start=1):
        ws.cell(row=header_row, column=index, value=name)
    _header(ws, header_row, len(columns))
    number_formats = number_formats or {}

    data = frame if max_rows is None else frame.head(max_rows)
    for offset, (_, record) in enumerate(data.iterrows(), start=1):
        excel_row = header_row + offset
        for index, name in enumerate(columns, start=1):
            value = _to_python(record[name])
            cell = ws.cell(row=excel_row, column=index, value=value)
            cell.font = Font(name=PERSIAN_FONT, size=9, color="0F172A")
            cell.border = BORDER
            if offset % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=LIGHT_ROW)
            if name in number_formats:
                cell.number_format = number_formats[name]
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif isinstance(value, (int, float)):
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=False)

    last_row = header_row + len(data)
    if len(data):
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(columns))}{last_row}"
    if freeze and len(columns):
        ws.freeze_panes = ws.cell(row=header_row + 1, column=min(3, len(columns) + 1))
    _widths(ws, columns, widths)
    return header_row, last_row


def _bar_from_table(ws, header_row: int, last_row: int, name_col: int, value_col: int, anchor: str, title: str, width=22, height=10):
    if last_row <= header_row:
        return
    chart = BarChart()
    chart.type = "bar"
    chart.style = 10
    chart.title = title
    chart.height = height
    chart.width = width
    data = Reference(ws, min_col=value_col, min_row=header_row, max_row=last_row)
    cats = Reference(ws, min_col=name_col, min_row=header_row + 1, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.legend = None
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    ws.add_chart(chart, anchor)


def _pie_from_table(ws, header_row: int, last_row: int, name_col: int, value_col: int, anchor: str, title: str, width=16, height=10):
    if last_row <= header_row:
        return
    chart = PieChart()
    chart.title = title
    chart.height = height
    chart.width = width
    data = Reference(ws, min_col=value_col, min_row=header_row, max_row=last_row)
    cats = Reference(ws, min_col=name_col, min_row=header_row + 1, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    ws.add_chart(chart, anchor)


def _line_from_table(ws, header_row: int, last_row: int, name_col: int, value_col: int, anchor: str, title: str, width=28, height=10):
    if last_row <= header_row:
        return
    chart = LineChart()
    chart.title = title
    chart.height = height
    chart.width = width
    data = Reference(ws, min_col=value_col, min_row=header_row, max_row=last_row)
    cats = Reference(ws, min_col=name_col, min_row=header_row + 1, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.y_axis.title = "تعداد اخطار"
    ws.add_chart(chart, anchor)


def _kpi_table(frame: pd.DataFrame) -> pd.DataFrame:
    values = kpis(frame)
    rows = [
        ("تعداد اخطارهای کیفی", values["warnings"], "ردیف"),
        ("تعداد قطعات معیوب", values["defective"], "قطعه"),
        ("مجموع نمره منفی مرجع", values["score"], "امتیاز"),
        ("مجموع نمره منفی سازنده", values["score_maker"], "امتیاز"),
        ("اخطارهای باز (غیر خاتمه‌یافته)", values["open"], "اخطار"),
        ("اخطارهای گرید A", values["grade_a"], "اخطار"),
        ("تعداد محصولات درگیر", values["products"], "محصول"),
        ("تعداد خانواده‌های درگیر", values["families"], "خانواده"),
        ("در دامنه گروه‌بندی", values["in_scope"], "اخطار"),
        ("درصد در دامنه", values["in_scope_pct"], "درصد"),
        ("در فایل گروه‌بندی (کد/نام محصول)", values["in_catalog"], "اخطار"),
        ("درصد در فایل گروه‌بندی", values["in_catalog_pct"], "درصد"),
        ("نیاز به بازبینی", values["review"], "اخطار"),
        ("برگه بررسی ثبت‌شده", values.get("reviewed", 0), "اخطار"),
        ("اخطار در اقدام کوتاه‌مدت", values.get("short_term", 0), "اخطار"),
        ("اخطار در اقدام میان‌مدت", values.get("medium_term", 0), "اخطار"),
        ("مجموع کلیم‌های شماره فنی", values.get("claims", 0), "کلیم"),
        ("تعداد شماره فنی یکتا", values["tech"], "شماره"),
    ]
    return pd.DataFrame(rows, columns=["شاخص", "مقدار", "واحد"])


def build_excel(
    enriched: pd.DataFrame,
    product_map: pd.DataFrame,
    tech_map: pd.DataFrame,
    output_path: str | Path,
    source_names: dict[str, str] | None = None,
    eight_d: pd.DataFrame | None = None,
    grouping_checks: pd.DataFrame | None = None,
    unmatched_review: pd.DataFrame | None = None,
    entries: dict[str, dict] | None = None,
) -> Path:
    source_names = source_names or {}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.properties.title = "گزارش دسته‌بندی اخطارهای کیفی بر اساس گروه محصول"
    wb.properties.creator = "Arena Agent"
    wb.properties.description = "دسته‌بندی اخطارهای کیفی مشتری بر اساس گروه، خانواده و محصول"

    # ---------------------------------------------------------------- راهنما
    ws = wb.active
    ws.title = "راهنما"
    ws.sheet_view.rightToLeft = True
    row = _title(
        ws,
        1,
        8,
        "گزارش دسته‌بندی اخطارهای کیفی بر اساس محصول، خانواده و گروه محصول",
        "اتصال شماره فنی و نام قطعهٔ مشتری به کاتالوگ محصولات راهکاران و فایل گروه‌بندی محصولات",
    )
    guide_rows = [
        ("۱. منابع ورودی", ""),
        ("فایل اخطار کیفی مشتری", source_names.get("warnings", "گزارش اخطار کيفي (3).xlsx")),
        ("فایل محصولات نهایی (کد راهکاران)", source_names.get("listdata", "ListData.xlsx")),
        ("فایل گروه‌بندی محصولات", source_names.get("catalog", "گروه بندی محصولات.xlsx")),
        ("", ""),
        ("۲. منطق اتصال", ""),
        ("گام اول", "شماره فنی اخطار با ستون «مشخصه فنی» فایل ListData تطبیق داده می‌شود (حذف IK، صفر ابتدایی، ارقام فارسی/عربی و علائم)."),
        ("گام دوم", "کد محصول راهکاران با «کد گروه محصول» فایل گروه‌بندی تطبیق داده می‌شود؛ اگر کد نبود، نام محصول با قواعد خانواده/محصول تطبیق داده می‌شود."),
        ("گام سوم", "برای ردیف‌های بدون شماره فنی، «شرح قطعه» و در صورت نیاز «شرح منشا» و «گروه خودرو» برای تشخیص خانواده و محصول به کار می‌رود."),
        ("گام چهارم", "اگر محصول در فایل گروه‌بندی نباشد ولی خانواده/گروه آن مشخص باشد، در شاخهٔ «(سایر)» همان خانواده ثبت می‌شود تا شکاف کاتالوگ دیده شود."),
        ("", ""),
        ("۳. تعریف ستون‌ها", ""),
        ("گروه محصول نهایی", "یکی از گروه‌های ۱۰گانهٔ فایل گروه‌بندی یا «خارج از دامنه گروه‌بندی»."),
        ("خانواده محصول", "خانوادهٔ فنی محصول در فایل گروه‌بندی؛ برای اقلام بدون محصول، شاخهٔ (سایر) یا دستهٔ خارج از دامنه."),
        ("محصول", "نام محصول در فایل گروه‌بندی (مثلاً ICN1 DENA یا NBCM TARA)."),
        ("در فایل گروه‌بندی", "بله یعنی محصول/خانواده دقیقاً در فایل گروه‌بندی پیدا شده است."),
        ("در دامنه گروه‌بندی", "بله یعنی گروه محصول نهایی یکی از گروه‌های فایل گروه‌بندی است (حتی اگر محصول در کاتالوگ نباشد)."),
        ("روش تطبیق", "مسیر رسیدن به محصول: شماره فنی ← کد راهکاران ← کد گروه، یا نام محصول، یا شرح قطعه/منشا."),
        ("اطمینان", "قطعی (کد گروه)، بالا، متوسط، پایین (محصول خارج از کاتالوگ)."),
        ("نیاز به بازبینی", "ردیف‌هایی که تطبیق آن‌ها کم‌اطمینان، مبتنی بر نام، یا دارای شماره فنی پرابهام است."),
        ("برنچ", "ELE / EMS / POL — از ستون «برنچ» فایل گروه‌بندی؛ برای اقلام خارج از فایل، POL برای خانواده‌های پلیمری (داشبورد، بدنه، تزئینات) و در بقیه موارد «نامشخص»."),
        ("ایراد مشتری", "متن «شرح خطا» به یک عبارت استاندارد یکسان‌سازی شده است (مثلاً «عدم عملكرد» و «عملكرد اشتباه يا عدم كاركرد» ← «عدم عملکرد / عملکرد نادرست»)."),
        ("تکرار ایراد در محصول", "تعداد اخطارهایی که همان ایراد استاندارد برای همان محصول ثبت شده است."),
        ("علت استاندارد", "«آنالیز علت ایراد» برگهٔ بررسی به شکل «ایراد <نوع> قطعه <قطعه>» یکسان شده است؛ نمونه: «اتصالی پد ic micro» ← «ایراد اتصالی قطعه IC Micro»."),
        ("گروه ۶M", "دسته‌بندی علت بر اساس ۶M: نیروی انسانی، تجهیزات، مواد، روش، اندازه‌گیری، محیط (یا نامشخص)."),
        ("وضعیت فرم 8D", "فرم‌ها در داشبورد (python serve.py) تکمیل و در output/8d-forms.json ذخیره می‌شوند؛ ستون «درصد تکمیل» از ۷ بخش D1 تا D8 محاسبه می‌شود."),
        ("", ""),
        ("۴. نکات مهم", ""),
        ("پوشش", "فایل گروه‌بندی فقط ۱۰ گروه و حدود ۱۹۶ محصول دارد؛ بسیاری از محصولات نهایی راهکاران در آن نیستند و به‌صورت شاخهٔ (سایر) نمایش داده می‌شوند."),
        ("تکرار شماره فنی", "چون یک شماره فنی می‌تواند به چند محصول راهکاران اشاره کند، ستون «تعداد کاندید شماره فنی» و «مغایرت خودرو» برای بازبینی اضافه شده است."),
        ("تاریخ", "ماه‌های شمسی از ستون «تاریخ تایید» استخراج شده‌اند؛ ۵ ردیف تاریخ نامعتبر دارند."),
        ("ویرایش نقشه", "برای اصلاح تطبیق، شیت «نقشه محصولات» یا «نقشه شماره فنی» را ویرایش و در اجرای بعدی از فایل اصلاح‌شده استفاده کنید."),
    ]
    for label, value in guide_rows:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        cell = ws.cell(row=row, column=1, value=label)
        cell.font = Font(name=PERSIAN_FONT, size=10, bold=bool(label and not label.startswith("گام")), color="0F172A")
        cell.alignment = Alignment(horizontal="right", vertical="top")
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=8)
        cell = ws.cell(row=row, column=3, value=value)
        cell.font = Font(name=PERSIAN_FONT, size=9, color="334155")
        cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = 30 if len(str(value)) > 100 else 20
        row += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    for col in range(3, 9):
        ws.column_dimensions[get_column_letter(col)].width = 20

    # ---------------------------------------------------------------- خلاصه مدیریتی
    ws = wb.create_sheet("خلاصه مدیریتی")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 10, "خلاصه مدیریتی", "نگاه یک‌صفحه‌ای به پرتکرارترین گروه‌ها و محصولات و شاخص‌های کلیدی")
    kpi = _kpi_table(enriched)
    kpi_header, kpi_last = _write_table(ws, kpi, row, "شاخص‌های کلیدی")
    for r in range(kpi_header + 1, kpi_last + 1):
        if ws.cell(row=r, column=1).value in {"درصد در دامنه", "درصد در فایل گروه‌بندی"}:
            ws.cell(row=r, column=2).number_format = "0.0%"

    groups = group_summary(enriched)
    group_view = groups[["گروه محصول نهایی", WARNING_COUNT, DEFECTIVE, SCORE, "سهم اخطار", "اخطار باز"]].copy()
    gh, gl = _write_table(ws, group_view, kpi_last + 3, "خلاصه گروه‌های محصول", number_formats={"سهم اخطار": "0.0%"})
    _bar_from_table(ws, gh, gl, 1, 2, f"H{gh}", "تعداد اخطار به تفکیک گروه محصول", width=20, height=10)
    _pie_from_table(ws, gh, gl, 1, 4, f"Q{gh}", "سهم قطعات معیوب", width=16, height=10)

    products = product_summary(enriched).head(12)
    _write_table(
        ws,
        products[["گروه محصول نهایی", "خانواده محصول", "محصول", WARNING_COUNT, DEFECTIVE, SCORE, "سهم اخطار", "آخرین ماه"]],
        gl + 24,
        "۱۲ محصول پرتکرار",
        number_formats={"سهم اخطار": "0.0%"},
    )
    ws.column_dimensions["A"].width = 30

    # ---------------------------------------------------------------- خلاصه گروه
    ws = wb.create_sheet("خلاصه گروه")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 11, "خلاصه بر اساس گروه محصول نهایی", "شامل گروه خارج از دامنه به‌عنوان یک ردیف مستقل")
    view = groups[["گروه محصول نهایی", WARNING_COUNT, "سهم اخطار", DEFECTIVE, "سهم قطعات معیوب", SCORE, "سهم نمره منفی", "محصولات", "خانواده‌ها", "اخطار باز", "گرید A"]]
    gh, gl = _write_table(
        ws,
        view,
        row,
        number_formats={"سهم اخطار": "0.0%", "سهم قطعات معیوب": "0.0%", "سهم نمره منفی": "0.0%"},
    )
    ws.conditional_formatting.add(
        f"B{gh + 1}:B{gl}",
        DataBarRule(start_type="num", start_value=0, end_type="max", color=ACCENT_COLOR),
    )
    ws.conditional_formatting.add(
        f"D{gh + 1}:D{gl}",
        DataBarRule(start_type="num", start_value=0, end_type="max", color="2563EB"),
    )
    ws.conditional_formatting.add(
        f"F{gh + 1}:F{gl}",
        ColorScaleRule(start_type="min", start_color="DCFCE7", end_type="max", end_color="FCA5A5"),
    )
    _bar_from_table(ws, gh, gl, 1, 2, f"A{gl + 3}", "تعداد اخطار به تفکیک گروه", width=24, height=10)

    # ---------------------------------------------------------------- برنچ
    branch = branch_summary(enriched)
    if not branch.empty:
        ws = wb.create_sheet("خلاصه برنچ")
        ws.sheet_view.rightToLeft = True
        row = _title(ws, 1, 8, "خلاصه بر اساس برنچ", "ELE / EMS / POL — برنچ از فایل گروه‌بندی و در صورت نبود، استنباط از خانواده")
        columns = [c for c in ["برنچ", WARNING_COUNT, "سهم", DEFECTIVE, SCORE, "محصولات", "خانواده‌ها", "اخطار باز", "گرید A"] if c in branch.columns]
        bh, bl = _write_table(ws, branch[columns], row, number_formats={"سهم": "0.0%"})
        _pie_from_table(ws, bh, bl, 1, 2, f"A{bl + 3}", "سهم برنچ‌ها از اخطارها", width=18, height=10)

    # ---------------------------------------------------------------- ایرادهای مشتری
    defects_table = defect_summary(enriched)
    if not defects_table.empty:
        ws = wb.create_sheet("ایرادهای مشتری")
        ws.sheet_view.rightToLeft = True
        row = _title(
            ws,
            1,
            9,
            "ایرادهای مشتری (یکسان‌شده)",
            "متن «شرح خطا» به یک عبارت استاندارد تبدیل شده تا تکرار همان ایراد در یک محصول قابل شمارش باشد",
        )
        dh, dl = _write_table(
            ws,
            defects_table[["ایراد مشتری (استاندارد)", "گروه ایراد", "تعداد اخطار", "سهم", "تعداد محصول", "تعداد خانواده", "تعداد قطعات معیوب", "اخطار باز", "آخرین تاریخ تایید"]],
            row,
            number_formats={"سهم": "0.0%"},
        )
        _bar_from_table(ws, dh, dl, 1, 3, f"K{dh}", "پرتکرارترین ایرادهای مشتری", width=24, height=12)

    # ---------------------------------------------------------------- علت و ۶M
    causes_table = cause_summary(enriched)
    m6_table = m6_summary(enriched)
    if not causes_table.empty or not m6_table.empty:
        ws = wb.create_sheet("علت و ۶M")
        ws.sheet_view.rightToLeft = True
        row = _title(
            ws,
            1,
            8,
            "علت‌های استاندارد و گروه ۶M",
            "«آنالیز علت ایراد» برگه‌های بررسی یکسان‌سازی شده است؛ نمونه: «اتصالی پد ic micro» ← «ایراد اتصالی قطعه IC Micro» / ۶M: تجهیزات",
        )
        next_row = row
        if not m6_table.empty:
            mh, ml = _write_table(ws, m6_table, next_row, "گروه ۶M", number_formats={"سهم": "0.0%"})
            _pie_from_table(ws, mh, ml, 1, 2, f"D{mh}", "توزیع ۶M", width=16, height=9)
            next_row = ml + 4
        if not causes_table.empty:
            _write_table(
                ws,
                causes_table,
                next_row,
                "علت‌های استاندارد",
                subtitle="بر اساس برگه‌های بررسی متصل‌شده",
                widths={"علت استاندارد": 44},
            )

    # ---------------------------------------------------------------- خانواده
    ws = wb.create_sheet("خلاصه خانواده")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 9, "خلاصه بر اساس خانواده محصول", "خانواده‌های (سایر) نشان‌دهندهٔ محصولاتی هستند که گروه آن‌ها مشخص است ولی در فایل گروه‌بندی نیستند")
    fam = family_summary(enriched)
    _write_table(
        ws,
        fam[["گروه محصول نهایی", "خانواده محصول", WARNING_COUNT, "سهم اخطار", DEFECTIVE, SCORE, "محصولات", "اخطار باز", "نیاز به بازبینی"]],
        row,
        number_formats={"سهم اخطار": "0.0%"},
    )

    # ---------------------------------------------------------------- محصول
    ws = wb.create_sheet("خلاصه محصول")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 12, "خلاصه بر اساس محصول", "مرتب‌شده بر اساس تعداد اخطار؛ ستون «آخرین ماه» از تاریخ تایید محاسبه شده است")
    prod = product_summary(enriched)
    _write_table(
        ws,
        prod[["گروه محصول نهایی", "خانواده محصول", "محصول", "کد گروه محصول", "در فایل گروه‌بندی", WARNING_COUNT, DEFECTIVE, SCORE, "سهم اخطار", "آخرین ماه", "اخطار باز", "نیاز به بازبینی"]],
        row,
        number_formats={"سهم اخطار": "0.0%"},
    )

    # ---------------------------------------------------------------- اخطارها
    ws = wb.create_sheet("اخطارها")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 40, "فهرست کامل اخطارها با دسته‌بندی محصول", "هر ردیف یک اخطار کیفی؛ ستون‌های انتهایی برای بازبینی تطبیق هستند")
    _write_table(ws, enriched, row, freeze=True)

    # ---------------------------------------------------------------- نقشه محصولات
    ws = wb.create_sheet("نقشه محصولات")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 14, "نقشهٔ محصولات نهایی راهکاران به گروه‌بندی", "هر ردیف یک محصول نهایی ListData و پیشنهاد گروه/خانواده/محصول")
    _write_table(ws, product_map, row)

    # ---------------------------------------------------------------- نقشه شماره فنی
    ws = wb.create_sheet("نقشه شماره فنی")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 13, "نقشهٔ شماره فنی به محصول و گروه", "شماره‌های فنی یکتا و محصول/گروه تشخیص‌داده‌شده با تعداد اخطار و قطعات معیوب")
    _write_table(ws, tech_map, row)

    # ---------------------------------------------------------------- خارج از دامنه
    ws = wb.create_sheet("خارج از دامنه")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 8, "اقلام خارج از دامنهٔ گروه‌بندی", "این اقلام در فایل گروه‌بندی موجود نیستند و برای شفافیت تفکیک شده‌اند")
    out = out_of_scope_summary(enriched)
    if out.empty:
        ws.cell(row=row, column=1, value="موردی یافت نشد.")
        out_last = row
    else:
        _, out_last = _write_table(
            ws,
            out[["خانواده محصول", "محصول", WARNING_COUNT, "سهم اخطار", DEFECTIVE, SCORE, "محصولات", "اخطار باز"]],
            row,
            number_formats={"سهم اخطار": "0.0%"},
        )
    parts = top_parts(enriched[enriched["گروه محصول نهایی"] == OUT_GROUP], limit=30)
    _write_table(ws, parts, out_last + 3, "قطعات پرتکرار خارج از دامنه")

    # ---------------------------------------------------------------- پیشنهاد گروه‌بندی
    ws = wb.create_sheet("پیشنهاد گروه‌بندی")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 10, "محصولات نیازمند افزودن به فایل گروه‌بندی", "گروه محصول مشخص است اما محصول/خانواده در فایل گروه‌بندی پیدا نشد؛ ستون «عنوان راهکاران» برای شناسایی دقیق قطعه است")
    buckets = bucket_summary(enriched)
    if buckets.empty:
        ws.cell(row=row, column=1, value="موردی یافت نشد.")
    else:
        _write_table(
            ws,
            buckets[["گروه محصول نهایی", "خانواده محصول", "محصول", "عنوان راهکاران (نمونه)", WARNING_COUNT, DEFECTIVE, SCORE, "اخطار باز", "نیاز به بازبینی"]],
            row,
        )

    # ---------------------------------------------------------------- وضعیت اقدام
    ws = wb.create_sheet("وضعیت اقدام")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 8, "وضعیت اخطار و اقدامات کوتاه‌مدت/میان‌مدت", "چند اخطار خاتمه یافته و چند اخطار در هر مرحلهٔ اقدام قرار دارد")
    stages = stage_summary(enriched)
    sh, sl = _write_table(
        ws,
        stages[["وضعیت اخطار", WARNING_COUNT, "سهم", DEFECTIVE, SCORE, "اخطار باز", "سهم اخطار"]],
        row,
        "وضعیت اخطار",
        number_formats={"سهم": "0.0%", "سهم اخطار": "0.0%"},
    )
    _pie_from_table(ws, sh, sl, 1, 2, f"H{sh}", "سهم وضعیت‌های اخطار", width=16, height=10)
    actions = action_summary(enriched)
    if not actions.empty:
        _write_table(
            ws,
            actions[["نوع اقدام", "وضعیت تایید", WARNING_COUNT, "سهم"]],
            sl + 3,
            "وضعیت تایید اقدامات",
            number_formats={"سهم": "0.0%"},
        )
    if "دارای برگه بررسی" in enriched.columns:
        covered = int((enriched["دارای برگه بررسی"] == "بله").sum())
        ws.cell(row=sl + 3 + len(actions) + 3, column=1, value="پوشش برگهٔ بررسی").font = Font(name=PERSIAN_FONT, size=10, bold=True)
        ws.cell(row=sl + 3 + len(actions) + 3, column=2, value=f"{covered:,} از {len(enriched):,} اخطار")

    # ---------------------------------------------------------------- بررسی اخطارها
    ws = wb.create_sheet("بررسی اخطارها")
    ws.sheet_view.rightToLeft = True
    row = _title(
        ws,
        1,
        13,
        "برگه‌های بررسی اخطار (علت ایراد و اقدام اصلاحی)",
        "داده‌های شیت «اخطار» فایل C_Plus بر اساس سریال اخطار به گزارش متصل شده است؛ ردیف‌های بدون اخطار متناظر در شیت «کیفیت داده» آمده‌اند.",
    )
    if "دارای برگه بررسی" in enriched.columns and (enriched["دارای برگه بررسی"] == "بله").any():
        reviewed = enriched[enriched["دارای برگه بررسی"] == "بله"].copy()
        reviewed["شماره فرم 8D"] = [
            f"8D-{int(y) if pd.notna(y) else 'XXXX'}-{int(s)}"
            for s, y in zip(reviewed["سریال اخطار"], reviewed["سال"])
        ]
        reviewed = reviewed.sort_values(["سال", "سریال اخطار"])
        columns = [
            "سریال اخطار",
            "تاریخ تایید",
            "گروه خودرو",
            "شرح قطعه",
            "شماره فنی",
            "محصول",
            "خانواده محصول",
            "دسته محصول (بررسی)",
            "آنالیز علت ایراد",
            "شرح اقدام اصلاحی",
            "منشاء ایراد",
            "شماره کلیم",
            "شماره کارت نارنجی",
            "شماره فرم 8D",
        ]
        columns = [c for c in columns if c in reviewed.columns]
        _write_table(ws, reviewed[columns], row)
        ws.column_dimensions["I"].width = 60
        ws.column_dimensions["J"].width = 45
    else:
        ws.cell(row=row, column=1, value="برگهٔ بررسی برای اخطارها پیدا نشد.")

    # ---------------------------------------------------------------- فرم 8D
    ws = wb.create_sheet("فرم 8D")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 14, "وضعیت فرم‌های 8D", "یک فرم برای هر اخطار با شماره 8D-سال-سریال؛ فرم‌ها در داشبورد تکمیل و ذخیره می‌شوند (python serve.py)")
    if eight_d is not None and not eight_d.empty:
        form_table = eight_d.copy()
        if "شماره فرم 8D" not in form_table.columns:
            form_table["شماره فرم 8D"] = [
                f"8D-{int(y) if pd.notna(y) else 'XXXX'}-{int(s)}"
                for s, y in zip(form_table["سریال اخطار"], form_table["سال"])
            ]
        if "وضعیت فرم" not in form_table.columns:
            form_table["وضعیت فرم"] = [
                "آمادهٔ تایید" if (r["دارای برگه بررسی"] == "بله" and str(r["آنالیز علت ایراد"]).strip()) else "در انتظار تکمیل"
                for _, r in form_table.iterrows()
            ]
        cols = [
            "شماره فرم 8D",
            "سریال اخطار",
            "تاریخ تایید",
            "گروه خودرو",
            "شرح قطعه",
            "محصول",
            "وضعیت اخطار",
            "مسئول پیگیری",
            "تاریخ تکمیل",
            "درصد تکمیل",
            "D4 — علت ریشه‌ای",
            "D5 — اقدام اصلاحی دائم",
            "وضعیت فرم",
            "در فایل ورد",
            "آخرین به‌روزرسانی",
            "دارای برگه بررسی",
            "آنالیز علت ایراد",
            "منشاء ایراد",
        ]
        cols = [c for c in cols if c in form_table.columns]
        fh, fl = _write_table(ws, form_table[cols], row)
        ws.column_dimensions["I"].width = 50
        ws.column_dimensions["J"].width = 40
        for name in ("مسئول پیگیری", "D4 — علت ریشه‌ای", "D5 — اقدام اصلاحی دائم"):
            if name in cols:
                ws.column_dimensions[get_column_letter(cols.index(name) + 1)].width = 38 if "D" in name else 18
        from openpyxl.formatting.rule import FormulaRule

        status_col = cols.index("وضعیت فرم") + 1
        letter = get_column_letter(status_col)
        first = f"${letter}{fh + 1}"
        ws.conditional_formatting.add(
            f"{letter}{fh + 1}:{letter}{fl}",
            FormulaRule(
                formula=[f'OR({first}="آمادهٔ تایید",{first}="آماده تأیید",{first}="بسته شده")'],
                fill=PatternFill("solid", fgColor="DCFCE7"),
            ),
        )
    else:
        ws.cell(row=row, column=1, value="فرم 8D ساخته نشده است.")
        ws.cell(row=row + 1, column=1, value="برای ساخت فرم‌ها کتابخانهٔ python-docx را نصب کنید:  pip install -r requirements.txt")

    # ---------------------------------------------------------------- روند سالانه و ماهانه
    ws = wb.create_sheet("روند زمانی")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 6, "روند سالانه و ماهانهٔ اخطارها", "بر اساس سال و ماه شمسی تاریخ تایید")
    years = year_summary(enriched)
    yh, yl = _write_table(
        ws,
        years[["سال", "اخطار", "قطعات معیوب", "نمره منفی", "اخطار باز", "نیاز به بازبینی"]],
        row,
        "خلاصه سالانه",
    )
    _bar_from_table(ws, yh, yl, 1, 2, f"H{yh}", "تعداد اخطار به تفکیک سال", width=22, height=10)
    months = month_summary(enriched)
    mh, ml = _write_table(
        ws,
        months[["ماه شمسی", "اخطار", "قطعات معیوب", "نمره منفی", "اخطار باز"]],
        max(yl, yh + 22) + 3,
        "جزئیات ماهانه",
        subtitle="برای نمودار خواناتر، روند کلی در شیت «روند زمانی» به‌صورت سالانه نمایش داده شده است.",
    )
    _line_from_table(ws, mh, ml, 1, 2, f"H{mh}", "روند ماهانه تعداد اخطار (کامل)", width=30, height=11)

    # ---------------------------------------------------------------- خودرو
    ws = wb.create_sheet("خودرو")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 8, "خلاصه بر اساس گروه خودرو", "پرتکرارترین خودروها و توزیع گروه محصول در هر خودرو")
    vehicles = vehicle_summary(enriched)
    _, v_last = _write_table(
        ws,
        vehicles[["گروه خودرو", WARNING_COUNT, "سهم اخطار", DEFECTIVE, SCORE, "اخطار باز", "گرید A"]],
        row,
        number_formats={"سهم اخطار": "0.0%"},
    )
    cross = pd.crosstab(enriched["گروه خودرو"], enriched["گروه محصول نهایی"], margins=True, margins_name="جمع")
    cross = cross.reset_index().rename(columns={"index": "گروه خودرو"})
    _write_table(ws, cross, v_last + 3, "تقاطع گروه خودرو و گروه محصول")

    # ---------------------------------------------------------------- کیفیت داده
    ws = wb.create_sheet("کیفیت داده")
    ws.sheet_view.rightToLeft = True
    row = _title(ws, 1, 6, "کیفیت داده و موارد نیازمند بازبینی", "شاخص‌های اعتبارسنجی و فهرست کوتاه موارد مشکوک")
    quality = date_quality(enriched)
    outliers = enriched[enriched[DEFECTIVE] > 1000]
    quality_rows = [
        ("تاریخ‌های نامعتبر", quality["missing_dates"]),
        ("سال شروع داده", quality["start"]),
        ("سال پایان داده", quality["end"]),
        ("ردیف‌های نیازمند بازبینی", int((enriched["نیاز به بازبینی"] == "بله").sum())),
        ("ردیف‌های با مغایرت خودرو", int((enriched["مغایرت خودرو"] == "بله").sum())),
        ("ردیف‌های بدون شماره فنی", int((enriched["شماره فنی"] == "").sum())),
        ("شماره‌های فنی یکتا", int(enriched["شماره فنی"].replace("", pd.NA).dropna().nunique())),
        ("ردیف‌های بدون تطبیق", int((enriched["روش تطبیق"] == "بدون تطابق").sum())),
        ("ردیف‌های با تعداد قطعات معیوب بیش از ۱۰۰۰", int(len(outliers))),
    ]
    quality_frame = pd.DataFrame(quality_rows, columns=["شاخص", "مقدار"])
    _, q_last = _write_table(ws, quality_frame, row, "شاخص‌های کیفیت")
    if not outliers.empty:
        _, o_last = _write_table(
            ws,
            outliers.nlargest(20, DEFECTIVE)[["سریال اخطار", "تاریخ تایید", "شرح قطعه", "محصول", DEFECTIVE, SCORE]],
            q_last + 3,
            "تعداد قطعات معیوب غیرعادی (بیش از ۱٬۰۰۰)",
            subtitle="این ردیف‌ها ممکن است خطای ثبت یا تعداد تجمعی باشند؛ مجموع قطعات معیوب را به‌شدت تحت تأثیر قرار می‌دهند.",
        )
        q_last = o_last
    if grouping_checks is not None and not grouping_checks.empty:
        _, g_last = _write_table(
            ws,
            grouping_checks,
            q_last + 3,
            "کنترل گروه‌بندی: ردیف‌های ناهمخوان با دستهٔ اعلامی مشتری",
            subtitle="دستهٔ محصول در برگهٔ بررسی مشتری با خانواده/محصول داخلی هم‌پوشانی ندارد؛ این ردیف‌ها را دستی بررسی کنید.",
        )
        q_last = g_last

    if unmatched_review is not None and not unmatched_review.empty:
        small = unmatched_review[["سریال اخطار", "شرح قطعه (بررسی)", "دسته محصول (بررسی)", "آنالیز علت ایراد"]].copy()
        small.columns = ["سریال اخطار", "شرح قطعه (بررسی)", "دسته محصول (بررسی)", "آنالیز علت ایراد"]
        _, q_last = _write_table(
            ws,
            small,
            q_last + 3,
            "برگه‌های بررسی بدون اخطار متناظر",
            subtitle="این سریال‌ها در فایل اخطارهای کیفی وجود ندارند و در گزارش اصلی لحاظ نشده‌اند.",
        )

    review = enriched[enriched["نیاز به بازبینی"] == "بله"].head(300)
    _write_table(
        ws,
        review[["سریال اخطار", "شماره فنی", "شرح قطعه", "گروه خودرو", "محصول", "خانواده محصول", "روش تطبیق", "اطمینان"]],
        q_last + 3,
        "نمونهٔ ردیف‌های نیازمند بازبینی (۳۰۰ ردیف اول)",
    )

    wb.save(output_path)
    return output_path
