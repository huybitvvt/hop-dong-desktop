from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from docx import Document
from lxml import etree
from pypdf import PdfWriter
import pytest

from contract_app.documents import document_text, render_contract, template_fields, template_is_draft
from contract_app.models import UserError
from contract_app.template_builder import (
    GeminiTemplateBuilder, LayoutBlock, LayoutPage, Replacement, TemplateDraft, TemplatePlan,
    anchors_from_word, build_template_bytes, layout_to_word, save_template, template_metadata,
    response_schema,
)
from contract_app.template_review import TemplateReview
from contract_app.template_selection import confident_template, rank_templates


@pytest.fixture
def filled(tmp_path):
    path = tmp_path / "Hop-dong-da-dien.docx"
    doc = Document()
    paragraph = doc.add_paragraph("BÊN B: ")
    first = paragraph.add_run("CÔNG TY ")
    first.bold = True
    paragraph.add_run("AN PHÚ DEMO").italic = True
    doc.add_paragraph("Hàng hóa: Container các loại phục vụ dự án cũ.")
    doc.add_table(rows=1, cols=2).cell(0, 1).text = "MST: 0000000111"
    doc.sections[0].header.paragraphs[0].text = "CÔNG TY AN PHÚ DEMO"
    doc.sections[0].footer.paragraphs[0].text = "Số: HD-CU-01"
    doc.save(path)
    return path


def draft_for(path):
    data = path.read_bytes()
    anchors = anchors_from_word(data)
    mappings = []
    for anchor in anchors:
        for source, name in [("CÔNG TY AN PHÚ DEMO", "company_name"),
                             ("Container các loại phục vụ dự án cũ", "work_description"),
                             ("0000000111", "tax_code"), ("HD-CU-01", "contract_number")]:
            if source in anchor.text:
                mappings.append(Replacement(anchor=anchor.id, source_text=source, field=name))
    plan = TemplatePlan(title="Nguyên tắc mua bán Container", contract_type="mua bán Container", replacements=mappings)
    return TemplateDraft(path, data, data, anchors, plan)


def test_filled_word_becomes_reusable_and_keeps_runs_tables_headers_and_footer(filled, store):
    original = filled.read_bytes()
    draft = draft_for(filled)
    target = save_template(store, draft, draft.plan, is_draft=False)
    assert filled.read_bytes() == original
    assert template_fields(target) == {"company_name", "work_description", "tax_code", "contract_number"}
    assert not template_is_draft(target)
    output = render_contract(target, {"company_name": "CÔNG TY MỚI & A", "work_description": "Container dự án Y-2026",
                                     "tax_code": "0012345678", "contract_number": "TEST-009"}, target.parent / "out", "Mới")
    doc = Document(output)
    assert doc.paragraphs[0].runs[1].bold
    assert doc.paragraphs[0].runs[2].italic
    assert "CÔNG TY MỚI & A" in doc.paragraphs[0].text
    assert doc.tables[0].cell(0, 1).text == "MST: 0012345678"
    assert doc.sections[0].header.paragraphs[0].text == "CÔNG TY MỚI & A"
    assert doc.sections[0].footer.paragraphs[0].text == "Số: TEST-009"
    assert "AN PHÚ DEMO" not in document_text(output)
    metadata = template_metadata(target)
    assert metadata["source_sha256"] == draft.sha256
    assert Path(metadata["source_path"]).read_bytes() == original


@pytest.mark.parametrize("change", [
    {"source_text": "Không có trong nguồn"}, {"anchor": "word/document.xml:999"},
    {"field": "os.system"}, {"occurrence": 2},
])
def test_incorrect_proposals_cannot_publish_partial_template(filled, store, change):
    draft = draft_for(filled)
    draft.plan.replacements[0] = Replacement.model_validate(draft.plan.replacements[0].model_dump() | change)
    before = set(store.templates.glob("*"))
    with pytest.raises(UserError):
        save_template(store, draft, draft.plan)
    assert set(store.templates.glob("*")) == before
    assert not (store.directory / "template_sources").exists()


def test_overlapping_proposals_are_rejected_and_cancellation_does_not_save(filled, store, qt_app):
    draft = draft_for(filled)
    draft.plan.replacements.append(draft.plan.replacements[0])
    with pytest.raises(UserError, match="chồng"):
        build_template_bytes(draft, draft.plan)
    before = set(store.templates.glob("*"))
    dialog = TemplateReview(store, draft)
    dialog.reject()
    assert not dialog.saved_path
    assert set(store.templates.glob("*")) == before
    assert not (store.directory / "template_sources").exists()


def test_ui_can_review_save_and_edit_bad_proposals(filled, store, qt_app):
    draft = draft_for(filled)
    draft.plan.replacements[0].source_text = "Sai nội dung"
    dialog = TemplateReview(store, draft)
    dialog.save()
    assert dialog.saved_path is None
    assert "Không khớp" in dialog.error.text()
    dialog.table.item(0, 1).setText("CÔNG TY AN PHÚ DEMO")
    dialog.save()
    assert dialog.saved_path.exists()
    assert template_is_draft(dialog.saved_path)


def test_source_snapshot_is_used_even_if_original_changes(filled, store):
    draft = draft_for(filled)
    filled.write_bytes(b"changed outside the app")
    target = save_template(store, draft, draft.plan)
    assert "company_name" in template_fields(target)
    assert Path(template_metadata(target)["source_path"]).read_bytes() == draft.source_data


def test_multiple_occurrences_and_adjacent_replacements_keep_labels(tmp_path):
    doc = Document()
    doc.add_paragraph("AA AA BB")
    path = tmp_path / "contract.docx"
    doc.save(path)
    data = path.read_bytes()
    anchors = anchors_from_word(data)
    plan = TemplatePlan(title="Mẫu", replacements=[
        Replacement(anchor=anchors[0].id, source_text="AA", field="company_name", occurrence=2),
        Replacement(anchor=anchors[0].id, source_text="BB", field="work_description"),
    ])
    draft = TemplateDraft(path, data, data, anchors, plan)
    output = Document(BytesIO(build_template_bytes(draft, plan)))
    assert output.paragraphs[0].text == "AA {{ company_name }} {{ work_description }}"


def test_multiline_values_and_tabs_are_preserved_and_replaced_as_one_field(tmp_path):
    doc = Document()
    p = doc.add_paragraph("Bên B:\tCÔNG TY ")
    p.add_run().add_break()
    p.add_run("AN PHÚ DEMO").bold = True
    doc.add_paragraph("Hàng hóa: Container")
    path = tmp_path / "multiline.docx"
    doc.save(path)
    data = path.read_bytes()
    anchors = anchors_from_word(data)
    assert anchors[0].text == "Bên B:\tCÔNG TY \nAN PHÚ DEMO"
    plan = TemplatePlan(title="Mẫu", replacements=[
        Replacement(anchor=anchors[0].id, source_text="CÔNG TY \nAN PHÚ DEMO", field="company_name"),
        Replacement(anchor=anchors[1].id, source_text="Container", field="work_description"),
    ])
    draft = TemplateDraft(path, data, data, anchors, plan)
    result = Document(BytesIO(build_template_bytes(draft, plan)))
    assert result.paragraphs[0].text == "Bên B:\t{{ company_name }}"


def test_signature_images_and_image_relationships_are_removed(filled, store):
    import base64
    doc = Document(filled)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7N8AAAAASUVORK5CYII=")
    doc.add_picture(BytesIO(png))
    doc.save(filled)
    draft = draft_for(filled)
    target = save_template(store, draft, draft.plan)
    with zipfile.ZipFile(target) as archive:
        assert not any(name.startswith("word/media/") for name in archive.namelist())
        for name in archive.namelist():
            if name.endswith(".rels"):
                assert b'relationships/image"' not in archive.read(name)
    assert Document(target).inline_shapes.__len__() == 0


def test_metadata_is_ignored_if_template_was_edited_after_review(filled, store):
    draft = draft_for(filled)
    target = save_template(store, draft, draft.plan)
    assert template_metadata(target)
    doc = Document(target)
    doc.add_paragraph("Edited outside")
    doc.save(target)
    assert template_metadata(target) == {}


class QueueClient:
    def __init__(self, responses):
        self.responses, self.calls, self.models = list(responses), [], self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        return SimpleNamespace(text=response)


def test_word_ai_request_contains_only_selected_contract_and_literal_plan(filled):
    draft = draft_for(filled)
    client = QueueClient([draft.plan.model_dump_json()])
    actual = GeminiTemplateBuilder("test-placeholder", client=client).prepare(filled, "Bên B")
    request = json.loads(client.calls[0]["contents"])
    assert request["customer_role"] == "Bên B"
    assert request["paragraphs"][0]["text"] == draft.anchors[0].text
    assert client.calls[0]["model"] == "gemini-3.5-flash-lite"
    assert actual.source_data == filled.read_bytes()
    assert "$defs" not in client.calls[0]["config"].response_json_schema
    schema = client.calls[0]["config"].response_json_schema
    assert "title" in schema["properties"] and "title" in schema["required"]


def test_request_schema_preserves_all_required_properties():
    def check(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert set(node.get("required", [])) <= set(node["properties"])
            assert "$ref" not in node and "$defs" not in node
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(response_schema(TemplatePlan))


def test_pdf_scan_is_rebuilt_with_tables_then_mapped(tmp_path):
    pdf = tmp_path / "scan.pdf"
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=595, height=842)
    with pdf.open("wb") as handle:
        writer.write(handle)
    layout = {"pages": [
        {"blocks": [{"kind": "heading", "text": "HỢP ĐỒNG MUA BÁN", "align": "center"},
                    {"text": "BÊN B: CÔNG TY AN PHÚ DEMO"}, {"text": "Hàng hóa: Container dự án cũ"}]},
        {"blocks": [{"kind": "table", "rows": [["Thông tin", "Giá trị"], ["Mã số thuế", "0000000111"]]}]},
    ]}
    pages = [LayoutPage.model_validate(page) for page in layout["pages"]]
    data = layout_to_word(pages, [(595, 842)] * 2)
    anchors = anchors_from_word(data)
    replacements = [Replacement(anchor=a.id, source_text=source, field=field)
                    for a in anchors for source, field in [("CÔNG TY AN PHÚ DEMO", "company_name"), ("Container dự án cũ", "work_description")]
                    if source in a.text]
    plan = TemplatePlan(title="Mua bán", replacements=replacements)
    client = QueueClient([json.dumps(layout, ensure_ascii=False), plan.model_dump_json()])
    result = GeminiTemplateBuilder("test-placeholder", client=client).prepare(pdf)
    assert result.reconstructed
    assert len(client.calls) == 2
    assert client.calls[0]["contents"][0].inline_data.mime_type == "application/pdf"
    doc = Document(BytesIO(result.word_data))
    assert len(doc.tables) == 1
    assert doc.tables[0].cell(1, 1).text == "0000000111"
    assert len(doc.element.xpath(".//w:br[@w:type='page']")) == 1
    build_template_bytes(result, result.plan)


def test_pdf_missing_pages_and_cancel_are_rejected_before_save(tmp_path):
    pdf = tmp_path / "scan.pdf"
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=595, height=842)
    with pdf.open("wb") as handle:
        writer.write(handle)
    client = QueueClient([json.dumps({"pages": [{"blocks": [{"text": "Thiếu trang"}]}]})])
    with pytest.raises(UserError, match="thiếu trang"):
        GeminiTemplateBuilder("test-placeholder", client=client).prepare(pdf)
    client = QueueClient([])
    with pytest.raises(UserError, match="dừng"):
        GeminiTemplateBuilder("test-placeholder", client=client).prepare(pdf, cancelled=lambda: True)
    assert not client.calls


def test_local_template_selection_distinguishes_purchase_from_project_construction(filled, store):
    draft = draft_for(filled)
    purchase = save_template(store, draft, draft.plan)
    paths = list(store.templates.glob("*.docx"))
    ranked = rank_templates("Tạo hợp đồng nguyên tắc mua bán Container với An Phú Demo. Nội dung: Container phục vụ thi công dự án Y", paths)
    assert confident_template(ranked) == purchase
    assert confident_template(rank_templates("Tạo hợp đồng với An Phú Demo", paths)) is None
