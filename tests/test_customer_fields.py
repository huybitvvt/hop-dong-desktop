from dataclasses import asdict, replace
from datetime import datetime
from io import BytesIO
import json
from types import SimpleNamespace

from docx import Document
from openpyxl import Workbook
import pytest

from contract_app.contract_import import ContractExtraction, ContractParty, GeminiDocumentExtractor, ImportDocument, ImportResult
from contract_app.customer_editor import CustomerEditor
from contract_app.customer_fields import customer_field_key, extra_context
from contract_app.customer_review import CustomerImportReview
from contract_app.customers import read_customers
from contract_app.documents import document_text, missing_fields, template_fields
from contract_app.models import Customer, Intent, UserError
from contract_app.service import ContractService
from contract_app.template_builder import GeminiTemplateBuilder, TemplateDraft, TemplatePlan, Replacement, anchors_from_word, blank_slots_from_word, save_template, template_metadata
from contract_app.template_review import TemplateReview
from contract_app.ui import MainWindow, MissingDialog


def excel(tmp_path, headers, rows, name="customers.xlsx"):
    book = Workbook()
    book.active.append(headers)
    for row in rows:
        book.active.append(row)
    path = tmp_path / name
    book.save(path)
    return path


def custom_template(tmp_path):
    path = tmp_path / "custom.docx"
    doc = Document()
    for text in ["Đối tác: {{ company_name }}", "Nội dung: {{ work_description }}", "Số CCCD: {{ customer_so_cccd }}", "Nơi cấp: {{ customer_noi_cap }}"]:
        doc.add_paragraph(text)
    doc.save(path)
    return path


def test_excel_keeps_unrecognized_fields_dates_and_leading_zeroes(tmp_path):
    book = Workbook()
    book.active.append(["Tên công ty", "Mã số thuế", "Số CCCD", "Ngày cấp", "Email kế toán", "Trường còn trống"])
    book.active.append(["Công ty A", "0123456789", 1234567, datetime(2020, 3, 4), "kt@example.test", None])
    book.active["C2"].number_format = "000000000000"
    path = tmp_path / "more.xlsx"
    book.save(path)
    customer = read_customers(path)[0]
    assert customer.contact_name == "" and customer.address == ""
    assert customer.extra_fields == {"Số CCCD": "000001234567", "Ngày cấp": "2020-03-04", "Email kế toán": "kt@example.test", "Trường còn trống": ""}


@pytest.mark.parametrize("headers,row", [
    (["Tên công ty"], ["Công ty A"]),
    (["Tên khách hàng", "Số CCCD"], ["Nguyễn Văn A", "000000000001"]),
    (["Mã số thuế", "Chi nhánh"], ["0123456789", "Đơn vị mô phỏng"]),
])
def test_partial_customer_does_not_require_all_old_fields(tmp_path, headers, row):
    customer = read_customers(excel(tmp_path, headers, [row]))[0]
    assert any((customer.company_name, customer.contact_name, customer.tax_code))


@pytest.mark.parametrize("headers,values", [
    (["Tên công ty", "Số CCCD", "so cccd"], ["A", "001", "002"]),
    (["Tên công ty", "Email kế toán"], ["A", '=HYPERLINK("http://example.test")']),
])
def test_bad_custom_excel_columns_do_not_change_existing_data(store, tmp_path, headers, values):
    before = store.customers()
    with pytest.raises(UserError):
        store.replace_excel_customers(read_customers(excel(tmp_path, headers, [values])))
    assert store.customers() == before


def test_reimport_fewer_excel_columns_keeps_old_values_and_extra_fields(store, tmp_path):
    first = excel(tmp_path, ["Tên công ty", "Mã số thuế", "Email", "Số CCCD", "Chi nhánh"], [["Công ty A", "0123456789", "a@example.test", "000001", "Cũ"]])
    store.replace_excel_customers(read_customers(first))
    less = excel(tmp_path, ["Tên công ty", "Mã số thuế", "Chi nhánh"], [["Công ty A", "0123456789", "Mới"]], "less.xlsx")
    store.replace_excel_customers(read_customers(less))
    customer = store.customers()[0]
    assert customer.email == "a@example.test"
    assert customer.extra_fields == {"Số CCCD": "000001", "Chi nhánh": "Mới"}


def test_reimport_name_only_person_keeps_extra_fields(store, tmp_path):
    store.replace_excel_customers(read_customers(excel(tmp_path, ["Tên khách hàng", "Số CCCD"], [["Nguyễn Văn A", "000001"]])))
    store.replace_excel_customers(read_customers(excel(tmp_path, ["Tên khách hàng"], [["Nguyễn Văn A"]], "less-person.xlsx")))
    assert store.customers()[0].extra_fields == {"Số CCCD": "000001"}


def test_manual_fields_survive_excel_refresh_and_new_columns_are_added(store):
    store.replace_customers([Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "000001"})])
    customer = store.customers()[0]
    edited = store.save_customer_edit(replace(customer, extra_fields=customer.extra_fields | {"Nơi cấp": "Nơi mô phỏng"}), customer.id)
    store.replace_excel_customers([replace(edited, extra_fields={"Email kế toán": "kt@example.test"})])
    assert len(store.customers()) == 1
    assert store.customers()[0].extra_fields == {"Email kế toán": "kt@example.test", "Số CCCD": "000001", "Nơi cấp": "Nơi mô phỏng"}


def test_old_database_rows_without_extra_fields_still_load_and_edit(store):
    old = store.customers()[0]
    raw = asdict(old)
    raw.pop("id")
    raw.pop("extra_fields")
    with store.connect() as conn:
        conn.execute("UPDATE customers SET data=? WHERE id=?", (json.dumps(raw), old.id))
    assert store.customers()[0].extra_fields == {}
    saved = store.save_customer_edit(replace(old, tax_code="", extra_fields={"Giấy phép": "GP-001"}), old.id)
    assert saved.company_name == old.company_name
    assert len(store.customers()) == 2


def test_contract_review_retains_and_merges_new_and_old_extra_fields(store, tmp_path, qt_app):
    original = Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "000001", "Nơi cấp": "Cũ"})
    saved = store.save_contract_customer(original, "fake-source", "fake")
    party = ContractParty(role="Bên B", company_name="Công ty A", tax_code="0123456789", extra_fields=[{"label": "Email kế toán", "value": "kt@example.test"}, {"label": "Nơi cấp", "value": ""}])
    source = tmp_path / "fake.docx"
    doc = Document()
    doc.add_paragraph("DỮ LIỆU GIẢ LẬP — Công ty A")
    doc.save(source)
    review = CustomerImportReview(store, ImportResult(ImportDocument(source, source.read_bytes()), ContractExtraction(parties=[party])))
    assert review.table.rowCount() > 12
    review.save_customer()
    assert review.saved_customer.id == saved.id
    assert review.saved_customer.extra_fields == {"Số CCCD": "000001", "Nơi cấp": "Cũ", "Email kế toán": "kt@example.test"}


def test_editor_adds_removes_fields_and_cancel_does_not_save(store, qt_app):
    customer = store.save_customer_edit(Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Cũ": "Không dùng"}))
    before = store.customers()
    cancelled = CustomerEditor(store, customer)
    cancelled.add_extra("Số CCCD", "000001")
    cancelled.reject()
    assert store.customers() == before
    editor = CustomerEditor(store, customer)
    editor.extras.selectRow(0)
    editor.remove_extra()
    editor.add_extra("Số CCCD", "000001")
    editor.add_extra("Nơi cấp", "Nơi mô phỏng")
    editor.save()
    assert editor.saved_customer.extra_fields == {"Số CCCD": "000001", "Nơi cấp": "Nơi mô phỏng"}


def test_custom_customer_fields_fill_word_and_missing_ones_are_requested(store, tmp_path):
    store.replace_customers([Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "000001", "Nơi cấp": ""})])
    template = custom_template(tmp_path)
    service = ContractService(store)
    intent = Intent(tax_code="0123456789", work_description="Thi công demo")
    pending = service.prepare(intent, "Tạo hợp đồng", template)
    assert service.missing(pending) == ["customer_noi_cap"]
    result = service.generate(pending, {"customer_noi_cap": "Nơi mô phỏng"})
    assert "Số CCCD: 000001" in document_text(result.path)
    assert "Nơi cấp: Nơi mô phỏng" in document_text(result.path)
    assert store.customers()[0].extra_fields["Nơi cấp"] == ""


def test_explicit_custom_field_lines_override_locally_and_conflicts_are_rejected(store, tmp_path):
    store.replace_customers([Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "Cũ", "Nơi cấp": "Nơi mô phỏng"})])
    service = ContractService(store)
    intent = Intent(tax_code="0123456789", work_description="Thi công demo")
    pending = service.prepare(intent, "Số CCCD: 000002", custom_template(tmp_path))
    assert service.context(pending)["customer_so_cccd"] == "000002"
    pending.prompt += "\nSố CCCD: 000003"
    with pytest.raises(UserError, match="hai giá trị"):
        service.generate(pending)


def test_main_table_and_missing_dialog_use_custom_labels(store, qt_app):
    store.replace_customers([Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "000001", "Nơi cấp": ""})])
    window = MainWindow(store)
    headers = [window.customer_table.horizontalHeaderItem(i).text() for i in range(window.customer_table.columnCount())]
    assert "Số CCCD" in headers and "Nơi cấp" in headers
    assert window.customer_table.item(0, headers.index("Số CCCD")).text() == "000001"
    dialog = MissingDialog(["customer_noi_cap"], window, store.customer_field_labels())
    assert dialog.inputs["customer_noi_cap"].accessibleName() == "Nơi cấp"
    dialog.reject()
    window.close()


@pytest.mark.parametrize("name", ["__class__", "customer___class__", "os.system"])
def test_custom_variable_namespace_cannot_be_used_for_arbitrary_expressions(tmp_path, name):
    path = tmp_path / "bad.docx"
    doc = Document()
    doc.add_paragraph("{{ company_name }} {{ work_description }} {{ " + name + " }}")
    doc.save(path)
    with pytest.raises(UserError):
        missing_fields(path, {"company_name": "A", "work_description": "B"})


def test_ai_template_custom_fields_are_safe_named_and_reviewable(store, tmp_path, qt_app):
    source = tmp_path / "blank-custom.docx"
    doc = Document()
    for text in ["BÊN B", "Tên công ty: ...", "Nội dung công việc: ...", "Số CCCD: ..."]:
        doc.add_paragraph(text)
    doc.save(source)
    slots = blank_slots_from_word(source.read_bytes())
    mappings = [Replacement(anchor=slot.anchor, slot_id=slot.id, field={1: "company_name", 2: "work_description", 3: "cccd"}[int(slot.anchor.rsplit(":", 1)[1])]) for slot in slots]
    plan = TemplatePlan(title="Mẫu trường mở", replacements=mappings, custom_fields=[{"key": "cccd", "label": "Số CCCD"}])
    class Client:
        models = None
        def __init__(self):
            self.models = self
        def generate_content(self, **kwargs):
            return SimpleNamespace(text=plan.model_dump_json())
    draft = GeminiTemplateBuilder("test-placeholder", client=Client()).prepare(source)
    review = TemplateReview(store, draft)
    review.save()
    assert review.saved_path is not None, review.error.text()
    assert "customer_so_cccd" in template_fields(review.saved_path)
    assert template_metadata(review.saved_path)["field_labels"]["customer_so_cccd"] == "Số CCCD"


def test_unicode_custom_labels_have_stable_noncolliding_flat_variables():
    assert customer_field_key("Số CCCD") == "customer_so_cccd"
    assert customer_field_key("  số cccd ") == "customer_so_cccd"
    assert customer_field_key("证件") != customer_field_key("身份")


def test_plus_adds_information_to_word_even_when_template_has_no_matching_slot(store, tmp_path, qt_app, monkeypatch):
    store.replace_customers([Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "000001", "Nơi cấp": "Nơi mô phỏng"})])
    window = MainWindow(store)
    dialog = MissingDialog(["duration"], window)
    dialog.inputs["duration"].setText("30 ngày")
    monkeypatch.setattr("contract_app.ui.QInputDialog.getItem", lambda *args: ("Địa điểm nghiệm thu", True))
    dialog.add_information()
    key = customer_field_key("Địa điểm nghiệm thu")
    dialog.inputs[key].setText("Khu mô phỏng A-01")
    values = dialog.values()
    pending = window.service.prepare(Intent(tax_code="0123456789", work_description="Thi công demo"), "Tạo hợp đồng", custom_template(tmp_path))
    result = window.service.generate(pending, values)
    text = document_text(result.path)
    assert "Thông tin bổ sung" in text
    assert "Địa điểm nghiệm thu: Khu mô phỏng A-01" in text
    assert key not in extra_context(store.customers()[0])
    dialog.reject()
    window.close()


def test_plus_field_already_in_template_fills_that_slot_without_duplicate_append(store, tmp_path, qt_app, monkeypatch):
    store.replace_customers([Customer(0, "A", "Công ty A", "0123456789", extra_fields={"Số CCCD": "000001"})])
    window = MainWindow(store)
    dialog = MissingDialog([], window, {"customer_noi_cap": "Nơi cấp"})
    monkeypatch.setattr("contract_app.ui.QInputDialog.getItem", lambda *args: ("Nơi cấp", True))
    dialog.add_information()
    dialog.inputs["customer_noi_cap"].setText("Nơi mô phỏng")
    pending = window.service.prepare(Intent(tax_code="0123456789", work_description="Thi công demo"), "Tạo hợp đồng", custom_template(tmp_path))
    text = document_text(window.service.generate(pending, dialog.values()).path)
    assert text.count("Nơi cấp: Nơi mô phỏng") == 1
    assert "Thông tin bổ sung" not in text
    dialog.reject()
    window.close()


def test_missing_form_stays_light_when_windows_palette_is_dark(store, qt_app):
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QWidget
    original = qt_app.palette()
    dark = QPalette(original)
    dark.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    dark.setColor(QPalette.ColorRole.Base, QColor("#202020"))
    dark.setColor(QPalette.ColorRole.WindowText, QColor("#eeeeee"))
    qt_app.setPalette(dark)
    window = dialog = None
    try:
        window = MainWindow(store)
        dialog = MissingDialog(["amount", "duration", "payment_terms"], window)
        dialog.show()
        qt_app.processEvents()
        content = dialog.findChild(QWidget, "FormContent")
        assert content.palette().color(QPalette.ColorRole.Window).lightness() > 200
        assert dialog.add_information_button.text().startswith("+")
    finally:
        if dialog:
            dialog.close()
        if window:
            window.close()
        qt_app.setPalette(original)
