import pytest

from contract_app.models import UserError
from contract_app.money import money_words, parse_money


@pytest.mark.parametrize("text,expected", [
    ("1 tỷ", 1_000_000_000), ("1,2 tỷ", 1_200_000_000), ("1.2 tỷ", 1_200_000_000),
    ("1 tỷ 200 triệu", 1_200_000_000), ("một tỷ hai trăm triệu đồng", 1_200_000_000),
    ("1.000.000.000 VND", 1_000_000_000), ("1,000,000,000", 1_000_000_000),
    ("500 triệu", 500_000_000), ("mười lăm triệu", 15_000_000),
    ("hai mươi mốt nghìn", 21_000), ("1 000 000", 1_000_000),
    ("một trăm lẻ năm nghìn", 105_000), ("1 đồng", 1), ("0,5 tỷ", 500_000_000),
])
def test_money_normalizes_vietnamese_amounts(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", ["", "0", "-100", "1-2 tỷ", "khoảng 1 tỷ", "1 tỷ 2", "1 tỷ rưỡi", "1.2", "USD 100", "1 tỷ 2 tỷ", "một hai triệu", "1 triệu 2 tỷ", "0,0000000001 tỷ", "1e9", "NaN", "1%", "1000000000000001"])
def test_unclear_or_invalid_money_is_rejected(text):
    with pytest.raises(UserError):
        parse_money(text)


@pytest.mark.parametrize("amount,expected", [
    (0, "Không đồng"), (15, "Mười lăm đồng"), (21, "Hai mươi mốt đồng"),
    (105, "Một trăm lẻ năm đồng"), (1001, "Một nghìn không trăm lẻ một đồng"),
    (1_000_000_000, "Một tỷ đồng"), (1_200_000_000, "Một tỷ hai trăm triệu đồng"),
])
def test_amount_in_words(amount, expected):
    assert money_words(amount) == expected
