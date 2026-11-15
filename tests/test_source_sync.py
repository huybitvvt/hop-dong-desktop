from pathlib import Path

from openpyxl import Workbook
import pytest

from contract_app.models import Intent, UserError
from contract_app.service import ContractService


def write_source(path, representative):
    book = Workbook()
    book.active.append(["Tên công ty", "Tên liên hệ", "Mã số thuế", "Người đại diện"])
    book.active.append(["Công ty X", "Thông", "SOURCE-X", representative])
    book.save(path)


def test_changed_source_is_reloaded_before_lookup(store, tmp_path):
    source = tmp_path / "customers.xlsx"
    write_source(source, "Người đại diện A")
    cfg = store.config()
    cfg.update(customer_source=str(source), demo_data=False)
    store.save_config(cfg)
    service = ContractService(store)
    service.synchronize_source()
    assert store.customers()[0].representative == "Người đại diện A"
    write_source(source, "Người đại diện đã được thay đổi")
    pending = service.prepare(Intent(company_name="Công ty X"), "sample", next(store.templates.glob("*.docx")))
    assert pending.customer.representative == "Người đại diện đã được thay đổi"


def test_missing_source_blocks_generation_instead_of_using_stale_data(store, tmp_path):
    cfg = store.config()
    cfg.update(customer_source=str(tmp_path / "missing.xlsx"), demo_data=False)
    store.save_config(cfg)
    with pytest.raises(UserError, match="Excel nguồn"):
        ContractService(store).prepare(Intent(company_name="Công ty X"), "sample", next(store.templates.glob("*.docx")))
    assert len(store.customers()) == 2
