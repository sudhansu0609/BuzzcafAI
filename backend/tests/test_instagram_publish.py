"""Instagram Reels publishing (integrations/instagram_publish.py), REELS_DESK_PLAN.md R7.
Every HTTP call goes through `_request`, which is faked here -- no test may
reach graph.facebook.com or rupload.facebook.com for real (conftest's
`_never_call_the_real_instagram_api` refuses any call this file does not
monkeypatch itself)."""
import re
import time

import pytest


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text or str(self._data)

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    from integrations import instagram_publish as ig
    monkeypatch.setattr(ig, "SETTINGS_FILE", tmp_path / "instagram_settings.json")
    monkeypatch.setattr(ig.time, "sleep", lambda s: None)  # the container poll loop and retry backoff


def test_discover_accounts_lists_each_connected_pages_instagram_account(monkeypatch):
    from integrations import instagram_publish as ig

    def dispatch(method, url, **kwargs):
        if url.endswith("/me/accounts"):
            return FakeResponse(200, {"data": [
                {"id": "pg1", "name": "Page One", "access_token": "pgtok1"},
                {"id": "pg2", "name": "Page Two (no IG)", "access_token": "pgtok2"},
            ]})
        if url.endswith("/pg1"):
            return FakeResponse(200, {"instagram_business_account": {"id": "17841", "username": "pageone_ig"}})
        if url.endswith("/pg2"):
            return FakeResponse(400, {"error": {"message": "no permission", "code": 200}})
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(ig, "_request", dispatch)
    accounts = ig.discover_accounts("usertoken")
    assert accounts == [{"page_id": "pg1", "page_name": "Page One", "ig_user_id": "17841",
                         "username": "pageone_ig", "access_token": "pgtok1"}]


def _connect(ig, **extra):
    base = {"ig_user_id": "1784111", "access_token": "longtok", "token_expires_at": time.time() + 40 * 86400}
    ig.set_account_settings("Raat3Baje", {**base, **extra})


def test_publish_reel_runs_the_full_resumable_sequence(monkeypatch, tmp_path):
    from integrations import instagram_publish as ig

    _connect(ig)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"fake reel bytes")
    polls = {"n": 0}
    log = []

    def dispatch(method, url, **kwargs):
        log.append((method, url, kwargs.get("params"), kwargs.get("headers")))
        if url.endswith("/content_publishing_limit"):
            return FakeResponse(200, {"data": [{"config": {"quota_total": 50}, "quota_usage": 2}]})
        if url.endswith("/media") and method == "POST":
            return FakeResponse(200, {"id": "container123",
                                      "uri": "https://rupload.facebook.com/ig-api-upload/container123"})
        if "rupload.facebook.com" in url:
            return FakeResponse(200, {"success": True})
        if url.endswith("/container123"):
            polls["n"] += 1
            code = "IN_PROGRESS" if polls["n"] == 1 else "FINISHED"
            return FakeResponse(200, {"status_code": code, "status": code})
        if url.endswith("/media_publish"):
            return FakeResponse(200, {"id": "media555"})
        if url.endswith("/media555"):
            return FakeResponse(200, {"permalink": "https://www.instagram.com/reel/abc123/"})
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(ig, "_request", dispatch)
    result = ig.publish_reel("Raat3Baje", str(video), "a caption #one", thumb_offset_ms=1000)
    assert result == {"media_id": "media555", "permalink": "https://www.instagram.com/reel/abc123/"}
    assert polls["n"] == 2  # polled once in progress, once finished

    open_call = next(c for c in log if c[1].endswith("/media") and c[0] == "POST")
    assert open_call[2]["media_type"] == "REELS" and open_call[2]["upload_type"] == "resumable"
    assert open_call[2]["thumb_offset"] == 1000

    upload_call = next(c for c in log if "rupload" in c[1])
    assert upload_call[3]["Authorization"] == "OAuth longtok" and upload_call[3]["file_size"] == str(len(b"fake reel bytes"))


def test_upload_resumes_from_the_confirmed_offset_after_a_dropped_connection(monkeypatch, tmp_path):
    """2026-10-24, Fable review #11: the upload streams from disk in chunks,
    and a dropped connection resumes from the offset rupload confirms --
    never re-sends the whole file from byte 0."""
    from integrations import instagram_publish as ig

    _connect(ig)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"x" * 20)
    monkeypatch.setattr(ig, "UPLOAD_CHUNK_BYTES", 10)  # two chunks: [0:10) and [10:20)
    posts = []

    def dispatch(method, url, **kwargs):
        if url.endswith("/content_publishing_limit"):
            return FakeResponse(200, {"data": [{"config": {"quota_total": 50}, "quota_usage": 0}]})
        if url.endswith("/media") and method == "POST":
            return FakeResponse(200, {"id": "c1", "uri": "https://rupload.facebook.com/x/c1"})
        if "rupload" in url and method == "POST":
            posts.append(kwargs.get("headers", {}).get("offset"))
            if len(posts) == 2:  # the second chunk's first attempt drops
                raise ig.InstagramError("connection dropped")
            return FakeResponse(200, {"success": True})
        if "rupload" in url and method == "GET":
            return FakeResponse(200, {"offset": 10})  # confirmed: only the first chunk landed
        if url.endswith("/c1"):
            return FakeResponse(200, {"status_code": "FINISHED"})
        if url.endswith("/media_publish"):
            return FakeResponse(200, {"id": "m1"})
        if url.endswith("/m1"):
            return FakeResponse(200, {"permalink": "https://instagram.com/p/x"})
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(ig, "_request", dispatch)
    result = ig.publish_reel("Raat3Baje", str(video), "caption")
    assert result["media_id"] == "m1"
    assert posts == ["0", "10", "10"]  # chunk 1 ok, chunk 2 dropped, chunk 2 resumed from the confirmed offset


def test_publish_reel_fails_when_processing_errors(monkeypatch, tmp_path):
    from integrations import instagram_publish as ig

    _connect(ig)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"bytes")

    def dispatch(method, url, **kwargs):
        if url.endswith("/content_publishing_limit"):
            return FakeResponse(200, {"data": [{"config": {"quota_total": 50}, "quota_usage": 1}]})
        if url.endswith("/media") and method == "POST":
            return FakeResponse(200, {"id": "container9", "uri": "https://rupload.facebook.com/x/container9"})
        if "rupload" in url:
            return FakeResponse(200, {"success": True})
        if url.endswith("/container9"):
            return FakeResponse(200, {"status_code": "ERROR", "status": "Publishing failed: file too large"})
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(ig, "_request", dispatch)
    with pytest.raises(ig.InstagramError, match="file too large"):
        ig.publish_reel("Raat3Baje", str(video), "caption")


def test_publish_reel_surfaces_the_graph_api_error_message(monkeypatch, tmp_path):
    from integrations import instagram_publish as ig

    _connect(ig, access_token="badtok")
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"bytes")

    def dispatch(method, url, **kwargs):
        if url.endswith("/content_publishing_limit"):
            return FakeResponse(200, {"data": []})
        if url.endswith("/media") and method == "POST":
            return FakeResponse(400, {"error": {"message": "Invalid OAuth access token.", "code": 190}})
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(ig, "_request", dispatch)
    with pytest.raises(ig.InstagramError, match="Invalid OAuth access token"):
        ig.publish_reel("Raat3Baje", str(video), "caption")


def test_publish_reel_refuses_over_the_daily_limit(monkeypatch, tmp_path):
    from integrations import instagram_publish as ig

    _connect(ig)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"bytes")

    def dispatch(method, url, **kwargs):
        if url.endswith("/content_publishing_limit"):
            return FakeResponse(200, {"data": [{"config": {"quota_total": 50}, "quota_usage": 50}]})
        raise AssertionError("no further calls expected once the daily limit is hit")

    monkeypatch.setattr(ig, "_request", dispatch)
    with pytest.raises(ig.InstagramError, match="publishing limit"):
        ig.publish_reel("Raat3Baje", str(video), "caption")


def test_refresh_token_if_needed_exchanges_under_ten_days(monkeypatch):
    from integrations import instagram_publish as ig

    _connect(ig, access_token="oldtok", app_id="app1", app_secret="secret1",
             token_expires_at=time.time() + 5 * 86400)

    def dispatch(method, url, **kwargs):
        assert url.endswith("/oauth/access_token")
        params = kwargs.get("params") or {}
        assert params["fb_exchange_token"] == "oldtok" and params["client_id"] == "app1" \
            and params["client_secret"] == "secret1"
        return FakeResponse(200, {"access_token": "newtok", "expires_in": 60 * 86400})

    monkeypatch.setattr(ig, "_request", dispatch)
    updated = ig.refresh_token_if_needed("Raat3Baje")
    assert updated["access_token"] == "newtok"
    assert ig.account_settings("Raat3Baje")["access_token"] == "newtok"


def test_refresh_token_if_needed_is_a_no_op_with_days_to_spare(monkeypatch):
    from integrations import instagram_publish as ig

    _connect(ig, access_token="tok", token_expires_at=time.time() + 40 * 86400)

    def dispatch(method, url, **kwargs):
        raise AssertionError("no network call expected with days to spare")

    monkeypatch.setattr(ig, "_request", dispatch)
    conf = ig.refresh_token_if_needed("Raat3Baje")
    assert conf["access_token"] == "tok"


def test_trim_caption_enforces_the_length_limit():
    from integrations import instagram_publish as ig
    assert len(ig.trim_caption("x" * 3000)) == ig.CAPTION_MAX_CHARS


def test_trim_caption_drops_hashtags_past_thirty():
    from integrations import instagram_publish as ig
    tags = " ".join(f"#tag{i}" for i in range(40))
    out = ig.trim_caption(f"A caption. {tags}")
    assert len(re.findall(r"#\w+", out)) == 30
    assert out.startswith("A caption.")


# --- accounts + routing (a channel can post to more than one account) --------------------

def test_life3baje_mood_reel_defaults_to_its_own_khayal3bajefeels_account():
    from integrations import instagram_publish as ig
    assert ig.account_for("Life3Baje", "mood_reel") == "khayal3bajefeels"
    assert ig.routes()["Life3Baje/mood_reel"] == "khayal3bajefeels"
    # unconnected until the creator adds a token -- still an empty, not missing, account
    assert ig.account_settings("khayal3bajefeels")["ig_user_id"] == ""


def test_a_channel_format_route_wins_over_the_plain_channel_route():
    from integrations import instagram_publish as ig
    ig.set_routes({"Life3Baje": "life3baje_main", "Raat3Baje": "raat3baje_main"})
    assert ig.account_for("Life3Baje") == "life3baje_main"
    assert ig.account_for("Life3Baje", "mood_reel") == "khayal3bajefeels"   # still wins
    assert ig.account_for("Life3Baje", "rules_horror") == "life3baje_main"  # falls back to the channel route
    assert ig.account_for("Raat3Baje", "rules_horror") == "raat3baje_main"
    assert ig.account_for("Beyond3Baje") is None


def test_clearing_a_route_with_an_empty_account_name_removes_it():
    from integrations import instagram_publish as ig
    ig.set_routes({"Life3Baje/mood_reel": ""})
    assert "Life3Baje/mood_reel" not in ig.routes()
    assert ig.account_for("Life3Baje", "mood_reel") is None


def test_set_account_settings_rejects_a_blank_name():
    from integrations import instagram_publish as ig
    with pytest.raises(ig.InstagramError):
        ig.set_account_settings("   ", {"ig_user_id": "1"})


def test_publish_reel_can_be_routed_to_two_different_accounts_for_the_same_channel(monkeypatch, tmp_path):
    """Life3Baje's ordinary reels and its mood reels post through different accounts."""
    from integrations import instagram_publish as ig

    ig.set_account_settings("life3baje_main", {"ig_user_id": "100", "access_token": "tok_main"})
    ig.set_account_settings("khayal3bajefeels", {"ig_user_id": "200", "access_token": "tok_feels"})
    ig.set_routes({"Life3Baje": "life3baje_main"})
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"bytes")
    seen_tokens = []

    def dispatch(method, url, **kwargs):
        params = kwargs.get("params") or {}
        if url.endswith("/content_publishing_limit"):
            return FakeResponse(200, {"data": []})
        if url.endswith("/media") and method == "POST":
            seen_tokens.append(params.get("access_token"))
            return FakeResponse(200, {"id": "c1", "uri": "https://rupload.facebook.com/x/c1"})
        if "rupload" in url:
            return FakeResponse(200, {"success": True})
        if url.endswith("/c1"):
            return FakeResponse(200, {"status_code": "FINISHED"})
        if url.endswith("/media_publish"):
            return FakeResponse(200, {"id": "m1"})
        if url.endswith("/m1"):
            return FakeResponse(200, {"permalink": "https://instagram.com/p/x"})
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(ig, "_request", dispatch)
    account = ig.account_for("Life3Baje", "rules_horror")
    assert account == "life3baje_main"
    ig.publish_reel(account, str(video), "caption")
    account2 = ig.account_for("Life3Baje", "mood_reel")
    assert account2 == "khayal3bajefeels"
    ig.publish_reel(account2, str(video), "caption")
    assert seen_tokens == ["tok_main", "tok_feels"]
