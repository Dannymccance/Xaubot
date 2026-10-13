# Baseline research workflow: MT5 XAUUSD to 201 paper configurations

The Wine MQL5 exporter, Ubuntu UTC bridge and Docker scanner are already
installed on the dedicated `xaumt5` VPS. No account credentials are needed
for this procedure. It is **research-only**, not an MT5 trading system.

## Step 1: audit existing 30,000 completed M1 candles

From root SSH:

```bash
cd /root/Xaubot
git pull --ff-only origin main
docker compose up -d --build
docker compose exec xaubot python -m xaubot audit \
  --csv /app/data/xauusd_m1.csv \
  --out /app/data/feed_audit.json
```

The audit reports SHA-256 fingerprint, first and last closed UTC bar,
source/provenance, observed chronology gaps, gap durations and the claimed
broker UTC offset. **Important:** the recorded +120 minute offset is only
the configured hypothesis, not independent broker confirmation.
The feed may be stale while the broker is closed. The audit **never**
asserts market open/closed solely from the candle age.

Stop for manual review if a CSV/manifest mismatch or a future UTC timestamp
is detected. In particular, a historical range crossing the broker's
daylight-saving transition requires manual offset segmentation; do not
treat the fixed UTC+2 shift as verified over the entire range.

## Step 2: exploratory all-strategies paper replay

Only after reviewing the audit, run the historical replay:

```bash
docker compose exec xaubot python -m xaubot backtest \
  --csv /app/data/xauusd_m1.csv \
  --out /app/data/backtest.json
```

This simulates one provisional GWS-style primary configuration plus
200 challengers against the imported price bars. It can take a while for
30,000 candles. It does not open or manage MT5 positions, has no broker
risk minimums and makes synthetic fill assumptions.

The generated JSON includes `metadata.feed_audit` with the SHA-256 hash,
broker time offset, and relevant warnings. The replay will refuse to
write results if the CSV contents changed during its run. If the market
is open and the bridge is updating, create a **manually frozen,
read-only snapshot** under another filename, including its corresponding
manifest, before long replays to guarantee reproducibility.

Inspect the experimental ranking only after a replay completes:

```bash
docker compose exec xaubot python -m xaubot report leaderboard --data-dir /app/data
```

No strategy with fewer than 20 **closed** theoretical ideas is ranked,
and even a nonempty table does not demonstrate a profitable edge. Most
of the 201 configurations may not generate adequate sample sizes in a
30,000-candle window. Do not cherry-pick the top backtest return.

## Step 3: forward validation and live feed testing

When the broker resumes quoting XAUUSD, first verify fresh timestamps,
no read errors from the systemd bridge, and correctness of server UTC
offset before enabling alerts. Collect an independent forward sample.
Historical paper replay alone is not out-of-sample proof.

When comparing strategies, include holdout periods, random/session
controls, multiple-comparison corrections and actual bid/ask tick-level
costs. The GWS baseline remains a hypothesis rather than an accurately
reconstructed original rule.

**Safety:** `XAUBOT_SEND_DISCORD=0` for this whole workflow, and
live order execution remains unavailable.
