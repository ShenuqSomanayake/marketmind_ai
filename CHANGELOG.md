# Changelog

## 0.7.0 — modern UI

### Changed
- New design system (`ui/style.py` + `.streamlit/config.toml`): deep-navy theme with a violet/teal accent, Inter typography, card-style metrics, rounded panels and a shared Plotly chart template.
- Branded sign-in screen with product pitch and feature highlights.
- Sidebar: logo, user chip, icon navigation menu (no radio circles), loaded-asset chip; developer toolbar hidden.
- Every page opens with an icon header and one-line purpose.
- **Overview is now a dashboard:** portfolio value and P&L, live and practice hit rates, alerts, quick-action buttons, recent calls with Correct/Incorrect/Pending badges, and the next 14 days.
- Practice: large green/grey/red call buttons.
- 149 tests (quick-action navigation test added).

## 0.6.0 — technical depth and chart patterns

### Added
- **Chart-pattern engine** (`patterns.py`): double top/bottom, head and shoulders, inverse H&S, ascending/descending/symmetrical triangles, support/resistance breakouts (volume-confirmed) and bullish/bearish RSI divergences. Swing points are only usable k bars after they form, and the scan walks forward bar by bar; a test verifies that truncating history never changes earlier detections.
- **Pattern track record**: hit rate after confirmation vs the asset's base rate for any bar, edge in points, a z-test (|z| ≥ 1.96) and "too few to judge" under 10 occurrences. Measured on up to 10 years of daily history.
- **Patterns & levels tab**: overlays, forming patterns with their confirmation trigger, recent patterns table, multi-touch support/resistance, Fibonacci retracements, swing points.
- **Technical readings**: ADX/DI, slow stochastic, OBV confirmation, 10-bar rate of change and Bollinger squeeze rank.
- Practice: optional **pattern hints**; every practice and live prediction records the patterns present at entry (migration v5).
- Report card: **patterns you read best and worst**, and whether you do better going with or against confirmed patterns.
- AI fact sheet and rules brief include ADX, stochastic, nearest levels and rule-detected patterns; prompts say patterns are detections, not forecasts.

### Fixed
- Chart legend no longer overlaps the subplot title; label-style metrics no longer show misleading ↑ arrows; backtest table headers are readable ("Total return", "CAGR").
- 148 tests (from 122). Requires Streamlit 1.67+.

## 0.5.0 — beta-ready

### Added
- **Practice mode:** instant-scored calls on random historical cut-offs, with blind mode (hidden ticker and dates, prices rebased to 100) and no look-ahead (verified by test). Results are stored as `mode='practice'`, excluded from live prediction stats, and selectable on the Report card (Live / Practice / Both).
- **Factual mode** (`MARKETMIND_FACTUAL_MODE=1`): "N of M rules met" instead of bullish/bearish labels, a descriptive-only AI prompt and headings, and the thesis review never says whether an asset is attractive. Server-wide, not user-switchable.
- **AI daily limit** (`MARKETMIND_AI_DAILY_LIMIT`): per-user quota with an automatic rules-based fallback.
- **Your data:** export everything as a ZIP of CSVs; password-confirmed, all-or-nothing restore (validated, including paper-ledger rules); permanent account deletion.
- Operator CLI: `backup` (online SQLite backup) and `reset-password` (temporary password, clears lockout).
- DB migration v4. 122 tests (from 100).

## 0.4.0 — "The investing journal that grades you"

### Added
- **Report card** page:
  - **Prediction report card:** hit rate vs a naive always-bullish baseline, optimism/pessimism bias, chasing after big rises (using the 20-bar return recorded when each prediction was made), agreement with the technical score, and short vs long horizons.
  - **Trading habits** from paper trades: win rate, average win vs loss, and disposition-effect detection.
  - **Thesis checker:** live status against user-set invalidation prices (Triggered / Near trigger within 5% / Review due / On track).
  - **AI thesis review:** Claude compares the user's own thesis with the computed facts, under the same number verification, with a rules fallback. The thesis text is treated as claims to check, never as instructions.
- Journal: price when written, plus lower and upper invalidation prices (editable).
- Overview: alerts for triggered and near-trigger theses.
- Predictions now record the 20-bar return and RSI at entry, for behavioural analysis.
- DB migration v3. 100 tests (from 79).

## 0.3.0

### Fixed
- Market intelligence "20-bar return" reported a price ratio (≈98%) instead of a return (≈−2%).
- Company health rejected negative net profit and equity, so loss-making companies couldn't be screened.
- RSI returned 100 for a flat series (now 50). RSI and ATR now use textbook SMA-seeded Wilder smoothing, verified against the StockCharts worked example.
- Volatility, Sharpe and CAGR always annualised with √252; now inferred from bar spacing (daily 252, weekly 52, monthly 12, intraday 252 × bars/day).
- `sample_nvda.csv` was a byte-identical copy of the synthetic demo file; removed.
- An uploaded CSV was silently labelled with whatever ticker sat in the text box (default "NVDA").
- 1h intervals with more than 2 years of history failed with an opaque provider error.
- SQLite connections were opened on every call and never closed.

### Security
- Admin access no longer goes to whoever registers a hard-coded username. Roles live in the database and are granted via `python -m marketmind.manage`.
- Login throttling (5 failures / 15 min), timing-safe unknown-user handling, 12-character minimum password, password change.
- Session user is re-validated on every request.

### Added
- **AI research brief** (Claude), grounded in an inspectable fact sheet, with automatic flagging of any number not in the facts and a labelled rules-based fallback.
- Backtest: buy-and-hold benchmark, out-of-sample split, slippage, CAGR, Sortino, exposure, win rate, trade list, configurable parameters.
- Portfolio: live prices, market value, unrealised P&L, per-currency weights, concentration warning; automatic correlation and relative performance.
- Paper trading: per-currency cash accounts, buy/sell validation, average-cost realised and unrealised P&L.
- Predictions: horizon and threshold, automatic objective scoring, per-view hit rate, small-sample warning.
- Journal: editable theses with required invalidation criteria; due reviews and upcoming events on Overview.
- Versioned DB migrations (0.2.0 databases upgrade in place).
- 79 tests (from 3), including AppTest coverage of every page; ruff lint/format; CI workflow.

### Removed
- Chart screenshot / OCR lab (it couldn't produce usable data), the unused Ichimoku and OBV calculations, and the "AI debate" page that relabelled rule output as analysts. Pages went from 16 to 9 (Market intelligence, Volatility, Company health and Calendar were merged into other pages).
- Code restructured from one 392-line `app.py` into a tested package.
