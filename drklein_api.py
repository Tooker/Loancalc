from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_HEADERS = {
    "Content-Type": "application/json;charset=utf-8",
    "Accept": "*/*",
    "Origin": "https://www.drklein.de",
    "Referer": "https://www.drklein.de/finanzierungsrechner.html",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Safari/605.1.15"
    ),
}

RATE_KEYS = (
    "sollzins",
    "sollZins",
    "nominalzins",
    "nominalZins",
    "effektivzins",
    "effektivZins",
    "zins",
    "zinssatz",
)


class DrKleinApiError(RuntimeError):
    pass


class ImmobiliePayload(BaseModel):
    kauf_preis: float = Field(alias="kaufPreis")
    postleitzahl: str

    model_config = ConfigDict(populate_by_name=True)


class FinanzierungPayload(BaseModel):
    darlehensbetrag: float
    monatliche_rate: float | None = Field(default=None, alias="monatlicheRate")
    auszahlungstermin: str | None = None
    finanzierungszweck: str = "KAUF"
    tilgungssatz: float | None = None
    darlehensart: str = "ANNUITAET"
    laufzeit: int

    model_config = ConfigDict(populate_by_name=True)


class AngebotPayload(BaseModel):
    immobilie: ImmobiliePayload
    finanzierung: FinanzierungPayload

    model_config = ConfigDict(populate_by_name=True)


class RateQuery(BaseModel):
    kaufpreis_eur: float
    postleitzahl: str
    darlehensbetrag_eur: float
    monatliche_rate_eur: float | None = None
    laufzeit_jahre: int
    finanzierungszweck: str = "KAUF"
    darlehensart: str = "ANNUITAET"
    auszahlungstermin: str | None = None
    tilgungssatz: float | None = None


class RateResult(BaseModel):
    laufzeit_jahre: int
    zinswerte: dict[str, float]
    response: dict[str, Any]


class DrKleinRateClient(BaseModel):
    endpoint: str = "https://www.drklein.de/rest-api/tav/angebot"
    headers: dict[str, str] = Field(default_factory=lambda: DEFAULT_HEADERS.copy())
    timeout_seconds: float = 20.0

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def build_offer_payload(self, query: RateQuery) -> AngebotPayload:
        return AngebotPayload(
            immobilie=ImmobiliePayload(
                kaufPreis=query.kaufpreis_eur,
                postleitzahl=query.postleitzahl,
            ),
            finanzierung=FinanzierungPayload(
                darlehensbetrag=query.darlehensbetrag_eur,
                monatlicheRate=query.monatliche_rate_eur,
                auszahlungstermin=query.auszahlungstermin,
                finanzierungszweck=query.finanzierungszweck,
                tilgungssatz=query.tilgungssatz,
                darlehensart=query.darlehensart,
                laufzeit=query.laufzeit_jahre,
            ),
        )

    def fetch_offer(self, payload: AngebotPayload) -> dict[str, Any]:
        body = payload.model_dump_json(by_alias=True).encode("utf-8")
        request = Request(self.endpoint, data=body, headers=self.headers, method="POST")

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DrKleinApiError(f"HTTP {exc.code} von Dr. Klein API: {detail}") from exc
        except URLError as exc:
            raise DrKleinApiError(f"Netzwerkfehler bei Dr. Klein API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise DrKleinApiError("Antwort der Dr. Klein API war kein gueltiges JSON.") from exc

    def fetch_rates_for_terms(
        self,
        base_query: RateQuery,
        terms_years: list[int],
    ) -> list[RateResult]:
        results: list[RateResult] = []

        for term in terms_years:
            query = base_query.model_copy(update={"laufzeit_jahre": term})
            payload = self.build_offer_payload(query)
            response = self.fetch_offer(payload)
            results.append(
                RateResult(
                    laufzeit_jahre=term,
                    zinswerte=self.extract_rate_candidates(response),
                    response=response,
                )
            )

        return results

    def extract_rate_candidates(self, data: Any) -> dict[str, float]:
        candidates: dict[str, float] = {}
        self._collect_rate_candidates(data, candidates)
        return candidates

    def extract_preferred_rate(self, data: Any) -> float:
        candidates = self.extract_rate_candidates(data)
        for key in RATE_KEYS:
            if key in candidates:
                return candidates[key]
        raise DrKleinApiError("In der API-Antwort wurde kein passender Zinswert gefunden.")

    def _collect_rate_candidates(self, value: Any, candidates: dict[str, float]) -> None:
        if isinstance(value, dict):
            for key, nested_value in value.items():
                if key in RATE_KEYS and isinstance(nested_value, int | float):
                    candidates[key] = float(nested_value)
                self._collect_rate_candidates(nested_value, candidates)
            return

        if isinstance(value, list):
            for item in value:
                self._collect_rate_candidates(item, candidates)
