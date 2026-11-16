import asyncio

from d_brain.bot.formatters import send_response


def test_rejected_html_is_sent_as_readable_plain_text():
    class Bot:
        def __init__(self):
            self.calls = []

        async def send_message(self, chat_id, text, **kwargs):
            self.calls.append((chat_id, text, kwargs))
            if not kwargs:
                raise ValueError("Telegram rejected markup")

    bot = Bot()
    asyncio.run(send_response(bot, 123, '<b>AT&T</b> < 5 & <a href="https://example.com">link</a>'))

    assert bot.calls[1] == (123, "AT&T < 5 & link", {"parse_mode": None})


def test_escaped_disallowed_tags_remain_visible():
    class Bot:
        async def send_message(self, chat_id, text, **kwargs):
            if not kwargs:
                raise ValueError("Telegram rejected markup")
            self.text = text

    bot = Bot()
    asyncio.run(send_response(bot, 1, "<script>hello</script>"))
    assert bot.text == "<script>hello</script>"
