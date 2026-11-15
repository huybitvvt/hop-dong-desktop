from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re

from openpyxl import load_workbook
from rapidfuzz.fuzz import ratio, token_set_ratio

from .models import Candidate, Customer, Intent, UserError
from .money import normalize
from .customer_fields import clean_extra_fields, customer_field_key


HEADERS = {
    "contact_name": ["ten khach hang", "ten lien he", "nguoi lien he", "ho ten", "contact name", "contact_name"],
    "company_name": ["ten cong ty", "cong ty", "ten doanh nghiep", "company name", "company_name", "ten phap nhan"],
    "tax_code": ["ma so thue", "mst", "tax code", "tax_code"],
    "address": ["dia chi", "dia chi tru so", "address"],
    "representative": ["nguoi dai dien", "dai dien", "dai dien phap luat", "representative"],
    "position": ["chuc vu", "position"], "phone": ["dien thoai", "sdt", "so dien thoai", "phone"],
    "email": ["email"], "bank_account": ["tai khoan", "so tai khoan", "stk", "bank_account"],
    "bank_name": ["ngan hang", "bank_name"], "aliases": ["bi danh", "ten viet tat", "aliases"],
}
HEADER_LOOKUP = {normalize(alias): key for key, aliases in HEADERS.items() for alias in aliases}


def cell_value(cell) -> str:
    if cell.data_type == "f":
        raise UserError(f"Ô {cell.coordinate} chứa công thức. Hãy lưu bản sao chỉ có giá trị trước khi nhập khách hàng.")
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not value.is_integer():
            return str(value)
        number = str(int(value))
        if re.fullmatch(r"0+", cell.number_format):
            return number.zfill(len(cell.number_format))
        return number
    return str(value).strip()


def read_customers(path: Path) -> list[Customer]:
    if path.suffix.lower() != ".xlsx":
        raise UserError("Chọn file khách hàng .xlsx. File .xls cũ cần lưu lại thành .xlsx.")
    if path.stat().st_size > 20_000_000:
        raise UserError("File Excel vượt 20 MB. Hãy tạo bản chỉ chứa danh sách khách hàng.")
    try:
        workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise UserError("Không đọc được Excel. Hãy đóng file, kiểm tra định dạng .xlsx và thử lại.") from exc
    result = []
    try:
        for sheet in workbook:
            mapping = None
            for row_number, row in enumerate(sheet.iter_rows(), start=1):
                if mapping is None:
                    if row_number > 30:
                        break
                    candidates = {i: HEADER_LOOKUP[normalize(str(c.value))] for i, c in enumerate(row) if c.value is not None and normalize(str(c.value)) in HEADER_LOOKUP}
                    if {"company_name", "contact_name", "tax_code"} & set(candidates.values()):
                        if len(set(candidates.values())) != len(candidates):
                            raise UserError(f"Sheet {sheet.title}: có các cột trùng ý nghĩa; hãy dùng file mẫu danh sách khách hàng.")
                        mapping = candidates
                        extra_columns = {}
                        extra_keys = set()
                        for i, cell in enumerate(row):
                            if i in mapping or cell.value is None or not str(cell.value).strip():
                                continue
                            name = cell_value(cell)
                            key = customer_field_key(name)
                            if key in extra_keys:
                                raise UserError(f"Sheet {sheet.title}: trùng cột bổ sung {name}.")
                            extra_columns[i] = name
                            extra_keys.add(key)
                        if len(extra_columns) > 100:
                            raise UserError("Excel có hơn 100 cột bổ sung. Hãy chia nhỏ thông tin khách hàng.")
                    continue
                values = {key: cell_value(row[i]) for i, key in mapping.items()}
                extras = clean_extra_fields({name: cell_value(row[i]) for i, name in extra_columns.items()})
                if not any(values.values()) and not any(extras.values()):
                    continue
                if not any(values.get(name) for name in ("company_name", "contact_name", "tax_code")):
                    raise UserError(f"Sheet {sheet.title}, dòng {row_number}: cần tên công ty, tên khách hàng hoặc mã số thuế để nhận diện. Chưa thay dữ liệu hiện có.")
                result.append(Customer(id=len(result) + 1, contact_name=values.pop("contact_name", ""), company_name=values.pop("company_name", ""), extra_fields=extras, **values))
                if len(result) > 50_000:
                    raise UserError("Danh sách vượt 50.000 khách hàng; hãy chia nhỏ trước khi nhập.")
    finally:
        workbook.close()
    if not result:
        raise UserError("Không tìm được bảng khách hàng. Cần cột Tên công ty, Tên liên hệ/Tên khách hàng hoặc Mã số thuế để nhận diện. Các cột khác có thể thêm tùy ý. Bảng theo dõi hợp đồng không phải danh bạ pháp nhân.")
    return result


def person_score(query: str, name: str) -> tuple[float, bool]:
    query, name = normalize(query), normalize(name)
    query = re.sub(r"^(anh|chi|ong|ba|mr|ms)\s+", "", query)
    exact = query == name or bool(query and name.endswith(" " + query))
    return (100.0 if exact else ratio(query, name)), exact


def company_score(query: str, customer: Customer) -> tuple[float, bool]:
    query = normalize(query)
    aliases = [normalize(customer.company_name)] + [normalize(x) for x in customer.aliases.split(";") if x.strip()]
    exact = query in aliases
    def distinctive(name):
        name = re.sub(r"\b(cong ty|co phan|cty|tnhh|mtv|cp)\b", " ", name)
        return " ".join(name.split())
    short_query = distinctive(query)
    score = max((token_set_ratio(short_query, distinctive(name)) for name in aliases), default=0) if short_query else 0
    # Substring matches are useful suggestions, but must never choose a legal entity automatically.
    return (100.0 if exact else min(score, 94.0)), exact


def match_customers(intent: Intent, customers: list[Customer]) -> list[Candidate]:
    if not any((intent.contact_name, intent.company_name, intent.tax_code)):
        raise UserError("Câu lệnh chưa có khách hàng. Hãy nêu tên người liên hệ, công ty hoặc mã số thuế.")
    matches = []
    for customer in customers:
        scores, exacts = [], []
        if intent.tax_code:
            if re.sub(r"\D", "", intent.tax_code) != re.sub(r"\D", "", customer.tax_code):
                continue
            scores.append(100.0)
            exacts.append(True)
        if intent.contact_name:
            score, exact = person_score(intent.contact_name, customer.contact_name)
            if score < 55:
                continue
            scores.append(score)
            exacts.append(exact)
        if intent.company_name:
            score, exact = company_score(intent.company_name, customer)
            if score < 55:
                continue
            scores.append(score)
            exacts.append(exact)
        matches.append(Candidate(customer, sum(scores) / len(scores), all(exacts)))
    return sorted(matches, key=lambda c: (-c.score, c.customer.company_name))[:10]
