"""Tests for tmux pane output parsing (pure functions).

Fixtures are real capture-pane excerpts from live spikes against
Claude Code 2.1.168. These functions must NOT touch tmux/subprocess —
they only parse text, so they are fully unit-testable.

Key invariant (from blind review + spikes): the model's answer markers are
LINE-ANCHORED (on their own line); the input echo shows the markers inline
(mid-sentence). So line-anchored matching alone distinguishes answer from
echo and from the model quoting the marker syntax inside its reply.
"""

import pytest

from d_brain.services.tmux_parse import (
    PaneState,
    classify_state,
    extract_reply,
    is_complete,
)

# ── Real capture excerpts (claude 2.1.168) ──────────────────────────────

READY_CAPTURE = """\
╭─── Claude Code v2.1.168 ──────────────────────────────────────╮
│                Welcome back Majento!                          │
╰───────────────────────────────────────────────────────────────╯
────────────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────────────
  hello | Opus 4.8 (1M context) | ~/T/dbrain_spk
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents
"""

# READY but in a normal permission mode (no "bypass permissions" footer);
# only the idle ❯ with a ghost suggestion is present. Exercises the ❯ branch.
READY_NO_BYPASS_CAPTURE = """\
────────────────────────────────────────────────────────────────
❯ Try "fix the failing test"
────────────────────────────────────────────────────────────────
  hello | Opus 4.8 (1M context) | ~/project
"""

TRUST_CAPTURE = """\
 Accessing workspace:
 /private/tmp
 Quick safety check: Is this a project you created or one you trust?
 Claude Code'll be able to read, edit, and execute files here.
 ❯ 1. Yes, I trust this folder
   2. No, exit
 Enter to confirm · Esc to cancel
"""

STARTING_CAPTURE = """\
╭─── Claude Code v2.1.168 ──────────────────────────────────────╮
│                  Loading...                                    │
╰───────────────────────────────────────────────────────────────╯
"""

# NOTE: rate-limit / logged-out strings NOT yet observed live — synthetic,
# based on known Claude Code wording. Must be verified on the VPS (open Q #2).
RATE_LIMIT_CAPTURE = """\
  You've reached your usage limit. Your limit resets at 3:00 PM.
❯
  ⏵⏵ bypass permissions on (shift+tab to cycle)
"""

LOGGED_OUT_CAPTURE = """\
  Invalid API key · Please run /login to authenticate.
❯
"""


# ── extract_reply ───────────────────────────────────────────────────────


def test_extract_reply_takes_line_anchored_pair_not_inline_echo():
    """Input echo has markers inline (mid-line); the answer has them on
    their own lines. Only the line-anchored pair is the real reply."""
    rid = "911e06a2"
    text = (
        f"> Reply PONG, put <<<R:{rid}>>> before and <<<E:{rid}>>> after\n"  # echo
        "  ... transcript ...\n"
        f"<<<R:{rid}>>>\n"
        "PONG\n"
        f"<<<E:{rid}>>>\n"
        "❯\n"
    )
    assert extract_reply(text, rid) == "PONG"


def test_extract_reply_with_tui_bullet_prefix():
    """Regression (live): Claude Code prefixes the first answer line with
    '⏺ ' and indents the rest. The marker is at the END of its line; that,
    not 'starts the line', is what distinguishes answer from inline echo."""
    rid = "bull1234"
    text = f"⏺ <<<R:{rid}>>>\n  PONG\n  <<<E:{rid}>>>\n❯\n"
    assert extract_reply(text, rid) == "PONG"


def test_extract_reply_multiline_answer():
    rid = "abc12345"
    text = f"<<<R:{rid}>>>\nline one\nline two\n<<<E:{rid}>>>\n"
    assert extract_reply(text, rid) == "line one\nline two"


def test_extract_reply_marker_quoted_inline_inside_answer():
    """CRITICAL (blind review): the model quotes the marker syntax inside
    its answer (inline). The inline quote must be ignored; the real
    line-anchored pair still yields the full answer."""
    rid = "deadbeef"
    text = (
        f"<<<R:{rid}>>>\n"
        f"To finish I print <<<E:{rid}>>> on its own line.\n"  # inline quote
        "Here is the real answer.\n"
        f"<<<E:{rid}>>>\n"
        "❯\n"
    )
    got = extract_reply(text, rid)
    assert got is not None
    assert "Here is the real answer." in got
    assert got.startswith("To finish I print")


def test_extract_reply_stray_end_marker_does_not_corrupt():
    """HIGH (blind review): a stray line-anchored end marker after a complete
    pair must not produce a span that swallows the real end marker + chrome."""
    rid = "cafe1234"
    text = (
        f"<<<R:{rid}>>>\n"
        "PONG\n"
        f"<<<E:{rid}>>>\n"
        "❯\n"
        f"<<<E:{rid}>>>\n"  # stray, no preceding R
    )
    got = extract_reply(text, rid)
    assert got == "PONG"


def test_extract_reply_none_when_no_markers():
    assert extract_reply("just some text\n❯\n", "deadbeef") is None


def test_extract_reply_none_when_only_open_marker():
    rid = "feedface"
    assert extract_reply(f"<<<R:{rid}>>>\nPONG (still typing)", rid) is None


def test_extract_reply_ignores_other_rid():
    text = "<<<R:aaaa1111>>>\nPONG\n<<<E:aaaa1111>>>\n"
    assert extract_reply(text, "bbbb2222") is None


def test_extract_reply_empty_rid_raises():
    with pytest.raises(ValueError):
        extract_reply("anything", "")


# ── is_complete ─────────────────────────────────────────────────────────


def test_is_complete_true_on_line_anchored_pair():
    rid = "11112222"
    assert is_complete(f"<<<R:{rid}>>>\nPONG\n<<<E:{rid}>>>\n", rid) is True


def test_is_complete_false_on_inline_echo_only():
    """The echo of the typed prompt (inline markers) is NOT a complete reply."""
    rid = "33334444"
    text = f"> do thing, wrap in <<<R:{rid}>>> .. <<<E:{rid}>>>\n❯\n"
    assert is_complete(text, rid) is False


def test_is_complete_false_when_answer_still_streaming():
    rid = "55556666"
    assert is_complete(f"<<<R:{rid}>>>\npartial...", rid) is False


# ── classify_state ──────────────────────────────────────────────────────


def test_classify_trust_prompt():
    assert classify_state(TRUST_CAPTURE) == PaneState.TRUST_PROMPT


def test_classify_ready_with_bypass_footer():
    assert classify_state(READY_CAPTURE) == PaneState.READY


def test_classify_ready_without_bypass_footer():
    """READY must be detected via the idle ❯ alone (bypass footer is
    permission-mode specific and may be absent)."""
    assert classify_state(READY_NO_BYPASS_CAPTURE) == PaneState.READY


def test_classify_ready_when_footer_above_empty_bottom():
    """Regression (live): the TUI draws content at the top and leaves the
    bottom of the screen blank, so the footer (bypass/idle) is NOT in the
    chrome region. READY must still be detected via the footer anchor."""
    text = READY_CAPTURE + "\n" * 30
    assert classify_state(text) == PaneState.READY


def test_classify_starting():
    assert classify_state(STARTING_CAPTURE) == PaneState.STARTING


def test_classify_rate_limited():
    assert classify_state(RATE_LIMIT_CAPTURE) == PaneState.RATE_LIMITED


def test_classify_logged_out():
    assert classify_state(LOGGED_OUT_CAPTURE) == PaneState.LOGGED_OUT


def test_classify_unknown_on_empty():
    assert classify_state("") == PaneState.UNKNOWN


def test_rate_limit_takes_priority_over_ready_idle():
    """A rate-limit banner co-existing with idle must classify as
    RATE_LIMITED so the watchdog does NOT treat it as healthy."""
    assert classify_state(RATE_LIMIT_CAPTURE) == PaneState.RATE_LIMITED


# ── classify_state false positives (transcript body mentions triggers) ───


def _long_transcript(mention: str) -> str:
    """A long transcript whose BODY mentions a trigger word, but whose
    chrome region (bottom) is a healthy idle pane."""
    body = f"❯ explain something\nThe model says: {mention}\n" + "filler line\n" * 25
    footer = (
        "────────────────────────────────────────────\n"
        "❯\n"
        "────────────────────────────────────────────\n"
        "  hello | Opus 4.8 (1M context) | ~/project\n"
        "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
    )
    return body + footer


def test_classify_no_false_positive_rate_limit_in_body():
    assert (
        classify_state(_long_transcript("you will hit your usage limit soon"))
        == PaneState.READY
    )


def test_classify_no_false_positive_login_in_body():
    assert (
        classify_state(_long_transcript("just run /login to authenticate"))
        == PaneState.READY
    )


def test_classify_no_false_positive_trust_in_body():
    assert (
        classify_state(
            _long_transcript("Is this a project you trust? appears on first run")
        )
        == PaneState.READY
    )


def test_classify_trust_when_menu_above_empty_chrome():
    """Regression (found in live integration): the trust dialog is a
    full-screen modal drawn at the TOP; on a tall pane the bottom 18 lines
    (chrome) are blank. Trust must still be detected over the whole pane."""
    text = TRUST_CAPTURE + "\n" * 40
    assert classify_state(text) == PaneState.TRUST_PROMPT


def test_classify_priority_stack_trust_first():
    """When several signatures co-occur in the chrome, TRUST wins (it must be
    answered before anything else is meaningful)."""
    stacked = (
        " Is this a project you created or one you trust?\n"
        " ❯ 1. Yes, I trust this folder\n"
        "   2. No, exit\n"
        " usage limit resets at 3:00 PM\n"
        " ❯\n"
    )
    assert classify_state(stacked) == PaneState.TRUST_PROMPT


def test_extract_reply_works_for_skill_invocation_turn():
    """Characterization: a /skill-name prompt is a NORMAL model turn — the
    model honors the appended marker instruction, so the existing marker path
    extracts the reply. No verbatim extractor is needed for skills."""
    rid = "ab12cd34"
    pane = (
        "❯ /vault-note сохрани мысль про autograph\n"
        "\n"
        "  When done, wrap your ENTIRE reply between a line containing only "
        f"<<<R:{rid}>>> and a line containing only <<<E:{rid}>>>.\n"
        "\n"
        f"⏺ <<<R:{rid}>>>\n"
        "  Заметка сохранена: thoughts/ideas/autograph.md\n"
        f"  <<<E:{rid}>>>\n"
        "\n"
        "❯\n"
    )
    assert is_complete(pane, rid)
    assert extract_reply(pane, rid) == "Заметка сохранена: thoughts/ideas/autograph.md"


# ── is_idle (turn-completion signal independent of the bypass footer) ──────

_FOOTER = (
    "────────────────────\n❯\n────────────────────\n"
    "  hello | Opus 4.8 (1M context) | ~/p\n"
    "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
)
_WORKING = "  ✻ Working…  (esc to interrupt)\n"


def test_is_idle_true_on_empty_input_prompt():
    from d_brain.services.tmux_parse import is_idle

    assert is_idle("transcript above\n" + _FOOTER)


def test_is_idle_false_while_working():
    from d_brain.services.tmux_parse import is_idle

    assert not is_idle("transcript\n" + _WORKING + _FOOTER)


def test_is_idle_false_when_footer_present_but_thinking():
    """The bypass footer is ALWAYS on screen under --dangerously-skip-
    permissions, so it must never be treated as an idle signal by itself."""
    from d_brain.services.tmux_parse import is_idle

    pane = "long transcript\n" + _WORKING + "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
    assert not is_idle(pane)


def test_is_idle_false_on_empty_pane():
    from d_brain.services.tmux_parse import is_idle

    assert not is_idle("")


def test_is_idle_false_on_menu_selector():
    """An interactive menu's selector (`❯ 1. Yes …`) is NOT an idle prompt —
    only a bare ❯ (empty input line) counts. Guards wrap=False completion
    against approval/menu prompts."""
    from d_brain.services.tmux_parse import is_idle

    pane = (
        "Do you approve this plan?\n"
        " ❯ 1. Yes, proceed\n   2. No, keep planning\n"
        "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
    )
    assert not is_idle(pane)


def test_classify_login_menu_as_logged_out():
    """Incident 2026-06-10: a fresh CLAUDE_CONFIG_DIR sent the new process
    into first-run onboarding (theme → login menu); classify_state saw
    UNKNOWN and the watchdog stayed silent while every ask timed out. The
    login/onboarding screens need a human — classify them LOGGED_OUT."""
    login = (
        " Claude Code can be used with your Claude subscription or billed "
        "based on API usage through your Console account.\n"
        " Select login method:\n"
        " ❯ 1. Claude account with subscription · Pro, Max, Team, or Enterprise\n"
        "   2. Anthropic Console account · API usage billing\n"
    )
    assert classify_state(login) == PaneState.LOGGED_OUT


def test_classify_onboarding_theme_as_logged_out():
    theme = (
        "   3. Light mode\n ❯ 6. Dark mode (ANSI colors only) ✔\n"
        "  Syntax theme: ansi (ctrl+t to disable)\n"
    )
    assert classify_state(theme) == PaneState.LOGGED_OUT
