from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

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
    annual_repayment_percent: Decimal | int | float | str
    interest_only_months: int = 0
    annual_special_payment_percent: Decimal | int | float | str = 0
    _special_payments: dict[int, Decimal] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.principal_eur = _to_decimal(self.principal_eur)
        self.annual_interest_percent = _to_decimal(self.annual_interest_percent)
        self.annual_repayment_percent = _to_decimal(self.annual_repayment_percent)
        self.annual_special_payment_percent = _to_decimal(self.annual_special_payment_percent)

        if self.principal_eur <= 0:
            raise ValueError("Der Kreditbetrag muss groesser als 0 sein.")
        if self.annual_interest_percent < 0:
            raise ValueError("Der Kreditzins darf nicht negativ sein.")
        if self.annual_repayment_percent < 0:
            raise ValueError("Die Tilgungsrate darf nicht negativ sein.")
        if self.interest_only_months < 0:
            raise ValueError("Tilgungsfreie Monate duerfen nicht negativ sein.")
        if self.annual_special_payment_percent < 0:
            raise ValueError("Sonderzahlungen pro Jahr duerfen nicht negativ sein.")
        if self.annual_interest_percent == 0 and self.annual_repayment_percent == 0:
            raise ValueError("Zins und Tilgung duerfen nicht gleichzeitig 0 sein.")

    def add_special_payment(self, month: int, amount_eur: Decimal | int | float | str) -> None:
        if month <= 0:
            raise ValueError("Der Abrechnungsmonat muss groesser als 0 sein.")
        amount = _round_money(_to_decimal(amount_eur))
        if amount <= 0:
            raise ValueError("Die Sonderzahlung muss groesser als 0 sein.")
        self._special_payments[month] = self._special_payments.get(month, Decimal("0")) + amount

    def create_schedule(self, max_months: int = 600) -> pl.DataFrame:
        if max_months <= 0:
            raise ValueError("max_months muss groesser als 0 sein.")

        balance = _round_money(self.principal_eur)
        monthly_interest_rate = self.annual_interest_percent / ONE_HUNDRED / TWELVE
        regular_annuity = self.principal_eur * (
            self.annual_interest_percent + self.annual_repayment_percent
        ) / ONE_HUNDRED / TWELVE
        annual_special_payment_cap = (
            self.principal_eur * self.annual_special_payment_percent / ONE_HUNDRED
        )

        rows: list[dict[str, object]] = []
        special_paid_by_year: dict[int, Decimal] = {}

        for month in range(1, max_months + 1):
            if balance <= 0:
                break

            year = ((month - 1) // 12) + 1
            interest = _round_money(balance * monthly_interest_rate)

            if month <= self.interest_only_months:
                scheduled_payment = interest
                principal_payment = Decimal("0")
            else:
                scheduled_payment = _round_money(regular_annuity)
                principal_payment = scheduled_payment - interest
                if principal_payment < 0:
                    principal_payment = Decimal("0")
                    scheduled_payment = interest

            principal_payment = min(principal_payment, balance)
            special_payment = min(
                self._allowed_special_payment(month, annual_special_payment_cap, special_paid_by_year),
                balance - principal_payment,
            )
            special_payment = max(_round_money(special_payment), Decimal("0"))

            remaining_balance = _round_money(balance - principal_payment - special_payment)
            actual_payment = _round_money(interest + principal_payment + special_payment)

            if special_payment > 0:
                special_paid_by_year[year] = special_paid_by_year.get(year, Decimal("0")) + special_payment

            rows.append(
                {
                    "kredit": self.name,
                    "monat": month,
                    "jahr": year,
                    "rate_eur": float(actual_payment),
                    "zinsen_eur": float(interest),
                    "tilgung_eur": float(principal_payment),
                    "sonderzahlung_eur": float(special_payment),
                    "restschuld_eur": float(remaining_balance),
                }
            )
            balance = remaining_balance

        return pl.DataFrame(rows)

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
                    "jahr": pl.Int64,
                    "rate_eur": pl.Float64,
                    "zinsen_eur": pl.Float64,
                    "tilgung_eur": pl.Float64,
                    "sonderzahlung_eur": pl.Float64,
                    "restschuld_eur": pl.Float64,
                }
            )

        schedules = [loan.create_schedule(max_months=max_months) for loan in self.loans]
        combined = pl.concat(schedules, how="vertical")

        return (
            combined.group_by(["monat", "jahr"])
            .agg(
                pl.col("rate_eur").sum(),
                pl.col("zinsen_eur").sum(),
                pl.col("tilgung_eur").sum(),
                pl.col("sonderzahlung_eur").sum(),
                pl.col("restschuld_eur").sum(),
            )
            .sort(["monat", "jahr"])
        )

    def create_detailed_schedule(self, max_months: int = 600) -> pl.DataFrame:
        if not self.loans:
            return pl.DataFrame(
                schema={
                    "kredit": pl.String,
                    "monat": pl.Int64,
                    "jahr": pl.Int64,
                    "rate_eur": pl.Float64,
                    "zinsen_eur": pl.Float64,
                    "tilgung_eur": pl.Float64,
                    "sonderzahlung_eur": pl.Float64,
                    "restschuld_eur": pl.Float64,
                }
            )

        return pl.concat(
            [loan.create_schedule(max_months=max_months) for loan in self.loans],
            how="vertical",
        ).sort(["monat", "kredit"])
