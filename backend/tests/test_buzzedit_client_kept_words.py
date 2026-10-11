"""`BuzzEditClient.get_kept_words` -- the post-cut word source `produce_api`
plans visuals against, with a fallback to the full transcript for a BuzzEdit
that predates the `/kept_words` endpoint."""

from integrations.buzzedit_client import BuzzEditClient


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_get_kept_words_returns_the_words_list(monkeypatch):
    client = BuzzEditClient()
    monkeypatch.setattr(
        client, "_get",
        lambda path, timeout=None: _FakeResponse(200, {"words": [{"word": "hi", "start": 0.0, "end": 0.2}]}),
    )
    assert client.get_kept_words("p1") == [{"word": "hi", "start": 0.0, "end": 0.2}]


def test_get_kept_words_empty_list_when_no_words_key(monkeypatch):
    client = BuzzEditClient()
    monkeypatch.setattr(client, "_get", lambda path, timeout=None: _FakeResponse(200, {}))
    assert client.get_kept_words("p1") == []


def test_get_kept_words_falls_back_to_full_transcript_on_404(monkeypatch):
    client = BuzzEditClient()

    def fake_get(path, timeout=None):
        if path.endswith("/kept_words"):
            return _FakeResponse(404)
        assert path.endswith("/transcript")
        return _FakeResponse(200, {"segments": [{"words": [{"word": "fallback"}]}]})

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.get_kept_words("p1") == [{"word": "fallback"}]
