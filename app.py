from __future__ import annotations

import copy
import json
from decimal import Decimal

import altair as alt
import polars as pl
import streamlit as st
import yaml

from drklein_api import DrKleinApiError, DrKleinRateClient, RateQuery
from loan_calculator import LoanCalculator, LoanPortfolio


DEFAULT_SPECIAL_PAYMENTS = [
    {"monat": 12, "betrag_eur": 5000.0},
]

DEFAULT_LOAN_COUNT = 2
DEFAULT_MAX_MONTHS = 360
SCENARIOS = {
    "scenario_a": "Szenario A",
    "scenario_b": "Szenario B",
}


def default_special_payments() -> list[dict[str, float]]:
    return [row.copy() for row in DEFAULT_SPECIAL_PAYMENTS]


def skey(scenario_id: str, key: str) -> str:
    return f"{scenario_id}__{key}"


def init_app_state() -> None:
    for scenario_id in SCENARIOS:
        st.session_state.setdefault(skey(scenario_id, "loan_count"), DEFAULT_LOAN_COUNT)
        st.session_state.setdefault(skey(scenario_id, "max_months"), DEFAULT_MAX_MONTHS)


def clone_scenario_state(source_scenario_id: str, target_scenario_id: str) -> None:
    source_prefix = f"{source_scenario_id}__"
    target_prefix = f"{target_scenario_id}__"
    for key in list(st.session_state.keys()):
        if key.startswith(target_prefix):
            del st.session_state[key]
    for key, value in list(st.session_state.items()):
        if key.startswith(source_prefix):
            cloned_key = key.replace(source_prefix, target_prefix, 1)
            st.session_state[cloned_key] = copy.deepcopy(value)


def extract_special_payments(edited_rows: object) -> list[dict[str, object]]:
    if isinstance(edited_rows, list):
        return edited_rows
    if isinstance(edited_rows, pl.DataFrame):
        return edited_rows.to_dicts()
    if hasattr(edited_rows, "to_dict"):
        records = edited_rows.to_dict(orient="records")
        if isinstance(records, list):
            return records
    return []


def format_duration(months: int) -> str:
    years, remaining_months = divmod(months, 12)
    parts: list[str] = []
    if years:
        parts.append(f"{years} Jahr" if years == 1 else f"{years} Jahre")
    if remaining_months or not parts:
        parts.append(f"{remaining_months} Monat" if remaining_months == 1 else f"{remaining_months} Monate")
    return " ".join(parts)


def format_euro(value: float) -> str:
    rounded = int(round(value))
    return f"{rounded:,}".replace(",", ".") + " €"


def prepare_combined_schedule_for_display(combined_schedule: pl.DataFrame) -> pl.DataFrame:
    schedule_with_ratio = combined_schedule.with_columns(
        pl.when(pl.col("zinsen_eur") > 0)
        .then(pl.col("tilgung_eur") / pl.col("zinsen_eur"))
        .otherwise(None)
        .alias("tilgung_zu_zinsen")
    )

    return schedule_with_ratio.with_columns(
        pl.col("rate_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("zinsen_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("tilgung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("sonderzahlung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("restschuld_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("tilgung_zu_zinsen")
        .map_elements(lambda value: "-" if value is None else f"{float(value):.2f}", return_dtype=pl.String)
        .alias("tilgung_zu_zinsen_text"),
    ).select(
        [
            "monat",
            "jahr",
            "rate_eur",
            "zinsen_eur",
            "tilgung_eur",
            "sonderzahlung_eur",
            "restschuld_eur",
            "tilgung_zu_zinsen_text",
        ]
    )


def build_api_signature(query: RateQuery) -> str:
    return json.dumps(query.model_dump(mode="json"), sort_keys=True, ensure_ascii=True)


def collect_special_payments_for_state(scenario_id: str, index: int) -> list[dict[str, float]]:
    rows = extract_special_payments(
        st.session_state.get(
            skey(scenario_id, f"specials_data_{index}"),
            st.session_state.get(skey(scenario_id, f"specials_editor_{index}"), default_special_payments()),
        )
    )
    special_payments: list[dict[str, float]] = []
    for row in rows:
        month = row.get("monat")
        amount = row.get("betrag_eur")
        if month and amount is not None:
            special_payments.append({"monat": int(month), "betrag_eur": float(amount)})
    return special_payments


def export_scenario_state(scenario_id: str) -> dict[str, object]:
    loan_count = int(st.session_state.get(skey(scenario_id, "loan_count"), DEFAULT_LOAN_COUNT))
    loans: list[dict[str, object]] = []

    for index in range(loan_count):
        repayment_mode = st.session_state.get(skey(scenario_id, f"repayment_mode_{index}"), "Prozent")
        loans.append(
            {
                "name": st.session_state.get(skey(scenario_id, f"name_{index}"), f"kredit_{index + 1}"),
                "principal_eur": float(st.session_state.get(skey(scenario_id, f"principal_{index}"), 0.0)),
                "interest_source": st.session_state.get(skey(scenario_id, f"interest_source_{index}"), "Manuell"),
                "annual_interest_percent": float(st.session_state.get(skey(scenario_id, f"interest_{index}"), 0.0)),
                "kaufpreis_eur": float(st.session_state.get(skey(scenario_id, f"purchase_price_{index}"), 0.0)),
                "postleitzahl": st.session_state.get(skey(scenario_id, f"postal_code_{index}"), ""),
                "api_laufzeit_jahre": int(st.session_state.get(skey(scenario_id, f"api_term_years_{index}"), 25)),
                "repayment_mode": repayment_mode,
                "annual_repayment_percent": float(
                    st.session_state.get(skey(scenario_id, f"repayment_percent_{index}"), 0.0)
                ),
                "monthly_payment_amount_eur": float(
                    st.session_state.get(skey(scenario_id, f"payment_amount_{index}"), 0.0)
                ),
                "interest_only_months": int(st.session_state.get(skey(scenario_id, f"interest_only_{index}"), 0)),
                "annual_special_payment_percent": float(
                    st.session_state.get(skey(scenario_id, f"special_percent_{index}"), 0.0)
                ),
                "special_payments": collect_special_payments_for_state(scenario_id, index),
            }
        )

    return {
        "loan_count": loan_count,
        "max_months": int(st.session_state.get(skey(scenario_id, "max_months"), DEFAULT_MAX_MONTHS)),
        "loans": loans,
    }


def export_app_state_to_yaml() -> str:
    data: dict[str, object] = {
        "scenarios": {
            scenario_id: export_scenario_state(scenario_id)
            for scenario_id in SCENARIOS
        }
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def load_scenario_state(scenario_id: str, scenario_data: dict[str, object]) -> None:
    loans = scenario_data.get("loans")
    if not isinstance(loans, list) or not loans:
        raise ValueError(f"{SCENARIOS.get(scenario_id, scenario_id)} enthaelt keine gueltigen Kredite.")

    st.session_state[skey(scenario_id, "loan_count")] = min(max(len(loans), 1), 5)
    st.session_state[skey(scenario_id, "max_months")] = int(scenario_data.get("max_months", DEFAULT_MAX_MONTHS))

    for index, loan in enumerate(loans[:5]):
        if not isinstance(loan, dict):
            raise ValueError("Mindestens ein Kredit in der YAML-Datei ist ungueltig.")
        repayment_mode = str(loan.get("repayment_mode", "Prozent"))
        interest_source = str(loan.get("interest_source", "Manuell"))
        st.session_state[skey(scenario_id, f"name_{index}")] = str(loan.get("name", f"kredit_{index + 1}"))
        st.session_state[skey(scenario_id, f"principal_{index}")] = float(loan.get("principal_eur", 0.0))
        st.session_state[skey(scenario_id, f"interest_{index}")] = float(loan.get("annual_interest_percent", 0.0))
        st.session_state[skey(scenario_id, f"interest_source_{index}")] = (
            interest_source if interest_source in {"Manuell", "API"} else "Manuell"
        )
        st.session_state[skey(scenario_id, f"purchase_price_{index}")] = float(loan.get("kaufpreis_eur", 0.0))
        st.session_state[skey(scenario_id, f"postal_code_{index}")] = str(loan.get("postleitzahl", ""))
        st.session_state[skey(scenario_id, f"api_term_years_{index}")] = int(loan.get("api_laufzeit_jahre", 25))
        st.session_state[skey(scenario_id, f"repayment_mode_{index}")] = (
            repayment_mode if repayment_mode in {"Prozent", "Feste Monatsrate"} else "Prozent"
        )
        st.session_state[skey(scenario_id, f"repayment_percent_{index}")] = float(
            loan.get("annual_repayment_percent", 0.0)
        )
        st.session_state[skey(scenario_id, f"payment_amount_{index}")] = float(
            loan.get("monthly_payment_amount_eur", 0.0)
        )
        st.session_state[skey(scenario_id, f"interest_only_{index}")] = int(loan.get("interest_only_months", 0))
        st.session_state[skey(scenario_id, f"special_percent_{index}")] = float(
            loan.get("annual_special_payment_percent", 0.0)
        )
        if st.session_state[skey(scenario_id, f"interest_source_{index}")] == "API":
            cached_query = RateQuery(
                kaufpreis_eur=st.session_state[skey(scenario_id, f"purchase_price_{index}")],
                postleitzahl=st.session_state[skey(scenario_id, f"postal_code_{index}")],
                darlehensbetrag_eur=st.session_state[skey(scenario_id, f"principal_{index}")],
                monatliche_rate_eur=(
                    st.session_state[skey(scenario_id, f"payment_amount_{index}")]
                    if st.session_state[skey(scenario_id, f"repayment_mode_{index}")] == "Feste Monatsrate"
                    else None
                ),
                laufzeit_jahre=st.session_state[skey(scenario_id, f"api_term_years_{index}")],
                tilgungssatz=(
                    st.session_state[skey(scenario_id, f"repayment_percent_{index}")]
                    if st.session_state[skey(scenario_id, f"repayment_mode_{index}")] == "Prozent"
                    else None
                ),
            )
            st.session_state[skey(scenario_id, f"api_interest_{index}")] = st.session_state[
                skey(scenario_id, f"interest_{index}")
            ]
            st.session_state[skey(scenario_id, f"api_signature_{index}")] = build_api_signature(cached_query)
        special_payments = loan.get("special_payments", [])
        if not isinstance(special_payments, list):
            raise ValueError(f"Die Sonderzahlungen fuer Kredit {index + 1} sind ungueltig.")
        st.session_state[skey(scenario_id, f"specials_data_{index}")] = [
            {
                "monat": int(item.get("monat", 0)),
                "betrag_eur": float(item.get("betrag_eur", 0.0)),
            }
            for item in special_payments
            if isinstance(item, dict)
        ] or default_special_payments()
        editor_key = skey(scenario_id, f"specials_editor_{index}")
        if editor_key in st.session_state:
            del st.session_state[editor_key]


def load_app_state_from_yaml(content: bytes) -> None:
    loaded = yaml.safe_load(content.decode("utf-8")) or {}

    scenarios = loaded.get("scenarios")
    if isinstance(scenarios, dict):
        for scenario_id in SCENARIOS:
            scenario_data = scenarios.get(scenario_id)
            if isinstance(scenario_data, dict):
                load_scenario_state(scenario_id, scenario_data)
        return

    portfolio = loaded.get("portfolio")
    if isinstance(portfolio, dict):
        load_scenario_state("scenario_a", portfolio)
        clone_scenario_state("scenario_a", "scenario_b")
        return

    raise ValueError("Die YAML-Datei enthaelt weder 'scenarios' noch einen gueltigen alten 'portfolio'-Block.")


def fetch_interest_from_api(scenario_id: str, index: int, query: RateQuery) -> None:
    client = DrKleinRateClient()
    response = client.fetch_offer(client.build_offer_payload(query))
    interest = client.extract_preferred_rate(response)
    st.session_state[skey(scenario_id, f"api_interest_{index}")] = interest
    st.session_state[skey(scenario_id, f"api_signature_{index}")] = build_api_signature(query)
    st.session_state[skey(scenario_id, f"api_rate_candidates_{index}")] = client.extract_rate_candidates(response)
    st.session_state[skey(scenario_id, f"interest_{index}")] = interest


def build_loan_from_inputs(scenario_id: str, index: int) -> LoanCalculator:
    loan_name = st.text_input(
        f"Kreditname {index + 1}",
        value=f"kredit_{index + 1}",
        key=skey(scenario_id, f"name_{index}"),
    )
    principal_eur = st.number_input(
        f"Kreditsumme {index + 1} (EUR)",
        min_value=0.0,
        value=250000.0 if index == 0 else 100000.0,
        step=1000.0,
        key=skey(scenario_id, f"principal_{index}"),
    )

    repayment_mode = st.radio(
        f"Tilgungsmodus {index + 1}",
        options=["Prozent", "Feste Monatsrate"],
        horizontal=True,
        key=skey(scenario_id, f"repayment_mode_{index}"),
    )

    annual_repayment_percent = 0.0
    monthly_payment_amount_eur = 0.0

    if repayment_mode == "Prozent":
        annual_repayment_percent = st.number_input(
            f"Tilgung {index + 1} (% p.a.)",
            min_value=0.0,
            value=2.0 if index == 0 else 3.0,
            step=0.1,
            key=skey(scenario_id, f"repayment_percent_{index}"),
        )
    else:
        monthly_payment_amount_eur = st.number_input(
            f"Monatsrate {index + 1} gesamt (EUR)",
            min_value=0.0,
            value=1400.0 if index == 0 else 650.0,
            step=50.0,
            key=skey(scenario_id, f"payment_amount_{index}"),
        )

    interest_source = st.radio(
        f"Zinsquelle {index + 1}",
        options=["Manuell", "API"],
        horizontal=True,
        key=skey(scenario_id, f"interest_source_{index}"),
    )

    annual_interest_percent: float
    if interest_source == "Manuell":
        annual_interest_percent = st.number_input(
            f"Zins {index + 1} (% p.a.)",
            min_value=0.0,
            value=3.5 if index == 0 else 2.8,
            step=0.1,
            key=skey(scenario_id, f"interest_{index}"),
        )
    else:
        purchase_price_eur = st.number_input(
            f"Kaufpreis {index + 1} (EUR)",
            min_value=0.0,
            value=300000.0 if index == 0 else 150000.0,
            step=1000.0,
            key=skey(scenario_id, f"purchase_price_{index}"),
        )
        postal_code = st.text_input(
            f"Postleitzahl {index + 1}",
            value="44139",
            key=skey(scenario_id, f"postal_code_{index}"),
        )
        api_term_years = st.number_input(
            f"API-Laufzeit {index + 1} (Jahre)",
            min_value=1,
            max_value=40,
            value=25,
            step=1,
            key=skey(scenario_id, f"api_term_years_{index}"),
        )

        if purchase_price_eur <= 0:
            raise ValueError(f"Kredit '{loan_name}': Fuer den API-Zins muss der Kaufpreis groesser als 0 sein.")
        if not postal_code.strip():
            raise ValueError(f"Kredit '{loan_name}': Fuer den API-Zins wird eine Postleitzahl benoetigt.")

        query = RateQuery(
            kaufpreis_eur=purchase_price_eur,
            postleitzahl=postal_code.strip(),
            darlehensbetrag_eur=principal_eur,
            monatliche_rate_eur=monthly_payment_amount_eur if repayment_mode == "Feste Monatsrate" else None,
            laufzeit_jahre=int(api_term_years),
            tilgungssatz=annual_repayment_percent if repayment_mode == "Prozent" else None,
        )

        if st.button(
            f"Sollzins von API abrufen {index + 1}",
            key=skey(scenario_id, f"fetch_interest_{index}"),
            use_container_width=True,
        ):
            try:
                fetch_interest_from_api(scenario_id, index, query)
                st.success("Sollzins von API abgerufen.")
            except DrKleinApiError as exc:
                st.error(str(exc))

        cached_interest = st.session_state.get(skey(scenario_id, f"api_interest_{index}"))
        cached_signature = st.session_state.get(skey(scenario_id, f"api_signature_{index}"))
        cached_candidates = st.session_state.get(skey(scenario_id, f"api_rate_candidates_{index}"), {})
        current_signature = build_api_signature(query)
        if cached_interest is not None:
            st.caption(f"Abgerufener Sollzins: {float(cached_interest):.2f} %")
        if cached_candidates:
            st.caption(f"Gefundene Zinsfelder: {cached_candidates}")

        if cached_interest is None:
            raise ValueError(f"Kredit '{loan_name}': Bitte den Sollzins zuerst ueber die API abrufen.")
        if cached_signature != current_signature:
            st.warning("Eingabedaten haben sich geaendert. Bitte den Sollzins erneut von der API abrufen.")
            raise ValueError(f"Kredit '{loan_name}': API-Sollzins ist veraltet und muss neu abgerufen werden.")

        annual_interest_percent = float(cached_interest)

    loan = LoanCalculator(
        name=loan_name,
        principal_eur=principal_eur,
        annual_interest_percent=annual_interest_percent,
        annual_repayment_percent=annual_repayment_percent,
        monthly_payment_amount_eur=monthly_payment_amount_eur,
        interest_only_months=st.number_input(
            f"Tilgungsfreie Monate {index + 1}",
            min_value=0,
            value=0,
            step=1,
            key=skey(scenario_id, f"interest_only_{index}"),
        ),
        annual_special_payment_percent=st.number_input(
            f"Erlaubte Sonderzahlung {index + 1} (% p.a.)",
            min_value=0.0,
            value=5.0,
            step=0.5,
            key=skey(scenario_id, f"special_percent_{index}"),
        ),
    )

    special_payments = st.data_editor(
        st.session_state.get(skey(scenario_id, f"specials_data_{index}"), default_special_payments()),
        key=skey(scenario_id, f"specials_editor_{index}"),
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "monat": st.column_config.NumberColumn("Monat", min_value=1, step=1),
            "betrag_eur": st.column_config.NumberColumn("Betrag (EUR)", min_value=0.0, step=100.0),
        },
    )
    st.session_state[skey(scenario_id, f"specials_data_{index}")] = extract_special_payments(special_payments)

    for row in extract_special_payments(special_payments):
        month = row.get("monat")
        amount = row.get("betrag_eur")
        if month and amount:
            loan.add_special_payment(month=int(month), amount_eur=Decimal(str(amount)))

    return loan


def build_restschuld_chart(detailed_schedule: pl.DataFrame, combined_schedule: pl.DataFrame) -> alt.Chart:
    total_schedule = combined_schedule.with_columns(pl.lit("gesamt").alias("kredit"))
    chart_data = pl.concat(
        [
            detailed_schedule.select(["kredit", "monat", "restschuld_eur"]),
            total_schedule.select(["kredit", "monat", "restschuld_eur"]),
        ],
        how="vertical",
    )
    burden_data = combined_schedule.sort("monat").with_columns(
        (pl.col("rate_eur") - pl.col("sonderzahlung_eur")).alias("monatsbelastung_eur")
    ).select(["monat", "monatsbelastung_eur"])
    special_payment_data = detailed_schedule.filter(pl.col("sonderzahlung_eur") > 0).select(
        ["kredit", "monat", "restschuld_eur", "sonderzahlung_eur"]
    )

    debt_chart = (
        alt.Chart(chart_data.to_pandas())
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("monat:Q", title="Monat"),
            y=alt.Y("restschuld_eur:Q", title="Restschuld (EUR)"),
            color=alt.Color("kredit:N", title="Kredit"),
            tooltip=["kredit:N", "monat:Q", alt.Tooltip("restschuld_eur:Q", format=",.2f")],
        )
        .properties(height=360)
    )

    burden_chart = (
        alt.Chart(burden_data.to_pandas())
        .mark_line(strokeWidth=3, strokeDash=[8, 6], color="#c2410c")
        .encode(
            x=alt.X("monat:Q"),
            y=alt.Y("monatsbelastung_eur:Q", title="Monatliche Belastung (EUR)"),
            tooltip=[
                "monat:Q",
                alt.Tooltip("monatsbelastung_eur:Q", title="Monatliche Belastung", format=",.2f"),
            ],
        )
    )

    if special_payment_data.is_empty():
        return alt.layer(debt_chart, burden_chart).resolve_scale(y="independent")

    marker_chart = (
        alt.Chart(special_payment_data.to_pandas())
        .mark_point(size=110, filled=True, shape="diamond")
        .encode(
            x=alt.X("monat:Q"),
            y=alt.Y("restschuld_eur:Q"),
            color=alt.Color("kredit:N", title="Kredit"),
            tooltip=[
                "kredit:N",
                "monat:Q",
                alt.Tooltip("sonderzahlung_eur:Q", title="Sonderzahlung", format=",.2f"),
                alt.Tooltip("restschuld_eur:Q", title="Restschuld", format=",.2f"),
            ],
        )
    )

    return alt.layer(debt_chart, burden_chart, marker_chart).resolve_scale(y="independent")


def build_monthly_burden_table(combined_schedule: pl.DataFrame) -> pl.DataFrame:
    chart_data = combined_schedule.sort("monat").with_columns(
        (pl.col("rate_eur") - pl.col("sonderzahlung_eur")).alias("monatsbelastung_eur")
    ).with_columns(
        pl.col("monatsbelastung_eur").shift(1).alias("vorherige_belastung_eur")
    ).with_columns(
        pl.when(
            pl.col("vorherige_belastung_eur").is_null()
            | (pl.col("monatsbelastung_eur") != pl.col("vorherige_belastung_eur"))
        )
        .then(True)
        .otherwise(False)
        .alias("rate_geaendert")
    )
    return chart_data.filter(pl.col("rate_geaendert")).with_columns(
        pl.col("monat").map_elements(lambda value: format_duration(int(value)), return_dtype=pl.String).alias("zeitpunkt"),
        pl.col("monatsbelastung_eur")
        .map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String)
        .alias("neue_belastung"),
        pl.when(pl.col("vorherige_belastung_eur").is_null())
        .then(pl.lit("-"))
        .otherwise(
            pl.col("vorherige_belastung_eur")
            .map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String)
        )
        .alias("vorherige_belastung"),
    ).select(["monat", "zeitpunkt", "vorherige_belastung", "neue_belastung"])


def build_interest_repayment_share_chart(combined_schedule: pl.DataFrame) -> alt.Chart:
    share_data = combined_schedule.select(["monat", "zinsen_eur", "tilgung_eur"]).to_pandas().melt(
        id_vars="monat",
        value_vars=["zinsen_eur", "tilgung_eur"],
        var_name="bestandteil",
        value_name="wert_eur",
    )
    share_data["bestandteil"] = share_data["bestandteil"].map(
        {"zinsen_eur": "Zinsen", "tilgung_eur": "Tilgung"}
    )

    return (
        alt.Chart(share_data)
        .mark_area()
        .encode(
            x=alt.X("monat:Q", title="Monat"),
            y=alt.Y("wert_eur:Q", stack="normalize", title="Anteil an der Monatsrate"),
            color=alt.Color(
                "bestandteil:N",
                title=None,
                scale=alt.Scale(domain=["Zinsen", "Tilgung"], range=["#b45309", "#0f766e"]),
            ),
            tooltip=[
                "monat:Q",
                "bestandteil:N",
                alt.Tooltip("wert_eur:Q", title="Betrag", format=",.2f"),
            ],
        )
        .properties(height=280)
    )


def build_restschuld_small_multiples(detailed_schedule: pl.DataFrame) -> alt.Chart:
    return (
        alt.Chart(detailed_schedule.to_pandas())
        .mark_line(strokeWidth=3, color="#1d4ed8")
        .encode(
            x=alt.X("monat:Q", title="Monat"),
            y=alt.Y("restschuld_eur:Q", title="Restschuld (EUR)"),
            tooltip=[
                "kredit:N",
                "monat:Q",
                alt.Tooltip("restschuld_eur:Q", title="Restschuld", format=",.2f"),
            ],
        )
        .properties(height=180)
        .facet(column=alt.Column("kredit:N", title="Restschuld je Kredit"))
    )


def build_yearly_aggregation(combined_schedule: pl.DataFrame) -> pl.DataFrame:
    return (
        combined_schedule.sort(["jahr", "monat"])
        .group_by("jahr")
        .agg(
            pl.col("zinsen_eur").sum().alias("zinsen_eur"),
            pl.col("tilgung_eur").sum().alias("tilgung_eur"),
            pl.col("sonderzahlung_eur").sum().alias("sonderzahlung_eur"),
            pl.col("rate_eur").sum().alias("rate_eur"),
            pl.col("restschuld_eur").last().alias("restschuld_eur"),
        )
        .sort("jahr")
    )


def build_yearly_aggregation_chart(yearly_aggregation: pl.DataFrame) -> alt.Chart:
    yearly_data = yearly_aggregation.select(
        ["jahr", "zinsen_eur", "tilgung_eur", "sonderzahlung_eur"]
    ).to_pandas().melt(
        id_vars="jahr",
        value_vars=["zinsen_eur", "tilgung_eur", "sonderzahlung_eur"],
        var_name="bestandteil",
        value_name="wert_eur",
    )
    yearly_data["bestandteil"] = yearly_data["bestandteil"].map(
        {
            "zinsen_eur": "Zinsen",
            "tilgung_eur": "Tilgung",
            "sonderzahlung_eur": "Sonderzahlung",
        }
    )

    bars = (
        alt.Chart(yearly_data)
        .mark_bar()
        .encode(
            x=alt.X("jahr:O", title="Jahr"),
            y=alt.Y("wert_eur:Q", title="Jahressumme (EUR)"),
            color=alt.Color(
                "bestandteil:N",
                title=None,
                scale=alt.Scale(
                    domain=["Zinsen", "Tilgung", "Sonderzahlung"],
                    range=["#b45309", "#0f766e", "#7c3aed"],
                ),
            ),
            tooltip=[
                "jahr:O",
                "bestandteil:N",
                alt.Tooltip("wert_eur:Q", title="Betrag", format=",.2f"),
            ],
        )
    )

    restschuld_line = (
        alt.Chart(yearly_aggregation.to_pandas())
        .mark_line(strokeWidth=3, color="#1d4ed8", point=True)
        .encode(
            x=alt.X("jahr:O"),
            y=alt.Y("restschuld_eur:Q", title="Restschuld Jahresende (EUR)"),
            tooltip=[
                "jahr:O",
                alt.Tooltip("restschuld_eur:Q", title="Restschuld", format=",.2f"),
            ],
        )
    )

    return alt.layer(bars, restschuld_line).resolve_scale(y="independent").properties(height=320)


def prepare_yearly_aggregation_for_display(yearly_aggregation: pl.DataFrame) -> pl.DataFrame:
    return yearly_aggregation.with_columns(
        pl.col("rate_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("zinsen_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("tilgung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("sonderzahlung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("restschuld_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
    )


def prepare_detailed_schedule_for_display(detailed_schedule: pl.DataFrame) -> pl.DataFrame:
    return detailed_schedule.with_columns(
        pl.col("rate_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("zinsen_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("tilgung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("sonderzahlung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
        pl.col("restschuld_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
    )


def build_laufzeit_table(detailed_schedule: pl.DataFrame, combined_schedule: pl.DataFrame) -> pl.DataFrame:
    per_loan = detailed_schedule.group_by("kredit").agg(pl.col("monat").max().alias("laufzeit_monate"))
    total = pl.DataFrame({"kredit": ["gesamt"], "laufzeit_monate": [combined_schedule["monat"].max()]})
    return pl.concat([per_loan, total], how="vertical").with_columns(
        pl.col("laufzeit_monate")
        .map_elements(lambda value: format_duration(int(value)), return_dtype=pl.String)
        .alias("laufzeit_text")
    ).select(["kredit", "laufzeit_text", "laufzeit_monate"])


def build_scenario_comparison_cumulative_cost_chart(
    scenario_schedules: list[tuple[str, pl.DataFrame]],
) -> alt.Chart:
    rows: list[dict[str, float | str | int]] = []
    for scenario_label, combined_schedule in scenario_schedules:
        cumulative = 0.0
        for row in combined_schedule.sort("monat").iter_rows(named=True):
            cumulative += float(row["rate_eur"])
            rows.append(
                {
                    "szenario": scenario_label,
                    "monat": int(row["monat"]),
                    "kumulierte_kosten_eur": cumulative,
                }
            )

    return (
        alt.Chart(pl.DataFrame(rows).to_pandas())
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("monat:Q", title="Monat"),
            y=alt.Y("kumulierte_kosten_eur:Q", title="Kumulierte Belastung (EUR)"),
            color=alt.Color("szenario:N", title="Szenario"),
            tooltip=[
                "szenario:N",
                "monat:Q",
                alt.Tooltip("kumulierte_kosten_eur:Q", title="Kumulierte Belastung", format=",.2f"),
            ],
        )
        .properties(height=320)
    )


def build_scenario_comparison_restschuld_chart(
    scenario_schedules: list[tuple[str, pl.DataFrame]],
) -> alt.Chart:
    rows: list[dict[str, float | str | int]] = []
    for scenario_label, combined_schedule in scenario_schedules:
        for row in combined_schedule.sort("monat").iter_rows(named=True):
            rows.append(
                {
                    "szenario": scenario_label,
                    "monat": int(row["monat"]),
                    "restschuld_eur": float(row["restschuld_eur"]),
                }
            )

    return (
        alt.Chart(pl.DataFrame(rows).to_pandas())
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("monat:Q", title="Monat"),
            y=alt.Y("restschuld_eur:Q", title="Restschuld gesamt (EUR)"),
            color=alt.Color("szenario:N", title="Szenario"),
            tooltip=[
                "szenario:N",
                "monat:Q",
                alt.Tooltip("restschuld_eur:Q", title="Restschuld", format=",.2f"),
            ],
        )
        .properties(height=320)
    )


def render_scenario_tab(scenario_id: str, scenario_label: str) -> dict[str, pl.DataFrame] | None:
    settings_col_1, settings_col_2 = st.columns(2)
    with settings_col_1:
        loan_count = st.slider(
            "Anzahl Kredite",
            min_value=1,
            max_value=5,
            step=1,
            key=skey(scenario_id, "loan_count"),
        )
    with settings_col_2:
        max_months = st.slider(
            "Maximale Laufzeit in Monaten",
            min_value=12,
            max_value=720,
            step=12,
            key=skey(scenario_id, "max_months"),
        )

    try:
        portfolio = LoanPortfolio()
        for index in range(loan_count):
            with st.expander(f"{scenario_label} - Kredit {index + 1}", expanded=True):
                loan = build_loan_from_inputs(scenario_id, index)
                portfolio.add_loan(loan)

        detailed_schedule = portfolio.create_detailed_schedule(max_months=max_months)
        combined_schedule = portfolio.create_combined_schedule(max_months=max_months)
    except ValueError as exc:
        st.error(str(exc))
        return None

    if combined_schedule.is_empty():
        st.warning("Keine Kreditdaten vorhanden.")
        return None

    combined_schedule_display = prepare_combined_schedule_for_display(combined_schedule)
    detailed_schedule_display = prepare_detailed_schedule_for_display(detailed_schedule)
    yearly_aggregation = build_yearly_aggregation(combined_schedule)
    yearly_aggregation_display = prepare_yearly_aggregation_for_display(yearly_aggregation)
    sorted_schedule = combined_schedule.sort("monat")
    first_row = sorted_schedule.head(1)
    last_row = sorted_schedule.tail(1)
    restschuld_total = float(last_row["restschuld_eur"].item())
    laufzeit_total = int(combined_schedule["monat"].max())
    zinsen_total = float(combined_schedule["zinsen_eur"].sum())
    monatliche_belastung = float(first_row["rate_eur"].item())
    kumulierte_gesamtrate = float(combined_schedule["rate_eur"].sum())

    metric_1, metric_2, metric_3, metric_4, metric_5 = st.columns(5)
    metric_1.metric("Restschuld gesamt", f"{restschuld_total:,.2f} EUR")
    metric_2.metric("Monatliche Belastung", f"{monatliche_belastung:,.2f} EUR")
    metric_3.metric("Laufzeit im Modell", format_duration(laufzeit_total))
    metric_4.metric("Zinsen gesamt", f"{zinsen_total:,.2f} EUR")
    metric_5.metric("Kumulierte Gesamtkosten", f"{kumulierte_gesamtrate:,.2f} EUR")

    st.subheader("Restschuldverlauf")
    st.altair_chart(build_restschuld_chart(detailed_schedule, combined_schedule), use_container_width=True)

    summary_table_col_1, summary_table_col_2 = st.columns(2)
    with summary_table_col_1:
        st.subheader("Laufzeit je Kredit")
        st.dataframe(build_laufzeit_table(detailed_schedule, combined_schedule), use_container_width=True, hide_index=True)
    with summary_table_col_2:
        st.subheader("Aenderungen der monatlichen Belastung")
        st.dataframe(build_monthly_burden_table(combined_schedule), use_container_width=True, hide_index=True)

    composition_col, small_multiples_col = st.columns(2)
    with composition_col:
        st.subheader("Anteil Zins/Tilgung pro Monat")
        st.altair_chart(build_interest_repayment_share_chart(combined_schedule), use_container_width=True)
    with small_multiples_col:
        st.subheader("Restschuld je Einzelkredit")
        st.altair_chart(build_restschuld_small_multiples(detailed_schedule), use_container_width=True)

    st.subheader("Jahresaggregation")
    st.altair_chart(build_yearly_aggregation_chart(yearly_aggregation), use_container_width=True)
    st.dataframe(
        yearly_aggregation_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "jahr": st.column_config.NumberColumn("Jahr"),
            "rate_eur": "Jahresrate",
            "zinsen_eur": "Zinsen",
            "tilgung_eur": "Tilgung",
            "sonderzahlung_eur": "Sonderzahlung",
            "restschuld_eur": "Restschuld Jahresende",
        },
    )

    table_col_1, table_col_2 = st.columns(2)
    with table_col_1:
        with st.expander("Gesamttabelle", expanded=False):
            st.dataframe(
                combined_schedule_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "monat": st.column_config.NumberColumn("Monat"),
                    "jahr": st.column_config.NumberColumn("Jahr"),
                    "rate_eur": "Rate",
                    "zinsen_eur": "Zinsen",
                    "tilgung_eur": "Tilgung",
                    "sonderzahlung_eur": "Sonderzahlung",
                    "restschuld_eur": "Restschuld",
                    "tilgung_zu_zinsen_text": "Tilgung / Zinsen",
                },
            )
    with table_col_2:
        with st.expander("Detailtabelle", expanded=False):
            st.dataframe(detailed_schedule_display, use_container_width=True, hide_index=True)

    return {
        "combined_schedule": combined_schedule,
        "detailed_schedule": detailed_schedule,
    }


def main() -> None:
    st.set_page_config(page_title="LoanCalc", page_icon=":material/account_balance:", layout="wide")
    st.title("LoanCalc")
    st.caption("Interaktive Berechnung mehrerer Kredite mit Szenarien und Gegenueberstellung.")
    init_app_state()

    with st.sidebar:
        st.header("Szenarien")
        download_placeholder = st.empty()
        uploaded_file = st.file_uploader("YAML laden", type=["yaml", "yml"])
        if uploaded_file is not None:
            try:
                load_app_state_from_yaml(uploaded_file.getvalue())
                st.success("YAML-Datei geladen.")
            except ValueError as exc:
                st.error(str(exc))

        if st.button("Szenario B von A forken", use_container_width=True):
            clone_scenario_state("scenario_a", "scenario_b")
            st.rerun()
        if st.button("Szenario A von B forken", use_container_width=True):
            clone_scenario_state("scenario_b", "scenario_a")
            st.rerun()

    scenario_results: dict[str, dict[str, pl.DataFrame] | None] = {}
    tabs = st.tabs(list(SCENARIOS.values()))
    for tab, (scenario_id, scenario_label) in zip(tabs, SCENARIOS.items(), strict=False):
        with tab:
            scenario_results[scenario_id] = render_scenario_tab(scenario_id, scenario_label)

    download_placeholder.download_button(
        "YAML speichern",
        data=export_app_state_to_yaml(),
        file_name="loancalc-scenarios.yaml",
        mime="application/x-yaml",
        use_container_width=True,
    )

    available_scenarios = [
        (SCENARIOS[scenario_id], result["combined_schedule"])
        for scenario_id, result in scenario_results.items()
        if result is not None
    ]

    st.subheader("Gegenueberstellung")
    if len(available_scenarios) < 2:
        st.info("Fuer die Gegenueberstellung werden zwei gueltige Szenarien benoetigt.")
        return

    comparison_col_1, comparison_col_2 = st.columns(2)
    with comparison_col_1:
        st.subheader("Kumulierte Belastung")
        st.altair_chart(
            build_scenario_comparison_cumulative_cost_chart(available_scenarios),
            use_container_width=True,
        )
    with comparison_col_2:
        st.subheader("Restschuld gesamt")
        st.altair_chart(
            build_scenario_comparison_restschuld_chart(available_scenarios),
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
