"""Bulk Editor: the text rules, the safety checks, and apply/restore without YouTube."""
import pytest

from integrations import youtube_bulk_edit as bulk
from integrations import youtube_publish as yt


def test_plain_removals_match_whole_words_only():
    assert bulk.apply_field("Cat category CAT", {"remove": ["cat"]}) == "category"


def test_regex_lines_and_literal_replacements():
    rule = {"remove": [r"/\s*\|\s*Ep\.\s*\d+/i"], "replace": [["@old", "@new $1"]]}
    assert bulk.apply_field("Story | ep. 12 by @old", rule) == "Story by @new $1"


def test_added_text_is_never_stacked():
    rule = {"append": "Follow @raat3baje", "separator": "\n\n"}
    once = bulk.apply_field("Story", rule)
    assert once == "Story\n\nFollow @raat3baje"
    assert bulk.apply_field(once, rule) == once


def test_text_no_rule_touched_keeps_its_spacing():
    assert bulk.apply_field("a  b ", {"remove": ["zzz"]}) == "a  b "


def test_a_title_emptied_by_removals_is_blocked_even_with_an_append():
    video = {"title": "SHOCKING", "description": ""}
    result = bulk.apply_rules(video, {"title": {"remove": ["shocking"], "append": "Part 2"}})
    assert result["problems"] and "empty" in result["problems"][0]


def test_youtube_limits_are_reported():
    assert bulk.validate("x" * 101, "")
    assert bulk.validate("ok", "<b>")
    assert not bulk.validate("ok", "fine")


def test_a_bad_regex_is_reported_before_any_network_call(monkeypatch):
    monkeypatch.setattr(bulk, "list_videos", lambda cid: pytest.fail("fetched"))
    with pytest.raises(ValueError):
        bulk.preview("UC1", {"title": {"remove": ["/([/"]}})


VIDEOS = [
    {"id": "v1", "title": "Ep 1 | SHOCKING", "description": "d1", "categoryId": "24", "tags": ["a"],
     "defaultLanguage": None, "defaultAudioLanguage": "hi", "publishedAt": "2026", "privacy": "public"},
    {"id": "v2", "title": "Ep 2", "description": "d2", "categoryId": "24", "tags": None,
     "defaultLanguage": None, "defaultAudioLanguage": None, "publishedAt": "2026", "privacy": "private"},
]


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(bulk, "list_videos", lambda cid, on_progress=None: [dict(v) for v in VIDEOS])
    sent = []
    monkeypatch.setattr(bulk, "update_text", lambda cid, video, title, desc: sent.append((video["id"], title)))

    class SyncThread:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(bulk.threading, "Thread", SyncThread)
    return sent


def test_apply_backs_up_first_and_needs_the_count(offline):
    plan = bulk.preview("UC1", {"title": {"remove": ["| SHOCKING"]}, "privacy": ["public"]})
    assert [i["id"] for i in plan["items"]] == ["v1"]
    with pytest.raises(yt.YouTubeError):
        bulk.apply(plan["preview_id"], ["v1"], confirm=2)
    result = bulk.apply(plan["preview_id"], ["v1"], confirm=1)
    assert offline == [("v1", "Ep 1")]
    assert result["backup"] and bulk.list_backups("UC1")[0]["count"] == 1
    assert bulk.job()["done"] == 1 and bulk.job()["state"] == "done"


def test_restore_only_touches_videos_that_differ_from_the_backup(offline, monkeypatch):
    name = bulk.write_backup("UC1", [{"id": "v1", "title": "Old title", "description": "d1"},
                                     {"id": "v2", "title": "Ep 2", "description": "d2"}], "test")
    plan = bulk.restore_plan("UC1", name)
    assert [(e["video"]["id"], e["title"]) for e in plan["entries"]] == [("v1", "Old title")]
    bulk.restore("UC1", name, confirm=1)
    assert offline == [("v1", "Old title")]


def test_backup_names_cannot_escape_the_channel_folder(offline):
    with pytest.raises(yt.YouTubeError):
        bulk.restore_plan("UC1", "../../config.json")
    with pytest.raises(yt.YouTubeError):
        bulk.list_backups("../x")
