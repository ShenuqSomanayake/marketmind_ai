# MarketMind AI — Product specification

## Product vision

An integrated investment intelligence workspace combining market analysis, AI-assisted research and quantitative strategy research. The product must distinguish measured facts, deterministic calculations, model-generated interpretation and forecasts.

## Included in 0.5.0

- Practice mode with blind rounds and instant scoring
- Factual mode and per-user AI daily limit for public deployments
- User data export/restore, account deletion, operator backup and password reset

- Report card: prediction biases vs baseline, trading habits (disposition effect), thesis trigger checks, AI thesis review

- Local accounts: PBKDF2 hashing, login throttling, DB-stored roles, admin CLI, password change
- OHLCV CSV import/validation; `yfinance` retrieval with ticker validation and caching
- EMA, SMA, Wilder RSI/ATR, MACD, Bollinger Bands, volume; frequency-aware annualisation
- Transparent rule-table technical score; unusual-activity flags; candle heuristics
- Fundamentals ratio screen that supports losses and negative equity
- AI research brief (Claude) grounded in an inspectable fact sheet, with number verification and a rules fallback
- Backtest with buy-and-hold benchmark, out-of-sample split, fees and slippage, full metric set and trade list
- Holdings with live P&L and weights; watchlist; correlation and relative performance
- Cash- and position-enforced paper trading with realised/unrealised P&L
- Predictions scored automatically and objectively
- Thesis journal with invalidation criteria and review reminders; personal event calendar
- Role-gated admin overview

## Not implemented / future production work

- Licensed exchange-wide live feeds for US, ASX and CSE
- Automated market-wide heatmaps, order-book depth or options flow
- Reliable chart-image-to-OHLC reconstruction
- Autonomous or self-training AI models
- Calibrated predictive probabilities
- Settlement, order types and order-book matching in paper trading
- FX conversion across currencies
- Broker connectivity or live order execution
- Automated news, filings and economic calendar ingestion
- Production multi-user authentication, persistent hosted database and secure role management
- Commercial billing, subscription entitlements and customer management
- Mobile-native application

## Product principles

1. Every market observation should have a provider and timestamp.
2. Stale, missing or inconsistent data must be visibly flagged.
3. A technical score is not a probability of profit.
4. Predictions must be timestamped before outcomes are known.
5. Strategy evaluation must include realistic costs and out-of-sample validation.
6. No automatic model promotion without review and validation.
7. No live trading without explicit user authorisation and broker-specific controls.
