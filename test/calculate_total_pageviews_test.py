from datetime import datetime
import importlib.util
from pathlib import Path
import requests

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "calculate_total_pageviews.py"
SPEC = importlib.util.spec_from_file_location("calculate_total_pageviews", MODULE_PATH)
pageviews = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pageviews)


def test_normalize_article_title_decodes_percent_encoded_title():
    assert pageviews.normalize_article_title("Kellogg%2C_Idaho") == "Kellogg,_Idaho"


def test_get_pageviews_normalizes_and_requotes_article_title(monkeypatch):
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [{"views": 12}, {"views": 30}]}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(pageviews.requests, "get", fake_get)

    views = pageviews.get_pageviews(
        "https://en.wikipedia.org/wiki/Kellogg%2C_Idaho",
        datetime(2025, 1, 1),
        datetime(2025, 1, 2),
    )

    assert views == 42
    assert "/Kellogg%2C_Idaho/daily/20250101/20250102" in captured["url"]
    assert captured["headers"]["User-Agent"] == pageviews.WP_BOT_USER_AGENT
    assert captured["timeout"] == 10


def test_get_pageviews_retries_with_canonical_title_after_404(monkeypatch):
    captured = {"urls": []}

    class DummyResponse:
        def __init__(self, status_code=200, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                error = requests.exceptions.HTTPError("boom")
                error.response = self
                raise error

        def json(self):
            return self._payload

    def fake_get(url, headers=None, params=None, timeout=None):
        if url == pageviews.MEDIAWIKI_API:
            return DummyResponse(
                payload={
                    "query": {
                        "pages": {
                            "123": {
                                "title": "Clinton, Maryland",
                            }
                        }
                    }
                }
            )

        captured["urls"].append(url)
        if len(captured["urls"]) == 1:
            return DummyResponse(status_code=404)

        return DummyResponse(payload={"items": [{"views": 7}, {"views": 8}]})

    monkeypatch.setattr(pageviews.requests, "get", fake_get)

    views = pageviews.get_pageviews(
        "Clinton,_Maryland",
        datetime(2025, 1, 1),
        datetime(2025, 1, 2),
    )

    assert views == 15
    assert "/Clinton%2C_Maryland/daily/20250101/20250102" in captured["urls"][0]
    assert "/Clinton%2C_Maryland/daily/20250101/20250102" in captured["urls"][1]
