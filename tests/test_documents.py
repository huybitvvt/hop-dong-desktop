from pathlib import Path
import zipfile

from docx import Document
from lxml import etree
import pytest

from contract_app.documents import document_text, render_contract, template_fields
from contract_app.models import Intent, UserError
from contract_app.service import ContractService


def intent(**changes):
    return Intent(**({"contact_name": "Thông", "company_name": "Công ty X", "amount_text": "1 tỷ", "work_description": "Thi công dự án Y"} | changes))


def test_entire_local_pipeline_generates_real_docx_and_history(store):
    service = ContractService(store)
    template = next(store.templates.glob("*.docx"))
    pending = service.prepare(intent(), "sample", template)
    assert pending.customer.tax_code == "DEMO-X"
    result = service.generate(pending)
    text = document_text(result.path)
    assert "1.000.000.000" in text
    assert "Một tỷ đồng" in text
    assert "Nguyễn Văn Bình" in text
    assert "Thi công dự án Y" in text
    assert "{{" not in text and "{%" not in text
    assert result.demo and result.path.name.startswith("MINH-HOA-")
    assert store.history()[0]["path"] == str(result.path)
    assert Document(result.path).tables[0].cell(0, 1).text == "1.000.000.000 đồng"


def test_duplicate_name_requires_explicit_choice(store):
    service = ContractService(store)
    pending = service.prepare(intent(company_name=None), "sample", next(store.templates.glob("*.docx")))
    assert pending.customer is None
    with pytest.raises(UserError, match="chọn đúng"):
        service.generate(pending)
    assert not store.history()


def test_repeated_generation_never_overwrites(store):
    service = ContractService(store)
    pending = service.prepare(intent(), "sample", next(store.templates.glob("*.docx")))
    a, b = service.generate(pending), service.generate(pending)
    assert a.path != b.path and a.path.exists() and b.path.exists()


def test_xml_escaping_formatting_headers_and_tables(tmp_path):
    template = tmp_path / "template.docx"
    doc = Document()
    run = doc.add_paragraph().add_run("{{ company_name }}")
    run.bold = True
    doc.add_paragraph("{{ work_description }}")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "{{ amount }}"
    doc.sections[0].header.paragraphs[0].text = "{{ tax_code }}"
    doc.save(template)
    target = render_contract(template, {"company_name": "A & B <Việt Nam>", "work_description": "A < B & C", "amount": "100", "tax_code": "001"}, tmp_path / "out", "A/B:*? Company")
    result = Document(target)
    assert result.paragraphs[0].text == "A & B <Việt Nam>"
    assert result.paragraphs[0].runs[0].bold
    assert result.sections[0].header.paragraphs[0].text == "001"
    assert result.tables[0].cell(0, 0).text == "100"
    with zipfile.ZipFile(target) as archive:
        for name in archive.namelist():
            if name.endswith(".xml"):
                etree.fromstring(archive.read(name))


def test_missing_required_info_prevents_output(store):
    customers = store.customers()
    from dataclasses import replace
    store.replace_customers([replace(customers[0], representative="")])
    service = ContractService(store)
    pending = service.prepare(intent(), "sample", next(store.templates.glob("*.docx")))
    assert "representative" in service.missing(pending)
    with pytest.raises(UserError):
        service.generate(pending)
    assert not store.history()
    result = service.generate(pending, {"representative": "Người đã được xác nhận"})
    assert "Người đã được xác nhận" in document_text(result.path)


def test_incomplete_contract_template_is_rejected(tmp_path):
    doc = Document()
    doc.add_paragraph("{{ company_name }}")
    source = tmp_path / "incomplete.docx"
    doc.save(source)
    with pytest.raises(UserError, match="work_description"):
        render_contract(source, {"company_name": "A"}, tmp_path / "out", "A")


def test_invalid_date_is_not_silently_substituted(store):
    service = ContractService(store)
    pending = service.prepare(intent(contract_date="2026-02-30"), "sample", next(store.templates.glob("*.docx")))
    with pytest.raises(UserError, match="Ngày ký"):
        service.generate(pending)
