from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class UserError(Exception):
    """An actionable message safe to show to the user."""


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_name: str | None = Field(default=None, max_length=160, description="Tên người liên hệ được nhắc trong câu lệnh; không tự đặt tên")
    company_name: str | None = Field(default=None, max_length=300, description="Tên hoặc bí danh công ty trong câu lệnh")
    tax_code: str | None = Field(default=None, max_length=30, description="Mã số thuế chỉ khi người dùng cung cấp")
    amount_text: str | None = Field(default=None, max_length=120, description="Chép NGUYÊN VĂN cụm tiền trong câu lệnh, ví dụ 1 tỷ, 1,2 tỷ, một tỷ đồng; không tính toán")
    work_description: str | None = Field(default=None, max_length=4000, description="Nội dung công việc người dùng yêu cầu; không thêm hạng mục hoặc điều khoản")
    contract_date: str | None = Field(default=None, max_length=10, description="Ngày ký ISO YYYY-MM-DD nếu được nêu rõ; nếu không có để null")
    contract_number: str | None = Field(default=None, max_length=120, description="Số hợp đồng khi người dùng chỉ định; nếu không để null")
    payment_terms: str | None = Field(default=None, max_length=2000, description="Điều kiện thanh toán chỉ khi được nêu rõ")
    duration: str | None = Field(default=None, max_length=1000, description="Thời hạn thực hiện chỉ khi được nêu rõ")
    currency: str | None = Field(default=None, max_length=20, description="VND nếu câu nói đồng hoặc tiền Việt; loại tiền khác chép đúng; không tự đổi tiền")


@dataclass(frozen=True)
class Customer:
    id: int
    contact_name: str
    company_name: str
    tax_code: str = ""
    address: str = ""
    representative: str = ""
    position: str = ""
    phone: str = ""
    email: str = ""
    bank_account: str = ""
    bank_name: str = ""
    aliases: str = ""
    extra_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    customer: Customer
    score: float
    exact: bool


@dataclass
class PendingContract:
    intent: Intent
    prompt: str
    template: Path
    candidates: list[Candidate]
    customer: Customer | None = None
    demo: bool = False


@dataclass(frozen=True)
class ContractResult:
    path: Path
    customer: Customer
    amount: int
    work: str
    template_name: str
    demo: bool = False


FIELD_LABELS = {
    "company_name": "Tên công ty đối tác", "contact_name": "Người liên hệ", "tax_code": "Mã số thuế đối tác",
    "address": "Địa chỉ đối tác", "representative": "Người đại diện ký", "position": "Chức vụ người đại diện",
    "phone": "Điện thoại", "email": "Email", "bank_account": "Tài khoản ngân hàng", "bank_name": "Ngân hàng",
    "work_description": "Nội dung công việc", "amount": "Giá trị hợp đồng (VND)", "amount_words": "Số tiền bằng chữ",
    "contract_date": "Ngày ký (YYYY-MM-DD)", "contract_number": "Số hợp đồng", "payment_terms": "Điều kiện thanh toán",
    "duration": "Thời hạn thực hiện", "seller_company": "Tên công ty của bạn", "seller_tax_code": "Mã số thuế công ty của bạn",
    "seller_address": "Địa chỉ công ty của bạn", "seller_representative": "Người đại diện công ty của bạn",
    "seller_position": "Chức vụ đại diện công ty của bạn", "project_name": "Tên dự án", "project_address": "Địa điểm công trình",
    "seller_contact_name": "Người liên hệ công ty của bạn", "seller_phone": "Điện thoại công ty của bạn",
    "seller_email": "Email công ty của bạn", "seller_bank_account": "Tài khoản công ty của bạn", "seller_bank_name": "Ngân hàng công ty của bạn",
}
