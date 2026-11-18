# MarketMind AI architecture — target design

## Current release (0.3.0)
A Streamlit app over a UI-independent, tested Python package. `app.py` only handles sign-in and navigation; each page in `marketmind/ui/` renders results from pure domain modules.

### Data flow
1. Sign-in against SQLite (`auth.py`): PBKDF2 hashes, throttling, DB-stored roles. Connections are opened per unit of work (`db.connect()`), and schema migrations run on open.
2. Data comes from a CSV upload or from `yfinance` (adjusted prices, cached for 15 min). `normalize_ohlcv` validates the schema, dates, numeric fields, duplicates and OHLC consistency.
3. `engine.add_indicators` computes EMA/SMA, Wilder RSI/ATR, MACD and Bollinger. `engine.analyse` scores a transparent rule list and infers the annualisation factor from bar spacing.
4. `backtest.run_backtest` applies signals on the next bar, charges fee and slippage on every position change, and reports strategy against buy-and-hold for full, in-sample and out-of-sample segments.
5. `research.build_facts` turns the outputs into a JSON fact sheet. `research.llm_brief` sends only that to Claude, then flags any number in the reply that isn't in the facts.
6. `portfolio` values holdings and replays paper trades through a cash/position-checked ledger. `predictions.evaluate` scores views from closes after the `as_of` bar.

## Production target

```text
Browser (Next.js / TypeScript)
  ├── Supabase Auth (identity, sessions, MFA)
  ├── Supabase Postgres (profiles, portfolios, trades, watchlists, reports)
  ├── Object storage (user-uploaded chart images / CSV, private buckets)
  └── FastAPI service
        ├── Ingestion adapters (CSV, licensed market-data vendors)
        ├── Validation / canonical OHLCV schema
        ├── Deterministic indicator engine
        ├── Pattern recognition (rule-based first, ML later)
        ├── Backtesting and risk engine
        ├── AI explanation adapter (only receives structured outputs)
        └── Scheduled data refresh / alert worker
```

## Suggested database entities
- `profiles`: auth user id, preferences, base currency.
- `portfolios`: owner, name, base currency.
- `transactions`: portfolio, symbol, side, quantity, price, fees, timestamp, source.
- `watchlists` and `watchlist_items`.
- `market_bars`: symbol, venue, interval, timestamp, OHLCV, provider, adjusted flag.
- `analysis_runs`: owner, symbol, interval, dataset fingerprint, engine version, score, evidence JSON, risk JSON, created timestamp.
- `uploaded_files`: owner, private storage path, checksum, MIME type, ingestion status.
- `alerts`: owner, symbol, condition JSON, enabled state.

Every user-owned table must enforce row-level security. Secrets and provider API keys must stay server-side. Public deployment requires security review, backups, audit logging, rate limits, data licensing review and persistent managed storage.

## Analysis design principles
- Indicator calculations are deterministic and unit-tested.
- Signals are not probabilities unless calibrated on held-out data and shown with calibration diagnostics.
- Every report includes dataset provider, timestamp, interval, missing-data warnings and engine version.
- Avoid look-ahead bias: signals formed on a bar are executed no earlier than the next bar in backtests.
- Include fees, slippage, corporate actions, FX, delisted assets and survivorship bias as the backtest matures.
- Image recognition must not silently convert chart pixels into exact prices. OCR and pixel-derived estimates are clearly labelled and require user confirmation.
- AI explains structured analysis; it does not fabricate quotes, indicators, company news or earnings facts.
