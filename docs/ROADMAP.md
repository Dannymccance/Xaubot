# Xaubot research roadmap

## Release 0.1 - FOUNDATION ONLY
- Main GWS-like heuristic plus 200 deterministic and reproducible challenger configurations.
- UTC M1 CSV feed, completed-candle higher-timeframe analysis, optional AI advice.
- Broker-independent abstract-oz paper replay; optional GWS-primary Discord alerts.
- No live order capability, no claim of original GWS reconstruction fidelity.

## Release 0.2 - EVIDENCE QUALITY
- Ingest original Telegram IDs, edit history and provider/authorship metadata.
- Link distinct trade ideas, manage repeated layers and retroactive updates.
- Label signals by earliest provable original-publication visibility.
- Add FVG/OB/flip parameter variations derived from timestamped examples.
- Evaluate candidate precision, recall and timing versus original GWS events.

## Release 0.3 - EXECUTION-QUALITY PAPER ENGINE
- MT5 authenticated read-only quote collector (server-time to UTC normalisation).
- Actual broker min lot, tick value, tick size, commission, swaps, stop level checks.
- Tick-level replay, simultaneous paper portfolios, stop/TP event order.
- Risk-budget enforcement per trade idea across layers and portfolio-wide.
- News and session controls, confidence calibration, out-of-sample protocol.

## Release 0.4 - VALIDATION
- Walk-forward train/validation/test with no reuse of locked test sets.
- Baselines matched for direction, session, holding-time and trade count.
- Bootstrap by trading day, multiple-comparison adjustment across 200 models.
- AI-on vs AI-off tests, model drift and Discord alert usefulness.

## Live execution gate
No live MT5 order interface exists in the repository. Introduce one only after
independent backtesting, sufficient forward shadow observation, broker feasibility
checks, kill switch, audit logs and explicit human authorisation.
