from __future__ import annotations

from pprint import pprint

from drklein_api import DrKleinApiError, DrKleinRateClient, RateQuery


def main() -> None:
    client = DrKleinRateClient()
    query = RateQuery(
        kaufpreis_eur=100000,
        postleitzahl="44139",
        darlehensbetrag_eur=50000,
        monatliche_rate_eur=500,
        laufzeit_jahre=25,
    )

    payload = client.build_offer_payload(query)
    print("Payload:")
    print(payload.model_dump(by_alias=True))

    try:
        print("\nEinzelabfrage:")
        single_response = client.fetch_offer(payload)
        pprint(single_response)

        print("\nMehrere Laufzeiten:")
        results = client.fetch_rates_for_terms(query, [5, 11, 15, 20, 25])
        for result in results:
            print(
                {
                    "laufzeit_jahre": result.laufzeit_jahre,
                    "zinswerte": result.zinswerte,
                }
            )
    except DrKleinApiError as exc:
        print(f"API-Fehler: {exc}")


if __name__ == "__main__":
    main()
