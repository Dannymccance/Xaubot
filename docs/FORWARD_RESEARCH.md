# Xaubot forward-only XAUUSD candidate journal (optional)

**Scope:** collect independently observed, point-in-time completed-M5
experimental **candidates** across the 201 research configurations.
This is NOT broker order placement, shadow trade execution, simulated
fill accounting or a profit-and-loss leaderboard. The separate historical
`backtest.json` is in-sample, not a substitute for forward observation.

The optional Docker Compose `forward` profile is **disabled by default**.
The existing Wine MT5 source exporter, sandboxed systemd UTC bridge,
Docker scanner and other MT5 terminals are not modified by this feature.

## Critical broker clock prerequisite

The currently configured MetaQuotes-Demo broker offset `+120 minutes`
is **provisional**. While no new quotes are observed, we cannot verify
that a fresh broker M1 bar is correctly aligned with UTC.

**Do NOT activate the forward collector until you independently compare**
the broker's new M1 bar time with the VPS UTC clock at the same instant
while the broker is publishing candles. If the actual offset is not +120
minutes, stop the bridge before changing any offset and preserve/archive
the existing converted CSV and matching manifest. The imported September
and October dataset may also span historical broker daylight-saving
transitions, which a single fixed offset does not account for.

Once you have verified the actual broker offset, manually set these
values in `/root/Xaubot/.env`:

```ini
XAUBOT_BROKER_OFFSET_VERIFIED=1
XAUBOT_BROKER_UTC_OFFSET_MINUTES=120
```

The `1` is the operator's **attestation**, not a software measurement,
and `120` is only correct if you have independently verified UTC+2.
The service refuses to start with the default `0` value.

## Deploy when verified

From the dedicated Xaubot root SSH session:

```bash
cd /root/Xaubot
git pull --ff-only origin main
docker compose --profile forward up -d --build forward
docker compose --profile forward logs --tail=30 forward
```

The dedicated `forward` container has no network interface, drops all
Linux capabilities, has a read-only root filesystem and shares only
the Xaubot `data` directory. It cannot connect to MT5 or Discord.

**On the FIRST start**, the process records the last already-observed
closed candle as its immutable forward-study baseline. It deliberately
does **not** produce any historical candidate events. It then polls
for later M1 updates every 30 seconds, evaluates only newly observed
completed M5 bars that have closed within the last 180 seconds, and
atomically appends candidate records to
`data/forward_journal.json`.

After an outage, candidate timestamps older than the 180-second
freshness window are counted as skipped rather than presented as
live-forward observations. The cursor and event IDs prevent duplicate
records on restart. If the historical cursor bar has been rewritten,
the source provenance changes, or the symbol or UTC offset differs,
the collector refuses to advance and requires manual investigation.

The market being closed can legitimately mean no new candidate records.

## Inspect the forward-study journal

```bash
docker compose --profile forward exec forward \
  python -m xaubot.forward --report \
  --state /app/data/forward_journal.json
```

The report includes the initial baseline candle, last observed candle,
the number of fresh M5 observations, stale intervals that were skipped,
candidate counts and counts by strategy. **There is no win rate, P&L
or forward trading result** at this stage.

The research workflow after sufficient independent observations will
add event reconciliation with real GWS timestamped source signals,
quote-level execution modelling, transaction costs, out-of-sample
comparisons, and portfolio risk validation.

## Disable independently without touching scanner or MT5

```bash
docker compose --profile forward stop forward
```

Do not reboot the VPS or interfere with the other MT5 terminals to
manage this optional collector. `XAUBOT_SEND_DISCORD=0` should remain
unchanged until alerts are separately validated.
