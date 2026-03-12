from decimal import Decimal

from loan_calculator import LoanCalculator, LoanPortfolio


def main() -> None:
    loan_a = LoanCalculator(
        name="kredit_a",
        principal_eur=300_000,
        annual_interest_percent=3.8,
        annual_repayment_percent=2.0,
        interest_only_months=3,
        annual_special_payment_percent=5.0,
    )
    loan_a.add_special_payment(month=12, amount_eur=Decimal("5000"))
    loan_a.add_special_payment(month=24, amount_eur=Decimal("7500"))

    loan_b = LoanCalculator(
        name="kredit_b",
        principal_eur=120_000,
        annual_interest_percent=2.9,
        monthly_payment_amount_eur=650.0,
        interest_only_months=0,
        annual_special_payment_percent=10.0,
    )
    loan_b.add_special_payment(month=6, amount_eur=Decimal("3000"))
    loan_b.add_special_payment(month=18, amount_eur=Decimal("4500"))

    portfolio = LoanPortfolio()
    portfolio.add_loan(loan_a)
    portfolio.add_loan(loan_b)

    combined_schedule = portfolio.create_combined_schedule(max_months=36)
    detailed_schedule = portfolio.create_detailed_schedule(max_months=36)

    print("Gesamttabelle:")
    print(combined_schedule)
    print("\nDetailtabelle:")
    print(detailed_schedule)


if __name__ == "__main__":
    main()
