# Xaubot: XAUUSD research and strategy laboratory

**The current research release is paper-only. It cannot place MT5 orders.** The original GWS methodology has not been independently verified or shown profitable.

## Included
- 1 provisional GWS-like main model, based on overlapping technical zones and M5 confirmation.
- 200 deterministic challenger configurations: 10 SMC-related families, 4 confirmation profiles and 5 timing profiles, each with a separate experimental strategy ID.
- Closed-bar UTC M1/M5/H1/H4/D1 calculations, FVGs, order blocks, role flips, liquidity sweeps and structural targets.
- Isolated abstract paper simulations with 30/30/40 partial exits and SL-first intrabar ambiguity.
- Optional OpenAI Responses API commentary (advisory only) and authenticated Discord bot messages for fresh primary candidates.
- Read-only MT5 historical M1 exporter (on a machine with a running MT5 terminal),
  atomic price CSV and origin manifest. Details in [MT5 feed guide](docs/MT5_FEED.md).
- **Ubuntu/Wine MT5 MQL5 EA exporter** (no Windows-only Python API required),
  with a separate UTC timestamp validation bridge. See [Wine MT5 integration](docs/WINE_MT5_SETUP.md).
- Optional read-only Discord slash commands: `/status`, `/signals`, `/leaderboard`, `/strategies`.
- Paper research summaries and unit tests with Docker Compose for a VPS.

**Not included:** native MT5 tick/bid-ask collector inside Docker, live execution, broker-valid lot sizing, commissions, swap, news controls, tick-accurate outcomes, GWS Telegram ground-truth matching, calibrated AI probabilities or verified trading performance. The 200 strategies are research hypotheses, not validated edges.

## VPS deployment (Ubuntu with Docker and Compose)

1. Clone: `git clone https://github.com/Dannymccance/Xaubot.git && cd Xaubot`
2. Configure: `cp .env.example .env && mkdir -p data`
3. Write completed UTC XAUUSD one-minute broker candles to `data/xauusd_m1.csv` using the included [Wine MT5/MQL5 exporter and Ubuntu timestamp bridge](docs/WINE_MT5_SETUP.md), the [native terminal-side Python exporter](docs/MT5_FEED.md), or a trusted equivalent data source. Neither terminal-side exporter runs inside the standard Docker container. Without the CSV feed, the scanner logs an error and continues to wait.
4. Start: `docker compose up -d --build`
5. Check: `docker compose logs --tail=100 -f xaubot`
6. Candidate journal: `data/candidates.json`. Current research status: `docker compose exec xaubot python -m xaubot report status --data-dir /app/data`.

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

### Enable read-only Discord commands later

The outbound alerts and the interactive bot use the same existing Discord
application and `DISCORD_BOT_TOKEN`, not webhooks. Slash commands need these
settings on the VPS, whenever you are ready: `DISCORD_GUILD_ID` for the
single authorised server, and `DISCORD_CHANNEL_ID` for the authorised channel.
The Discord install should include the `bot` and `applications.commands`
scopes with View Channel and Send Messages access; no Administrator or
message-content privileged intent is needed.

The slash command service is **off by default** and runs in a separate
container that reads `./data` in read-only mode. Once the bot is invited
and credentials are configured, start it with:

```bash
docker compose --profile commands up -d --build
```

Slash commands available to authorised users in the configured channel:
`/status` checks last closed MT5 candle timestamp, `/signals` shows
the latest primary *paper* candidate, `/leaderboard` ranks only experimental
paper portfolios with at least 20 fully closed ideas, and `/strategies`
shows the 201-strategy registry. Replies are ephemeral. They do not place
trades or change strategy configuration. No credentials are needed to run
unit tests or offline reports.

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
python3 -m xaubot audit --csv data/xauusd_m1.csv --out data/feed_audit.json
python3 -m xaubot scan --csv data/xauusd_m1.csv --out data/candidates.json
python3 -m xaubot backtest --csv data/xauusd_m1.csv --out data/backtest.json
python3 -m xaubot report status --data-dir data
python3 -m xaubot report leaderboard --data-dir data
```

Before comparing paper results, run `xaubot audit` to fingerprint the exact CSV and identify source, broker time-offset, gaps, and stale data. This audit cannot independently certify that UTC+2 was the correct broker offset for September and October: verify that separately. Missing candles can reflect market closures rather than connectivity faults. The `backtest` command stores the audit in `backtest.json.metadata.feed_audit` and aborts if the CSV changes while it is running, instead of silently misattributing a replay to a new dataset.

The backtest allocates 0.5% theoretical per-idea risk but ignores minimum lots, margin, swaps, commissions and order rejection; its reported P&L is **not broker-executable**. A replay of the same data used to design a strategy is exploratory, not out-of-sample validation. Use the paper model for early logical comparisons only. Heuristic candidate score is not a probability.

## Known limitations and next steps

- The original GWS strategy is discretionary; exact entry rules and timing are unconfirmed.
- GWS message edits often preserve only the final state. The benchmark must not assume final edited text was available at the original send time.
- Test all 201 configurations on independent forward periods, including direction/session-matched random controls and multiple-testing adjustment.
- Before execution discussions: independently verify the MT5 read-only data feeds and Wine stability, implement a quote-level simulator, tick-value/lot-step checks, aggregate risk budgets, kill switch and independently verified shadow trading.

See [development and live-trading gates](docs/ROADMAP.md). Nothing in this repository authorises real-money trading.
