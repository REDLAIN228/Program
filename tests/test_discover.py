from dataclasses import asdict
import io
import json

import httpx
from PIL import Image
import pytest

from app.discover import CommonsClient, DiscoveryImage, difficulty


def response_page():
    return {"query": {"pages": {"17": {"pageid": 17, "title": "File:Test portrait.png",
        "fullurl": "https://commons.wikimedia.org/wiki/File:Test_portrait.png",
        "imageinfo": [{"mime": "image/png", "width": 64, "height": 64,
            "url": "https://upload.wikimedia.org/wikipedia/commons/test.png",
            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/test.png",
            "extmetadata": {"Artist": {"value": '<a href="https://example.org">Test author</a>'},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"}}}]}}}}


def test_official_query_parses_real_api_shape_and_caches_requests_and_provenance(tmp_path, monkeypatch):
    seen = []
    def transport(request):
        seen.append(request)
        assert request.url.host == "commons.wikimedia.org"
        assert request.url.params["gsrnamespace"] == "6" and request.url.params["generator"] == "search"
        assert "authorization" not in request.headers
        return httpx.Response(200, json=response_page())
    monkeypatch.setattr(CommonsClient, "_last_request", -100.)
    client = CommonsClient(tmp_path, httpx.MockTransport(transport))
    rows, cached = client.search("portrait")
    assert not cached and len(rows) == 1 and rows[0].author == "Test author"
    assert rows[0].license == "CC BY-SA 4.0"
    assert client.search("portrait")[1] and len(seen) == 1


def test_download_favorite_and_offline_reuse_preserve_actual_image(tmp_path, monkeypatch):
    output = io.BytesIO()
    Image.new("RGB", (64, 64), (25, 100, 150)).save(output, "PNG")
    raw = output.getvalue()
    item = DiscoveryImage(17, "Portrait", "https://upload.wikimedia.org/thumb.png", "https://upload.wikimedia.org/original.png",
                          "https://commons.wikimedia.org/wiki/File:Portrait.png", "Author", "CC0", "", 64, 64)
    client = CommonsClient(tmp_path, httpx.MockTransport(lambda request: httpx.Response(200, content=raw)))
    image, path = client.download(item)
    client.favorite(item)
    assert path.exists() and image.getpixel((10, 10)) == (25, 100, 150)
    offline = CommonsClient(tmp_path, httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))))
    assert offline.favorites() == [item]
    thumbnail, _ = offline.download(item, thumbnail=True)
    assert thumbnail.getpixel((10, 10)) == (25, 100, 150)
    assert offline.download(item)[0].size == (64, 64)


def test_network_errors_never_return_embedded_demo_results(tmp_path, monkeypatch):
    monkeypatch.setattr(CommonsClient, "_last_request", -100.)
    client = CommonsClient(tmp_path, httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(RuntimeError, match="Нет доступа"):
        client.search("anime")
    assert client.favorites() == []


def test_untrusted_urls_and_oversized_downloads_are_rejected(tmp_path):
    item = DiscoveryImage(1, "Bad", "https://evil.example/thumb.png", "file:///secret", "", "", "", "", 1, 1)
    client = CommonsClient(tmp_path)
    with pytest.raises(ValueError): client.download(item)
    with pytest.raises(ValueError): client.download(item, thumbnail=True)
    item.original = "https://upload.wikimedia.org/too-large.png"
    client.transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-length": "33000000"}))
    with pytest.raises(ValueError, match="велико"):
        client.download(item)


def test_difficulty_uses_actual_planning_not_placeholder_numbers():
    image = Image.new("RGB", (64, 64), (40, 100, 140))
    result = difficulty(image, (64, 64), (1, 4, 16))
    assert result["strokes"] > 0 and result["colors"] == 1
    assert result["estimated_seconds"] > 0 and result["recommended_mode"] in ("FAST", "BALANCED", "MASTERPIECE")


def test_user_agent_carries_contact_required_by_wikimedia_robot_policy():
    # Commons answered 403 "Please respect our robot policy" to the 3.0 agent without contact info.
    from app.discover import USER_AGENT
    assert "REDLAIN-DRAW-ENGINE/" in USER_AGENT and "https://" in USER_AGENT
