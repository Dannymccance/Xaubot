# Xaubot: XAUUSD research and strategy laboratory

**Release 0.1.0 is research-only. It cannot place MT5 orders.** The original GWS methodology has not been independently verified or shown profitable.

## Included
- 1 provisional GWS-like main model, based on overlapping technical zones and M5 confirmation.
- 200 deterministic challenger configurations: 10 SMC-related families, 4 confirmation profiles and 5 timing profiles, each with a separate experimental strategy ID.
- Closed-bar UTC M1/M5/H1/H4/D1 calculations, FVGs, order blocks, role flips, liquidity sweeps and structural targets.
- Isolated abstract paper simulations with 30/30/40 partial exits and SL-first intrabar ambiguity.
- Optional OpenAI Responses API commentary (advisory only) and authenticated Discord bot messages for fresh primary candidates.
- Unit tests and Docker Compose for a VPS.

**Not included:** native MT5 price collector, live execution, broker-valid lot sizing, commissions, swap, news controls, tick-accurate outcomes, GWS Telegram ground-truth matching, calibrated AI probabilities or verified trading performance. The 200 strategies are research hypotheses, not validated edges.

## VPS deployment (Ubuntu with Docker and Compose)

1. Clone: `git clone https://github.com/Dannymccance/Xaubot.git && cd Xaubot`
2. Configure: `cp .env.example .env && mkdir -p data`
3. Write completed UTC XAUUSD one-minute broker candles to `data/xauusd_m1.csv` using your own MT5 exporter or trusted data source. **This first release does not capture or download prices.** Without the feed, the service logs an error and continues to wait.
4. Start: `docker compose up -d --build`
5. Check: `docker compose logs --tail=100 -f xaubot`
6. Candidate journal: `data/candidates.json`

### Connect your Discord bot and optional AI

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), create or select the Xaubot application and open its **Bot** page. Obtain a bot token. Never paste the token into chats or GitHub.
2. Install the bot in **your Discord server** using the application installation/OAuth2 setup with the `bot` scope. Grant **View Channel** and **Send Messages** for the chosen text channel (not Administrator). No privileged message-content intent is required for this outbound-only version.
3. Enable **Developer Mode** in Discord settings and **Copy Channel ID** from the target channel.
4. In VPS `.env`, set `DISCORD_BOT_TOKEN=...` and `DISCORD_CHANNEL_ID=...`. Keep `XAUBOT_SEND_DISCORD=0` until the connectivity test works.
5. Build or refresh the container, then send an explicit test message:

```bash
docker compose build
docker compose run --rm xaubot python -m xaubot discord-test
```

6. Set `XAUBOT_SEND_DISCORD=1` and restart with `docker compose up -d --force-recreate` when your M1 feed is fresh and ready.

Only fresh `GWS_PRIMARY` paper candidates are posted. The 200 challengers remain silent. The Discord REST transport sends as your **bot identity**, not a webhook. A Gateway listener and slash commands are not implemented in this first release; those can be added without changing bot credentials.

For optional AI explanations, set `OPENAI_API_KEY` and `OPENAI_MODEL` to a Responses-API-compatible model available on your API account. AI output is limited to a short qualitative explanation; it cannot modify trades, stops, prices or any execution logic. Missing credentials are handled by a deterministic, AI-free signal.

### Required price-feed format

All timestamps must be timezone-aware **UTC** and represent the *start* of a fully completed one-minute bar. CSV columns:

```text
timestamp,open,high,low,close
```

Optional, only as a complete set:

```text
open_bid,high_bid,low_bid,close_bid,open_ask,high_ask,low_ask,close_ask
```

Example *format* (illustrative numbers, not genuine market data):

```csv
timestamp,open,high,low,close
2026-10-13T10:00:00Z,4160.0,4161.2,4159.7,4160.8
2026-10-13T10:01:00Z,4160.8,4161.0,4159.9,4160.1
```

The feed must be monotonically ordered and include enough completed higher-timeframe history to produce technical zones. Scanner alerts require a fresh feed (no more than 180 seconds behind UTC wall time) and refuse to notify about old historical candidates. It is not a substitute for a broker price/quote feed and must not be treated as real-time when stale.

## Local and VPS research commands

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m xaubot strategies
python3 -m xaubot scan --csv data/xauusd_m1.csv --out data/candidates.json
python3 -m xaubot backtest --csv data/xauusd_m1.csv --out data/backtest.json
```

The backtest allocates 0.5% theoretical per-idea risk but ignores minimum lots, margin, swaps, commissions and order rejection; its reported P&L is **not broker-executable**. Use the paper model for early logical comparisons only. Heuristic candidate score is not a probability.

## Known limitations and next steps

- The original GWS strategy is discretionary; exact entry rules and timing are unconfirmed.
- GWS message edits often preserve only the final state. The benchmark must not assume final edited text was available at the original send time.
- Test all 201 configurations on independent forward periods, including direction/session-matched random controls and multiple-testing adjustment.
- Before execution discussions: implement read-only MT5 data acquisition, proper quote-level simulator, tick-value/lot-step checks, aggregate risk budgets, kill switch and independently verified shadow trading.

See [development and live-trading gates](docs/ROADMAP.md). Nothing in this repository authorises real-money trading.
