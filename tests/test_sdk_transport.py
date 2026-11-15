import json

from google import genai
from google.genai import types
import httpx

from contract_app.gemini import GeminiExtractor
from contract_app.models import Intent


def test_real_sdk_serializes_request_without_network_or_local_files():
    requests = []
    intent = Intent(company_name="Công ty X", amount_text="1 tỷ", work_description="Thi công Y")
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": intent.model_dump_json()}]}, "finishReason": "STOP"}]})
    client = genai.Client(api_key="test-placeholder", vertexai=False, http_options=types.HttpOptions(client_args={"transport": httpx.MockTransport(respond)}))
    try:
        result = GeminiExtractor("test-placeholder", client=client).extract("Tạo hợp đồng công ty X, 1 tỷ, thi công Y")
    finally:
        client.close()
    assert result.company_name == "Công ty X"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path.endswith("models/gemini-3.5-flash-lite:generateContent")
    assert "key" not in request.url.params
    data = json.loads(request.content)
    assert data["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in data["generationConfig"]
    assert "inlineData" not in json.dumps(data)
    assert "fileData" not in json.dumps(data)
