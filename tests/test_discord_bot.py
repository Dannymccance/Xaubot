"""Discord bot outgoing REST contract. All external calls mocked."""
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from xaubot.engine import Candidate
from xaubot.integrations import _post_bot_message, send_discord, send_discord_test


BOT_ENV = {
    "DISCORD_BOT_TOKEN": "VERY_SECRET_DISCORD_BOT_TOKEN",
    "DISCORD_CHANNEL_ID": "123456789012345678",
}


class Reply:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def fixture():
    return Candidate(
        datetime(2026,10,13,10,5,tzinfo=timezone.utc),
        "GWS_PRIMARY", "gws_replica", 1, 4160., 4158., 4161.,
        4157., 4160., 4155., 4164., 4166.5, 4172.,
        "fallback_3R_hypothesis", 50, "fixture", "scalp",
    )


class DiscordBotTests(unittest.TestCase):
    def test_sends_to_channel_message_endpoint_as_bot(self):
        with patch.dict(os.environ, BOT_ENV, clear=True):
            with patch("urllib.request.urlopen", return_value=Reply()) as transport:
                _post_bot_message("hello")
        request = transport.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://discord.com/api/v10/channels/123456789012345678/messages",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bot VERY_SECRET_DISCORD_BOT_TOKEN")
        payload = json.loads(request.data.decode())
        self.assertEqual(payload["content"], "hello")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("webhook", request.full_url)

    def test_missing_token_or_channel_blocks_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("urllib.request.urlopen") as transport:
                with self.assertRaisesRegex(RuntimeError, "DISCORD_BOT_TOKEN"):
                    _post_bot_message("hello")
                transport.assert_not_called()
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN":"token","DISCORD_CHANNEL_ID":"wrong"}, clear=True):
            with patch("urllib.request.urlopen") as transport:
                with self.assertRaisesRegex(RuntimeError, "DISCORD_CHANNEL_ID"):
                    _post_bot_message("hello")
                transport.assert_not_called()

    def test_http_error_does_not_expose_bot_token(self):
        http_error = HTTPError(
            "https://discord.com/api/v10/channels/123456789012345678/messages",
            403, "not permitted", {}, None,
        )
        with patch.dict(os.environ, BOT_ENV, clear=True):
            with patch("urllib.request.urlopen", side_effect=http_error):
                with self.assertRaisesRegex(RuntimeError, "HTTP 403") as ctx:
                    _post_bot_message("hello")
        self.assertNotIn(BOT_ENV["DISCORD_BOT_TOKEN"], str(ctx.exception))
        self.assertNotIn("123456789012345678", str(ctx.exception))

    def test_primary_uses_bot_and_multiline_content(self):
        with patch.dict(os.environ, BOT_ENV, clear=True):
            with patch("urllib.request.urlopen", return_value=Reply()) as transport:
                send_discord(fixture(), "advisory")
        request = transport.call_args.args[0]
        content = json.loads(request.data.decode())["content"]
        self.assertIn("GWS-STYLE BUY | PAPER CANDIDATE", content)
        self.assertIn("AI advisory: advisory", content)
        self.assertIn("\nSL:", content)
        self.assertIn("NO BROKER ORDER SENT", content)

    def test_explicit_connection_test_does_not_emulate_signal(self):
        with patch.dict(os.environ, BOT_ENV, clear=True):
            with patch("urllib.request.urlopen", return_value=Reply()) as transport:
                send_discord_test()
        request = transport.call_args.args[0]
        content = json.loads(request.data.decode())["content"]
        self.assertIn("DISCORD BOT CONNECTIVITY TEST", content)
        self.assertNotIn("GWS-STYLE BUY", content)
        self.assertNotIn("GWS-STYLE SELL", content)


if __name__ == "__main__":
    unittest.main()
