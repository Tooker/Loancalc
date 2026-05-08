<!-- Context: project-intelligence/technical | Priority: critical | Version: 1.0 | Updated: 2026-05-04 -->

# Technical Domain

**Purpose**: Tech stack, architecture, and implementation patterns for LoanCalc.
**Last Updated**: 2026-05-04

## Quick Reference

**Update Triggers**: Dependency changes | Calculator behavior changes | YAML shape changes | API integration changes
**Audience**: Developers and AI agents modifying this project
**Priority**: critical because most changes touch the calculator, Streamlit UI, import/export, or API client.

## Primary Stack

LoanCalc is a Python 3.13 mortgage/loan calculator with a Streamlit UI and a small Dr. Klein interest-rate client. Core calculations are local and deterministic; only `drklein_example.py` and optional UI interest fetching perform live network calls.

| Layer | Technology | Version | Rationale |
|---|---|---|---|
| Runtime | Python | 3.13+ | Declared in `.python-version` and `pyproject.toml` |
| App UI | Streamlit | 1.44+ | Interactive German loan input, scenarios, tables |
| DataFrames | Polars | 1.33+ | Fast amortization schedules and aggregations |
| Charts | Altair | 5.5+ | Streamlit-friendly visualizations |
| Validation | Pydantic | 2.11+ | Dr. Klein request/response payload models |
| Config | PyYAML | 6.0+ | Scenario import/export |
| Tooling | uv, Docker | current | Local runs and containerized Streamlit app |

## Core Calculator Pattern

Keep money math in `Decimal` until schedule output, then expose floats in `polars.DataFrame` rows. Validate invalid combinations early with German user-facing errors using the existing ASCII transliteration style (`groesser`, `duerfen`, `Rueckgabe`).

Key points:

- Use `@dataclass(slots=True)` for calculator state objects.
- Convert numeric inputs through `_to_decimal()` and round money with `_round_money()`.
- Return explicit empty `polars.DataFrame` schemas for no-data cases.
- Keep `LoanCalculator` focused on one loan and `LoanPortfolio` focused on aggregation.

```python
loan = LoanCalculator(
    name="kredit_1",
    principal_eur=300000,
    annual_interest_percent=3.5,
    annual_repayment_percent=2.0,
    annual_special_payment_percent=5,
)
loan.add_special_payment(month=12, amount_eur=5000, is_gift=False)
schedule = loan.create_schedule(max_months=360)
```

Ref: `loan_calculator.py`

## Streamlit UI Pattern

The UI is stateful and scenario-based. Prefix every `st.session_state` key with `skey(scenario_id, key)` so Szenario A/B can be cloned, imported, exported, and compared without key collisions.

Key points:

- Keep reusable normalization helpers near the top of `app.py`.
- Use German labels in UI text and errors.
- Preserve current YAML keys: `monat`, `betrag_eur`, `geschenk`, `monat_ab`, `rate_eur`.
- Treat legacy `portfolio` YAML as scenario A input and clone to scenario B.

```python
def collect_special_payments_for_state(scenario_id: str, index: int) -> list[dict[str, object]]:
    rows = extract_special_payments(
        st.session_state.get(skey(scenario_id, f"specials_data_{index}"), default_special_payments())
    )
    return [row for raw in rows if (row := normalize_special_payment_row(raw)) is not None]
```

Ref: `app.py`

## API Client Pattern

There are no internal HTTP endpoints. External API access is isolated in `drklein_api.py` using Pydantic payload models, stdlib `urllib`, an explicit timeout, and a project-specific `DrKleinApiError` wrapper.

Key points:

- Model request payloads with Pydantic aliases matching Dr. Klein JSON fields.
- Keep headers and endpoint defaults in the client, not the UI.
- Raise `DrKleinApiError` for HTTP, network, JSON, and missing-rate failures.
- Do not use `drklein_example.py` as offline verification because it performs live calls.

```python
query = RateQuery(kaufpreis_eur=500000, postleitzahl="10115", darlehensbetrag_eur=300000, laufzeit_jahre=25)
client = DrKleinRateClient()
payload = client.build_offer_payload(query)
response = client.fetch_offer(payload)
interest = client.extract_preferred_rate(response)
```

Ref: `drklein_api.py`

## Naming Conventions

Prefer simple Python naming and keep persisted/imported keys stable. Do not rename YAML keys or DataFrame columns unless all import/export, display, and README references are updated together.

| Type | Convention | Example |
|---|---|---|
| Files/modules | `snake_case.py` | `loan_calculator.py`, `drklein_api.py` |
| Classes | `PascalCase` | `LoanCalculator`, `LoanPortfolio`, `RateQuery` |
| Functions | `snake_case` verbs | `create_schedule`, `fetch_interest_from_api` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_MAX_MONTHS`, `RATE_KEYS` |
| YAML keys | German/domain keys | `monat`, `betrag_eur`, `geschenk`, `monat_ab` |
| DataFrame columns | German/domain snake_case | `restschuld_eur`, `sonderzahlung_eur` |

Ref: `app.py`, `loan_calculator.py`, `README.md`

## Code Standards

Most changes should be small and localized. Preserve the separation between calculation, UI state, and external API access.

Key points:

- Use `uv` commands; quickest verification is `uv run python -m py_compile app.py loan_calculator.py drklein_api.py drklein_example.py hello.py`.
- Keep user-facing labels/errors in German, following the existing ASCII transliteration style.
- Add validation before computation or external calls, not after partial state mutation.
- Avoid introducing tests, formatters, or CI assumptions unless explicitly requested.
- Prefer native Polars expressions for table/chart preparation over row-by-row Python where practical.

Ref: `AGENTS.md`, `pyproject.toml`

## Security Requirements

This is a local calculator app, but it accepts uploaded YAML and can call an external financial API. Protect data integrity and avoid leaking personal financial inputs.

Key points:

- Parse imports with `yaml.safe_load()` only and validate expected dictionary/list shapes.
- Keep Dr. Klein calls timeout-bound and surface errors through `DrKleinApiError`/Streamlit messages.
- Do not log or print uploaded loan data, postal codes, or API responses unless explicitly debugging.
- Keep Docker/Streamlit exposure local by default unless deployment requirements are provided.
- Do not commit secrets or personal financing YAML exports.

Ref: `app.py`, `drklein_api.py`, `Dockerfile`, `docker-compose.yml`

## 📂 Codebase References

| Context | Implementation |
|---|---|
| Streamlit app, YAML import/export, scenarios, charts | `app.py` |
| Core loan calculations and portfolio aggregation | `loan_calculator.py` |
| External Dr. Klein API client and Pydantic models | `drklein_api.py` |
| CLI/demo calculator usage | `hello.py` |
| Live Dr. Klein example, not offline verification | `drklein_example.py` |
| Runtime dependencies | `pyproject.toml`, `uv.lock` |
| Docker runtime | `Dockerfile`, `docker-compose.yml` |
| Project instructions and verification command | `AGENTS.md` |

## Related Files

- `navigation.md` for quick routing across Project Intelligence files.
- `README.md` for user-facing installation, usage, and YAML examples.
