from __future__ import annotations

from decimal import Decimal

import altair as alt
import polars as pl
import streamlit as st
import yaml

from loan_calculator import LoanCalculator, LoanPortfolio


DEFAULT_SPECIAL_PAYMENTS = [
    {"monat": 12, "betrag_eur": 5000.0},
]

DEFAULT_LOAN_COUNT = 2
DEFAULT_MAX_MONTHS = 360


def default_special_payments() -> list[dict[str, float]]:
    return [row.copy() for row in DEFAULT_SPECIAL_PAYMENTS]


def init_app_state() -> None:
    st.session_state.setdefault("loan_count", DEFAULT_LOAN_COUNT)
    st.session_state.setdefault("max_months", DEFAULT_MAX_MONTHS)


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


def collect_special_payments_for_state(index: int) -> list[dict[str, float]]:
    rows = extract_special_payments(st.session_state.get(f"specials_{index}", default_special_payments()))
    special_payments: list[dict[str, float]] = []
    for row in rows:
        month = row.get("monat")
        amount = row.get("betrag_eur")
        if month and amount is not None:
            special_payments.append({"monat": int(month), "betrag_eur": float(amount)})
    return special_payments


def export_app_state_to_yaml() -> str:
    loan_count = int(st.session_state.get("loan_count", DEFAULT_LOAN_COUNT))
    data: dict[str, object] = {
        "portfolio": {
            "loan_count": loan_count,
            "max_months": int(st.session_state.get("max_months", DEFAULT_MAX_MONTHS)),
            "loans": [],
        }
    }

    loans: list[dict[str, object]] = []
    for index in range(loan_count):
        repayment_mode = st.session_state.get(f"repayment_mode_{index}", "Prozent")
        loans.append(
            {
                "name": st.session_state.get(f"name_{index}", f"kredit_{index + 1}"),
                "principal_eur": float(st.session_state.get(f"principal_{index}", 0.0)),
                "annual_interest_percent": float(st.session_state.get(f"interest_{index}", 0.0)),
                "repayment_mode": repayment_mode,
                "annual_repayment_percent": float(st.session_state.get(f"repayment_percent_{index}", 0.0)),
                "monthly_payment_amount_eur": float(st.session_state.get(f"payment_amount_{index}", 0.0)),
                "interest_only_months": int(st.session_state.get(f"interest_only_{index}", 0)),
                "annual_special_payment_percent": float(st.session_state.get(f"special_percent_{index}", 0.0)),
                "special_payments": collect_special_payments_for_state(index),
            }
        )

    data["portfolio"]["loans"] = loans
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def load_app_state_from_yaml(content: bytes) -> None:
    loaded = yaml.safe_load(content.decode("utf-8")) or {}
    portfolio = loaded.get("portfolio")
    if not isinstance(portfolio, dict):
        raise ValueError("Die YAML-Datei enthaelt keinen gueltigen 'portfolio'-Block.")

    loans = portfolio.get("loans")
    if not isinstance(loans, list) or not loans:
        raise ValueError("Die YAML-Datei enthaelt keine gueltigen Kredite.")

    st.session_state["loan_count"] = min(max(len(loans), 1), 5)
    st.session_state["max_months"] = int(portfolio.get("max_months", DEFAULT_MAX_MONTHS))

    for index, loan in enumerate(loans[:5]):
        if not isinstance(loan, dict):
            raise ValueError("Mindestens ein Kredit in der YAML-Datei ist ungueltig.")
        repayment_mode = str(loan.get("repayment_mode", "Prozent"))
        st.session_state[f"name_{index}"] = str(loan.get("name", f"kredit_{index + 1}"))
        st.session_state[f"principal_{index}"] = float(loan.get("principal_eur", 0.0))
        st.session_state[f"interest_{index}"] = float(loan.get("annual_interest_percent", 0.0))
        st.session_state[f"repayment_mode_{index}"] = (
            repayment_mode if repayment_mode in {"Prozent", "Feste Monatsrate"} else "Prozent"
        )
        st.session_state[f"repayment_percent_{index}"] = float(loan.get("annual_repayment_percent", 0.0))
        st.session_state[f"payment_amount_{index}"] = float(loan.get("monthly_payment_amount_eur", 0.0))
        st.session_state[f"interest_only_{index}"] = int(loan.get("interest_only_months", 0))
        st.session_state[f"special_percent_{index}"] = float(loan.get("annual_special_payment_percent", 0.0))
        special_payments = loan.get("special_payments", [])
        if not isinstance(special_payments, list):
            raise ValueError(f"Die Sonderzahlungen fuer Kredit {index + 1} sind ungueltig.")
        st.session_state[f"specials_{index}"] = [
            {
                "monat": int(item.get("monat", 0)),
                "betrag_eur": float(item.get("betrag_eur", 0.0)),
            }
            for item in special_payments
            if isinstance(item, dict)
        ] or default_special_payments()


def build_loan_from_inputs(index: int) -> LoanCalculator:
    loan_name = st.text_input(f"Kreditname {index + 1}", value=f"kredit_{index + 1}", key=f"name_{index}")
    principal_eur = st.number_input(
        f"Kreditsumme {index + 1} (EUR)",
        min_value=0.0,
        value=250000.0 if index == 0 else 100000.0,
        step=1000.0,
        key=f"principal_{index}",
    )

    repayment_mode = st.radio(
        f"Tilgungsmodus {index + 1}",
        options=["Prozent", "Feste Monatsrate"],
        horizontal=True,
        key=f"repayment_mode_{index}",
    )

    annual_repayment_percent = 0.0
    monthly_payment_amount_eur = 0.0

    if repayment_mode == "Prozent":
        annual_repayment_percent = st.number_input(
            f"Tilgung {index + 1} (% p.a.)",
            min_value=0.0,
            value=2.0 if index == 0 else 3.0,
            step=0.1,
            key=f"repayment_percent_{index}",
        )
    else:
        monthly_payment_amount_eur = st.number_input(
            f"Monatsrate {index + 1} gesamt (EUR)",
            min_value=0.0,
            value=1400.0 if index == 0 else 650.0,
            step=50.0,
            key=f"payment_amount_{index}",
        )

    loan = LoanCalculator(
        name=loan_name,
        principal_eur=principal_eur,
        annual_interest_percent=st.number_input(
            f"Zins {index + 1} (% p.a.)",
            min_value=0.0,
            value=3.5 if index == 0 else 2.8,
            step=0.1,
            key=f"interest_{index}",
        ),
        annual_repayment_percent=annual_repayment_percent,
        monthly_payment_amount_eur=monthly_payment_amount_eur,
        interest_only_months=st.number_input(
            f"Tilgungsfreie Monate {index + 1}",
            min_value=0,
            value=0,
            step=1,
            key=f"interest_only_{index}",
        ),
        annual_special_payment_percent=st.number_input(
            f"Erlaubte Sonderzahlung {index + 1} (% p.a.)",
            min_value=0.0,
            value=5.0,
            step=0.5,
            key=f"special_percent_{index}",
        ),
    )

    special_payments = st.data_editor(
        default_special_payments(),
        key=f"specials_{index}",
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "monat": st.column_config.NumberColumn("Monat", min_value=1, step=1),
            "betrag_eur": st.column_config.NumberColumn("Betrag (EUR)", min_value=0.0, step=100.0),
        },
    )

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


def build_laufzeit_table(detailed_schedule: pl.DataFrame, combined_schedule: pl.DataFrame) -> pl.DataFrame:
    per_loan = detailed_schedule.group_by("kredit").agg(pl.col("monat").max().alias("laufzeit_monate"))
    total = pl.DataFrame({"kredit": ["gesamt"], "laufzeit_monate": [combined_schedule["monat"].max()]})
    return pl.concat([per_loan, total], how="vertical").with_columns(
        pl.col("laufzeit_monate")
        .map_elements(lambda value: format_duration(int(value)), return_dtype=pl.String)
        .alias("laufzeit_text")
    ).select(["kredit", "laufzeit_text", "laufzeit_monate"])


def main() -> None:
    st.set_page_config(page_title="LoanCalc", page_icon=":material/account_balance:", layout="wide")
    st.title("LoanCalc")
    st.caption("Interaktive Berechnung mehrerer Kredite mit gemeinsamer Auswertung.")
    init_app_state()

    with st.sidebar:
        st.header("Portfolio")
        uploaded_file = st.file_uploader("YAML laden", type=["yaml", "yml"])
        if uploaded_file is not None:
            try:
                load_app_state_from_yaml(uploaded_file.getvalue())
                st.success("YAML-Datei geladen.")
            except ValueError as exc:
                st.error(str(exc))

        loan_count = st.slider("Anzahl Kredite", min_value=1, max_value=5, step=1, key="loan_count")
        max_months = st.slider(
            "Maximale Laufzeit in Monaten", min_value=12, max_value=720, step=12, key="max_months"
        )

    try:
        portfolio = LoanPortfolio()
        for index in range(loan_count):
            with st.expander(f"Kredit {index + 1}", expanded=True):
                loan = build_loan_from_inputs(index)
                portfolio.add_loan(loan)

        detailed_schedule = portfolio.create_detailed_schedule(max_months=max_months)
        combined_schedule = portfolio.create_combined_schedule(max_months=max_months)
    except ValueError as exc:
        st.error(str(exc))
        return

    if combined_schedule.is_empty():
        st.warning("Keine Kreditdaten vorhanden.")
        return

    combined_schedule_display = prepare_combined_schedule_for_display(combined_schedule)
    sorted_schedule = combined_schedule.sort("monat")
    first_row = sorted_schedule.head(1)
    last_row = sorted_schedule.tail(1)
    restschuld_total = last_row["restschuld_eur"].item()
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
            st.dataframe(
                detailed_schedule.with_columns(
                    pl.col("rate_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
                    pl.col("zinsen_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
                    pl.col("tilgung_eur").map_elements(lambda value: format_euro(float(value)), return_dtype=pl.String),
                    pl.col("sonderzahlung_eur").map_elements(
                        lambda value: format_euro(float(value)), return_dtype=pl.String
                    ),
                    pl.col("restschuld_eur").map_elements(
                        lambda value: format_euro(float(value)), return_dtype=pl.String
                    ),
                ),
                use_container_width=True,
                hide_index=True,
            )

    with st.sidebar:
        st.download_button(
            "YAML speichern",
            data=export_app_state_to_yaml(),
            file_name="loancalc-config.yaml",
            mime="application/x-yaml",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
