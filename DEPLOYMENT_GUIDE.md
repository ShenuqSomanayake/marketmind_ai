# MarketMind AI 0.5.0 — Deployment guide

## Important before publishing

This release is a **private-use prototype**, not a production multi-user financial service. It uses a local SQLite database (`marketmind.db`). Accounts are throttled and admin roles are DB-stored, but there is no MFA, email verification or password reset by email. Streamlit Community Cloud filesystems are not a durable database: app restarts/redeployments can lose local SQLite data. Do not use this release to store sensitive customer portfolios or expose the admin centre publicly.

For a public launch, first migrate authentication and persistence to Supabase Auth + PostgreSQL (or an equivalent managed service), enable MFA for administrators, add audit logging, backups, rate limits and security review. Do not put API keys in source code or GitHub.

## Deploy the current prototype to Streamlit Community Cloud (testing only)

1. Extract this ZIP on your computer.
2. Create a **private** GitHub repository named `marketmind-ai`.
3. Upload the contents of the `marketmind_ai` folder to the repository root. Do not upload `.venv`, `marketmind.db`, passwords, or secrets.
4. Visit https://share.streamlit.io/ and sign in with GitHub.
5. Create an app and select your repository, branch `main`, and main file `app.py`.
6. Deploy. Streamlit installs packages from `requirements.txt`.
7. Test with the included synthetic CSV before attempting external market data.
8. To grant yourself admin, run `python -m marketmind.manage grant-admin <username>` on the host. Streamlit Community Cloud has no shell, so the Admin page is unavailable there by design.

### Local Windows / Git Bash setup

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

PowerShell activation instead:

```powershell
.venv\Scripts\Activate.ps1
```

## Beta settings (anyone other than you using it)

Set `MARKETMIND_FACTUAL_MODE=1` and `MARKETMIND_AI_DAILY_LIMIT=10` (or similar) as environment variables or Streamlit secrets. Schedule `python -m marketmind.manage backup` daily and copy the `backups/` folder off the machine.

## Market data

The optional `yfinance` integration is a community connector, not an official Yahoo Finance API or a commercial redistribution licence. Coverage, latency and availability vary. Do not assume it provides licensed real-time exchange data. For a commercial service, evaluate and contract with licensed providers for US, ASX and CSE data, including display, derived-data and redistribution rights.

## Secrets

The `.env.example` file is a reference only. Never commit real keys. Configure secrets using the hosting provider's secrets manager. `ANTHROPIC_API_KEY` is optional; without it AI briefs fall back to the rules-based summary. On Streamlit Cloud, set it under *App settings → Secrets* as a top-level key; Streamlit exposes top-level secrets as environment variables.

## Verification

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Expected: 122 tests pass.
