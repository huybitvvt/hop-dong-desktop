from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from .customers import match_customers, read_customers
from .documents import missing_fields, render_contract, template_fields, template_is_draft
from .models import ContractResult, Customer, Intent, PendingContract, UserError
from .money import format_money, money_words, parse_money
from .storage import Store, desktop_directory
from .customer_fields import customer_field_key, extra_context, explicit_customer_values, is_customer_field
from .models import FIELD_LABELS


class ContractService:
    def __init__(self, store: Store):
        self.store = store

    def prepare(self, intent: Intent, prompt: str, template: Path, demo=False) -> PendingContract:
        uses_amount = bool(template_fields(template) & {"amount", "amount_words", "amount_number"})
        if intent.amount_text and not uses_amount:
            raise UserError("Mẫu đang chọn không có tổng tiền cố định. Câu lệnh có số tiền nên chưa xuất file để tránh bỏ sót giá trị. Hãy chọn mẫu có biến amount hoặc dùng yêu cầu phù hợp với mẫu nguyên tắc theo đơn hàng.")
        source_error = None
        try:
            self.synchronize_source()
            customers = self.store.customers()
        except UserError as exc:
            customers = self.store.contract_customers()
            if not customers:
                raise
            source_error = exc
        if not customers:
            raise UserError("Chưa có khách hàng. Mở Danh sách khách hàng để nhập Excel.")
        matches = match_customers(intent, customers)
        if not matches:
            if source_error:
                raise source_error
            raise UserError("Không tìm thấy khách hàng phù hợp. Kiểm tra tên/công ty hoặc nhập danh sách Excel mới.")
        exacts = [candidate for candidate in matches if candidate.exact]
        customer = exacts[0].customer if len(exacts) == 1 else None
        return PendingContract(intent, prompt, template, matches, customer, demo)

    def synchronize_source(self):
        config = self.store.config()
        if config.get("demo_data") or not config.get("customer_source"):
            return
        source = Path(config["customer_source"])
        if not source.is_file():
            raise UserError("Không tìm thấy Excel nguồn. Mở Khách hàng và nhập lại file; chưa dùng dữ liệu cũ để tạo hợp đồng.")
        stat = source.stat()
        signature = [stat.st_size, stat.st_mtime_ns]
        if signature != config.get("source_signature"):
            customers = read_customers(source)
            current = source.stat()
            if [current.st_size, current.st_mtime_ns] != signature:
                raise UserError("Excel đang được thay đổi. Lưu và đóng file rồi thử lại.")
            self.store.replace_excel_customers(customers, str(source))
            config["source_signature"] = signature
            self.store.save_config(config)

    def context(self, pending: PendingContract, extra: dict | None = None) -> dict:
        if pending.customer is None:
            raise UserError("Cần chọn đúng khách hàng trước khi tạo hợp đồng.")
        intent = pending.intent
        cfg = self.store.config()
        # Data source marked as demo is always marked in the output, even with a real API call.
        demo = pending.demo or cfg.get("demo_data", False) or pending.template.name == "Mau-thi-cong-minh-hoa.docx" or template_is_draft(pending.template)
        data = asdict(pending.customer)
        data.pop("id")
        data.pop("extra_fields", None)
        data.update(extra_context(pending.customer))
        data.update(cfg.get("seller", {}))
        data.update({"work_description": intent.work_description or "", "payment_terms": intent.payment_terms or "", "duration": intent.duration or "", "is_demo": demo, "currency": "VND", "contract_date": intent.contract_date or date.today().isoformat(), "contract_number": intent.contract_number or f"{datetime.now():%Y%m%d-%H%M%S}/HD"})
        from .template_builder import template_metadata
        labels = {customer_field_key(label): label for label in pending.customer.extra_fields} | template_metadata(pending.template).get("field_labels", {})
        data.update(explicit_customer_values(pending.prompt, labels))
        if extra:
            data.update({key: str(value).strip() for key, value in extra.items() if key != "__additional_fields__"})
        additional = (extra or {}).get("__additional_fields__", {})
        if not isinstance(additional, dict) or len(additional) > 100:
            raise UserError("Thông tin bổ sung chưa hợp lệ. Hãy kiểm tra các mục đã thêm.")
        names = template_fields(pending.template)
        data["additional_information"] = []
        for key, label in additional.items():
            if key not in FIELD_LABELS and not is_customer_field(key):
                raise UserError("Trường bổ sung chưa hợp lệ.")
            if key not in names and data.get(key):
                data["additional_information"].append((str(label)[:100], str(data[key])))
        raw_amount = str((extra or {}).get("amount", intent.amount_text or ""))
        if raw_amount:
            amount = parse_money(raw_amount)
            data.update(amount=format_money(amount), amount_number=amount, amount_words=money_words(amount))
        else:
            data.update(amount="", amount_number=0, amount_words="")
        try:
            signed = date.fromisoformat(data["contract_date"])
        except ValueError as exc:
            raise UserError("Ngày ký không hợp lệ. Dùng dạng YYYY-MM-DD.") from exc
        data.update(day=f"{signed.day:02d}", month=f"{signed.month:02d}", year=str(signed.year))
        return data

    def missing(self, pending: PendingContract, extra: dict | None = None) -> list[str]:
        context = self.context(pending, extra)
        required = missing_fields(pending.template, context)
        expected = ["work_description"]
        if template_fields(pending.template) & {"amount", "amount_words", "amount_number"}:
            expected.append("amount")
        for key in expected:
            if not context.get(key) and key not in required:
                required.append(key)
        return required

    def generate(self, pending: PendingContract, extra: dict | None = None) -> ContractResult:
        context = self.context(pending, extra)
        missing = self.missing(pending, extra)
        if missing:
            raise UserError("Cần bổ sung thông tin bắt buộc trước khi xuất Word.")
        cfg = self.store.config()
        output = Path(cfg["output_directory"]).expanduser() if cfg.get("output_directory") else desktop_directory()
        target = render_contract(pending.template, context, output, pending.customer.company_name)
        result = ContractResult(target, pending.customer, context["amount_number"], context["work_description"], pending.template.name, context["is_demo"])
        self.store.add_history(result)
        return result
