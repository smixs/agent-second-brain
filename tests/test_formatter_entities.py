"""An HTML entity must stay intact when a Telegram message is split."""

from d_brain.bot.formatters import MAX_RESPONSE_LENGTH, split_text


def test_split_preserves_entities_across_the_boundary():
    cut = MAX_RESPONSE_LENGTH - 50
    for entity in ("&amp;", "&lt;", "&#128512;", "&#x1f600;"):
        text = "x" * (cut - 2) + entity + "y" * 100
        chunks = split_text(text, MAX_RESPONSE_LENGTH)
        assert len(chunks) == 2
        assert chunks[0].endswith("...")
        assert chunks[1].startswith(entity)
        assert all(len(chunk) <= MAX_RESPONSE_LENGTH for chunk in chunks)
        assert "".join(chunks).count(entity) == 1
