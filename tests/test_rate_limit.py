"""Tests for the rate-limit record — the cure for the sticky 'limit' status.

The bug it fixes: the limit signal was read from pane text only, so once the
banner was on screen ask() short-circuited before typing anything, the pane
never changed, and the state survived the actual reset forever. The record
here gives that signal an EXPIRY, after which the caller must probe.
"""

from datetime import datetime, timedelta

import pytest

from d_brain.services.rate_limit import (
    MAX_COOLDOWN,
    RateLimitState,
    parse_reset_time,
)

NOW = datetime(2026, 6, 10, 12, 0)


def _state(tmp_path, now=NOW, **over):
    return RateLimitState(tmp_path / "rate_limit.json", now_fn=lambda: now, **over)


# ── parsing the reset moment ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "banner,expected",
    [
        ("Your limit resets at 3:00 PM.", datetime(2026, 6, 10, 15, 0)),
        ("5-hour limit reached ∙ resets 3pm", datetime(2026, 6, 10, 15, 0)),
        ("limit reached. Will reset at 14:30", datetime(2026, 6, 10, 14, 30)),
        # 11am today is in the PAST at 12:00 → the next occurrence is tomorrow,
        # but MAX_COOLDOWN caps how far out we are willing to wait.
        ("resets at 11am", NOW + timedelta(seconds=MAX_COOLDOWN)),
        ("try again in 45 minutes", datetime(2026, 6, 10, 12, 45)),
        ("resets in 2 hours", datetime(2026, 6, 10, 14, 0)),
        ("12am is midnight", None),  # no reset verb → not a reset time
        ("", None),
    ],
)
def test_parse_reset_time(banner, expected):
    assert parse_reset_time(banner, NOW) == expected


def test_parse_rejects_impossible_clock():
    assert parse_reset_time("resets at 99:99", NOW) is None


def test_parsed_window_is_capped():
    """A weekly limit may be days out; probing every few hours costs one
    prompt and guarantees a misparse can never strand the brain."""
    got = parse_reset_time("resets in 900 hours", NOW)
    assert got == NOW + timedelta(seconds=MAX_COOLDOWN)


# ── the record ───────────────────────────────────────────────────────────


def test_no_file_means_no_limit(tmp_path):
    assert _state(tmp_path).status() == (None, False)


def test_recorded_limit_holds_until_its_reset_time(tmp_path):
    _state(tmp_path).record("You've reached your usage limit. Resets at 3pm.")
    rec, holding = _state(tmp_path).status()
    assert holding
    assert rec.until == datetime(2026, 6, 10, 15, 0)


def test_limit_lapses_after_the_reset_time(tmp_path):
    """THE regression: a record must stop holding on its own. Before this,
    the status could only be cleared by killing the tmux session by hand."""
    _state(tmp_path).record("resets at 3pm")
    later = _state(tmp_path, now=datetime(2026, 6, 10, 15, 1))
    rec, holding = later.status()
    assert rec is not None and not holding  # present but stale ⇒ probe


def test_banner_without_a_reset_time_falls_back_to_the_cooldown(tmp_path):
    rec = _state(tmp_path, default_cooldown=600.0).record("usage limit reached")
    assert rec.until == NOW + timedelta(seconds=600)


def test_clear_forgets_the_limit(tmp_path):
    st = _state(tmp_path)
    st.record("resets at 3pm")
    st.clear()
    assert st.status() == (None, False)


def test_corrupt_file_is_dropped_not_fatal(tmp_path):
    """A half-written record must never brick every request."""
    path = tmp_path / "rate_limit.json"
    path.write_text("{not json", encoding="utf-8")
    st = _state(tmp_path)
    assert st.status() == (None, False)
    assert not path.exists()


def test_record_survives_a_reread(tmp_path):
    st = _state(tmp_path)
    written = st.record("Weekly limit reached · resets at 4:15 PM")
    assert _state(tmp_path).read().until == written.until
