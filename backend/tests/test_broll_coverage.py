"""`produce_api.check_broll_coverage`: whether a finished render came back
with (almost) no B-roll because ComfyUI was offline during it -- the
2026-10-20 incident where a render was delivered anyway with 263 beats
planned and 0 B-roll placed. A pure function of BuzzEdit's presentation
report, so it is tested without a render."""
from app.api.produce_api import check_broll_coverage


def _report(**kwargs):
    base = dict(beats_planned=0, broll_placed=0, assets_generated=0, assets_cached=0, assets_failed=[])
    base.update(kwargs)
    return base


def test_no_beats_planned_is_not_a_problem():
    result = check_broll_coverage(_report())
    assert result["coverage_low"] is False
    assert result["should_fail"] is False
    assert result["warning"] is None


def test_missing_report_is_not_a_problem():
    result = check_broll_coverage(None)
    assert result["coverage_low"] is False
    assert result["should_fail"] is False


def test_full_coverage_is_fine():
    result = check_broll_coverage(_report(beats_planned=10, broll_placed=10, assets_generated=10))
    assert result["coverage_low"] is False
    assert result["should_fail"] is False
    assert result["warning"] is None


def test_zero_broll_placed_because_comfyui_was_offline_fails_and_does_not_deliver():
    failures = [{"beat_id": f"b{i}", "reason": "ComfyUI offline"} for i in range(10)]
    result = check_broll_coverage(_report(beats_planned=10, broll_placed=0, assets_generated=0,
                                           assets_cached=0, assets_failed=failures))
    assert result["coverage_low"] is True
    assert result["should_fail"] is True
    assert result["message"]
    assert "ComfyUI" in result["message"]
    assert result["warning"] is None


def test_mostly_aborted_beats_also_fails():
    failures = ([{"beat_id": "b0", "reason": "ComfyUI offline"}]
               + [{"beat_id": f"b{i}", "reason": "not attempted: aborted (ComfyUI offline)"} for i in range(1, 9)])
    result = check_broll_coverage(_report(beats_planned=10, broll_placed=1, assets_generated=1,
                                           assets_failed=failures))
    assert result["should_fail"] is True


def test_low_coverage_for_other_reasons_delivers_with_a_warning_instead():
    failures = [{"beat_id": f"b{i}", "reason": "no output produced"} for i in range(9)]
    result = check_broll_coverage(_report(beats_planned=10, broll_placed=1, assets_generated=1,
                                           assets_failed=failures))
    assert result["coverage_low"] is True
    assert result["should_fail"] is False
    assert result["message"] is None
    assert result["warning"]


def test_coverage_just_above_half_is_fine_even_with_comfyui_failures():
    # 6/10 placed, failures all ComfyUI's fault -- still delivered: coverage
    # itself is not low.
    failures = [{"beat_id": f"b{i}", "reason": "ComfyUI offline"} for i in range(4)]
    result = check_broll_coverage(_report(beats_planned=10, broll_placed=6, assets_generated=6,
                                           assets_failed=failures))
    assert result["coverage_low"] is False
    assert result["should_fail"] is False


def test_cached_assets_count_toward_coverage():
    result = check_broll_coverage(_report(beats_planned=10, broll_placed=9, assets_generated=2,
                                           assets_cached=7))
    assert result["coverage_low"] is False
    assert result["should_fail"] is False
