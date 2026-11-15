"""Locate bounded blank form targets without rewriting labels or document XML."""
from dataclasses import asdict, dataclass
import re

from .documents import NAMESPACE
from .money import normalize

W = "{" + NAMESPACE["w"] + "}"
DOTS = re.compile(r"(?:[._＿·](?:[ \u00a0]*[._＿·]){2,}|…+)")
LABEL_FIELDS = [
    (r"(?:bang chu|so tien bang chu)", "amount_words"),
    (r"(?:ma so thue|mst|tax(?: code| id)?)", "tax_code"),
    (r"(?:nguoi lien he|ten lien he|contact(?: name)?)", "contact_name"),
    (r"(?:nguoi dai dien|dai dien|representative)", "representative"),
    (r"(?:chuc vu|position|title)", "position"),
    (r"(?:so dien thoai|dien thoai|sdt|phone|tel)", "phone"),
    (r"(?:dia chi email|e-?mail)", "email"),
    (r"(?:so tai khoan|tai khoan|stk|bank account)", "bank_account"),
    (r"(?:ten ngan hang|ngan hang|bank)", "bank_name"),
    (r"(?:dia chi du an|dia diem cong trinh|project address)", "project_address"),
    (r"(?:ten du an|project name)", "project_name"),
    (r"(?:dia chi|address)", "address"),
    (r"(?:noi dung(?: cong viec| hang hoa)?|cong viec|hang hoa|doi tuong hop dong|work description)", "work_description"),
    (r"(?:tong gia tri(?: hop dong)?|gia tri hop dong|tong tien|so tien|tri gia|gia tri|amount)", "amount"),
    (r"(?:dieu kien thanh toan|phuong thuc thanh toan|thanh toan|payment terms)", "payment_terms"),
    (r"(?:thoi han thuc hien|thoi gian thuc hien|thoi han|thoi gian|duration)", "duration"),
    (r"(?:ngay ky(?: hop dong)?|ngay hop dong|contract date)", "contract_date"),
    (r"(?:so hop dong|so hd|contract number|so)", "contract_number"),
    (r"(?:ten cong ty|ten doanh nghiep|ten phap nhan|ten don vi|cong ty|doanh nghiep|company(?: name)?)", "company_name"),
    (r"ngay", "day"), (r"thang", "month"), (r"nam", "year"),
]
PARTY_FIELDS = {"company_name", "tax_code", "address", "representative", "position", "contact_name", "phone", "email", "bank_account", "bank_name"}


def field_hint(label):
    text = normalize(label).strip(" :\t\n-–()")
    text = re.sub(r"^(?:dieu\s+[\divx]+|\d+)[.):\s-]+", "", text)
    for pattern, field in LABEL_FIELDS:
        if re.fullmatch(pattern, text):
            return field
    return None


def role_of(text):
    normalized = normalize(text).strip()
    if not re.match(r"^ben\b", normalized) or len(normalized) > 250:
        return ""
    matches = re.findall(r"\bben\s+([ab])\b", normalized)
    return "Bên " + matches[0].upper() if len(set(matches)) == 1 else ""


@dataclass(frozen=True)
class BlankSlot:
    id: str
    anchor: str
    start: int
    end: int
    kind: str
    context: str = ""
    hint: str | None = None
    role: str = ""
    automatic: bool = True

    def target_hint(self, customer_role):
        if self.hint in PARTY_FIELDS and self.role and self.role != customer_role:
            return {"company_name": "seller_company", **{key: "seller_" + key for key in PARTY_FIELDS - {"company_name"}}}[self.hint]
        return self.hint

    def model_value(self, customer_role):
        return asdict(self) | {"suggested_field": self.target_hint(customer_role)}


def _ancestor(node, tag):
    return next((parent for parent in node.iterancestors() if parent.tag == W + tag), None)


def _cell_text(cell, text_of):
    return " ".join(text_of(p).strip() for p in cell.findall(".//w:p", NAMESPACE) if text_of(p).strip())


def _column_role(cell, text_of):
    row = cell.getparent()
    column = 0
    for sibling in row.findall("w:tc", NAMESPACE):
        if sibling is cell:
            break
        span = sibling.find("w:tcPr/w:gridSpan", NAMESPACE)
        column += int(span.get(W + "val", "1")) if span is not None else 1
    for prior in row.itersiblings(preceding=True):
        if prior.tag != W + "tr":
            continue
        col = 0
        header_role = ""
        for candidate in prior.findall("w:tc", NAMESPACE):
            span = candidate.find("w:tcPr/w:gridSpan", NAMESPACE)
            width = int(span.get(W + "val", "1")) if span is not None else 1
            candidate_text = _cell_text(candidate, text_of)
            role = role_of(candidate_text)
            if role:
                header_role = role
            if col <= column < col + width and (role or not candidate_text.strip()) and header_role:
                return header_role
            col += width
    return ""


def analyze_parts(parts, text_of):
    """Return paragraph metadata and immutable blank ranges, including empty cells."""
    paragraphs, slots = [], []
    for name, root in parts:
        nodes = root.findall(".//w:p", NAMESPACE)
        section_role, section_text = "", ""
        for index, paragraph in enumerate(nodes):
            if paragraph.findall(".//w:p", NAMESPACE):
                continue
            text = text_of(paragraph)
            identity = f"{name}:{index}"
            current_role = role_of(text)
            if current_role:
                section_role, section_text = current_role, text.strip()[:200]
            prior = paragraph.getprevious()
            previous = text_of(prior).strip() if prior is not None and prior.tag == W + "p" else ""
            context = section_text
            cell = _ancestor(paragraph, "tc")
            hint = None
            empty_target = False
            role = section_role
            if cell is not None:
                row = cell.getparent()
                cells = row.findall("w:tc", NAMESPACE)
                column = cells.index(cell)
                texts = [_cell_text(item, text_of) for item in cells]
                role = _column_role(cell, text_of) or role
                left = texts[column - 1] if column else ""
                hint = field_hint(left)
                context = f"{role or section_text} | Dòng bảng: " + " | ".join(value or "[ô trống]" for value in texts)[:600] + f" | Ô {column + 1}"
                first = next(iter(cell.findall("w:p", NAMESPACE)), None)
                # The model may recognize labels beyond our small local vocabulary.
                empty_target = paragraph is first and not texts[column].strip() and bool(left.strip())
            if not text.strip() and previous and (field_hint(previous.rstrip(":：")) or previous.endswith((":", "："))):
                hint = field_hint(previous.rstrip(":："))
                context = f"{role or section_text} | Sau nhãn: {previous}"
                empty_target = True
            paragraphs.append((identity, text, context))
            regions = []
            for match in DOTS.finditer(text):
                before = text[:match.start()].rstrip()
                nearest = re.split(r"[:：\n]", before)
                label = nearest[-2] if before.endswith((":", "：")) and len(nearest) > 1 else nearest[-1]
                label = re.split(r"[;\t]", label)[-1].strip()
                date = re.search(r"\b(ngay|thang|nam)\s*$", normalize(before))
                local_hint = {"ngay": "day", "thang": "month", "nam": "year"}[date.group(1)] if date else field_hint(label)
                start = match.start()
                # A printed '20...' is one year fill area. The year value already
                # includes its century; leaving '20' outside produces '202026'.
                normalized_before = normalize(before)
                year_prefix = re.search(r"\bnam\s*(?:19|20|21)\d?\s*$", normalized_before)
                if year_prefix and (year_prefix.start() == 0 or re.search(r"\b(?:ngay|thang)\b", normalized_before[:year_prefix.start()])):
                    prefix = re.search(r"\d{2,3}\s*$", text[:start])
                    if prefix:
                        start, local_hint = prefix.start(), "year"
                regions.append((start, match.end(), "dotted", local_hint or hint, True))
            if not text.strip():
                regions.append((0, len(text), "empty_cell" if cell is not None else "empty_paragraph", hint, empty_target))
            else:
                # A colon is itself a useful label; place data after it, retaining it.
                label = text.rstrip().rstrip(":：").strip()
                append_hint = field_hint(label)
                next_node = paragraph.getnext()
                has_empty_next = next_node is not None and next_node.tag == W + "p" and not text_of(next_node).strip()
                right_empty = False
                if cell is not None:
                    right_empty = column + 1 < len(cells) and not texts[column + 1].strip()
                if append_hint and text.rstrip().endswith((":", "：")) and not right_empty and not has_empty_next:
                    regions.append((len(text.rstrip()), len(text), "after_label", append_hint, True))
                # Inline gaps: 'Ngày    tháng    năm    ' or 'Tên:    MST:'.
                for match in re.finditer(r"(?:[ \u00a0]{2,}|[ \t\u00a0]*\t[ \t\u00a0]*)", text):
                    if any(match.start() < end and match.end() > start for start, end, *_ in regions):
                        continue
                    before, after = text[:match.start()].rstrip(), text[match.end():]
                    preceding = re.split(r"(?:[._…]{2,}|[;\t\n:：])", before)
                    preceding = next((part.strip() for part in reversed(preceding) if part.strip()), "")
                    inline_hint = field_hint(preceding)
                    date = re.search(r"\b(ngay|thang|nam)\s*$", normalize(before))
                    if date:
                        inline_hint = {"ngay": "day", "thang": "month", "nam": "year"}[date.group(1)]
                    following_label = re.match(r"(?:tháng|năm|MST|Địa chỉ|Chức vụ|Điện thoại)\b", after, re.I)
                    if inline_hint and (not after.strip() or following_label):
                        regions.append((match.start(), match.end(), "gap", inline_hint, True))
            for number, (start, end, kind, suggested, automatic) in enumerate(sorted(regions), 1):
                slots.append(BlankSlot(f"{identity}#blank{number}", identity, start, end, kind, context[:800], suggested, role, automatic))
    return paragraphs, slots
