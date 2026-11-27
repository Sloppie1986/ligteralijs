#!/usr/bin/env python3
"""Gemeten ijsdikte uit heel Nederland: verzamelen, op de kaart zetten en per plek
schatten hoeveel er tot morgenochtend bij komt.

Bronnen: forum Weerwoord (leden posten hun meting), IJsclub Vlietland (dagelijks ijsbericht),
Weerstation De Arend (schaatsnieuws), natuurijs-sites en de nieuwsfeeds van NOS en alle
regionale omroepen. Uit elke tekst halen we zinnen met "ijs" en een maat in cm of mm,
en we laten verwachtingen en vuistregels ("minimaal 8 cm", "komt nog 2 cm bij") weg.

Plaatsen: PDOK Locatieserver (alleen Nederland). Groei: Open-Meteo uurtemperatuur per plek
met de formule van Stefan, h² = h0² + a² · vorstgraaddagen. Geen sneeuw, wind of
bewolking meegerekend: een grove schatting, geen garantie.

Los te testen:  python3 -I ijsmetingen.py [vorige data.json]
"""
import json, math, re, sys, time, html, urllib.request, urllib.parse, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (schaatsmonitor; ijskaart)"}
AMS = dt.timezone(dt.timedelta(hours=1))   # wintertijd
A_STEFAN = 2.0      # cm per wortel(graaddag); voorzichtig voor helder ijs zonder sneeuw
MELT = 0.03         # cm per graad-uur boven nul (grof)
KEEP_HOURS = 72     # metingen zo lang op de kaart houden
MAX_ARTICLES = 12   # nieuwe nieuwsartikelen per run openen
errors = {}

NEWS_FEEDS = [
    ("NOS", "https://feeds.nos.nl/nosnieuwsbinnenland"),
    ("RTV Utrecht", "https://www.rtvutrecht.nl/rss/index.xml"),
    ("Omroep West", "https://www.omroepwest.nl/rss/index.xml"),
    ("Omroep Gelderland", "https://www.omroepgelderland.nl/rss"),
    ("RTV Noord", "https://www.rtvnoord.nl/rss/index.xml"),
    ("Omroep Brabant", "https://www.omroepbrabant.nl/rss"),
    ("RTV Oost", "https://www.rtvoost.nl/rss/index.xml"),
    ("RTV Drenthe", "https://www.rtvdrenthe.nl/rss/index.xml"),
    ("Omrop Fryslân", "https://www.omropfryslan.nl/rss/index.xml"),
    ("Omroep Leeuwarden", "https://omroepleeuwarden.nl/feed"),
    ("Natuurijswijzer", "https://www.natuurijswijzer.nl/feed/"),
    ("Nieuws uit Berkelland", "https://nieuwsuitberkelland.nl/feed/"),
]

# vaste plekken van bronnen die altijd over dezelfde plek gaan
FIXED = {
    "vlietland": ("IJsbaan Vlietland (Leidschendam)", 52.0985, 4.4205),
    "dearend": ("Kortenhoef (Wijdemeerse plassen)", 52.2385, 5.1050),
}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def text_of(fragment):
    fragment = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def iso(d):
    if d.tzinfo is None:
        d = d.replace(tzinfo=AMS)
    return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------ tekst -> meting
NUM = r"(\d{1,2}(?:[.,]\d{1,2})?)"
UNIT = r"\s*(cm|centimeter|mm|millimeter)\b"
RANGE = re.compile(NUM + r"(?:" + UNIT + r")?\s*(?:tot|à|a|á|-|–|en)\s*" + NUM + UNIT, re.I)
SINGLE = re.compile(NUM + UNIT, re.I)
NOT_MEASURED = re.compile(
    r"minimaal|minstens|tenminste|ten minste|nodig|vuistregel|moet|veilig|draagt|dragen|verwacht|prognose|model|pluim|"
    r"zou|zal |kan er|kunnen|komt .*bij|erbij|groei(t|en)? .*(nog|tot)|bij komt|aangroeien|morgen|vannacht nog|"
    r"neerslag|regen|sneeuw|hagel|elfstedentocht|toertocht|record|in 19\d\d|in 20[0-2]\d|vorig jaar|destijds", re.I)
AFTER_SKIP = re.compile(r"\s*(?:(?:van|uit|vanaf) de (?:kant|wal|oever)|diep|onder|water|sneeuw|regen|neerslag|hoog)", re.I)
ICE = re.compile(r"\bijs|ijsdikte|ijslaag|ijsvloer|dik\b|gemeten|meet\b", re.I)


def cm_value(num, unit):
    v = float(num.replace(",", "."))
    return v / 10 if unit.lower().startswith("m") else v


def measurements_in(text):
    """Geeft [(min_cm, max_cm, zin)] voor zinnen die een echte ijsmeting lijken.
    Verwachtingen en vuistregels vlak rond het getal ("minimaal 8 cm", "komt nog 2 cm bij") tellen niet."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        s = sent.strip()
        if len(s) < 6 or not ICE.search(s):
            continue
        vals, used = [], []
        for m in RANGE.finditer(s):
            if AFTER_SKIP.match(s, m.end()) or NOT_MEASURED.search(s[max(0, m.start() - 45):m.end() + 30]):
                used.append((m.start(), m.end()))
                continue
            u = m.group(4)
            vals.append((cm_value(m.group(1), m.group(2) or u), cm_value(m.group(3), u)))
            used.append((m.start(), m.end()))
        for m in SINGLE.finditer(s):
            if any(a <= m.start() < b for a, b in used):
                continue
            if AFTER_SKIP.match(s, m.end()) or NOT_MEASURED.search(s[max(0, m.start() - 45):m.end() + 30]):
                continue
            v = cm_value(m.group(1), m.group(2))
            vals.append((v, v))
        vals = [(min(a, b), max(a, b)) for a, b in vals if 0.2 <= min(a, b) and max(a, b) <= 40]
        if vals:
            out.append((round(min(v[0] for v in vals), 1), round(max(v[1] for v in vals), 1), s[:300]))
    return out


# ------------------------------------------------------------------ plaatsen
GEO = {}   # naam -> [lat, lon, weergave] of None


def geocode(name):
    key = name.strip().lower()
    if key in GEO:
        return GEO[key]
    hit = None
    for typ in ("woonplaats", "gemeente"):
        q = urllib.parse.urlencode({"q": name, "fq": "type:" + typ, "rows": 1})
        try:
            docs = json.loads(get("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?" + q, 15))["response"]["docs"]
        except Exception:
            docs = []
        if docs:
            d = docs[0]
            naam = d.get("woonplaatsnaam") or d.get("gemeentenaam") or ""
            if naam.lower().replace("-", " ") == key.replace("-", " ") or key in naam.lower():
                lon, lat = map(float, re.findall(r"[\d.]+", d["centroide_ll"]))
                hit = [round(lat, 4), round(lon, 4), d.get("weergavenaam") or naam]
                break
    GEO[key] = hit
    return hit


PLACE = re.compile(r"\b(?:in|op|bij|te|rond|nabij|vanuit|uit)\s+(?:de |het |'t )?([A-Z][a-zà-ÿ'’]+(?:[ -](?:aan|op|de|den|bij|en|[A-Z][a-zà-ÿ'’]+))*(?:[ -][A-Z][a-zà-ÿ'’]+)?)")
SKIP_WORDS = {"Nederland", "Friesland", "Holland", "Utrecht provincie", "Europa", "Duitsland", "Belgie", "België", "Twente", "Drenthe",
              "Groningen provincie", "Gelderland", "Overijssel", "Brabant", "Zeeland", "Limburg", "Flevoland", "Randstad", "De Bilt model"}


def find_place(*texts):
    for t in texts:
        for m in PLACE.finditer(t or ""):
            cand = m.group(1).strip(" -")
            if cand in SKIP_WORDS or len(cand) < 3:
                continue
            g = geocode(cand)
            if g:
                return cand, g
    return None, None


# ------------------------------------------------------------------ bronnen
def rss_items(xml):
    root = ET.fromstring(xml)
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            when = None
        body = (it.findtext("content:encoded", namespaces=ns) or "") + "\n" + (it.findtext("description") or "")
        body = re.sub(r"Het bericht .*? verscheen eerst op .*", "", text_of(body))
        yield {"title": (it.findtext("title") or "").strip(), "url": (it.findtext("link") or "").strip(), "time": when, "text": body}


def m_entry(source, place, geo, lo, hi, when, quote, url, kind="meting", who=None):
    return {"source": source, "place": place, "lat": geo[0], "lon": geo[1], "area": geo[2] if len(geo) > 2 else place,
            "min": lo, "max": hi, "cm": round((lo + hi) / 2, 1), "time": iso(when), "quote": quote, "url": url,
            "kind": kind, "who": who}


def src_vlietland(out):
    name, lat, lon = FIXED["vlietland"]
    for it in rss_items(get("https://ijsclubvlietland.nl/feed/")):
        if "ijsbericht" not in it["title"].lower() or not it["time"]:
            continue
        found = measurements_in(it["text"])
        if found:
            lo = min(f[0] for f in found); hi = max(f[1] for f in found)
            q = next((f[2] for f in found), "")
            out.append(m_entry("IJsclub Vlietland", name, [lat, lon, "Leidschendam-Voorburg"], lo, hi, it["time"], q, it["url"], "ijsbaan", "ijsclub"))


def src_dearend(out, dearend):
    name, lat, lon = FIXED["dearend"]
    for m in (dearend or {}).get("history") or []:
        when = dt.datetime.fromisoformat(m["time"]).replace(tzinfo=AMS)
        out.append(m_entry("Weerstation De Arend", name, [lat, lon, "Wijdemeren"], m["cm"], m["cm"], when, m["text"],
                           (dearend or {}).get("url") or "https://weerstationdearend.nl/schaatsnieuws/", "meting", "weerstation"))


def src_weerwoord(out, seen):
    raw = get("https://www.weerwoord.be/", 30)
    budget = 8
    for post in weerwoord_posts(raw):
        txt = post["title"] + ". " + post["text"]
        # de index toont maar het begin; bij ijsberichten de hele tekst ophalen (één keer per bericht)
        if ICE_NEWS.search(txt) and "ww" + post["id"] not in seen and budget > 0:
            budget -= 1
            seen["ww" + post["id"]] = iso(dt.datetime.now(dt.timezone.utc))
            try:
                full = get("https://www.weerwoord.be/api/getmessage?messageid=" + post["id"], 20)
                mc = re.search(r'<div id="message-content">(.*?)<a href="#" id="quote-message-div"', full, re.S)
                if mc:
                    txt = post["title"] + ". " + re.sub(r"https?://\S+", " ", text_of(mc.group(1)))
                    post["full"] = txt
            except Exception:
                pass
        found = measurements_in(txt)
        if not found:
            continue
        place = post.get("loc")
        geo = geocode(place) if place else None
        if not geo:
            place, geo = find_place(txt)
        if not geo:
            continue
        lo = min(f[0] for f in found); hi = max(f[1] for f in found)
        out.append(m_entry("Weerwoord", place, geo, lo, hi, post["time"], found[0][2], post["url"], "meting", post.get("author")))


def weerwoord_posts(raw):
    """Berichten uit de forumindex: titel, auteur (woonplaats), tijd, begin van de tekst, link.
    Alleen de openingsberichten staan met tekst in de index; reacties laadt de site pas met JavaScript."""
    posts = []
    parts = re.split(r'<div class="message_header" data-hide-threadid="(\d+)"', raw)
    for i in range(1, len(parts) - 1, 2):
        mid, block = parts[i], parts[i + 1][:6000]
        tt = re.search(r'class="[^"]*msg-title[^"]*">(.*?)</a>', block, re.S)
        meta = re.search(r'<small style="font-family[^>]*>(.*?)</small>', block, re.S)
        pv = re.search(r'data-message-preview-id="' + mid + r'">(.*?)</div>', block, re.S)
        if not tt or not meta:
            continue
        m = re.sub(r'<span class="msg-altitude">.*?</span>', "", meta.group(1), flags=re.S)
        m = text_of(m)
        tm = re.search(r"(\d{2})-(\d{2})-(\d{4})\s+(\d{1,2}):(\d{2})", m)
        if not tm:
            continue
        who = m[:tm.start()].replace("--", "").strip()
        loc = re.search(r"\(([^()]{2,40})\)\s*$", who)
        name = who[:loc.start()].strip() if loc else who
        place = loc.group(1).strip() if loc else (who.split()[-1] if len(who.split()) > 1 else None)
        when = dt.datetime(int(tm.group(3)), int(tm.group(2)), int(tm.group(1)), int(tm.group(4)), int(tm.group(5)), tzinfo=AMS)
        text = text_of(pv.group(1)) if pv else ""
        text = re.sub(r"\(link\)|https?://\S+|\.\.\.$", " ", text).strip()
        posts.append({"url": "https://www.weerwoord.be/m/" + mid, "id": mid, "time": when, "title": text_of(tt.group(1)),
                      "text": text[:800], "author": name or None, "loc": place})
    return posts


def src_app(out):
    """Metingen die gebruikers zelf in de app doorgeven (Supabase, alleen lezen met de openbare sleutel)."""
    try:
        cfg = json.load(open("site/config.json"))
    except Exception:
        return
    url, key = cfg.get("supabase_url"), cfg.get("supabase_key")
    if not url or not key:
        return
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=KEEP_HOURS)).isoformat().replace("+00:00", "Z")
    q = urllib.parse.urlencode({"select": "id,measured_at,name,cm,lat,lon,place,note,photo", "hidden": "eq.false",
                                "measured_at": "gte." + since, "order": "measured_at.desc", "limit": "300"})
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/reports?" + q, headers={**UA, "apikey": key, "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read())
    for r in rows:
        when = parse_iso(r["measured_at"])
        place = r.get("place") or "Eigen meting"
        e = m_entry("Gemeld in de app", place, [r["lat"], r["lon"], place], float(r["cm"]), float(r["cm"]), when,
                    r.get("note") or "", "https://sloppie1986.github.io/ligteralijs/#kaart", "gebruiker", r.get("name"))
        e["id"] = "sb:" + r["id"]
        e["photo"] = r.get("photo")
        out.append(e)


ICE_NEWS = re.compile(r"\bijs|schaats|natuurijs|ijsbaan|ijsclub|ijsmeester", re.I)


def src_news(out, seen_articles):
    budget = MAX_ARTICLES
    now = dt.datetime.now(dt.timezone.utc)
    for name, url in NEWS_FEEDS:
        try:
            items = list(rss_items(get(url)))
        except Exception as e:
            errors["nieuws " + name] = f"{type(e).__name__}: {e}"[:200]
            continue
        for it in items:
            if not it["time"] or now - it["time"] > dt.timedelta(hours=KEEP_HOURS):
                continue
            head = it["title"] + ". " + it["text"]
            if not ICE_NEWS.search(head):
                continue
            text = head
            found = measurements_in(text)
            if not found and it["url"] not in seen_articles and budget > 0:
                budget -= 1
                seen_articles[it["url"]] = iso(now)
                try:
                    page = get(it["url"])
                    art = re.search(r"(?is)<article.*?</article>", page)
                    text = head + "\n" + text_of(art.group(0) if art else page)
                    found = measurements_in(text)
                except Exception:
                    found = []
            for lo, hi, q in found[:3]:
                place, geo = find_place(q, it["title"], text[:1500])
                if geo:
                    out.append(m_entry(name, place, geo, lo, hi, it["time"], q, it["url"], "nieuws"))


# ------------------------------------------------------------------ groei tot morgenochtend
def target_time(now):
    loc = now.astimezone(AMS)
    t = loc.replace(hour=9, minute=0, second=0, microsecond=0)
    if loc >= t:
        t += dt.timedelta(days=1)
    return t


def temps_for(points):
    """Uurtemperatuur (2 dagen terug, 2 vooruit) per afgeronde plek, in één aanroep."""
    keys = sorted({(round(p["lat"], 1), round(p["lon"], 1)) for p in points})
    res = {}
    for i in range(0, len(keys), 40):
        chunk = keys[i:i + 40]
        q = urllib.parse.urlencode({"latitude": ",".join(str(k[0]) for k in chunk), "longitude": ",".join(str(k[1]) for k in chunk),
                                    "hourly": "temperature_2m", "past_days": 2, "forecast_days": 2, "timezone": "UTC"})
        js = json.loads(get("https://api.open-meteo.com/v1/forecast?" + q, 40))
        if isinstance(js, dict):
            js = [js]
        for k, j in zip(chunk, js):
            h = j["hourly"]
            res[k] = [(dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc), v) for t, v in zip(h["time"], h["temperature_2m"]) if v is not None]
    return res


OBS_HOURS = 36      # gemeten uurtemperaturen zo lang bewaren
MAX_KM = 50         # dichtstbijzijnde station moet binnen deze afstand liggen
BIAS_HOURS = 12     # verschil meting-model loopt in zoveel uur af naar nul


def km(a, b, c, d):
    p = math.pi / 180
    x = (d - b) * p * math.cos((a + c) / 2 * p)
    return 6371 * math.hypot(x, (c - a) * p)


def station_obs(old, now):
    """Gemeten temperatuur (1,5 m en 10 cm) van de KNMI-stations via de Buienradar-feed.
    Per station en per uur bewaard over de runs heen, zodat de groei sinds de meting met echte waarden wordt gerekend."""
    hist = {k: v for k, v in (old.get("obs") or {}).items()}
    d = json.loads(get("https://data.buienradar.nl/2.0/feed/json"))
    stations = {}
    for st in d["actual"]["stationmeasurements"]:
        t = st.get("temperature")
        if t is None or st.get("lat") is None or not st.get("timestamp"):
            continue
        name = st["stationname"].replace("Meetstation ", "")
        when = dt.datetime.fromisoformat(st["timestamp"][:19]).replace(tzinfo=AMS)
        if now - when > dt.timedelta(hours=2):
            continue
        stations[name] = {"lat": st["lat"], "lon": st["lon"], "temp": t, "ground": st.get("groundtemperature"), "time": iso(when)}
        hour = iso(when.replace(minute=0, second=0))
        rows = hist.setdefault(name, [])
        if rows and rows[-1][0] == hour:
            rows[-1] = [hour, round((rows[-1][1] * rows[-1][3] + t) / (rows[-1][3] + 1), 1), st.get("groundtemperature"), rows[-1][3] + 1]
        else:
            rows.append([hour, t, st.get("groundtemperature"), 1])
    for k in list(hist):
        hist[k] = [r for r in hist[k] if now - parse_iso(r[0]) < dt.timedelta(hours=OBS_HOURS)]
        if not hist[k]:
            del hist[k]
    return stations, hist


WOW_KM = 12         # een amateurstation telt alleen als het echt dichtbij ligt
WOW_MAXDIFF = 4.0   # en niet meer dan zoveel graden afwijkt van het dichtstbijzijnde KNMI-station


def wow_obs(now, official):
    """Amateurstations uit WOW (KNMI WOW-NL / KMI WOW-BE, één gezamenlijke kaart). Alleen Nederland en omgeving,
    alleen verse waarden, en alleen als ze redelijk overeenkomen met het dichtstbijzijnde KNMI-station."""
    d = json.loads(get("https://wow.meteo.be/api/v2/observation", timeout=40))
    out = {}
    for f in d.get("features") or []:
        lon, lat = f["geometry"]["coordinates"][:2]
        if not (50.75 <= lat <= 53.6 and 3.3 <= lon <= 7.25):
            continue
        pr = f.get("properties") or {}
        t = (pr.get("primary") or {}).get("dt")
        if t is None or not pr.get("timestamp") or not -30 < t < 30:
            continue
        when = dt.datetime.fromisoformat(pr["timestamp"])
        if now - when > dt.timedelta(minutes=75):
            continue
        ref = min(((km(lat, lon, v["lat"], v["lon"]), v) for v in official.values()), default=None, key=lambda x: x[0])
        if not ref or ref[0] > 40 or abs(t - ref[1]["temp"]) > WOW_MAXDIFF:
            continue
        name = (pr.get("name") or "WOW-station").strip()[:40]
        out["wow:" + pr.get("site_id", f.get("id", name))] = {"lat": lat, "lon": lon, "temp": round(t, 1), "ground": None,
                                                              "time": iso(when), "name": name, "amateur": True}
    return out


def add_obs(hist, key, st):
    hour = iso(parse_iso(st["time"]).replace(minute=0, second=0, microsecond=0))
    rows = hist.setdefault(key, [])
    if rows and rows[-1][0] == hour:
        rows[-1] = [hour, round((rows[-1][1] * rows[-1][3] + st["temp"]) / (rows[-1][3] + 1), 1), None, rows[-1][3] + 1]
    else:
        rows.append([hour, st["temp"], None, 1])


def corrected(series, obs_rows, st, now):
    """Modelreeks bijgesteld met metingen: verleden = gemeten uurtemperatuur, toekomst = model + afnemend verschil."""
    if not st:
        return series, None
    by_hour = {r[0][:13]: r[1] for r in obs_rows or []}
    model_now = min(series, key=lambda x: abs((x[0] - now).total_seconds()))[1] if series else None
    bias = round(st["temp"] - model_now, 1) if model_now is not None else 0.0
    out = []
    for t, v in series:
        if t <= now:
            v = by_hour.get(iso(t)[:13], v)
        else:
            f = max(0.0, 1 - (t - now).total_seconds() / 3600 / BIAS_HOURS)
            v = v + bias * f
        out.append((t, v))
    return out, {"model": model_now, "bias": bias, "hours_measured": sum(1 for t, _ in series if t <= now and iso(t)[:13] in by_hour)}


def grow(h0, series, t0, t1):
    h, fdd, tmin = h0, 0.0, None
    for t, temp in series:
        if t <= t0 or t > t1:
            continue
        tmin = temp if tmin is None else min(tmin, temp)
        if temp < 0:
            h = math.sqrt(h * h + A_STEFAN ** 2 * (-temp) / 24)
            fdd += -temp / 24
        else:
            h = max(0.0, h - MELT * temp)
    return round(h, 1), round(fdd, 2), tmin


def build(prev=None, dearend=None):
    now = dt.datetime.now(dt.timezone.utc)
    old = (prev or {}).get("ijskaart") or {}
    GEO.update(old.get("geocache") or {})
    seen_articles = {u: t for u, t in (old.get("seen") or {}).items() if now - parse_iso(t) < dt.timedelta(days=4)}
    found = []
    for name, fn, args in (("Weerwoord", src_weerwoord, (seen_articles,)), ("IJsclub Vlietland", src_vlietland, ()),
                           ("De Arend", src_dearend, (dearend,)), ("nieuws", src_news, (seen_articles,)), ("app", src_app, ())):
        try:
            fn(found, *args)
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"[:200]
    # samenvoegen met eerdere runs (forumindex en feeds schuiven door)
    allm = {}
    fresh_app = {m["id"] for m in found if m.get("id")}
    olds = [m for m in (old.get("measurements") or []) if not (str(m.get("id", "")).startswith("sb:") and "app" not in errors and m["id"] not in fresh_app)]
    for m in olds + found:
        if now - parse_iso(m["time"]) > dt.timedelta(hours=KEEP_HOURS) or parse_iso(m["time"]) > now + dt.timedelta(hours=1):
            continue
        key = m.get("id") or f'{m["url"]}|{m["place"]}|{m["min"]}|{m["max"]}'
        allm[key] = m
    ms = sorted(allm.values(), key=lambda m: m["time"], reverse=True)
    # per plek alleen de nieuwste meting op de kaart, de rest als geschiedenis
    points = {}
    for m in ms:
        k = m.get("id") or f'{m["place"].lower()}|{m["source"]}'
        if k not in points:
            points[k] = dict(m, history=[])
        elif len(points[k]["history"]) < 5:
            points[k]["history"].append({"cm": m["cm"], "min": m["min"], "max": m["max"], "time": m["time"], "url": m["url"]})
    points = list(points.values())
    tgt = target_time(now)
    try:
        temps = temps_for(points) if points else {}
    except Exception as e:
        errors["temperatuur"] = f"{type(e).__name__}: {e}"[:200]
        temps = {}
    try:
        stations, obs = station_obs(old, now)
    except Exception as e:
        errors["stations"] = f"{type(e).__name__}: {e}"[:200]
        stations, obs = {}, old.get("obs") or {}
    try:
        wow = wow_obs(now, stations) if stations else {}
    except Exception as e:
        errors["WOW"] = f"{type(e).__name__}: {e}"[:200]
        wow = {}
    used_wow = set()
    for p in points:
        series = temps.get((round(p["lat"], 1), round(p["lon"], 1)))
        if not series:
            continue
        t0 = parse_iso(p["time"])
        base = p["min"]   # voorzichtig: de dunste plek telt
        near = min(((km(p["lat"], p["lon"], v["lat"], v["lon"]), n) for n, v in stations.items()), default=None)
        st = stations[near[1]] if near and near[0] <= MAX_KM else None
        rows = obs.get(near[1]) if st else None
        # een goedgekeurd amateurstation vlakbij gaat voor als het dichterbij ligt dan het KNMI-station
        wnear = min(((km(p["lat"], p["lon"], v["lat"], v["lon"]), n) for n, v in wow.items()), default=None)
        if wnear and wnear[0] <= WOW_KM and (not near or wnear[0] < near[0]):
            near, st = wnear, wow[wnear[1]]
            if wnear[1] not in used_wow:
                add_obs(obs, wnear[1], st)
                used_wow.add(wnear[1])
            # uren zonder eigen meting van het amateurstation vullen met het KNMI-station
            rows = (rows or []) + obs[wnear[1]]
        fixed, corr = corrected(series, rows, st, now)
        p["model_morning_cm"], _, _ = grow(base, series, t0, tgt)
        p["now_cm"], _, _ = grow(base, fixed, t0, now)
        p["morning_cm"], p["fdd"], p["tmin"] = grow(base, fixed, t0, tgt)
        p["night_gain"] = round(p["morning_cm"] - p["now_cm"], 1)
        if st:
            p["station"] = {"name": st.get("name", near[1]), "km": round(near[0]), "temp": st["temp"], "ground": st["ground"],
                            "time": st["time"], "amateur": bool(st.get("amateur")), **corr}
    ground = [{"name": n, "lat": v["lat"], "lon": v["lon"], "ground": v["ground"], "temp": v["temp"], "time": v["time"]}
              for n, v in stations.items() if v.get("ground") is not None]
    # compacte lijst van alle stations voor "nu bij jou" in de app: [lat, lon, temp, naam, amateur]
    nearby = [[round(v["lat"], 3), round(v["lon"], 3), v["temp"], n, 0] for n, v in stations.items()] + \
             [[round(v["lat"], 3), round(v["lon"], 3), v["temp"], v["name"], 1] for v in wow.values()]
    return {"updated": iso(now), "target": iso(tgt), "points": points, "ground": ground, "wow_count": len(wow), "nearby": nearby, "measurements": ms[:200], "obs": obs,
            "geocache": GEO, "seen": seen_articles, "errors": errors, "a": A_STEFAN,
            "sources": ["Weerwoord (forum)", "IJsclub Vlietland"] + (["Weerstation De Arend"] if dearend else []) + [n for n, _ in NEWS_FEEDS]}


if __name__ == "__main__":
    prev = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else None
    r = build(prev, (prev or {}).get("schaatsnieuws"))
    for p in r["points"]:
        print(f'{p["time"][:16]} {p["source"][:14]:14} {p["place"][:24]:24} {p["min"]}-{p["max"]} cm  nu~{p.get("now_cm")}  ochtend~{p.get("morning_cm")} (model {p.get("model_morning_cm")})  {p.get("station")}')
    print("fouten:", json.dumps(r["errors"], ensure_ascii=False))
