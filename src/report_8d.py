"""پر کردن فرم 8D (QA-DA-02-C) برای هر اخطار و ساخت یک فایل ورد یکجا.

قالب فرم در فایل `QA-DA-02-C.docx` است. برای هر اخطار یک نسخه از قالب
بارگذاری، سرصفحه و بخش‌های قابل استخراج از داده‌های اخطار و برگهٔ بررسی
در آن نوشته می‌شود و در پایان همهٔ فرم‌ها در یک سند ورد کنار هم قرار می‌گیرند.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

try:  # pragma: no cover - در محیط بدون python-docx
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
except Exception:  # pragma: no cover
    Document = None  # type: ignore

from .review import eight_d_number

ER_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@dataclass
class EightDContext:
    serial: object
    status: str
    number: str
    title: str
    part: str
    tech: str
    car: str
    date: str
    issuer: str
    maker: str
    supplier: str
    location: str
    error: str
    cause: str
    action: str
    origin: str
    claim: str
    orange_card: str
    grade: str


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = " ".join(str(value).split())
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _context(row: pd.Series) -> EightDContext:
    return EightDContext(
        serial=row.get("سریال اخطار"),
        status=_text(row.get("وضعیت اخطار")),
        number=eight_d_number(row.get("سریال اخطار"), row.get("سال")),
        title=_text(row.get("شرح قطعه")),
        part=_text(row.get("نام محصول راهکاران")) or _text(row.get("محصول")),
        tech=_text(row.get("شماره فنی")),
        car=_text(row.get("گروه خودرو")),
        date=_text(row.get("تاریخ تایید")),
        issuer=_text(row.get("محل صدور")),
        maker=_text(row.get("نام سازنده")),
        supplier=_text(row.get("تامین‌کننده (بررسی)")),
        location=_text(row.get("محل صدور")),
        error=_text(row.get("شرح خطا")),
        cause=_text(row.get("آنالیز علت ایراد")),
        action=_text(row.get("شرح اقدام اصلاحی")),
        origin=_text(row.get("منشاء ایراد")),
        claim=_text(row.get("شماره کلیم")),
        orange_card=_text(row.get("شماره کارت نارنجی")),
        grade=_text(row.get("گرید ایراد")),
    )


def _append(cell, text: str, prefix: str = "") -> None:
    """متن را به انتهای پاراگراف اول سلول اضافه می‌کند (بدون حذف قالب)."""
    if not text:
        return
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run((" " if prefix else "") + (prefix + text if prefix else text))
    run.font.size = Pt(9)
    try:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    except Exception:
        pass


def _append_after_label(cell, label: str, text: str) -> None:
    """متن را به همان پاراگرافی که برچسب در آن است اضافه می‌کند."""
    if not text:
        return
    for paragraph in cell.paragraphs:
        if label in paragraph.text:
            run = paragraph.add_run(" " + text)
            run.font.size = Pt(9)
            return
    _append(cell, text, prefix=" ")


def _set_line(cell, text: str) -> None:
    if not text:
        return
    paragraph = cell.paragraphs[0]
    if paragraph.runs:
        paragraph.runs[0].text = text
    else:
        run = paragraph.add_run(text)
        run.font.size = Pt(9)


def _fill(template_path: Path, context: EightDContext, index: int):
    doc = Document(str(template_path))

    # شماره فرم در سرصفحهٔ راهنما
    for paragraph in doc.paragraphs:
        if "8D-" in paragraph.text and "XXXX" in paragraph.text:
            for run in paragraph.runs:
                if "8D-" in run.text:
                    run.text = run.text.replace("8D-XXXX-Y", context.number + " ")

    tables = doc.tables
    if len(tables) < 12:
        return doc

    _append(tables[0].rows[4].cells[0], f"شماره اخطار کیفی: {context.serial}  |  فرم {context.number}", prefix=" ")
    _append(tables[0].rows[4].cells[0], context.claim, prefix=" | شماره کلیم: ")

    header = tables[1]
    _append(header.rows[0].cells[0], context.issuer, prefix=" ")
    _append(header.rows[0].cells[2], str(context.serial), prefix=" ")
    _append(header.rows[1].cells[0], context.supplier or context.maker, prefix=" ")
    _append(header.rows[1].cells[2], context.date, prefix=" ")
    _append(header.rows[2].cells[0], context.title, prefix=" ")
    _append(header.rows[3].cells[0], context.part, prefix=" ")
    _append(header.rows[3].cells[2], context.tech, prefix=" ")

    # تعریف مسئله (5W)
    describe = tables[2]
    _append(describe.rows[0].cells[2], context.location, prefix=" ← ")
    _append(describe.rows[4].cells[2], " | ".join(x for x in (context.title, context.error) if x), prefix=" ← ")
    _append(describe.rows[6].cells[2], context.location, prefix=" ← ")
    _append(describe.rows[8].cells[2], context.date, prefix=" ← ")

    # آنالیز اولیه
    analysis = tables[3]
    _append_after_label(analysis.rows[8].cells[1], "دلایل ایجاد ایراد", context.cause)
    _append_after_label(analysis.rows[8].cells[1], "دلایل عدم کنترل ایراد", context.action)

    # اقدام محدودکنندهٔ موقت
    temporary = tables[4]
    _append(temporary.rows[2].cells[2], context.action)
    _append(temporary.rows[2].cells[3], context.supplier)
    _append(temporary.rows[2].cells[4], context.maker)
    _append(temporary.rows[2].cells[5], context.date)

    # ریشه‌یابی (Drill Deep) - ردیف M-RC
    deep = tables[6]
    _append(deep.rows[7].cells[3], " | ".join(x for x in (context.origin, context.cause) if x))

    # اقدام اصلاحی دائم
    permanent = tables[7]
    _append(permanent.rows[3].cells[2], context.action)
    _append(permanent.rows[3].cells[6], context.supplier)

    # درس آموخته
    lesson = tables[11]
    _append(
        lesson.rows[2].cells[1],
        f"{context.title} — علت: {context.cause or 'در دست بررسی'} / منشا: {context.origin or 'نامشخص'}"
        if context.cause
        else "",
        prefix=" ",
    )
    return doc


def _style_table(table) -> None:
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    # راست‌به‌چپ کردن جدول
    tbl_pr = table._tbl.tblPr
    bidi = OxmlElement("w:bidiVisual")
    tbl_pr.append(bidi)
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                for run in paragraph.runs:
                    run.font.size = Pt(9)


def _compact_form(doc, context: EightDContext, index: int) -> None:
    """یک فرم 8D فشرده و قابل چاپ برای یک اخطار."""
    from docx.shared import Cm

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(f"فرم تحلیل 8D — {context.number}")
    run.bold = True
    run.font.size = Pt(14)
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = subtitle.add_run("بر اساس فرم QA-DA-02-C — کیفیت محصولات الکترونیکی")
    sub_run.font.size = Pt(8)

    info = doc.add_table(rows=0, cols=4)
    rows = [
        ("شماره اخطار کیفی", str(context.serial), "تاریخ تایید", context.date),
        ("شماره فنی", context.tech, "گروه خودرو", context.car),
        ("نام قطعه (مشتری)", context.title, "محصول راهکاران", context.part),
        ("وضعیت اخطار", context.status, "گرید / شماره کلیم", f"{context.grade} / {context.claim or '—'}"),
    ]
    for a, b, c, d in rows:
        cells = info.add_row().cells
        cells[0].text, cells[1].text, cells[2].text, cells[3].text = a, b, c, d
    _style_table(info)

    sections = [
        ("D1 — تیم", "اعضای تیم، دبیر جلسه و مسئول پیگیری: (تکمیل توسط واحد کیفیت)"),
        (
            "D2 — تعریف مسئله",
            "\n".join(
                x
                for x in (
                    f"شرح قطعه: {context.title}" if context.title else "",
                    f"شرح خطا: {context.error}" if context.error else "",
                    f"محل صدور / اعلام‌کننده: {context.location}" if context.location else "",
                    f"تاریخ وقوع: {context.date}" if context.date else "",
                )
                if x
            ),
        ),
        ("D3 — اقدام محدودکنندهٔ موقت", context.action or "(ثبت نشده)"),
        (
            "D4 — تحلیل علت ریشه‌ای",
            "\n".join(
                x
                for x in (
                    f"آنالیز علت ایراد: {context.cause}" if context.cause else "",
                    f"منشاء ایراد: {context.origin}" if context.origin else "",
                )
                if x
            )
            or "(ثبت نشده)",
        ),
        ("D5 — اقدام اصلاحی دائم", context.action or "(ثبت نشده)"),
        ("D6 — اجرا و صحه‌گذاری", "تاریخ اجرا، مسئول و شاخص اثربخشی: (تکمیل توسط واحد کیفیت)"),
        ("D7 — پیشگیری از تکرار", "به‌روزرسانی PFMEA / دستورالعمل / پوکایوکه: (تکمیل توسط واحد کیفیت)"),
        ("D8 — بستن پرونده و درس آموخته", "درس آموخته و تاریخ بسته شدن: (تکمیل توسط واحد کیفیت)"),
    ]
    for label, value in sections:
        table = doc.add_table(rows=1, cols=2)
        table.columns[0].width = Cm(4.2)
        table.columns[1].width = Cm(12.8)
        head, body = table.rows[0].cells
        head.text = label
        body.text = value
        _style_table(table)


def build_8d_document(
    rows: pd.DataFrame,
    template_path: str | Path,
    output_path: str | Path,
    split_dir: str | Path | None = None,
) -> tuple[Path, int]:
    """ساخت سند 8D فشرده برای همهٔ ردیف‌ها؛ خروجی: (مسیر فایل، تعداد فرم)."""
    if Document is None:
        raise RuntimeError("کتابخانهٔ python-docx نصب نیست.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run("فرم‌های 8D اخطارهای کیفی")
    run.bold = True
    run.font.size = Pt(16)
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    note_run = note.add_run(
        "برای هر اخطار بررسی‌شده یا باز، یک فرم با شماره 8D-سال-سریال ساخته شده است. "
        "بخش‌های خاکستری از داده‌های اخطار و برگهٔ بررسی پر شده‌اند و بخش‌های باقی‌مانده باید توسط تیم تکمیل شود."
    )
    note_run.font.size = Pt(9)

    if rows.empty:
        doc.add_paragraph("هیچ اخطاری برای تشکیل فرم 8D پیدا نشد.")
        doc.save(str(output_path))
        return output_path, 0

    if split_dir is not None:
        Path(split_dir).mkdir(parents=True, exist_ok=True)

    count = 0
    for index, (_, row) in enumerate(rows.iterrows()):
        context = _context(row)
        doc.add_page_break()
        _compact_form(doc, context, index)
        if split_dir is not None:
            single = Document()
            _compact_form(single, context, index)
            single.save(str(Path(split_dir) / f"8D-{context.serial}.docx"))
        count += 1

    doc.save(str(output_path))
    return output_path, count


def build_official_form(row: pd.Series, template_path: str | Path, output_path: str | Path) -> Path:
    """پر کردن قالب رسمی QA-DA-02-C برای یک اخطار."""
    if Document is None:
        raise RuntimeError("کتابخانهٔ python-docx نصب نیست.")
    context = _context(row)
    document = _fill(Path(template_path), context, 0)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
    return output_path
