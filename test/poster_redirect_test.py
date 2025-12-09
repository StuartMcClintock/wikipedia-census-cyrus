import types

from poster import process_single_article


class DummyClient:
    def __init__(self, wikitext):
        self.wikitext = wikitext
        self.fetches = 0
        self.edits = 0

    def fetch_article_wikitext(self, title):
        self.fetches += 1
        return self.wikitext

    def edit_article_wikitext(self, *args, **kwargs):
        self.edits += 1
        return {}


def test_process_single_article_skips_redirect(monkeypatch):
    client = DummyClient("#REDIRECT [[Target]]")
    args = types.SimpleNamespace(
        skip_should_update_check=True,
        skip_deterministic_fixes=False,
        show_codex_output=False,
    )

    # Swap out heavy helpers with no-ops for this test.
    monkeypatch.setattr("poster.generate_county_paragraphs", lambda *a, **k: "")
    monkeypatch.setattr("poster.update_demographics_section", lambda *a, **k: "")
    monkeypatch.setattr("poster.update_wp_page", lambda *a, **k: "")

    process_single_article(
        "Some_County,_State",
        "00",
        "000",
        args,
        client,
        use_mini_prompt=False,
    )

    assert client.fetches == 1
    assert client.edits == 0
