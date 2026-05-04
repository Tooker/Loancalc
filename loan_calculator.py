from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import polars as pl


TWOPLACES = Decimal("0.01")
TWELVE = Decimal("12")
ONE_HUNDRED = Decimal("100")


def _to_decimal(value: int | float | str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class LoanCalculator:
    name: str
    principal_eur: Decimal | int | float | str
    annual_interest_percent: Decimal | int | float | str
    annual_repayment_percent: Decimal | int | float | str = 0
    monthly_payment_amount_eur: Decimal | int | float | str = 0
    interest_only_months: int = 0
    fixed_interest_months: int = 0
    annual_special_payment_percent: Decimal | int | float | str = 0
    follow_up_enabled: bool = False
    follow_up_annual_interest_percent: Decimal | int | float | str = 0
    follow_up_annual_repayment_percent: Decimal | int | float | str = 0
    follow_up_monthly_payment_amount_eur: Decimal | int | float | str = 0
    follow_up_interest_only_months: int = 0
    follow_up_fixed_interest_months: int = 0
    follow_up_annual_special_payment_percent: Decimal | int | float | str = 0
    _drawdowns: dict[int, Decimal] = field(default_factory=dict, init=False)
    _special_payments: dict[int, Decimal] = field(default_factory=dict, init=False)
    _gift_special_payments: dict[int, Decimal] = field(default_factory=dict, init=False)
    _payment_changes: dict[int, Decimal] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.principal_eur = _to_decimal(self.principal_eur)
        self.annual_interest_percent = _to_decimal(self.annual_interest_percent)
        self.annual_repayment_percent = _to_decimal(self.annual_repayment_percent)
        self.monthly_payment_amount_eur = _to_decimal(self.monthly_payment_amount_eur)
        self.annual_special_payment_percent = _to_decimal(self.annual_special_payment_percent)
        self.follow_up_annual_interest_percent = _to_decimal(self.follow_up_annual_interest_percent)
        self.follow_up_annual_repayment_percent = _to_decimal(self.follow_up_annual_repayment_percent)
        self.follow_up_monthly_payment_amount_eur = _to_decimal(self.follow_up_monthly_payment_amount_eur)
        self.follow_up_annual_special_payment_percent = _to_decimal(self.follow_up_annual_special_payment_percent)

        if self.principal_eur <= 0:
            raise ValueError("Der Kreditbetrag muss groesser als 0 sein.")
        if self.annual_interest_percent < 0:
            raise ValueError("Der Kreditzins darf nicht negativ sein.")
        if self.annual_repayment_percent < 0:
            raise ValueError("Die Tilgungsrate darf nicht negativ sein.")
        if self.monthly_payment_amount_eur < 0:
            raise ValueError("Die feste Monatsrate darf nicht negativ sein.")
        if self.interest_only_months < 0:
            raise ValueError("Tilgungsfreie Monate duerfen nicht negativ sein.")
        if self.fixed_interest_months < 0:
            raise ValueError("Die Festzinszeit darf nicht negativ sein.")
        if self.annual_special_payment_percent < 0:
            raise ValueError("Sonderzahlungen pro Jahr duerfen nicht negativ sein.")
        if self.annual_repayment_percent > 0 and self.monthly_payment_amount_eur > 0:
            raise ValueError("Bitte entweder Tilgung in Prozent oder eine feste Monatsrate setzen.")
        if self.annual_interest_percent == 0 and self.annual_repayment_percent == 0 and self.monthly_payment_amount_eur == 0:
            raise ValueError("Zins und Tilgung duerfen nicht gleichzeitig 0 sein.")
        if self.follow_up_enabled:
            if self.follow_up_annual_interest_percent < 0:
                raise ValueError("Der Anschlusszins darf nicht negativ sein.")
            if self.follow_up_annual_repayment_percent < 0:
                raise ValueError("Die Anschlusstilgung darf nicht negativ sein.")
            if self.follow_up_monthly_payment_amount_eur < 0:
                raise ValueError("Die Anschluss-Monatsrate darf nicht negativ sein.")
            if self.follow_up_interest_only_months < 0:
                raise ValueError("Tilgungsfreie Monate der Anschlussfinanzierung duerfen nicht negativ sein.")
            if self.follow_up_fixed_interest_months <= 0:
                raise ValueError("Die Festzinszeit der Anschlussfinanzierung muss groesser als 0 sein.")
            if self.follow_up_annual_special_payment_percent < 0:
                raise ValueError("Sonderzahlungen der Anschlussfinanzierung duerfen nicht negativ sein.")
            if self.follow_up_annual_repayment_percent > 0 and self.follow_up_monthly_payment_amount_eur > 0:
                raise ValueError("Bitte fuer die Anschlussfinanzierung entweder Tilgung in Prozent oder eine feste Monatsrate setzen.")
            if (
                self.follow_up_annual_interest_percent == 0
                and self.follow_up_annual_repayment_percent == 0
                and self.follow_up_monthly_payment_amount_eur == 0
            ):
                raise ValueError("Zins und Tilgung der Anschlussfinanzierung duerfen nicht gleichzeitig 0 sein.")

    def add_drawdown(self, month: int, percent: Decimal | int | float | str) -> None:
        if month <= 0:
            raise ValueError("Der Abrufmonat muss groesser als 0 sein.")
        drawdown_percent = _to_decimal(percent)
        if drawdown_percent <= 0:
            raise ValueError("Der Abruf-Prozentwert muss groesser als 0 sein.")
        updated_percent = self._drawdowns.get(month, Decimal("0")) + drawdown_percent
        total_percent = sum(self._drawdowns.values(), Decimal("0")) - self._drawdowns.get(month, Decimal("0")) + updated_percent
        if total_percent > ONE_HUNDRED:
            raise ValueError(f"Kredit '{self.name}': Die Abruftranchen duerfen zusammen hoechstens 100 % ergeben.")
        self._drawdowns[month] = updated_percent

    def add_special_payment(
        self,
        month: int,
        amount_eur: Decimal | int | float | str,
        is_gift: bool = False,
    ) -> None:
        if month <= 0:
            raise ValueError("Der Abrechnungsmonat muss groesser als 0 sein.")
        amount = _round_money(_to_decimal(amount_eur))
        if amount <= 0:
            raise ValueError("Die Sonderzahlung muss groesser als 0 sein.")
        updated_amount = self._special_payments.get(month, Decimal("0")) + amount
        self._validate_special_payment_limit(month=month, amount_eur=updated_amount)
        self._special_payments[month] = updated_amount
        if is_gift:
            self._gift_special_payments[month] = self._gift_special_payments.get(month, Decimal("0")) + amount

    def add_payment_change(
        self,
        month: int,
        monthly_payment_amount_eur: Decimal | int | float | str,
    ) -> None:
        if month <= 0:
            raise ValueError("Der Monat fuer die Ratenaenderung muss groesser als 0 sein.")
        payment_amount = _round_money(_to_decimal(monthly_payment_amount_eur))
        if payment_amount <= 0:
            raise ValueError("Die neue Monatsrate muss groesser als 0 sein.")
        self._payment_changes[month] = payment_amount

    def create_schedule(self, max_months: int = 600) -> pl.DataFrame:
        if max_months <= 0:
            raise ValueError("max_months muss groesser als 0 sein.")

        rows: list[dict[str, object]] = []
        global_month = 1
        round_number = 1
        round_principal = _round_money(self.principal_eur)

        while global_month <= max_months and round_principal > 0:
            balance, global_month = self._append_financing_round(
                rows=rows,
                max_months=max_months,
                global_start_month=global_month,
                round_number=round_number,
                round_principal=round_principal,
            )

            if balance <= 0 or not self.follow_up_enabled or global_month > max_months:
                break

            round_number += 1
            round_principal = self._round_up_to_thousand(balance)

        return pl.DataFrame(rows)

    def _append_financing_round(
        self,
        rows: list[dict[str, object]],
        max_months: int,
        global_start_month: int,
        round_number: int,
        round_principal: Decimal,
    ) -> tuple[Decimal, int]:
        is_follow_up = round_number > 1
        annual_interest_percent = self.follow_up_annual_interest_percent if is_follow_up else self.annual_interest_percent
        annual_repayment_percent = self.follow_up_annual_repayment_percent if is_follow_up else self.annual_repayment_percent
        monthly_payment_amount_eur = self.follow_up_monthly_payment_amount_eur if is_follow_up else self.monthly_payment_amount_eur
        interest_only_months = self.follow_up_interest_only_months if is_follow_up else self.interest_only_months
        fixed_interest_months = self.follow_up_fixed_interest_months if is_follow_up else self.fixed_interest_months
        annual_special_payment_percent = (
            self.follow_up_annual_special_payment_percent if is_follow_up else self.annual_special_payment_percent
        )
        drawdowns = {1: ONE_HUNDRED} if is_follow_up else (self._drawdowns or {1: ONE_HUNDRED})

        balance = Decimal("0")
        cumulative_drawdown_percent = Decimal("0")
        monthly_interest_rate = annual_interest_percent / ONE_HUNDRED / TWELVE
        monthly_payment = self._monthly_payment_amount_for(round_principal, annual_interest_percent, annual_repayment_percent, monthly_payment_amount_eur)
        annual_special_payment_cap = round_principal * annual_special_payment_percent / ONE_HUNDRED
        special_paid_by_year: dict[int, Decimal] = {}
        round_limit = fixed_interest_months if fixed_interest_months > 0 else max_months - global_start_month + 1

        for month_in_round in range(1, round_limit + 1):
            global_month = global_start_month + month_in_round - 1
            if global_month > max_months:
                return balance, global_month
            if balance <= 0 and month_in_round > max(drawdowns):
                return balance, global_month

            year = ((global_month - 1) // 12) + 1
            drawdown_percent = drawdowns.get(month_in_round, Decimal("0"))
            drawdown_amount = _round_money(round_principal * drawdown_percent / ONE_HUNDRED)
            cumulative_drawdown_percent += drawdown_percent
            balance = _round_money(balance + drawdown_amount)

            interest = _round_money(balance * monthly_interest_rate)
            monthly_payment = self._payment_amount_for_month(global_month, monthly_payment)

            if month_in_round <= interest_only_months:
                scheduled_payment = interest
                principal_payment = Decimal("0")
            else:
                scheduled_payment = monthly_payment
                principal_payment = scheduled_payment - interest
                if principal_payment < 0:
                    principal_payment = Decimal("0")
                    scheduled_payment = interest

            principal_payment = min(principal_payment, balance)
            requested_special_payment = self._allowed_special_payment(global_month, annual_special_payment_cap, special_paid_by_year)
            special_payment = min(requested_special_payment, balance - principal_payment)
            special_payment = max(_round_money(special_payment), Decimal("0"))
            gift_special_payment = self._gift_special_payment(global_month, requested_special_payment, special_payment)
            actual_payment = interest + principal_payment + special_payment
            cost_relevant_payment = _round_money(_round_money(actual_payment) - gift_special_payment)
            remaining_balance = _round_money(balance - principal_payment - special_payment)

            if special_payment > 0:
                special_paid_by_year[year] = special_paid_by_year.get(year, Decimal("0")) + special_payment

            rows.append(
                {
                    "kredit": self.name,
                    "runde": round_number,
                    "monat": global_month,
                    "monat_in_runde": month_in_round,
                    "jahr": year,
                    "auszahlung_eur": float(drawdown_amount),
                    "abruf_prozent": float(drawdown_percent),
                    "abruf_kumuliert_prozent": float(cumulative_drawdown_percent),
                    "finanzierter_betrag_eur": float(round_principal),
                    "rate_eur": float(actual_payment),
                    "zinsen_eur": float(interest),
                    "tilgung_eur": float(principal_payment),
                    "sonderzahlung_eur": float(special_payment),
                    "sonderzahlung_geschenk_eur": float(gift_special_payment),
                    "kosten_eur": float(cost_relevant_payment),
                    "restschuld_eur": float(remaining_balance),
                }
            )
            balance = remaining_balance

        return balance, global_start_month + round_limit

    def _allowed_special_payment(
        self,
        month: int,
        annual_special_payment_cap: Decimal,
        special_paid_by_year: dict[int, Decimal],
    ) -> Decimal:
        requested_payment = self._special_payments.get(month, Decimal("0"))
        if requested_payment <= 0:
            return Decimal("0")
        if annual_special_payment_cap <= 0:
            return Decimal("0")

        year = ((month - 1) // 12) + 1
        already_paid = special_paid_by_year.get(year, Decimal("0"))
        remaining_cap = annual_special_payment_cap - already_paid
        if remaining_cap <= 0:
            return Decimal("0")
        return min(requested_payment, remaining_cap)

    def _gift_special_payment(
        self,
        month: int,
        requested_special_payment: Decimal,
        actual_special_payment: Decimal,
    ) -> Decimal:
        if actual_special_payment <= 0 or requested_special_payment <= 0:
            return Decimal("0")

        requested_gift_payment = self._gift_special_payments.get(month, Decimal("0"))
        if requested_gift_payment <= 0:
            return Decimal("0")

        if actual_special_payment >= requested_special_payment:
            return min(_round_money(requested_gift_payment), actual_special_payment)

        proportional_gift_payment = actual_special_payment * requested_gift_payment / requested_special_payment
        return min(_round_money(proportional_gift_payment), actual_special_payment)

    def _monthly_payment_amount(self) -> Decimal:
        return self._monthly_payment_amount_for(
            self.principal_eur,
            self.annual_interest_percent,
            self.annual_repayment_percent,
            self.monthly_payment_amount_eur,
        )

    def _monthly_payment_amount_for(
        self,
        principal_eur: Decimal,
        annual_interest_percent: Decimal,
        annual_repayment_percent: Decimal,
        monthly_payment_amount_eur: Decimal,
    ) -> Decimal:
        if monthly_payment_amount_eur > 0:
            return _round_money(monthly_payment_amount_eur)

        payment = principal_eur * (annual_interest_percent + annual_repayment_percent) / ONE_HUNDRED / TWELVE
        return _round_money(payment)

    def _round_up_to_thousand(self, value: Decimal) -> Decimal:
        return (value / Decimal("1000")).to_integral_value(rounding=ROUND_CEILING) * Decimal("1000")

    def _payment_amount_for_month(self, month: int, current_payment: Decimal) -> Decimal:
        return self._payment_changes.get(month, current_payment)

    def _validate_special_payment_limit(self, month: int, amount_eur: Decimal) -> None:
        year = ((month - 1) // 12) + 1
        annual_cap = _round_money(self.principal_eur * self.annual_special_payment_percent / ONE_HUNDRED)
        year_total = amount_eur

        for existing_month, existing_amount in self._special_payments.items():
            existing_year = ((existing_month - 1) // 12) + 1
            if existing_year == year and existing_month != month:
                year_total += existing_amount

        if annual_cap <= 0:
            raise ValueError(
                f"Kredit '{self.name}': Sonderzahlungen sind nicht erlaubt, das Jahreslimit liegt bei 0 €."
            )

        if year_total > annual_cap:
            raise ValueError(
                f"Kredit '{self.name}': Sonderzahlungen in Jahr {year} uebersteigen das erlaubte Jahreslimit "
                f"von {annual_cap} €."
            )


@dataclass(slots=True)
class LoanPortfolio:
    loans: list[LoanCalculator] = field(default_factory=list)

    def add_loan(self, loan: LoanCalculator) -> None:
        if any(existing_loan.name == loan.name for existing_loan in self.loans):
            raise ValueError(f"Ein Kredit mit dem Namen '{loan.name}' existiert bereits.")
        self.loans.append(loan)

    def create_combined_schedule(self, max_months: int = 600) -> pl.DataFrame:
        if not self.loans:
            return pl.DataFrame(
                schema={
                    "monat": pl.Int64,
                    "runde": pl.Int64,
                    "monat_in_runde": pl.Int64,
                    "jahr": pl.Int64,
                    "auszahlung_eur": pl.Float64,
                    "abruf_prozent": pl.Float64,
                    "abruf_kumuliert_prozent": pl.Float64,
                    "finanzierter_betrag_eur": pl.Float64,
                    "rate_eur": pl.Float64,
                    "zinsen_eur": pl.Float64,
                    "tilgung_eur": pl.Float64,
                    "sonderzahlung_eur": pl.Float64,
                    "sonderzahlung_geschenk_eur": pl.Float64,
                    "kosten_eur": pl.Float64,
                    "restschuld_eur": pl.Float64,
                }
            )

        schedules = [loan.create_schedule(max_months=max_months) for loan in self.loans]
        combined = pl.concat(schedules, how="vertical")

        return (
            combined.group_by(["monat", "jahr"])
            .agg(
                pl.col("rate_eur").sum(),
                pl.col("auszahlung_eur").sum(),
                pl.col("finanzierter_betrag_eur").sum(),
                pl.col("abruf_prozent").sum(),
                pl.col("abruf_kumuliert_prozent").max(),
                pl.col("zinsen_eur").sum(),
                pl.col("tilgung_eur").sum(),
                pl.col("sonderzahlung_eur").sum(),
                pl.col("sonderzahlung_geschenk_eur").sum(),
                pl.col("kosten_eur").sum(),
                pl.col("restschuld_eur").sum(),
            )
            .sort(["monat", "jahr"])
        )

    def create_detailed_schedule(self, max_months: int = 600) -> pl.DataFrame:
        if not self.loans:
            return pl.DataFrame(
                schema={
                    "kredit": pl.String,
                    "runde": pl.Int64,
                    "monat": pl.Int64,
                    "monat_in_runde": pl.Int64,
                    "jahr": pl.Int64,
                    "auszahlung_eur": pl.Float64,
                    "abruf_prozent": pl.Float64,
                    "abruf_kumuliert_prozent": pl.Float64,
                    "finanzierter_betrag_eur": pl.Float64,
                    "rate_eur": pl.Float64,
                    "zinsen_eur": pl.Float64,
                    "tilgung_eur": pl.Float64,
                    "sonderzahlung_eur": pl.Float64,
                    "sonderzahlung_geschenk_eur": pl.Float64,
                    "kosten_eur": pl.Float64,
                    "restschuld_eur": pl.Float64,
                }
            )

        return pl.concat(
            [loan.create_schedule(max_months=max_months) for loan in self.loans],
            how="vertical",
        ).sort(["monat", "kredit"])
