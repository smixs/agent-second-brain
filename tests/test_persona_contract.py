"""The persona file is the agent's identity — verify its contract shape."""

from pathlib import Path

PERSONA = Path(__file__).resolve().parent.parent / "deploy" / "brain-system.md"


def test_persona_has_sentinel_header():
    text = PERSONA.read_text(encoding="utf-8")
    assert text.startswith("# second brain session contract")


def test_marker_instruction_is_conditional():
    """v3.0: markers are required ONLY when the request carries the marker
    instruction (wrap=True turns). Verbatim/steered input gets a normal
    reply — no unconditional 'every request' wording allowed."""
    text = PERSONA.read_text(encoding="utf-8")
    assert "Every request ends with an instruction" not in text
    low = text.lower()
    assert "when" in low and "marker" in low
    assert "no marker instruction" in low or "without a marker instruction" in low


def test_persona_names_autograph_memory():
    assert "autograph" in PERSONA.read_text(encoding="utf-8")


def test_persona_states_both_roles():
    """The whole point of the fork: the brain must know who it works for.
    A generic assistant produces generic answers."""
    text = PERSONA.read_text(encoding="utf-8")
    assert "обследовани" in text.lower()
    assert "TRONIX" in text
    assert "CVO" in text


def test_persona_forbids_manager_speak_and_emoji_padding():
    low = PERSONA.read_text(encoding="utf-8").lower()
    assert "concrete over descriptive" in low
    assert "смайл" in low


def test_persona_guards_against_invented_standards():
    """A fabricated СП clause in a technical report is a licence problem,
    not a typo — the persona must say so explicitly."""
    text = PERSONA.read_text(encoding="utf-8")
    assert "[сверить редакцию]" in text


def test_persona_states_telegram_has_no_tables():
    """Style asks for tables; the transport cannot render them. The contract
    has to resolve that or the brain emits broken pipe tables."""
    assert "Telegram has no tables" in PERSONA.read_text(encoding="utf-8")
