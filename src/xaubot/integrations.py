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


def send_discord(candidate: Candidate, ai_note: str) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
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
    payload = json.dumps({"content": message[:1900], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(webhook, data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "Xaubot/0.1"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status not in (200, 204):
            raise RuntimeError("Discord rejected the webhook request")
