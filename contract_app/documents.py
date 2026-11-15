from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import uuid
import zipfile

from docxtpl import DocxTemplate
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from lxml import etree

from .models import FIELD_LABELS, UserError
from .customer_fields import is_customer_field

NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def check_docx(path: Path):
    if path.suffix.lower() != ".docx":
        raise UserError("Cần mẫu Word .docx. PDF scan cần được dựng lại thành Word trước khi dùng làm mẫu.")
    try:
        if path.stat().st_size > 30_000_000:
            raise UserError("Mẫu Word vượt 30 MB. Hãy giảm ảnh hoặc tách phụ lục.")
        with zipfile.ZipFile(path) as archive:
            if sum(x.file_size for x in archive.infolist()) > 100_000_000:
                raise UserError("Nội dung giải nén của Word vượt giới hạn 100 MB.")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("Not a Word document")
            if any("vbaProject" in name for name in archive.namelist()):
                raise UserError("Mẫu có macro không được hỗ trợ.")
    except UserError:
        raise
    except Exception as exc:
        raise UserError("Không đọc được mẫu Word .docx; file có thể hỏng hoặc đang bị khóa.") from exc


def template_fields(path: Path) -> set[str]:
    check_docx(path)
    try:
        return DocxTemplate(path).get_undeclared_template_variables(jinja_env=SandboxedEnvironment(undefined=StrictUndefined, autoescape=True))
    except Exception as exc:
        raise UserError("Biến trong mẫu Word bị lỗi. Kiểm tra cú pháp {{ company_name }} trong mẫu.") from exc


def template_is_draft(path: Path) -> bool:
    with zipfile.ZipFile(path) as archive:
        if "docProps/core.xml" not in archive.namelist():
            return False
        root = etree.fromstring(archive.read("docProps/core.xml"), parser=XML_PARSER)
        category = root.find("{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}category")
        return category is not None and category.text == "hopdongai:draft"


def document_text(path: Path) -> str:
    parts = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("word/") and name.endswith(".xml"):
                root = etree.fromstring(archive.read(name), parser=XML_PARSER)
                parts += ["".join(p.itertext()) for p in root.findall(".//w:p", NAMESPACE)]
    return "\n".join(parts)


def safe_filename(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D")) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:65] or "Khach-hang"


def missing_fields(template: Path, context: dict) -> list[str]:
    names = template_fields(template)
    if not names:
        raise UserError("Mẫu chưa có biến điền dữ liệu. Vào Mẫu hợp đồng → Tạo mẫu từ Word/PDF để chuyển mẫu trống hoặc hợp đồng đã điền thành mẫu tái sử dụng.")
    essential = {"company_name", "work_description"} - names
    if essential:
        raise UserError("Mẫu hợp đồng cần có các biến: " + ", ".join(sorted(essential)) + ". Chưa xuất file để tránh bỏ sót thông tin chính.")
    unknown = {name for name in names - set(FIELD_LABELS) - {"day", "month", "year", "amount_number", "currency", "is_demo"} if not is_customer_field(name)}
    if unknown:
        raise UserError("Mẫu chứa biến chưa được hỗ trợ: " + ", ".join(sorted(unknown)))
    return sorted(name for name in names if context.get(name) is None or str(context[name]).strip() == "")


def render_contract(template: Path, context: dict, output: Path, company: str) -> Path:
    missing = missing_fields(template, context)
    if missing:
        raise UserError("Thiếu thông tin: " + ", ".join(FIELD_LABELS.get(x, x) for x in missing))
    output.mkdir(parents=True, exist_ok=True)
    prefix = "MINH-HOA-" if context.get("is_demo") else "HD-"
    target = output / f"{prefix}{safe_filename(company)}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.docx"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", dir=output, delete=False) as handle:
            temporary = Path(handle.name)
        doc = DocxTemplate(template)
        doc.render(context, jinja_env=SandboxedEnvironment(undefined=StrictUndefined, autoescape=True), autoescape=True)
        if context.get("additional_information"):
            doc.docx.add_heading("Thông tin bổ sung", level=2)
            for label, value in context["additional_information"]:
                doc.docx.add_paragraph(f"{label}: {value}")
        doc.save(temporary)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():
                raise ValueError("Damaged output")
        text = document_text(temporary)
        if "{{" in text or "{%" in text:
            raise UserError("Word còn biến chưa được điền. Chưa xuất hợp đồng; hãy kiểm tra mẫu.")
        # Same-volume atomic publication, with no overwrite in either platform.
        if os.name == "nt":
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
        return target
    except UserError:
        raise
    except PermissionError as exc:
        raise UserError("Không ghi được file. Kiểm tra quyền thư mục xuất hoặc chọn thư mục khác trong Cài đặt.") from exc
    except Exception as exc:
        raise UserError("Chưa tạo được Word. Kiểm tra mẫu và thư mục xuất rồi thử lại.") from exc
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
