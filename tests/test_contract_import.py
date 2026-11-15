from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from google import genai
from google.genai import types
import httpx
from pypdf import PdfWriter
import pytest

from contract_app.contract_import import (
    ContractExtraction, ContractParty, GeminiDocumentExtractor, ImportResult,
    extraction_schema, load_import_document, save_imported_customer,
)
from contract_app.customer_review import CustomerImportReview, CUSTOMER_FIELDS
from contract_app.models import Customer, Intent, UserError
from contract_app.service import ContractService


@pytest.fixture
def pdf(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    source = tmp_path / "contract.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    return source


@pytest.fixture
def party():
    return ContractParty(role="Bên B", company_name="Công ty TNHH A", tax_code="0123456789", representative="Nguyễn Văn An", address="Địa chỉ có trong hợp đồng", bank_account="00112233")


@pytest.fixture
def real_store(store):
    cfg = store.config()
    cfg.update(demo_data=False, customer_source="")
    store.save_config(cfg)
    return store


def imported(pdf, party):
    return ImportResult(load_import_document(pdf), ContractExtraction(parties=[party]))


class Client:
    def __init__(self, response):
        self.models, self.response, self.calls = self, response, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.response)


def test_pdf_bytes_are_sent_to_vision_and_zeroes_preserved(pdf, party):
    client = Client(ContractExtraction(parties=[party]).model_dump_json())
    result = GeminiDocumentExtractor("test-placeholder", client=client).extract_file(pdf)
    assert result.extraction.parties[0].tax_code == "0123456789"
    assert result.extraction.parties[0].bank_account == "00112233"
    part = client.calls[0]["contents"][1]
    assert part.inline_data.mime_type == "application/pdf"
    assert part.inline_data.data == pdf.read_bytes()


def test_docx_is_read_locally_and_only_text_is_sent(tmp_path, party):
    doc = Document()
    doc.add_paragraph("HỢP ĐỒNG — Công ty TNHH A, mã số thuế 0123456789")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Người đại diện Nguyễn Văn An"
    path = tmp_path / "contract.docx"
    doc.save(path)
    client = Client(ContractExtraction(parties=[party]).model_dump_json())
    result = GeminiDocumentExtractor("test-placeholder", client=client).extract_file(path)
    contents = client.calls[0]["contents"]
    assert all(isinstance(part, str) for part in contents)
    assert "0123456789" in contents[1] and "Nguyễn Văn An" in contents[1]
    assert result.extraction.parties[0].source_pages == []


def test_real_sdk_serializes_inline_pdf_without_network(pdf, party):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": ContractExtraction(parties=[party]).model_dump_json()}]}, "finishReason": "STOP"}]})
    client = genai.Client(api_key="test-placeholder", vertexai=False, http_options=types.HttpOptions(client_args={"transport": httpx.MockTransport(handler)}))
    try:
        GeminiDocumentExtractor("test-placeholder", client=client).extract_file(pdf)
    finally:
        client.close()
    data = json.loads(requests[0].content)
    blob = data["contents"][0]["parts"][1]["inlineData"]
    assert blob.get("mimeType", blob.get("mime_type")) == "application/pdf"
    import base64
    assert base64.urlsafe_b64decode(blob["data"]) == pdf.read_bytes()
    assert "$defs" not in data["generationConfig"]["responseJsonSchema"]
    assert "key" not in requests[0].url.params


def test_no_customer_saved_before_review_or_after_cancel(qt_app, real_store, pdf, party):
    before = real_store.customers()
    result = imported(pdf, party)
    dialog = CustomerImportReview(real_store, result)
    dialog.party_selector.setCurrentIndex(0)
    dialog.reject()
    assert real_store.customers() == before
    assert not (real_store.directory / "imported_contracts").exists()


def test_review_requires_party_selection_for_two_companies(qt_app, real_store, pdf, party):
    result = imported(pdf, party)
    result.extraction.parties.append(party.model_copy(update={"role": "Bên A", "company_name": "Công ty khác", "tax_code": "0987654321"}))
    dialog = CustomerImportReview(real_store, result)
    assert dialog.party_selector.currentIndex() == -1
    assert not dialog.save_button.isEnabled()
    dialog.reject()


def test_review_edits_are_saved_and_existing_customers_retained(qt_app, real_store, pdf, party):
    before = len(real_store.customers())
    dialog = CustomerImportReview(real_store, imported(pdf, party))
    row = CUSTOMER_FIELDS.index("contact_name")
    dialog.table.item(row, 2).setText("Người liên hệ được xác nhận")
    dialog.save_customer()
    assert dialog.saved_customer.contact_name == "Người liên hệ được xác nhận"
    assert len(real_store.customers()) == before + 1
    assert len(real_store.contract_customers()) == 1
    assert len(list((real_store.directory / "imported_contracts").glob("*.pdf"))) == 1


def test_reimport_same_tax_updates_one_record_and_preserves_unknown_fields(real_store, pdf, party):
    source = imported(pdf, party)
    first = save_imported_customer(real_store, source, replace(party.customer(), contact_name="Thông", aliases="Công ty A"))
    incoming = replace(party.customer(), representative="Người đại diện mới", address="", contact_name="")
    second = save_imported_customer(real_store, source, incoming)
    assert first.id == second.id
    assert second.contact_name == "Thông"
    assert second.address == party.address
    assert second.aliases == "Công ty A"
    assert second.representative == "Người đại diện mới"
    assert len(real_store.contract_customers()) == 1
    with real_store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM customer_imports").fetchone()[0] == 2


def test_excel_refresh_keeps_contract_customer_and_does_not_duplicate_tax(real_store, pdf, party):
    saved = save_imported_customer(real_store, imported(pdf, party), party.customer())
    real_store.replace_excel_customers([
        replace(saved, representative="Excel không được ghi đè bản đã xác nhận"),
        Customer(0, "Bình", "Công ty B", "0987654321"),
    ])
    all_customers = real_store.customers()
    assert len(all_customers) == 2
    assert next(c for c in all_customers if c.id == saved.id).representative == party.representative


def test_contract_customer_works_when_excel_source_missing(real_store, pdf, party):
    save_imported_customer(real_store, imported(pdf, party), party.customer())
    cfg = real_store.config()
    cfg["customer_source"] = str(pdf.parent / "moved.xlsx")
    real_store.save_config(cfg)
    template = next(real_store.templates.glob("*.docx"))
    pending = ContractService(real_store).prepare(Intent(tax_code=party.tax_code, amount_text="1 tỷ", work_description="Thi công Y"), "sample", template)
    assert pending.customer.tax_code == party.tax_code
    with pytest.raises(UserError, match="Excel nguồn"):
        ContractService(real_store).prepare(Intent(company_name="Công ty X", amount_text="1 tỷ", work_description="Thi công Y"), "sample", template)


def test_invalid_tax_cannot_be_approved(qt_app, real_store, pdf, party):
    dialog = CustomerImportReview(real_store, imported(pdf, party))
    dialog.table.item(CUSTOMER_FIELDS.index("tax_code"), 2).setText("123")
    dialog.save_customer()
    assert dialog.saved_customer is None
    assert not real_store.contract_customers()
    dialog.reject()


def test_representative_and_signatory_difference_is_flagged(pdf, party):
    party = party.model_copy(update={"representative": "Ông Nguyễn Văn An", "signatory_name": "Trần Văn Bình"})
    result = GeminiDocumentExtractor("test-placeholder", client=Client(ContractExtraction(parties=[party]).model_dump_json())).extract_file(pdf)
    assert "khác người ký" in result.extraction.parties[0].notes


@pytest.mark.parametrize("response", [None, "not-json", '{"parties":[]}', '{"parties":[{"role":"Bên B","company_name":123}]}'])
def test_invalid_extraction_is_not_accepted(pdf, response):
    with pytest.raises(UserError):
        GeminiDocumentExtractor("test-placeholder", client=Client(response)).extract_file(pdf)


def test_pdf_encryption_and_page_limit_rejected_before_api(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt("password")
    encrypted = tmp_path / "encrypted.pdf"
    with encrypted.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(UserError, match="mật khẩu"):
        load_import_document(encrypted)
    writer = PdfWriter()
    for _ in range(41):
        writer.add_blank_page(width=595, height=842)
    long_pdf = tmp_path / "long.pdf"
    with long_pdf.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(UserError, match="40 trang"):
        load_import_document(long_pdf)
