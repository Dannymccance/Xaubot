# Xaubot experimental 1:200 paper-margin backtest

**Purpose:** simulate maximum 200:1 leverage for the imported XAUUSD
historical paper strategies, without turning any existing MT5 terminal
into an execution engine or changing the forward candidate collector.

## Exact assumption

The paper account is denominated in USD. For every new hypothetical
position (expressed directly in **theoretical gold ounces**):

```text
theoretical_ounces = equity_USD * risk_fraction / abs(entry_USD_per_oz - stop_USD_per_oz)
notional_USD       = theoretical_ounces * entry_USD_per_oz
initial_margin_USD = notional_USD / 200
```

Reject a hypothetical entry if the required initial margin is greater
than the strategy's realised USD equity, then log `MARGIN_REJECT`.
There is at most one open position **per separate strategy account**,
so no two challengers share margin. Margin is reserved, not subtracted
from the initial cash equity; closing part of a position releases the
corresponding reservation. Paper P&L is still calculated from
`(exit_price - entry_price) × direction × theoretical_ounces × fraction`.
**200:1 means maximum allowed notional exposure, not automatic 200× P&L.**

Example for $1,000 initial equity, 0.5% risk ($5), $5 stop distance,
XAUUSD entry price $4,160:
- hypothetical position 1 ounce
- notional $4,160; simplified 1:200 required initial margin **$20.80**
- effective exposure **4.16× account equity**, not 200×
- $1 move in gold means about $1 theoretical P&L before further costs

## Retain old results then rerun with 1:200

The original `data/backtest.json` lacked broker leverage modelling.
Preserve it before overwriting the default leaderboard report:

```bash
cd /root/Xaubot
git pull --ff-only origin main
cp -n data/backtest.json data/backtest_before_margin_20261013.json
docker compose up -d --build
docker compose exec -T xaubot python -m xaubot backtest \
  --csv /app/data/xauusd_m1_baseline_20261013.csv \
  --leverage 200 \
  --equity 1000 \
  --risk 0.005 \
  --out /app/data/backtest.json
docker compose exec -T xaubot python -m xaubot report leaderboard \
  --data-dir /app/data
```

The frozen input CSV and its adjacent manifest must remain unchanged;
the paper replay records the SHA-256 feed audit. The market does not
need to be open for this historical research step.

Per-strategy report fields include:
`margin_rejected`, `peak_initial_margin_usd`,
`peak_margin_utilization_pct`, `peak_notional_usd`,
`peak_effective_leverage` and
`open_reserved_initial_margin_usd`. The backtest metadata records
the selected leverage and model limitations. `OPEN` and
`MARGIN_REJECT` events show entry notional and margin computations.

## What 1:200 DOES NOT imply

This is a **simplified maximum-leverage initial-margin test** only.
Actual broker XAUUSD lot contract size, minimum lot/step, volume limits,
variable leverage tiers, trade size, account currency, mark-to-market
free margin, intrabar margin calls, liquidation/stop-out threshold,
swap, financing, commissions, spread history, bid/ask tick sequence
and realistic fills have not been independently measured or modelled.
The initial margin ratio alone does not prevent real trading losses in
excess of margin, nor does it prove a strategy is feasible on a broker.

The broker's +120-minute UTC offset remains provisional in historical
data. An in-sample ranking over 201 configurations is *not*
out-of-sample evidence. Trading and Discord alerts remain disabled.
