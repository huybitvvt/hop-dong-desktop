from docx import Document
import pytest

from contract_app.documents import document_text
from contract_app.models import Intent, UserError
from contract_app.service import ContractService


def master_template(tmp_path, draft=False):
    doc = Document()
    doc.add_paragraph("HỢP ĐỒNG NGUYÊN TẮC")
    doc.add_paragraph("Đối tác: {{ company_name }}")
    doc.add_paragraph("Hàng hóa: {{ work_description }}")
    doc.add_paragraph("Giá cả theo từng đơn hàng cụ thể.")
    if draft:
        doc.core_properties.category = "hopdongai:draft"
    path = tmp_path / "master.docx"
    doc.save(path)
    return path


def test_master_without_fixed_amount_does_not_invent_total(store, tmp_path):
    service = ContractService(store)
    pending = service.prepare(Intent(company_name="Công ty X", work_description="Container"), "sample", master_template(tmp_path))
    assert not service.missing(pending)
    result = service.generate(pending)
    assert result.amount == 0
    assert "Giá cả theo từng đơn hàng" in document_text(result.path)
    assert "0 đồng" not in document_text(result.path)


def test_explicit_amount_cannot_be_silently_omitted_by_master_template(store, tmp_path):
    service = ContractService(store)
    with pytest.raises(UserError, match="bỏ sót"):
        service.prepare(Intent(company_name="Công ty X", amount_text="1 tỷ", work_description="Container"), "sample", master_template(tmp_path))
    assert not store.history()


def test_draft_metadata_marks_output_as_test_even_with_real_data_flag(store, tmp_path):
    cfg = store.config()
    cfg.update(demo_data=False, customer_source="")
    store.save_config(cfg)
    service = ContractService(store)
    pending = service.prepare(Intent(company_name="Công ty X", work_description="Container"), "sample", master_template(tmp_path, True))
    result = service.generate(pending)
    assert result.demo
    assert result.path.name.startswith("MINH-HOA-")
