# Xaubot Linux/Wine MT5 market-data bridge

This is the recommended method for **Ubuntu 24.04 with MT5 under Wine**, as
used by the `xaumt5` VNC `:2` installation.

**No Python MetaTrader5 wheel is needed under Wine. No order placement.**
The MQL5 Expert Advisor exports only closed XAUUSD M1 candles. A small
Python process on the Ubuntu host converts the broker server timestamps
to UTC and atomically publishes `/root/Xaubot/data/xauusd_m1.csv`.

## Two separate components

1. `mt5/XaubotM1Exporter.mq5` - read-only MQL5 Expert Advisor running
   inside MT5. It uses `CopyRates(_Symbol,PERIOD_M1,1,...)` so it **never
   intentionally reads MT5 position-zero forming candles**.
2. `python -m xaubot.wine_bridge` - host-side conversion process. It
   only parses the MQL5 CSV and writes the existing Xaubot scanner feed.

Broker timestamps are **not assumed to be UTC**. The host bridge
requires `--broker-utc-offset-minutes`, which must be verified for the
selected demo broker and date. Fixed offsets do not cover historical
periods spanning broker daylight-saving-time transitions. Archive
separate periods and use the correct offsets before running historical
comparisons. Wrong offsets can create false candidate timing and leakage.

## Part A: Place the exporter in MetaTrader through SSH

The terminal must already be installed under `/home/xaumt5/.wine-xaubot`,
connected to a broker and displaying a chart of `XAUUSD`. The MT5 file
path may vary, so **discover it** rather than assuming a hard-coded hash.

In a normal SSH terminal as `root`, run:

```bash
# Source checkout (clone once if missing)
cd /root
test -d Xaubot/.git || git clone https://github.com/Dannymccance/Xaubot.git
cd Xaubot
git pull --ff-only origin main

# Find the dedicated xaumt5 terminal's Experts directory
find /home/xaumt5/.wine-xaubot -type d -path '*/MQL5/Experts' -print
```

If there is **exactly one correct** Experts directory, place the MQL5
source file in it with owner `xaumt5`. You may use the `find` result
to form the path rather than pasting a long Windows directory name.
For a single matching directory, the following automatic method works:

```bash
EXPERTS=$(find /home/xaumt5/.wine-xaubot -type d -path '*/MQL5/Experts' -print -quit)
test -n "$EXPERTS" || { echo "No MT5 Experts directory found"; exit 1; }
curl -fL \
  https://raw.githubusercontent.com/Dannymccance/Xaubot/main/mt5/XaubotM1Exporter.mq5 \
  -o "$EXPERTS/XaubotM1Exporter.mq5"
chown xaumt5:xaumt5 "$EXPERTS/XaubotM1Exporter.mq5"
```

If multiple terminal directories appear, **stop and identify the correct
terminal via MT5 File > Open Data Folder** before copying. Never write
into an existing unrelated MT5 installation.

The source has not been automatically compiled by GitHub Actions. An
MT5 **MetaEditor compilation** is required on the Wine terminal.

## Part B: Compile and attach in the VNC desktop

1. In your Xaubot MT5 terminal on VNC display `:2`, press **F4** to
   open MetaEditor (or Tools > MetaQuotes Language Editor).
2. Open `XaubotM1Exporter.mq5` under the Experts directory and press
   **F7** to compile. Inspect the compiler's error and warning counts.
3. Return to MT5. Open `XAUUSD` **M1** chart. In Navigator > Expert
   Advisors, refresh, then drag `XaubotM1Exporter` onto the chart.
4. Verify `InpExpectedSymbol=XAUUSD` (replace only if the broker uses a
   different **exact** gold symbol).
5. Leave **Algo Trading disabled**. The EA contains no trading or account
   actions. Confirm its Experts or Journal tab reports "MARKET DATA ONLY"
   and periodically "exported ... closed M1 bars".

The exporter first exports whatever completed M1 history the terminal
has loaded, up to `InpHistoryBars=30000`. If history is incomplete,
MT5 may need time to download older candles. The exporter publishes its
CSV to `TERMINAL_COMMONDATA_PATH\\Files`, which is a folder inside
this isolated Wine prefix.

## Part C: Discover the exported file (SSH)

Once the exporter logs a successful publish:

```bash
find /home/xaumt5/.wine-xaubot -type f -name xaubot_xauusd_m1_server.csv -print
```

One path should appear under `.../Terminal/Common/Files/`. If there
is no output, the EA is not publishing yet. Check the MT5 Experts log.

The source CSV has **broker server time** in an epoch-like number.
**Do not rename or directly copy it** to Xaubot's normal UTC CSV path.

## Part D: Run the Ubuntu host bridge

Install Python venv tools once, as root:

```bash
apt install -y python3-venv
cd /root/Xaubot
python3 -m venv .venv
.venv/bin/python -m pip install -e .
mkdir -p data
```

For the next command, substitute the actual path returned by `find`.
Replace the UTC offset example with the broker server's **verified**
UTC offset for the dates represented in the exported history:

```bash
/root/Xaubot/.venv/bin/python -m xaubot.wine_bridge \
  --source "/ACTUAL/PATH/FROM/FIND/xaubot_xauusd_m1_server.csv" \
  --symbol XAUUSD \
  --broker-utc-offset-minutes 0 \
  --out /root/Xaubot/data/xauusd_m1.csv
```

This is a one-off test; check `data/xauusd_m1.csv` and the adjacent
`data/xauusd_m1.manifest.json`. You can add `--watch --poll 30`
when verified; a systemd service can be configured once source,
timestamps and permissions are confirmed.

**No broker account passwords, Discord tokens or AI credentials belong
in the exporter or bridge.** Because the Linux bridge needs access to
the private Wine directory and `/root/Xaubot/data`, the straightforward
initial operation is from an SSH root shell; the bridge itself runs no
shell commands or MT5 trading APIs. We can make a least-privilege
systemd unit with an explicit read-only ACL once the actual paths
are known.

## Part E: Start Xaubot scanner

After the CSV is populated and timestamps are verified:

```bash
cd /root/Xaubot
test -f .env || cp .env.example .env
docker compose up -d --build
docker compose exec xaubot python -m xaubot report status --data-dir /app/data
```

The `XAUBOT_SEND_DISCORD` default is `0`; no Discord or AI keys
are required. The scanner reads only the **UTC-normalized** feed.

## Boundaries / verification

- No real-money execution, minimum-lot validation or order routing.
- The MQL5 code compiles only after the terminal-side F7 step; GitHub
  CI can test Python parsing and code contracts, **not MetaEditor**.
- MT5 chart candles are not true bid/ask data. Backtest results use
  synthetic spreads unless separate quote history is supplied.
- If you change symbols, exporter implementation, historical values or
  broker UTC offsets, archive the existing feed and manifest. The
  bridge rejects unannounced mixing and historical revisions.
- MT5 under Wine 9 previously showed an unsupported version warning.
  This should be resolved via a carefully staged Wine upgrade that
  does not interrupt your existing trading terminals; a currently
  visible chart alone does not prove unattended stability.

MetaQuotes APIs: [CopyRates](https://www.mql5.com/en/docs/series/copyrates),
[FileOpen](https://www.mql5.com/en/docs/files/fileopen),
[FileMove](https://www.mql5.com/en/docs/files/filemove).
