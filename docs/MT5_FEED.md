# Read-only MetaTrader 5 price bridge

The research scanner runs in its standard Python/Docker environment. The
`xaubot.mt5_export` collector runs **next to the MetaTrader 5 terminal** in a
separate Python environment. These are deliberately separate: installing the
MetaTrader5 Python package in a generic Linux Docker image does not create a
running terminal or a logged-in broker connection.

## Host prerequisites

- An installed and running MT5 terminal with an account **already logged in by
  the operator**. A demo account is preferable for the research phase.
- Python compatible with the MetaTrader5 package on that host (commonly Windows).
- The exact broker symbol, e.g. `XAUUSD`, `XAUUSDm`, etc.
- In MT5 settings, sufficient **Max. bars in chart** for the historical window.
- A clock synchronised to UTC. The exporter uses UTC epoch seconds supplied by
  MetaTrader5 and never assumes that broker-server time is your local timezone.
- A writeable folder from which the scanner will receive `xauusd_m1.csv`.

## Installation on the MT5 terminal host

Run these steps in a PowerShell terminal from a checkout of the same GitHub repo
next to the MT5 terminal. This does **not** need the Discord bot token or OpenAI.

```powershell
py -m pip install -e ".[mt5]"
py -m xaubot.mt5_export --symbol XAUUSD --out data/xauusd_m1.csv --once
```

Use the exact broker symbol, not necessarily `XAUUSD`. To poll every 30 seconds:

```powershell
py -m xaubot.mt5_export --symbol XAUUSD --out data/xauusd_m1.csv --poll 30
```

If auto-discovery selects the wrong terminal, pass `--terminal-path` with the
full MT5 executable path. The collector only calls terminal initialisation,
symbol selection, M1 historical price copying and shutdown. It contains
**no** broker login function, trading order API, modification or closing API.

The exporter requests MT5 `TIMEFRAME_M1` starting at **position 1**, not
position 0. MT5 documents that position 0 is the forming bar; its use would
introduce lookahead and false completed-candle signals.

The published files:
- `xauusd_m1.csv`: ordered, validated, fully closed UTC M1 OHLC.
- `xauusd_m1.manifest.json`: source, exact symbol, candle count and last
  completed candle timestamps (no trading account identifiers).

Writes are atomic. Existing completed bars cannot be revised silently.
If broker-provided historical values change, the exporter refuses the
rewriting and needs an explicit offline review. It never synthesizes gaps.
Missing M1 bars may be caused by illiquid periods or disconnections.

## Linux VPS and Windows MT5 terminal separation

For a Linux VPS hosting Xaubot Docker and a separate Windows MT5 terminal:
securely **copy the completed CSV and manifest** from the terminal host to the
VPS, into the directory mounted as `./data:/app/data` by Compose. Use a
transport you control, such as SSH/SFTP over a protected network. The
market-data bridge deliberately does not run an unauthenticated HTTP server.
An operator can also use a shared filesystem if both processes access it.

Do not write directly to the scanner's CSV with a non-atomic transfer.
Transfer to a temporary name in the same filesystem, then rename to the
final name. Sync both files. Do not copy the MT5 terminal's data directory,
saved passwords or trading history account files.

A Windows VPS running MT5 and Python could instead run both the exporter and
the scanner directly (Docker is optional). For Linux Wine-based MT5 setups,
the terminal-side exporter needs its own tested compatible environment.
No claim is made that MT5 works inside this Docker image.

## Limitations

MT5 candle OHLC is *not* a reliable substitute for true bid/ask OHLC.
The paper simulator uses a stated synthetic spread unless a later independent
broker bid/ask quote collector is supplied. This exporter does not collect
tick-level quotes, commissions, market depth, broker min lots or trade results.
No alerts are sent merely because the exporter is running. The scanner needs
sufficient closed-bar history and a fresh feed before its opt-in outbound
Discord notifications can run.

Official API references:
- https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py
