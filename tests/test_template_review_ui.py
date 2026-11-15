from io import BytesIO

from docx import Document
from PySide6.QtCore import Qt

from contract_app.template_builder import TemplateDraft, TemplatePlan, add_blank_hints, anchors_from_word, blank_slots_from_word, build_template_bytes
from contract_app.template_review import TemplateReview
from contract_app.theme import STYLE


def review_draft(tmp_path):
    doc = Document()
    for value in ["HỢP ĐỒNG THỬ NGHIỆM", "BÊN A (BÊN GIAO THẦU): ...", "Mã số thuế: ...", "Địa chỉ: ...",
                  "Đại diện: ... — Chức vụ: ...", "BÊN B (BÊN NHẬN THẦU): ...", "Địa chỉ: ...", "Nội dung công việc: ..."]:
        doc.add_paragraph(value)
    path = tmp_path / "review.docx"
    doc.save(path)
    data = path.read_bytes()
    anchors, slots = anchors_from_word(data), blank_slots_from_word(data)
    # Bare party headings have a clear identity but no explicit company label.
    from contract_app.template_builder import Replacement
    names = [Replacement(anchor=slot.anchor, slot_id=slot.id, field="company_name" if slot.role == "Bên A" else "seller_company")
             for slot in slots if "BÊN " in next(a.text for a in anchors if a.id == slot.anchor)]
    names += [Replacement(anchor=slot.anchor, slot_id=slot.id, field="position") for slot in slots
              if slot.hint is None and next(a.text for a in anchors if a.id == slot.anchor).startswith("Đại diện:")]
    plan = add_blank_hints(TemplatePlan(title="Mẫu dễ đọc", replacements=names), anchors, slots, "Bên A")
    return TemplateDraft(path, data, data, anchors, plan, "Bên A", slots=slots)


def test_simple_review_uses_source_labels_and_full_field_names_without_technical_columns(tmp_path, store, qt_app):
    draft = review_draft(tmp_path)
    dialog = TemplateReview(store, draft)
    dialog.setStyleSheet(STYLE)
    dialog.resize(980, 680)
    dialog.show()
    qt_app.processEvents()
    captions = [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]
    assert "Bên A · Địa chỉ" in captions and "Bên B · Địa chỉ" in captions
    assert "Bên A · Đại diện" in captions and "Bên A · Chức vụ" in captions
    assert all("..." not in value and not value.isdigit() for value in captions)
    assert "Bên A (bên giao thầu)" in dialog.role_hint.text()
    assert "Bên B (bên nhận thầu)" in dialog.role_hint.text()
    assert dialog.table.isColumnHidden(1) and dialog.table.isColumnHidden(3)
    assert not dialog.source_panel.isVisible() and not dialog.table.verticalHeader().isVisible()
    for row in range(dialog.table.rowCount()):
        combo = dialog.table.cellWidget(row, 2)
        assert combo.fontMetrics().horizontalAdvance(combo.currentText()) < combo.width() - 36
    assert [r.model_dump() for r in dialog.plan().replacements] == [r.model_dump() for r in draft.plan.replacements]
    dialog.close()


def test_advanced_controls_toggle_without_losing_mappings_or_adding_source_noise(tmp_path, store, qt_app):
    draft = review_draft(tmp_path)
    dialog = TemplateReview(store, draft)
    before = dialog.plan().model_dump()
    dialog.advanced_toggle.setChecked(True)
    assert not dialog.table.isColumnHidden(1) and not dialog.table.isColumnHidden(3)
    dialog.advanced_toggle.setChecked(False)
    assert dialog.plan().model_dump() == before
    dialog.save()
    assert dialog.saved_path is not None, dialog.error.text()
    assert draft.source.read_bytes() == draft.source_data
    assert "Mã số thuế: {{ tax_code }}" in "\n".join(p.text for p in Document(dialog.saved_path).paragraphs)


def test_source_caption_stays_true_when_changing_destination_and_preview_updates(tmp_path, store, qt_app):
    dialog = TemplateReview(store, review_draft(tmp_path))
    row = next(i for i in range(dialog.table.rowCount()) if dialog.table.item(i, 0).text() == "Bên A · Địa chỉ")
    dialog.table.setCurrentCell(row, 0)
    assert "Khách hàng · Địa chỉ" in dialog.preview.toPlainText()
    combo = dialog.table.cellWidget(row, 2)
    combo.setCurrentIndex(combo.findData("phone"))
    assert dialog.table.item(row, 0).text() == "Bên A · Địa chỉ"
    assert "Khách hàng · Điện thoại" in dialog.preview.toPlainText()
    dialog.close()


def test_review_preview_renders_document_markup_as_literal_text(tmp_path, store, qt_app):
    draft = review_draft(tmp_path)
    # Source text is untrusted. Escape it when building the visual preview.
    data = draft.source_data
    doc = Document(BytesIO(data))
    doc.paragraphs[3].text = "Địa chỉ <văn phòng & kho>: ..."
    stream = BytesIO()
    doc.save(stream)
    draft.word_data = stream.getvalue()
    draft.anchors = anchors_from_word(draft.word_data)
    dialog = TemplateReview(store, draft)
    row = next(i for i in range(dialog.table.rowCount()) if "Địa chỉ <văn phòng & kho>" in dialog.table.item(i, 0).text())
    dialog.table.setCurrentCell(row, 0)
    assert "Địa chỉ <văn phòng & kho>" in dialog.preview.toPlainText()
    dialog.close()
