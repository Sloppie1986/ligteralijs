# Ligt er al ijs?

Weer, vorst, een ijsindicator en alle laatste berichten van weermannen, X-accounts, YouTube en het Noodweer-forum voor Midden-Nederland, op één pagina.

**App:** https://sloppie1986.github.io/ligteralijs/

## Hoe het werkt
- `monitor.py` haalt alle bronnen op en schrijft `data.json` (alleen Python-standaardbibliotheek, plus Pillow voor plaatjes).
- `site/index.html` is de app. Hij leest `data.json` en kijkt elke 15 minuten of er nieuwe data is.
- `.github/workflows/update.yml` draait elke 15 minuten op GitHub Actions en zet het resultaat op GitHub Pages. Er wordt niets gecommit; de vorige `data.json` wordt van de live site gelezen.

## Instellingen (Settings → Secrets and variables → Actions)
- `X_BEARER_TOKEN`: token van de X API, voor de posts van de weermannen.
- `NTFY_TOPIC` (optioneel): een zelfbedachte, moeilijk te raden naam. Installeer de app *ntfy* op je telefoon en abonneer je op dezelfde naam om meldingen te krijgen bij nieuwe waarschuwingen, ijs of een nieuwe kaartendraad.

## Bronnen
Open-Meteo / MET Norway, KNMI via MeteoAlarm, Buienradar, NoodweerBenelux (artikelen en Disqus-forum), Wintersportweerman, Kai Zorn Wetter, Sneeuwhoogte.nl, Meteo Kortenhoef (De Arend), X API. Alle inhoud blijft van de oorspronkelijke makers; elk bericht linkt naar het origineel.
