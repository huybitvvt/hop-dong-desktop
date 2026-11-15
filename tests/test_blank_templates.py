from io import BytesIO
import json
from types import SimpleNamespace

from docx import Document
import pytest

from contract_app.documents import document_text, render_contract, template_fields
from contract_app.models import UserError
from contract_app.processing_cache import ProcessingCache
from contract_app.template_builder import (
    GeminiTemplateBuilder, Replacement, TemplateDraft, TemplatePlan, add_blank_hints,
    anchors_from_word, blank_slots_from_word, build_template_bytes, replacement_spans,
    save_template, LayoutPage, layout_to_word,
)
from contract_app.template_review import TemplateReview


def blank_draft(path, doc, role="Bên B"):
    doc.save(path)
    data = path.read_bytes()
    anchors, slots = anchors_from_word(data), blank_slots_from_word(data)
    plan = add_blank_hints(TemplatePlan(title="Mẫu trống thử nghiệm"), anchors, slots, role)
    return TemplateDraft(path, data, data, anchors, plan, role, slots=slots)


def minimal_blank(tmp_path, company="Tên công ty: ........", work="Nội dung công việc: ________"):
    doc = Document()
    doc.add_paragraph("BÊN B — ĐỐI TÁC")
    doc.add_paragraph(company)
    doc.add_paragraph(work)
    return blank_draft(tmp_path / "blank.docx", doc)


@pytest.mark.parametrize("blank", ["........", "_ _ _ _ _", "……", "＿＿＿＿"])
def test_dotted_blank_preserves_labels_and_original_and_fills_word(tmp_path, store, blank):
    draft = minimal_blank(tmp_path, "Tên công ty: " + blank)
    before = draft.source.read_bytes()
    template = save_template(store, draft, draft.plan)
    result = render_contract(template, {"company_name": "CÔNG TY A & B", "work_description": "Sơn văn phòng"}, tmp_path / "out", "A")
    doc = Document(result)
    assert doc.paragraphs[1].text == "Tên công ty: CÔNG TY A & B"
    assert doc.paragraphs[2].text == "Nội dung công việc: Sơn văn phòng"
    assert draft.source.read_bytes() == before
    assert "{{" not in document_text(result)


@pytest.mark.parametrize("role", ["Bên A", "Bên B"])
def test_two_empty_parties_in_table_use_correct_company_and_seller_fields(tmp_path, store, role):
    doc = Document()
    table = doc.add_table(rows=5, cols=4)
    table.style = "Table Grid"
    table.cell(0, 0).merge(table.cell(0, 1)).text = "BÊN A — CÔNG TY CỦA BẠN"
    table.cell(0, 2).merge(table.cell(0, 3)).text = "BÊN B — ĐỐI TÁC"
    for row, label in enumerate(["Tên công ty", "Mã số thuế", "Địa chỉ", "Số điện thoại"], 1):
        table.cell(row, 0).text = table.cell(row, 2).text = label
    doc.add_paragraph("Điều 1. Nội dung công việc:")
    draft = blank_draft(tmp_path / "parties.docx", doc, role)
    assert {"company_name", "seller_company", "tax_code", "seller_tax_code", "seller_phone"} <= {r.field for r in draft.plan.replacements}
    template = save_template(store, draft, draft.plan)
    values = {name: name + "_VALUE" for name in template_fields(template)}
    result = Document(render_contract(template, values, tmp_path / "out", "two-parties"))
    client, seller = (1, 3) if role == "Bên A" else (3, 1)
    assert result.tables[0].cell(1, client).text == "company_name_VALUE"
    assert result.tables[0].cell(1, seller).text == "seller_company_VALUE"
    assert result.tables[0].cell(2, client).text == "tax_code_VALUE"
    assert result.tables[0].cell(2, seller).text == "seller_tax_code_VALUE"
    assert result.tables[0].cell(1, 0).text == result.tables[0].cell(1, 2).text == "Tên công ty"
    assert result.tables[0].style.name == "Table Grid"


@pytest.mark.parametrize("trailing", ["", "   ", "\t"])
def test_label_only_insertions_keep_text_and_spacing(tmp_path, trailing):
    draft = minimal_blank(tmp_path, "Tên công ty:" + trailing, "Nội dung công việc:" + trailing)
    result = Document(BytesIO(build_template_bytes(draft, draft.plan)))
    assert result.paragraphs[1].text == "Tên công ty: {{ company_name }}"
    assert result.paragraphs[2].text == "Nội dung công việc: {{ work_description }}"


def test_empty_paragraph_after_label_keeps_label_and_paragraph_style(tmp_path):
    doc = Document()
    for text in ["BÊN B", "Tên công ty:", "", "Nội dung công việc:", ""]:
        doc.add_paragraph(text)
    doc.paragraphs[2].style = "Caption"
    draft = blank_draft(tmp_path / "paragraph.docx", doc)
    assert all(r.source_text == "" and r.slot_id for r in draft.plan.replacements)
    result = Document(BytesIO(build_template_bytes(draft, draft.plan)))
    assert result.paragraphs[1].text == "Tên công ty:"
    assert result.paragraphs[2].text == "{{ company_name }}"
    assert result.paragraphs[2].style.name == "Caption"
    assert result.paragraphs[3].text == "Nội dung công việc:"
    assert result.paragraphs[4].text == "{{ work_description }}"


@pytest.mark.parametrize("date", ["Ngày ... tháng ... năm ...", "Ngày    tháng    năm    ", "Ngày\ttháng\tnăm\t"])
def test_multiple_date_blanks_in_one_paragraph_stay_separated(tmp_path, date):
    doc = Document()
    doc.add_paragraph(date)
    doc.add_paragraph("BÊN B")
    doc.add_paragraph("Tên công ty: ...")
    doc.add_paragraph("Nội dung công việc: ...")
    draft = blank_draft(tmp_path / "date.docx", doc)
    assert {"day", "month", "year"} <= {r.field for r in draft.plan.replacements}
    result = Document(BytesIO(build_template_bytes(draft, draft.plan)))
    assert result.paragraphs[0].text == "Ngày {{ day }} tháng {{ month }} năm {{ year }}"


def test_split_run_underscores_keep_formatting(tmp_path):
    doc = Document()
    doc.add_paragraph("BÊN B")
    p = doc.add_paragraph("Tên công ty: ")
    p.add_run("____").bold = True
    p.add_run("____").italic = True
    doc.add_paragraph("Nội dung công việc: ...")
    draft = blank_draft(tmp_path / "runs.docx", doc)
    result = Document(BytesIO(build_template_bytes(draft, draft.plan)))
    assert result.paragraphs[1].text == "Tên công ty: {{ company_name }}"
    assert result.paragraphs[1].runs[1].bold


@pytest.mark.parametrize("change", [
    {"slot_id": "made-up"}, {"anchor": "word/document.xml:0"},
    {"source_text": "wrong data"}, {"slot_id": None, "source_text": ""},
])
def test_invalid_blank_targets_cannot_save_or_modify_source(tmp_path, store, change):
    draft = minimal_blank(tmp_path)
    draft.plan.replacements[0] = Replacement.model_validate(draft.plan.replacements[0].model_dump() | change)
    before = set(store.templates.iterdir())
    with pytest.raises(UserError):
        save_template(store, draft, draft.plan)
    assert set(store.templates.iterdir()) == before
    assert draft.source.read_bytes() == draft.source_data


def test_duplicate_zero_length_insertions_and_label_replacement_rejected(tmp_path):
    draft = minimal_blank(tmp_path, "Tên công ty:", "Nội dung công việc:")
    draft.plan.replacements.append(draft.plan.replacements[0].model_copy())
    with pytest.raises(UserError, match="chồng"):
        build_template_bytes(draft, draft.plan)
    draft.plan.replacements.pop()
    draft.plan.replacements[0] = Replacement(anchor=draft.anchors[1].id, source_text="Tên công ty:", field="company_name")
    with pytest.raises(UserError, match="nhãn"):
        build_template_bytes(draft, draft.plan)


def test_spacer_paragraphs_not_automatically_filled_and_unknown_empty_cell_can_be_selected(tmp_path, store, qt_app):
    doc = Document()
    doc.add_paragraph("HỢP ĐỒNG THỬ NGHIỆM")
    doc.add_paragraph("")
    doc.add_paragraph("BÊN B")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Thông tin đơn vị bên mua"
    table.cell(1, 0).text = "Phần hàng hóa cần cung cấp"
    draft = blank_draft(tmp_path / "manual.docx", doc)
    assert not draft.plan.replacements
    assert not next(slot for slot in draft.slots if slot.kind == "empty_paragraph").automatic
    assert all(slot.automatic for slot in draft.slots if slot.kind == "empty_cell")
    dialog = TemplateReview(store, draft)
    for field, label in [("company_name", "Thông tin đơn vị bên mua"), ("work_description", "Phần hàng hóa cần cung cấp")]:
        index = next(i for i, a in enumerate(draft.anchors) if not a.text and label in a.context)
        dialog.anchors.setCurrentRow(index)
        assert dialog.add_blank_button.isEnabled()
        dialog.add_blank()
        dialog.table.cellWidget(dialog.table.rowCount() - 1, 2).setCurrentIndex(dialog.table.cellWidget(dialog.table.rowCount() - 1, 2).findData(field))
    dialog.save()
    assert dialog.saved_path is not None, dialog.error.text()
    result = Document(dialog.saved_path)
    assert result.paragraphs[1].text == ""
    assert result.tables[0].cell(0, 0).text == "Thông tin đơn vị bên mua"
    assert result.tables[0].cell(0, 1).text == "{{ company_name }}"
    assert result.tables[0].cell(1, 1).text == "{{ work_description }}"
    dialog.close()


def test_review_displays_empty_slot_and_round_trips_without_losing_id(tmp_path, store, qt_app):
    draft = minimal_blank(tmp_path, "Tên công ty:", "Nội dung công việc:")
    dialog = TemplateReview(store, draft)
    assert dialog.table.item(0, 1).text() == "[Chèn sau nhãn]"
    assert dialog.plan().replacements[0].slot_id == draft.plan.replacements[0].slot_id
    dialog.anchors.setCurrentRow(1)
    count = dialog.table.rowCount()
    dialog.add_blank()
    assert dialog.table.rowCount() == count
    assert "đã có" in dialog.error.text()
    dialog.save()
    assert dialog.saved_path is not None, dialog.error.text()
    assert template_fields(dialog.saved_path) == {"company_name", "work_description"}


def test_ai_receives_blank_context_and_repeated_import_uses_cache(tmp_path):
    draft = minimal_blank(tmp_path)
    class Client:
        def __init__(self):
            self.calls, self.models = [], self

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text=TemplatePlan(title="Mẫu trống").model_dump_json())

    client = Client()
    builder = GeminiTemplateBuilder("test-placeholder", client=client, cache=ProcessingCache(tmp_path / "cache"))
    first = builder.prepare(draft.source)
    request = json.loads(client.calls[0]["contents"])
    assert request["blank_slots"][0]["role"] == "Bên B"
    assert request["blank_slots"][0]["suggested_field"] == "company_name"
    assert request["paragraphs"][1]["context"]
    replacement_spans(first.anchors, first.plan, first.slots)
    again = builder.prepare(draft.source)
    assert len(client.calls) == 1
    assert "không gọi lại API" in again.processing_note
    assert again.plan.replacements == first.plan.replacements


def test_shortened_dotted_text_from_model_uses_validated_slot_not_guessed_length(tmp_path):
    draft = minimal_blank(tmp_path)
    proposal = draft.plan.model_copy(deep=True)
    proposal.replacements[0].source_text = "..."
    plan = add_blank_hints(proposal, draft.anchors, draft.slots, "Bên B")
    result = Document(BytesIO(build_template_bytes(draft, plan)))
    assert result.paragraphs[1].text == "Tên công ty: {{ company_name }}"
    assert "..." not in result.paragraphs[1].text


@pytest.mark.parametrize("header", [["BÊN A", "", "BÊN B", ""], ["BÊN A", "BÊN B"], ["BÊN A", "BÊN B", "", ""]])
def test_reconstructed_pdf_table_with_empty_header_cells_keeps_party_columns(tmp_path, header):
    layout = LayoutPage.model_validate({"blocks": [
        {"kind": "heading", "text": "HỢP ĐỒNG THỬ NGHIỆM"},
        {"kind": "table", "rows": [header,
            ["Tên công ty", "", "Tên công ty", ""], ["Mã số thuế", "...", "Mã số thuế", "..."]]},
        {"text": "Nội dung công việc: ..."},
    ]})
    data = layout_to_word([layout], [(595, 842)])
    anchors, slots = anchors_from_word(data), blank_slots_from_word(data)
    plan = add_blank_hints(TemplatePlan(title="Mẫu PDF"), anchors, slots, "Bên B")
    path = tmp_path / "reconstructed.docx"
    draft = TemplateDraft(path, data, data, anchors, plan, slots=slots)
    result = Document(BytesIO(build_template_bytes(draft, plan)))
    assert result.tables[0].cell(1, 1).text == "{{ seller_company }}"
    assert result.tables[0].cell(1, 3).text == "{{ company_name }}"
    assert result.tables[0].cell(2, 1).text == "{{ seller_tax_code }}"
    assert result.tables[0].cell(2, 3).text == "{{ tax_code }}"


def test_obvious_customer_and_seller_blank_roles_override_an_incorrect_ai_mapping(tmp_path):
    draft = minimal_blank(tmp_path)
    draft.plan.replacements[0].field = "seller_company"
    corrected = add_blank_hints(draft.plan, draft.anchors, draft.slots, "Bên B")
    assert corrected.replacements[0].field == "company_name"
    build_template_bytes(draft, corrected)
