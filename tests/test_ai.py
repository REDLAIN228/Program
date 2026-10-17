import base64
import io

import httpx
from PIL import Image
import pytest

from app.ai import OpenAIImageProvider, ProviderSettings


def response_image():
    stream = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(stream, "PNG")
    return base64.b64encode(stream.getvalue()).decode()


def test_text_generation_and_reference_edit_use_distinct_real_endpoints():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": response_image()}]})
    provider = OpenAIImageProvider(ProviderSettings(), "test-secret", httpx.MockTransport(handler))
    assert provider.generate("anime").getpixel((0, 0)) == (255, 0, 0)
    assert requests[-1].url.path == "/v1/images/generations"
    provider.generate("reference edit", Image.new("RGB", (20, 20), "blue"))
    assert requests[-1].url.path == "/v1/images/edits"
    assert b'filename="reference.png"' in requests[-1].content
    assert requests[-1].headers["Authorization"] == "Bearer test-secret"


def test_downloaded_images_do_not_receive_api_authorization():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("generations"):
            return httpx.Response(200, json={"data": [{"url": "https://storage.example/art.png"}]})
        return httpx.Response(200, content=base64.b64decode(response_image()))
    provider = OpenAIImageProvider(ProviderSettings(), "test-secret", httpx.MockTransport(handler))
    provider.generate("test")
    assert "Authorization" in requests[0].headers
    assert "Authorization" not in requests[1].headers


def test_provider_errors_are_sanitized():
    provider = OpenAIImageProvider(ProviderSettings(), "secret",
                httpx.MockTransport(lambda _: httpx.Response(401, text="echo secret")))
    with pytest.raises(RuntimeError) as error:
        provider.generate("test")
    assert "401" in str(error.value)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://example.com?key=secret"])
def test_provider_rejects_insecure_urls(url):
    with pytest.raises(ValueError):
        OpenAIImageProvider(ProviderSettings(url), "key")
