# LoanCalc

Kleiner Kreditrechner auf Basis von `uv` und `polars`.

## Installation

```bash
uv sync
```

Falls kein Netzwerk verfuegbar ist, sind `polars` und `streamlit` lokal noch nicht installierbar.

## Nutzung

```bash
uv run hello.py
uv run streamlit run app.py
uv run drklein_example.py
```

## Docker

Build:

```bash
docker build -t loancalc .
```

Start:

```bash
docker run --rm -p 8501:8501 loancalc
```

Oder mit Compose:

```bash
docker compose up -d --build
```

Die App ist dann unter `http://localhost:8501` erreichbar.

## Was die Klasse kann

- Kreditbetrag in Euro
- Sollzins in Prozent pro Jahr
- Anfaengliche Tilgung in Prozent pro Jahr oder als feste Monatsrate
- Tilgungsfreie Monate
- Maximal erlaubte Sonderzahlungen pro Jahr in Prozent
- Konkrete Sonderzahlungen per Monat und Betrag
- Optionale Markierung von Sonderzahlungen als Geschenk, damit sie die Restschuld senken, aber nicht in die Gesamtkosten laufen
- Rueckgabe eines Tilgungsplans als `polars.DataFrame`
- Mehrere parallele Kredite mit gemeinsamer Gesamttabelle
- Streamlit-App fuer interaktive Eingabe, Tabellen und Diagramme
- Laden und Speichern der Eingaben per YAML-Datei
- API-Client fuer Zinsabfragen ueber feste Laufzeiten
- Optionaler Sollzins-Abruf in der Streamlit-App auf Basis der Eingabedaten
- Zwei Szenarien mit Forking, Tabs und Gegenueberstellung

## Noch sinnvolle Felder

- Startdatum des Kredits fuer echte Monatsangaben
- Wahl, ob die Jahres-Sonderzahlung pro Kalenderjahr oder Vertragsjahr gilt
- Optional feste Monatsrate statt Ableitung aus Zins plus Tilgung
- Bereitstellungszinsen oder einmalige Nebenkosten

## YAML-Hinweis fuer Sonderzahlungen

`special_payments` unterstuetzt jetzt optional das Feld `geschenk`. Fehlt das Feld, bleibt das bisherige Verhalten aktiv.

```yaml
special_payments:
  - monat: 12
    betrag_eur: 5000
    geschenk: true
```
