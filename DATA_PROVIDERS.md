# Market data integration plan

## Prototype connector

The current optional connector uses the community `yfinance` package for historical data retrieval. It is not an official Yahoo Finance API, does not guarantee real-time quotes, and should not be assumed to permit commercial redistribution.

## Production provider requirements

Evaluate providers separately for:

- US equities and ETFs
- Australian Securities Exchange (ASX)
- Colombo Stock Exchange (CSE)
- FX rates for AUD/USD/LKR portfolio reporting
- Corporate actions and adjusted historical prices
- Fundamentals, company filings and earnings calendars
- News and macroeconomic events

For each provider, document exchange coverage, entitlement requirements, timestamp/latency, historical depth, rate limits, uptime, correction policy, redistribution rights and cost. Prefer official exchange or appropriately licensed vendors. Do not label data as live unless the contract and feed actually support real-time display.

## Canonical OHLCV schema

`timestamp, symbol, exchange, currency, open, high, low, close, volume, adjusted_close, provider, data_status`

All timestamps should be timezone-aware and normalised internally. Preserve source metadata and avoid silently mixing adjusted and unadjusted prices.
