import json
from types import SimpleNamespace

from google.genai.errors import ClientError
import pytest

from contract_app.gemini import GeminiExtractor
from contract_app.models import Intent, UserError


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.models = self
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def test_only_user_prompt_and_schema_sent_no_local_database():
    prompt = "Tạo hợp đồng công ty X, 1 tỷ, thi công Y"
    client = FakeClient(Intent(company_name="X", amount_text="1 tỷ", work_description="Thi công Y").model_dump_json())
    result = GeminiExtractor("test-placeholder", client=client).extract(prompt)
    assert result.amount_text == "1 tỷ"
    call = client.calls[0]
    assert call["model"] == "gemini-3.5-flash-lite"
    assert call["contents"] == prompt
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema["additionalProperties"] is False
    assert "DEMO-X" not in json.dumps(call["config"].model_dump(), default=str)


@pytest.mark.parametrize("raw_amount,prompt", [("2 tỷ", "Tạo hợp đồng 1 tỷ"), ("1 tỷ", "Tạo hợp đồng 11 tỷ")])
def test_model_cannot_replace_amount_with_an_unquoted_substring(raw_amount, prompt):
    client = FakeClient(Intent(amount_text=raw_amount).model_dump_json())
    with pytest.raises(UserError, match="nguyên văn"):
        GeminiExtractor("test-placeholder", client=client).extract(prompt)


@pytest.mark.parametrize("code,phrase", [(400, "không chấp nhận"), (401, "không hợp lệ"), (403, "chưa có quyền"), (404, "Không tìm thấy model"), (429, "hạn mức")])
def test_api_errors_are_actionable_and_never_echo_key(code, phrase):
    error = ClientError(code, {"error": {"message": "secret-api-key-in-request", "status": "DENIED"}})
    client = FakeClient(error=error)
    with pytest.raises(UserError, match=phrase) as caught:
        GeminiExtractor("test-placeholder", client=client).extract("Tạo hợp đồng công ty X")
    assert "secret-api-key" not in str(caught.value)
    assert client.calls[0]["model"] == "gemini-3.5-flash-lite"


@pytest.mark.parametrize("response", [None, "not-json", '{"unknown":"value"}', '{"contact_name": 99}'])
def test_bad_response_does_not_become_a_contract(response):
    with pytest.raises(UserError):
        GeminiExtractor("test-placeholder", client=FakeClient(response)).extract("Tạo hợp đồng công ty X")


def test_non_vnd_currency_requires_clarification():
    client = FakeClient(Intent(amount_text="100", currency="USD").model_dump_json())
    with pytest.raises(UserError, match="VND"):
        GeminiExtractor("test-placeholder", client=client).extract("Tạo hợp đồng 100 USD")


@pytest.mark.parametrize("number_phrase", ["mua bán số TEST-001", "mua bán. Số hợp đồng: TEST-001"])
def test_explicit_contract_fields_survive_model_omissions_and_truncation(number_phrase):
    prompt = f"Tạo hợp đồng nguyên tắc {number_phrase} với công ty An Phú Demo, mã số thuế 0000000111. Nội dung hàng hóa: Container các loại phục vụ thi công dự án Y."
    client = FakeClient(Intent(company_name="An Phú Demo", tax_code="0000000112", work_description="Mua bán số TES, dự án").model_dump_json())
    intent = GeminiExtractor("test-placeholder", client=client).extract(prompt)
    assert intent.contract_number == "TEST-001"
    assert intent.tax_code == "0000000111"
    assert intent.work_description == "Container các loại phục vụ thi công dự án Y"


def test_work_label_does_not_swallow_following_contract_field():
    prompt = "Tạo hợp đồng công ty X. Công việc: Thi công tầng 1. Kiểm tra tầng 2. Số hợp đồng: HD-002."
    result = GeminiExtractor("test-placeholder", client=FakeClient(Intent(company_name="X").model_dump_json())).extract(prompt)
    assert result.work_description == "Thi công tầng 1. Kiểm tra tầng 2"
    assert result.contract_number == "HD-002"


def test_conflicting_explicit_contract_numbers_require_clarification():
    prompt = "Tạo hợp đồng công ty X. Số hợp đồng: HD-001. Số hợp đồng: HD-002."
    with pytest.raises(UserError, match="nhiều số hợp đồng"):
        GeminiExtractor("test-placeholder", client=FakeClient(Intent(company_name="X").model_dump_json())).extract(prompt)


@pytest.mark.parametrize("suffix", ["số tiền 1 tỷ", "thi công dự án số 3", "nội dung: thi công số lượng 3 căn"])
def test_unrelated_numbers_do_not_become_contract_number(suffix):
    prompt = f"Tạo hợp đồng với công ty X, {suffix}"
    result = GeminiExtractor("test-placeholder", client=FakeClient(Intent(company_name="X").model_dump_json())).extract(prompt)
    assert result.contract_number is None
