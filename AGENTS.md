# AGENTS.md

## Runtime And Commands
- This repo targets Python 3.13 (`.python-version`, `pyproject.toml`) and uses `uv`; install with `uv sync`.
- Run the Streamlit app with `uv run streamlit run app.py`.
- Run the non-UI calculator demo with `uv run hello.py`.
- Run the Dr. Klein API example with `uv run drklein_example.py`; it performs live network calls to `https://www.drklein.de/rest-api/tav/angebot`.
- Docker runs the Streamlit app on port 8501: `docker build -t loancalc .`, `docker run --rm -p 8501:8501 loancalc`, or `docker compose up -d --build`.

## Verification
- No test, lint, typecheck, formatter, CI, or task-runner config is currently present.
- Use `uv run python -m py_compile app.py loan_calculator.py drklein_api.py drklein_example.py hello.py` as the quickest local syntax/import sanity check.
- Avoid treating `drklein_example.py` as an offline verification step because it calls the external Dr. Klein API.

## Code Map
- `app.py` is the Streamlit entrypoint and owns UI state, YAML import/export, scenario forking, charts, and optional interest-rate fetching.
- `loan_calculator.py` contains the core `LoanCalculator` and `LoanPortfolio` logic; monetary calculations use `Decimal` internally and return `polars.DataFrame` schedules.
- `drklein_api.py` is a small stdlib `urllib` client plus Pydantic payload models for the Dr. Klein endpoint.
- `hello.py` is only a CLI/demo for the calculator and portfolio classes.

## Repo-Specific Gotchas
- The app supports two YAML shapes: current `scenarios` data and a legacy `portfolio` block that is loaded into scenario A and cloned to B.
- Special payments use German YAML keys (`monat`, `betrag_eur`, optional `geschenk`); payment changes use `monat_ab` and `rate_eur`.
- Special payments are ignored unless the loan's `annual_special_payment_percent` allows them; `LoanCalculator.add_special_payment` raises when the yearly cap is exceeded.
- Keep user-facing labels/errors in German; existing text often uses ASCII transliterations like `gueltig`, `groesser`, and `Rueckgabe`.
