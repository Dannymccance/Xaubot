# Xaubot automatic strategy-discovery laboratory (paper only)

This research feature implements **120 Order Block + 80 FVG point-in-time
variations**, one new backtested variation per UTC day after explicit setup.
It keeps the original 201 Xaubot strategies, all DKCapital installations,
MT5 terminals, bridge, scanner and raw historical files untouched.

**No real trades, broker order API, auto-promoted live strategies or
Discord signal execution.** A qualified candidate can only be added to
the independently guarded forward-only **signal observation journal**
after the existing broker UTC time gate is manually cleared. That journal
does not track realistic broker fills or live P&L.

## 1. Why more MT5 history is necessary

30,000 M1 bars cover only about a month of gold trading. With 200
new challengers this is far too little for reliable selection.

The **existing XaubotM1Exporter.mq5** is a 30k rolling export.
**Do not increase its history count to 300,000 or rename its source file
while the current live Wine bridge is running.** The bridge forbids
implicit backfilling and changing the existing feed can cause errors.

Instead, `mt5/XaubotHistorySnapshot.mq5` is a completely separate,
read-only, one-shot **Script**, not an EA:

1. On the **Xaubot-owned MetaQuotes-Demo XAUUSD terminal only**
   (dedicated Wine user `xaumt5`), open *File -> Open Data Folder* and
   copy this source to `MQL5/Scripts`. Do not install into DKCapital
   Account 1/2 or change its EAs.
2. Compile in that terminal's MetaEditor and confirm 0 errors. Adjust
   MT5 **Tools -> Options -> Charts -> Max. bars in chart** if needed,
   ensure older M1 history is locally downloaded, then run this one-shot
   script on XAUUSD.
3. Default `InpRequestedBars=500000` and `InpChunkBars=10000`. It
   exports **completed M1 chart candles only**, in chronological chunks,
   into the *separate* FILE_COMMON
   `xaubot_history_xauusd_m1_server.csv`. It excludes forming bar 0.
4. Review the MT5 *Experts* output for the actual **written** bar count
   and oldest/newest broker timestamp. The requested 500,000 bars are
   NOT guaranteed: terminal chart limits, broker retention, available
   download and local cache can reduce it. An approximate 6-12 month
   target may require substantially more than 500,000 weekday bars.

The immutable raw history must be preserved. No DKCapital terminal
service is touched or restarted.

## 2. Historical broker time is not automatically UTC

The broker-server timestamps in the raw CSV are not independently UTC
verified. Xaubot's current `120` minute offset is provisional. Over
6-12 months, broker seasonal UTC offset transitions may invalidate a
single fixed conversion.

`python -m xaubot.history` imports the raw snapshot into a **separate**
UTC CSV only when supplied with an explicit broker-wall-clock
offset schedule. This is a deliberate validation gate; the system
cannot guess dates or DST practices.

A *schema example*, not verified real broker transition dates:

```json
{
  "segments": [
    {"from_server": "2026-01-01T00:00:00",
     "until_server": "2026-04-01T00:00:00",
     "offset_minutes": 120},
    {"from_server": "2026-04-01T00:00:00",
     "until_server": "2027-01-01T00:00:00",
     "offset_minutes": 180}
  ]
}
```

**Never copy the example offsets/dates as fact.** Verify using that
broker's actual server clock and independent historical timestamps,
accounting for DST. The segments must cover every exported candle
unambiguously and be contiguous without overlap. If unsure, **leave
the source CSV raw and postpone conversion**. Do not fill historical
market gaps with invented prices.

After verification, run from the dedicated Xaubot VPS:

```bash
cd /root/Xaubot
/root/Xaubot/.venv/bin/python -m xaubot.history \
  --raw /home/xaumt5/.wine-xaubot/drive_c/users/xaumt5/AppData/Roaming/MetaQuotes/Terminal/Common/Files/xaubot_history_xauusd_m1_server.csv \
  --out /root/Xaubot/data/xauusd_m1_archive_20261014.csv \
  --symbol XAUUSD \
  --offset-schedule /root/Xaubot/data/broker_server_offsets.json \
  --operator-attests-offsets
```

The importer rejects unknown offset periods, invalid candles, duplicate
UTC timestamps, future candles and output collisions. It stores source
SHA-256, offset schedule SHA-256, actual bar count and explicit
operator-assertion provenance beside the CSV. Even an operator
attestation does not independently prove every historical timestamp
is accurate. **The ongoing live 30k-bar bridge is not changed.**

## 3. Build one immutable OB/FVG signal candidate cache

After the new archive passes its provenance/time audit, choose its
immutable filename and use a separate experiment ledger. Sample:

```bash
cd /root/Xaubot
cp -n deploy/optimizer_config.example.json data/optimizer_config.json
```

In `data/optimizer_config.json`, update `dataset` to
`/app/data/xauusd_m1_archive_20261014.csv` and confirm it matches the
actual archive filename. Keep other paths new for that dataset epoch.
The GBP/USD reference `1.325`, 100 oz/lot, 0.01 lot min/step and
Vantage-like execution-cost model are research assumptions, **not
broker-verified historical spread, account specification or FX**.
Set `broker_offset_attested` to `true` **only after independent
verification of all applicable broker time segments**.

Compute the candidate tape once (can be CPU-heavy on long datasets):

```bash
docker compose --profile optimizer run --rm --no-deps optimizer \
  python -m xaubot.optimizer cache \
  --dataset /app/data/xauusd_m1_archive_20261014.csv \
  --out /app/data/ob_fvg_candidate_tape.json
```

This never computes future-bar signals or looks at trade outcomes. It
stores the two frozen original baselines:
`ob_continuation__c1__t1` and
`fvg_continuation__c1__t2`. The tape fingerprints the immutable
dataset and the engine code; it is never rewritten silently.
Archive both tape and original feed when moving to a newer snapshot.

## 4. Run exactly one new challenger per UTC day

```bash
docker compose --profile optimizer run --rm --no-deps optimizer
```

The command uses `/app/data/optimizer_config.json`, without any
Discord or broker credentials. It handles only one new variation,
even if repeated on the same UTC day. A lock prevents concurrent
evaluations. The first challenger is a replay of the underlying OB
baseline; second is the corresponding FVG baseline, then
interleaved parameter variations.

Each variation genuinely changes signal admission with a deterministic
combination of:

- fixed **UTC-labelled session** (all/London proxy/New York proxy/overlap
  proxy/Asia proxy);
- M5 directional body strength, two-bar momentum, or structural breakout;
- completed-M5 candle minimum price range in USD.

These are **hypothesis filters**, not new broker-provided stops. Entries,
three-leg TP/SL, Friday 0.01 x 3, £75 group and £150 GBP portfolio
risk, 1:200 initial margin and generated stop/TP provenance remain
those of the DKCapital-inspired paper engine.

Every day's variation is tested twice: assumed $0.40 spread / $0.05
slippage and stress $0.80 spread / $0.10 slippage, against a fixed
chronological first 75% development section of the history archive.
The last 25% is not consumed by the optimizer, but the original
201-strategy models have already been examined on our old September/
October dataset. **Do not claim those previously seen dates are truly
unseen holdout data.**

Daily results go to `data/optimizer_lab.json`: candidate definition,
input SHA, simulator/code fingerprints, closed-group initial-risk
R expectancy, GBP P&L, realised weekly P&L, biggest-week exclusion,
drawdown, lot/risk/margin rejections, ranked results and evidence status.

A shortlisting status requires **at least 180 calendar days** of
training history, independently operator-checked historical offsets,
30 closed groups, at least 8 exiting weeks, positive standard and
stressed initial-risk R expectancy, no more than 15% simulated
drawdown, positive stressed P&L without the single best week,
and positive results in >=60% of exiting weeks.

If these are not met, Xaubot records a provisional diagnostic,
**not a ready-to-trade edge**. One result/day means 200 variants take
200 days. No optimisation step silently changes already-tested
parameters. Comparing 200 variants still incurs multiple-testing
selection bias, and all candidates require independent forward
observations and real-cost verification.

Inspect the ranking:

```bash
docker compose --profile optimizer run --rm --no-deps optimizer \
  python -m xaubot.optimizer status \
  --state /app/data/optimizer_lab.json
```

If a candidate passes the offline evidence gates, the existing opt-in,
broker-clock-gated Xaubot forward journal may observe up to three
shortlisted candidates in fresh M5 candles. It **never** retroactively
inserts historical candidate signals, updates DKCapital, assumes fills,
or sends trades.

## 5. Optional daily systemd timer (disabled by default)

Once the archive, cache and optimizer config have been separately
prepared, the VPS can run one research variant per day without an open
SSH session. Units are staged in `deploy/` but **not installed or
activated by Git pull or Docker Compose**:

```bash
sudo cp deploy/xaubot-optimizer.service /etc/systemd/system/
sudo cp deploy/xaubot-optimizer.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xaubot-optimizer.timer
systemctl list-timers xaubot-optimizer.timer
```

The job runs around 03:00 UTC daily with up to 10 minutes of
randomised delay; only 1 candidate is tested per UTC day regardless
of repeated invocations. It has no network interface, drops
capabilities and receives no DKCapital credentials. The existing
MT5 exporter, Wine bridge, scanner and DKCapital services are
never restarted by this timer.

To stop ONLY the optimizer schedule:

```bash
sudo systemctl disable --now xaubot-optimizer.timer
```

Do not enable full VPS upgrades, reboot or unrelated Docker cleanup
as part of this procedure. Source market snapshots do not update
automatically; new datasets must create a **new experiment epoch**
rather than corrupting comparability with the original.
