# DKCapital V2 research constraints applied to all 201 Xaubot strategies

This is an **independent experimental simulator**. The original DKCapital
ruleset is [DKCAPITAL_RULESET_V2.md](https://github.com/Dannymccance/DKCAPITAL/blob/main/docs/DKCAPITAL_RULESET_V2.md).
DKCapital's EA is not altered or restarted. Xaubot's 201 models still
generate their own XAUUSD candidate entries, stops and targets.

**Critical distinction:** Xaubot-generated stops and targets are explicitly
labelled `XAUBOT_GENERATED_HYPOTHESIS`. They are NOT stops supplied by
GWS VIP or Elite Portfolios, and therefore they do NOT fulfil the real
DKCapital V2 provider-only stop rule. None of these simulated events may
be fed into the DKCapital live/demo execution system.

## Confirmed constraints translated into research modelling

- Each strategy receives an **independent £1,000 GBP paper account**.
  Do not sum 201 portfolios as if they shared one broker account.
- Size from each strategy's *realised GBP balance*:
  `floor(balance_GBP / 100) × 0.01 lots`. Before entering, reduce the
  proposed total volume as needed to satisfy stop-risk and margin constraints.
  Require all three legally sized TP legs or reject the idea.
- Assign TP1 / TP2 / TP3 separate paper lots, as close as possible to
  30% / 30% / 40% after broker step rounding, without exceeding the allowed
  total. Example: £1,000 = `0.03 / 0.03 / 0.04` on 0.01 lot steps.
- On **Friday by Europe/Isle_of_Man time**, cap entry at exactly
  `0.01 / 0.01 / 0.01` if normal permitted lots and account/risk/margin
  allow. Do not inflate underfunded accounts up to Friday minimum.
- Planned gross stop-loss exposure per independent signal group <= **£75**,
  and gross planned exposure across the simultaneously open groups on
  that strategy account <= **£150**. Includes all three active legs.
  Never net opposing side risks; additional layers are not simulated.
- Recalculate budget after every modelled TP/SL. Following *simulated*
  TP1 fill, move TP2/TP3 paper stops to their own synthetic entry price,
  never widening protection. This is **not broker-confirmed TP1**.
- The simulator never closes based solely on Friday, market close, a
  missed feed or a change of date. Paper legs close on conservative
  simulated price crossings. Provider exit commands are NOT implemented
  because these research strategies are not provider signals.
- Margin requires `XAUUSD USD/oz × contract ounces/lot × lots ÷ 200`,
  then ÷ USD-per-GBP, summed over the portfolio. It does not automatically
  give 200× profit. Unknown broker tiered margins, unrealised equity,
  liquidations and financing are explicitly excluded.
- Estimated planned risk uses USD price distance to the generated SL,
  converts at an explicitly supplied reference USD-per-GBP rate, then
  includes `0.05 USD/oz` adverse slippage and `£1` per leg cost padding.
  These cushions are research assumptions, not verified broker fees.

## Required broker / currency assumptions

The DKCapital V2 ruleset calls for broker-native symbol details and
fresh USD/GBP conversion. Xaubot's Wine market feed currently exports
only OHLC, not broker contract specification or historical FX rates.

**Do not silently substitute invented historical values.** Before
interpreting a backtest, verify the Xaubot demo account symbol's
`SYMBOL_TRADE_CONTRACT_SIZE`, `SYMBOL_VOLUME_MIN`,
`SYMBOL_VOLUME_STEP`, and the USD per GBP exchange rate for the
intended modelling window. This prototype requires an explicit FX
reference rate and broker lot assumptions at the CLI. A single constant
FX conversion over the September-October historical window is a
simplification, **not validated historical GBP P&L**.

To see the interface, run `python -m xaubot backtest --help`.

## Safe independent replay

The original September-October paper leaderboard remains saved as
`data/backtest.json`; the new mode writes a separate file, and the
forward journal is unchanged. From VPS root SSH:

```bash
cd /root/Xaubot
git pull --ff-only origin main
docker compose up -d --build
docker compose exec -T xaubot python -m xaubot backtest \
  --risk-model dkcapital \
  --csv /app/data/xauusd_m1_baseline_20261013.csv \
  --leverage 200 \
  --equity 1000 \
  --usd-per-gbp <VERIFIED_OR_EXPLICITLY_HYPOTHETICAL_USD_PER_GBP> \
  --contract-oz-per-lot <CONFIRMED_BROKER_CONTRACT_SIZE> \
  --lot-min <CONFIRMED_BROKER_MIN_LOT> \
  --lot-step <CONFIRMED_BROKER_LOT_STEP> \
  --out /app/data/backtest_dkcapital_200x.json
```

Replace the angle-bracket values with actual numeric inputs; the block
above is a **template**, not directly executable. Do not paste broker
credentials or account logins into chat.

A run includes `metadata.feed_audit`, SHA-256 and a record of each
FX/contract assumption. Compare only after the replay completes:

```bash
docker compose exec -T xaubot python -m xaubot report leaderboard \
  --data-dir /app/data \
  --backtest-file /app/data/backtest_dkcapital_200x.json
```

The old `backtest.json` is preserved. The `--risk-model legacy`
option remains available for reproduction of pre-DKCapital experiments.

## Research limitations, not yet authorised for trading

- This is synthetic **three-leg paper simulation**, not three real
  MT5 positions with broker-native SL/TP tickets. No market or stop
  order placement and no connection to running DKCapital terminals.
- Assumed paper TP1 is not MT5 broker-confirmed. Ambiguous M1 candles
  settle with stop first. Adverse gap-open stop prices are modelled,
  but the true intrabar bid/ask and commissions are unavailable.
- Static USD/GBP conversion, simplified 1:200 initial margin, no
  broker margin tiering, lot maximum, price-dependent FX, maintenance
  margin calls or stop-out, no real-life broker rejection/partial fills.
- DKCapital V2's provider-directed close/partial close, editing,
  locking, real-broker fill reconciliation and exact provider SL
  cannot be reproduced from these purely Xaubot-generated ideas.
- Agreed £75 / £150 exposure ceilings apply to these **separate**
  £1,000 GBP paper accounts only; scale-up to other balances is not
  approved. Proposed DKcapital layering/re-entry policies remain off.
- The broker UTC+2 timestamp offset of the imported 30,000 XAUUSD bars
  is still provisional. Historical 201-way selection is in-sample,
  not proof of an edge. Discord and execution must stay disabled.

See [DKCapital V2](https://github.com/Dannymccance/DKCAPITAL/blob/main/docs/DKCAPITAL_RULESET_V2.md)
for original operational rules and unresolved approvals.
