"""Optional outbound integrations. Never authorises or sends broker orders."""
import json
import os
import urllib.error
import urllib.request

from .engine import Candidate


def ai_commentary(candidate: Candidate) -> str:
    """Advisory, bounded, single-candidate interpretation. Fail open to deterministic signal."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()
    if not key or not model:
        return "AI commentary disabled (configure OPENAI_API_KEY and OPENAI_MODEL)."
    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": 250,
        "instructions": (
            "You are an XAUUSD research commentator, NOT a trading authority. "
            "Use only supplied facts. Summarize evidence for and against this proposed "
            "setup in at most 80 words. Explicitly say when information is absent. "
            "Never assert live prices, broker fills, actual win rates, or calibrated probabilities. "
            "Do not change stop, targets, sizing, or execution decisions."
        ),
        "input": json.dumps(candidate.to_dict(), sort_keys=True),
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.load(response)
        parts = [c.get("text", "") for item in data.get("output", [])
                 for c in item.get("content", []) if c.get("type") == "output_text"]
        return " ".join(parts).strip()[:700] or "AI returned no readable commentary."
    except (OSError, ValueError, KeyError) as error:
        # Do not log tokens, webhook URLs, prompts, or full HTTP error bodies.
        return f"AI unavailable ({type(error).__name__}); deterministic alert unchanged."


def _post_bot_message(content: str) -> None:
    """Send via the Discord application's bot identity, not a webhook.

    This REST-only outbound path does not require a Discord Gateway connection,
    privileged intents or a slash-command listener.
    """
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")
    if not channel_id or not channel_id.isascii() or not channel_id.isdecimal() or not 15 <= len(channel_id) <= 24:
        raise RuntimeError("DISCORD_CHANNEL_ID must be a numeric Discord channel ID")
    payload = json.dumps({
        "content": content[:1900],
        "allowed_mentions": {"parse": []},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=payload,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "Xaubot/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Discord bot message rejected (HTTP {response.status})")
    except urllib.error.HTTPError as exc:
        # Do not expose response bodies, tokens or credential-bearing request objects.
        raise RuntimeError(f"Discord bot message rejected (HTTP {exc.code})") from None
    except urllib.error.URLError:
        raise RuntimeError("Discord bot transport failed") from None


def send_discord(candidate: Candidate, ai_note: str) -> None:
    """Post the primary paper candidate through the authorised Discord bot."""
    side = "BUY" if candidate.side == 1 else "SELL"
    message = (
        f"**XAUBOT | GWS-STYLE {side} | PAPER CANDIDATE**\n"
        f"UTC close: {candidate.timestamp.isoformat()} | ID: {candidate.event_id}\n"
        f"Entry hypothesis: {candidate.entry_low:.2f} to {candidate.entry_high:.2f} "
        f"(reference {candidate.ref_price:.2f})\n"
        f"SL: {candidate.stop:.2f} | TP1: {candidate.tp1:.2f} | "
        f"TP2: {candidate.tp2:.2f} | TP3: {candidate.tp3:.2f}\n"
        f"TP3 basis: {candidate.tp3_source} | Research score (NOT probability): {candidate.score}\n"
        f"Logic: {candidate.rationale}\n"
        f"AI advisory: {ai_note[:700]}\n"
        "**NO BROKER ORDER SENT. No claim of actual fill or proven edge.**"
    )
    _post_bot_message(message)


def send_discord_test() -> None:
    """Explicit operator-initiated test; does not use historical or live candles."""
    _post_bot_message(
        "**XAUBOT | DISCORD BOT CONNECTIVITY TEST**\n"
        "Outbound bot-token delivery is configured.\n"
        "Research-only mode: no trading signal and no MT5 order."
    )
