"""The persona file is the agent's identity — verify its contract shape."""

from pathlib import Path

PERSONA = Path(__file__).resolve().parent.parent / "deploy" / "brain-system.md"


def test_persona_has_sentinel_header():
    text = PERSONA.read_text()
    assert text.startswith("# d-brain session contract")


def test_marker_instruction_is_conditional():
    """v3.0: markers are required ONLY when the request carries the marker
    instruction (wrap=True turns). Verbatim/steered input gets a normal
    reply — no unconditional 'every request' wording allowed."""
    text = PERSONA.read_text()
    assert "Every request ends with an instruction" not in text
    low = text.lower()
    assert "when" in low and "marker" in low
    assert "no marker instruction" in low or "without a marker instruction" in low


def test_persona_names_autograph_memory():
    assert "autograph" in PERSONA.read_text()
