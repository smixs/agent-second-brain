"""Pure parsing of `tmux capture-pane -p` output from an interactive
Claude Code session. No subprocess/tmux access — text in, value out.

Kept separate from claude_session.py so the fragile parsing logic is
fully unit-testable against real capture fixtures.

Design invariants (from live spikes + adversarial review):
* The model's answer markers are LINE-ANCHORED (each on its own line).
  The input echo shows the markers INLINE (mid-sentence), and the model
  quoting the marker syntax also appears inline. So matching only
  line-anchored markers distinguishes the real answer from the echo and
  from inline self-references — no fragile occurrence-counting needed.
* State signatures are matched only against the CHROME region (the bottom
  of the pane: footer/banner/idle line), never the whole transcript, so a
  reply that *mentions* "usage limit" or "/login" cannot be misclassified.

The rate-limit / logged-out signatures are not yet confirmed against a
live session and may need adjustment per CLI version (see tests, open Q #2).
"""

import re
from enum import Enum

# How many trailing lines count as "chrome" (footer/banner/idle region).
# State signatures are matched only here, not against the transcript body.
_CHROME_LINES = 18


class PaneState(str, Enum):
    """Coarse state of the interactive session, read from the pane text."""

    TRUST_PROMPT = "trust_prompt"  # "Is this a project you trust?" — needs Enter
    STARTING = "starting"  # welcome box visible, not yet idle
    READY = "ready"  # idle prompt / bypass-permissions footer
    RATE_LIMITED = "rate_limited"  # usage limit hit — do NOT kill, wait for reset
    LOGGED_OUT = "logged_out"  # auth lost — needs re-login
    UNKNOWN = "unknown"


def _require_rid(rid: str) -> None:
    if not rid:
        raise ValueError("rid must be a non-empty string")


def _line_anchored(rid: str, kind: str) -> re.Pattern[str]:
    # The marker must be at the END of its line (only whitespace after it).
    # Any prefix is allowed — Claude Code prefixes the first answer line with
    # "⏺ " and indents the rest. The input echo has TEXT after the marker
    # ("<<<R:id>>> and a line..."), so it never matches end-of-line.
    return re.compile(rf"(?m)^.*?<<<{kind}:{re.escape(rid)}>>>[ \t]*\r?$")


def extract_reply(text: str, rid: str) -> str | None:
    """Return the text of the last well-formed, line-anchored
    ``<<<R:rid>>> .. <<<E:rid>>>`` pair, stripped, or ``None``.

    Only line-anchored markers are considered (the input echo and inline
    self-references are mid-line and thus ignored). The chosen span must not
    contain another line-anchored marker of either kind, so a stray end
    marker cannot make the span swallow chrome.
    """
    _require_rid(rid)
    opens = list(_line_anchored(rid, "R").finditer(text))
    ends = list(_line_anchored(rid, "E").finditer(text))
    if not opens or not ends:
        return None

    # Walk end markers from last to first; pair each with the nearest
    # preceding open marker and accept the first span with no inner marker.
    open_starts = [m.start() for m in opens]
    for end_m in reversed(ends):
        end_pos = end_m.start()
        preceding = [s for s in open_starts if s < end_pos]
        if not preceding:
            continue
        start_m = next(m for m in opens if m.start() == preceding[-1])
        inner = text[start_m.end() : end_pos]
        # Reject if another line-anchored marker hides inside the span.
        if _line_anchored(rid, "E").search(inner) or _line_anchored(rid, "R").search(
            inner
        ):
            continue
        return inner.strip()
    return None


def is_complete(text: str, rid: str) -> bool:
    """True iff a complete line-anchored answer pair is present.

    Replaces the fragile "count >= 2" heuristic: because the echo is inline,
    a single line-anchored pair already means the model's answer is done.
    """
    _require_rid(rid)
    return extract_reply(text, rid) is not None


# Signature tables. Order of checks in classify_state encodes priority.
# TRUST anchors on the numbered menu (structural), not the prose sentence,
# so the model describing the trust prompt cannot trigger it.
_TRUST_MENU_RE = re.compile(r"(?m)^\s*(?:❯\s*)?1\.\s+Yes, I trust this folder")
_RATE_RE = re.compile(
    r"usage limit|rate limit|limit reached|resets at|5-hour limit|weekly limit",
    re.I,
)
_LOGGED_OUT_RE = re.compile(
    r"invalid api key|please run /login|logged out|please log ?in|"
    r"authentication (failed|required|expired)|session expired|"
    # First-run onboarding screens (fresh CLAUDE_CONFIG_DIR): they need a
    # human, restarts won't help — alert like a logout, don't kill.
    r"select login method|syntax theme: \w+ \(ctrl\+t to disable\)",
    re.I,
)
# READY signals. The bypass footer is our always-present anchor (we launch
# with --dangerously-skip-permissions); it can sit above a blank bottom, so
# it is matched over the WHOLE pane. The idle ❯ is a secondary signal matched
# only in chrome (a bare ❯ elsewhere could be model output).
_FOOTER_RE = re.compile(r"bypass permissions on")
_IDLE_RE = re.compile(r"(?m)^\s*❯")
_STARTING_RE = re.compile(r"Claude Code v\d", re.I)
# Active-turn marker. The TUI shows "(esc to interrupt)" next to its spinner
# for the whole turn, so its absence + an idle ❯ is the idle signal. The
# bypass footer is ALWAYS on screen under --dangerously-skip-permissions and
# must never be used as an idle signal by itself.
_WORKING_RE = re.compile(r"esc to interrupt")
# Idle = a BARE ❯ on its own line (empty input). A menu selector ("❯ 1. Yes…")
# has text after the chevron and must NOT count — otherwise a turn stuck on an
# approval/menu prompt would be mistaken for completion (wrap=False).
_IDLE_BARE_RE = re.compile(r"(?m)^\s*❯\s*$")


def _chrome(text: str) -> str:
    return "\n".join(text.splitlines()[-_CHROME_LINES:])


_CHROME_LINE_RE = re.compile(
    r"^\s*❯?\s*$"               # empty / bare idle prompt
    r"|^\s*─+\s*$"              # box rule
    r"|bypass permissions on"   # always-present footer
    r"|esc to interrupt"        # working spinner hint
    r"|^\s*⏵⏵"                  # footer arrows
    r"|^\s{2}\S.* \| .* \| "    # status line: "  name | model | path"
)


def strip_chrome(text: str) -> str:
    """Best-effort body of a non-marker turn: drop TUI chrome lines.

    Used for ``wrap=False`` turns where no marker pair exists; the result may
    still contain the input echo — callers treat it as informational text,
    not a structured reply.
    """
    kept = [ln for ln in text.splitlines() if not _CHROME_LINE_RE.search(ln)]
    return "\n".join(kept).strip()


def is_working(text: str) -> bool:
    """True iff the pane shows an ACTIVE turn (the working spinner).

    The shared liveness predicate for ask()'s stall detector and the
    watchdog: silence is not a hang signal — a long task that prints nothing
    still shows '(esc to interrupt)'. Hung == stuck WITHOUT this marker.
    """
    return bool(_WORKING_RE.search(_chrome(text)))


def is_idle(text: str) -> bool:
    """True iff the session sits at an idle input prompt (no active turn).

    Unlike READY in classify_state (anchored on the always-present bypass
    footer), this checks the chrome for an idle ``❯`` AND the absence of the
    working spinner — usable as a turn-completion signal for prompts that
    produce no marker pair.
    """
    if not text.strip():
        return False
    chrome = _chrome(text)
    if _WORKING_RE.search(chrome):
        return False
    return bool(_IDLE_BARE_RE.search(chrome))


def classify_state(text: str) -> PaneState:
    """Classify the pane into a coarse state.

    State signatures are matched against the chrome region only; STARTING is
    matched against the whole text (its banner can sit above the fold during
    boot). Priority: TRUST > RATE_LIMITED > LOGGED_OUT > READY > STARTING.
    """
    if not text.strip():
        return PaneState.UNKNOWN
    # TRUST is a full-screen modal whose menu sits at the TOP; on a tall pane
    # the chrome (bottom) is blank, so match it over the WHOLE pane. Safe
    # because it anchors on the numbered menu line, which the model cannot
    # reproduce verbatim in a reply.
    if _TRUST_MENU_RE.search(text):
        return PaneState.TRUST_PROMPT
    chrome = _chrome(text)
    if _RATE_RE.search(chrome):
        return PaneState.RATE_LIMITED
    if _LOGGED_OUT_RE.search(chrome):
        return PaneState.LOGGED_OUT
    if _FOOTER_RE.search(text) or _IDLE_RE.search(chrome):
        return PaneState.READY
    if _STARTING_RE.search(text):
        return PaneState.STARTING
    return PaneState.UNKNOWN
