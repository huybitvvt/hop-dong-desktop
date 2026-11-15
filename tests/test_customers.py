from pathlib import Path

from openpyxl import Workbook
import pytest

from contract_app.customers import match_customers, read_customers
from contract_app.models import Customer, Intent, UserError


def test_company_and_person_resolve_correct_record(store):
    candidates = match_customers(Intent(contact_name="Thong", company_name="Công ty X"), store.customers())
    exact = [c for c in candidates if c.exact]
    assert len(exact) == 1
    assert exact[0].customer.tax_code == "DEMO-X"
    assert "Bình" in exact[0].customer.representative
    assert "Thông" in exact[0].customer.contact_name


def test_duplicate_first_names_remain_ambiguous(store):
    candidates = match_customers(Intent(contact_name="Thông"), store.customers())
    assert len([c for c in candidates if c.exact]) == 2


def test_fuzzy_company_match_never_marked_exact():
    customer = Customer(1, "Thông", "Công ty TNHH Xây dựng X")
    candidates = match_customers(Intent(company_name="Xây dựng X"), [customer])
    assert candidates and not candidates[0].exact


def test_tax_code_is_a_hard_filter(store):
    assert not match_customers(Intent(contact_name="Thông", tax_code="9999999999"), store.customers())


def test_excel_preserves_leading_zeroes(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["Tên công ty", "Tên liên hệ", "Mã số thuế"])
    sheet.append(["Công ty A", "Thông", 123456789])
    sheet["C2"].number_format = "0000000000"
    source = tmp_path / "customers.xlsx"
    book.save(source)
    assert read_customers(source)[0].tax_code == "0123456789"


def test_failed_import_does_not_erase_existing_customers(store, tmp_path):
    book = Workbook()
    book.active.append(["Tên công ty", "Tên liên hệ", "Mã số thuế"])
    book.active.append(["Công ty A", "Thông", '=SUM(1,2)'])
    path = tmp_path / "bad.xlsx"
    book.save(path)
    with pytest.raises(UserError, match="công thức"):
        store.replace_customers(read_customers(path))
    assert len(store.customers()) == 2


def test_tracking_sheet_is_not_silently_imported_as_legal_database(tmp_path):
    book = Workbook()
    book.active.append(["Hợp đồng số", "Đối tác", "Nội dung thi công"])
    book.active.append(["001/HD", "X", "Cầu Y"])
    source = tmp_path / "tracking.xlsx"
    book.save(source)
    with pytest.raises(UserError, match="danh bạ pháp nhân"):
        read_customers(source)
