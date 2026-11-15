from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .models import UserError


def normalize(value: str) -> str:
    value = value.lower().replace("đ", "d")
    return " ".join("".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn").split())


DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
WORD_DIGITS = {normalize(word): i for i, word in enumerate(DIGITS)} | {"tu": 4, "lam": 5, "mot": 1}


def small_words(text: str) -> int:
    tokens = text.split()
    if not tokens:
        return 0
    value = 0
    if len(tokens) >= 2 and tokens[0] in WORD_DIGITS and tokens[1] == "tram":
        value = WORD_DIGITS[tokens[0]] * 100
        tokens = tokens[2:]
        if not tokens:
            return value
        if tokens[0] in ("linh", "le"):
            if len(tokens) == 2 and tokens[1] in WORD_DIGITS:
                return value + WORD_DIGITS[tokens[1]]
            tokens = []
    if len(tokens) == 1 and tokens[0] in WORD_DIGITS:
        return value + WORD_DIGITS[tokens[0]]
    if tokens and tokens[0] == "muoi" and len(tokens) <= 2:
        if len(tokens) == 1 or tokens[1] in WORD_DIGITS:
            return value + 10 + (WORD_DIGITS[tokens[1]] if len(tokens) == 2 else 0)
    if len(tokens) in (2, 3) and tokens[0] in WORD_DIGITS and WORD_DIGITS[tokens[0]] >= 2 and tokens[1] == "muoi":
        if len(tokens) == 2 or tokens[2] in WORD_DIGITS:
            return value + WORD_DIGITS[tokens[0]] * 10 + (WORD_DIGITS[tokens[2]] if len(tokens) == 3 else 0)
    raise UserError("Chưa đọc được số tiền. Hãy nhập dạng 1 tỷ, 1,2 tỷ hoặc 1.000.000.000 đồng.")


def numeric(text: str, scaled: bool) -> Decimal:
    text = text.replace(" ", "").replace("_", "")
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", text):
        raise UserError("Số tiền không hợp lệ.")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    elif scaled and len(re.findall(r"[.,]", text)) == 1:
        text = text.replace(",", ".")
    elif re.search(r"[.,]", text):
        raise UserError("Số tiền chưa rõ cách phân tách. Dùng 1,2 tỷ hoặc 1.200.000.000 đồng.")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise UserError("Số tiền không hợp lệ.") from exc


def parse_money(raw: str) -> int:
    text = normalize(raw)
    text = re.sub(r"\b(vnd|dong|vnđ)\b", "", text).strip()
    if not text or re.search(r"[-+/%]|\b(den|khoang|hon|duoi|usd|eur|ty\s+ruoi)\b", text):
        raise UserError("Cần một giá trị tiền VND cụ thể, ví dụ 1 tỷ hoặc 1,2 tỷ.")
    scales = {"ty": 1_000_000_000, "trieu": 1_000_000, "nghin": 1000, "ngan": 1000}
    matches = list(re.finditer(r"\b(ty|trieu|nghin|ngan)\b", text))
    total, cursor, last_scale = Decimal(0), 0, float("inf")
    for match in matches:
        scale = scales[match.group()]
        if scale >= last_scale:
            raise UserError("Đơn vị tiền bị lặp hoặc sai thứ tự. Hãy nhập lại số tiền.")
        segment = text[cursor:match.start()].strip()
        if not segment:
            raise UserError("Thiếu số trước đơn vị tiền.")
        quantity = numeric(segment, True) if re.search(r"\d", segment) else Decimal(small_words(segment))
        total += quantity * scale
        cursor, last_scale = match.end(), scale
    tail = text[cursor:].strip()
    if matches and tail:
        raise UserError("Số tiền còn phần chưa rõ đơn vị. Ví dụ hãy viết 1 tỷ 200 triệu.")
    if not matches:
        total = numeric(text, False) if re.search(r"\d", text) else Decimal(small_words(text))
    if total != total.to_integral_value() or not 0 < total <= 1_000_000_000_000_000:
        raise UserError("Giá trị hợp đồng phải là số nguyên VND dương, tối đa 1 triệu tỷ đồng.")
    return int(total)


def read_group(n: int, full: bool = False) -> str:
    hundreds, rest = divmod(n, 100)
    tens, units = divmod(rest, 10)
    out = []
    if hundreds or full:
        out += [DIGITS[hundreds], "trăm"]
    if tens >= 2:
        out += [DIGITS[tens], "mươi"]
    elif tens == 1:
        out += ["mười"]
    elif units and (hundreds or full):
        out += ["lẻ"]
    if units:
        out += ["mốt" if units == 1 and tens >= 2 else "lăm" if units == 5 and tens else DIGITS[units]]
    return " ".join(out)


def money_words(amount: int) -> str:
    if not 0 <= amount <= 1_000_000_000_000_000:
        raise UserError("Số tiền ngoài phạm vi hỗ trợ.")
    if amount == 0:
        return "Không đồng"
    groups = []
    while amount:
        amount, part = divmod(amount, 1000)
        groups.append(part)
    labels = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]
    parts = []
    for i in reversed(range(len(groups))):
        if groups[i]:
            parts.append((read_group(groups[i], bool(parts) and groups[i] < 100) + " " + labels[i]).strip())
    text = " ".join(parts) + " đồng"
    return text[0].upper() + text[1:]


def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", ".")
