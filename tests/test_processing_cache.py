import json
from types import SimpleNamespace

from docx import Document
from pypdf import PdfWriter

from contract_app.contract_import import ContractExtraction, ContractParty, GeminiDocumentExtractor
from contract_app.gemini import GeminiExtractor
from contract_app.models import Intent
from contract_app.processing_cache import ProcessingCache
from contract_app.template_builder import GeminiTemplateBuilder, LayoutPage, Replacement, TemplatePlan, anchors_from_word, layout_to_word


class Client:
    def __init__(self, responses):
        self.responses, self.calls, self.models = list(responses), [], self
    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.responses.pop(0))


def test_cache_ignores_corruption_and_keeps_identifiers_out_of_filenames(tmp_path):
    cache = ProcessingCache(tmp_path / "cache")
    cache.put("private task", {"result": "Đã đọc"})
    assert cache.get("private task") == {"result": "Đã đọc"}
    path = next(cache.folder.glob("*.json"))
    assert "private" not in path.name
    path.write_text('{"version":1,"checksum":"bad","payload":{"result":"changed"}}')
    assert cache.get("private task") is None


def test_chat_reuses_intent_but_model_or_prompt_change_makes_new_request(tmp_path):
    cache = ProcessingCache(tmp_path / "cache")
    response = Intent(company_name="An Phú Demo", work_description="Container dự án Y").model_dump_json()
    client = Client([response] * 3)
    parser = GeminiExtractor("test-placeholder", client=client, cache=cache)
    prompt = "Tạo hợp đồng với An Phú Demo, nội dung: Container dự án Y"
    assert parser.extract(prompt) == parser.extract(prompt)
    assert len(client.calls) == 1
    parser.extract(prompt + ".")
    GeminiExtractor("test-placeholder", model="gemini-test", client=client, cache=cache).extract(prompt)
    assert len(client.calls) == 3
    assert all("test-placeholder" not in path.read_text(encoding="utf-8") for path in cache.folder.glob("*.json"))


def test_customer_import_reuses_result_and_explicit_refresh_calls_api(tmp_path):
    source = tmp_path / "contract.docx"
    doc = Document()
    doc.add_paragraph("Công ty An Phú Demo — mã số thuế 0000000111")
    doc.save(source)
    response = ContractExtraction(parties=[ContractParty(role="Bên B", company_name="An Phú Demo", tax_code="0000000111")]).model_dump_json()
    client = Client([response] * 2)
    parser = GeminiDocumentExtractor("test-placeholder", client=client, cache=ProcessingCache(tmp_path / "cache"))
    first = parser.extract_file(source)
    assert parser.extract_file(source).extraction == first.extraction
    assert len(client.calls) == 1
    parser.extract_file(source, force_refresh=True)
    assert len(client.calls) == 2


def test_pdf_layout_and_template_plan_are_both_reused_without_api(tmp_path):
    pdf = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with pdf.open("wb") as handle:
        writer.write(handle)
    layout = {"pages": [{"blocks": [{"text": "BÊN B: CÔNG TY AN PHÚ DEMO"},
                                    {"text": "Hàng hóa: Container phục vụ dự án cũ"}]}]}
    page = LayoutPage.model_validate(layout["pages"][0])
    data = layout_to_word([page], [(595, 842)], compact=True)
    anchors = anchors_from_word(data)
    plan = TemplatePlan(title="Mua bán", replacements=[
        Replacement(anchor=anchors[0].id, source_text="CÔNG TY AN PHÚ DEMO", field="company_name"),
        Replacement(anchor=anchors[1].id, source_text="Container phục vụ dự án cũ", field="work_description"),
    ])
    client = Client([json.dumps(layout, ensure_ascii=False), plan.model_dump_json()])
    builder = GeminiTemplateBuilder("test-placeholder", client=client, cache=ProcessingCache(tmp_path / "cache"))
    first = builder.prepare(pdf)
    second = builder.prepare(pdf)
    assert len(client.calls) == 2
    assert first.plan.replacements == second.plan.replacements
