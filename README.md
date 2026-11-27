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

## Instagram-voorstellen (@ligteralijs)

`insta.py` draait elk kwartier na de monitor. Bij belangrijk ijsnieuws (ijsverwachting verandert, nieuwe ijsmeting,
ijsstatus bij De Arend, strenge nachtvorst, code oranje/rood) maakt het een voorstelbericht: bijschrift (door Claude,
met vaste hashtags en de korte link `is.gd/ligteralijs`) plus een plaatje van 1080×1080. Dat komt als **issue** in deze repo
(plaatje op de branch `instagram`) en, als het secret `NTFY_INSTA_TOPIC` gezet is, als ntfy-melding met plaatje op je telefoon.
Er wordt nooit automatisch gepost. Hooguit één voorstel per 6 uur, behalve als de ijsverwachting zelf verandert.
