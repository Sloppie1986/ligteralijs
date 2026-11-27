#!/usr/bin/env python3
"""Schaatsmonitor Midden-Nederland: haalt alle bronnen op en schrijft data.json.

Gebruik:  python3 -I monitor.py <uitvoer.json> [vorige.json]
Alleen standaardbibliotheek. Elke bron faalt los: een fout komt in 'errors'.
Met een vorige data.json worden 'alerts' berekend (relevante veranderingen).
"""
import json, math, re, sys, time, html, urllib.request, urllib.parse, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

LAT, LON = 52.10, 5.18          # De Bilt, midden van Nederland
UA = {"User-Agent": "Mozilla/5.0 (schaatsmonitor)"}
TZ = dt.timezone(dt.timedelta(hours=1))  # wintertijd; ruim genoeg voor weergave
errors = {}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def text_of(fragment):
    fragment = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def iso(d):
    try:
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def safe(name):  # noqa
    def deco(fn):
        def run(*a):
            try:
                return fn(*a)
            except Exception as e:  # bron mag de rest niet breken
                errors[name] = f"{type(e).__name__}: {e}"[:300]
                return None
        return run
    return deco


# ---------------------------------------------------------------- plaatjes
IMG_CACHE = {}   # bron-url -> data-uri (gevuld uit vorige run)


def get_bytes(url, limit=6_000_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limit)


def thumb(url, size=640):
    """Download een plaatje en maak er een kleine JPEG data-URI van (pagina mag geen externe plaatjes laden)."""
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return None
    if IMG_CACHE.get(url):
        return IMG_CACHE[url]
    raw_url = url
    url = re.sub(r"^https://i\d\.ytimg\.com/", "https://i.ytimg.com/", url)
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@~!$'()*[]")
    if url in IMG_CACHE:
        return IMG_CACHE[url]
    try:
        import io, base64
        from PIL import Image
        im = Image.open(io.BytesIO(get_bytes(url)))
        im.seek(0)
        im = im.convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=58, optimize=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        errors.setdefault("plaatjes", f"{type(e).__name__}: {e}"[:200])
        uri = None
    IMG_CACHE[url] = IMG_CACHE[raw_url] = uri
    return uri


def og_image(page_url):
    try:
        h = get(page_url)
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', h) or \
            re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', h)
        return html.unescape(m.group(1)) if m else None
    except Exception:
        return None


def add_images(posts, prev_posts):
    """Zet per bericht 'img' (data-URI). Hergebruikt bron-urls uit de vorige run."""
    prev_src = {p.get("url"): p.get("img_src") for p in prev_posts or [] if p.get("img_src")}
    og_budget = 12
    for p in posts:
        src = p.get("img_src") or prev_src.get(p.get("url"))
        if not src and p.get("url") and p["source"] in ("Wintersportweerman", "Meteo Kortenhoef (De Arend)", "NoodweerBenelux") and og_budget > 0:
            og_budget -= 1
            src = og_image(p["url"])
        p["img_src"] = src
        p["img"] = thumb(src) if src else None


# ---------------------------------------------------------------- weer
OM_BLOCK = {}


def forecast(prev=None):
    today = dt.datetime.now(TZ).date().isoformat()
    om_err = None
    if ((prev or {}).get("om_blocked") or "") != today:
        try:
            d = forecast_openmeteo()
            d["provider"] = "Open-Meteo (KNMI/ECMWF)"
            return d
        except Exception as e:
            om_err = f"{type(e).__name__}: {e}"[:300]
            if "429" in om_err:
                OM_BLOCK["day"] = today   # daglimiet op: rest van de dag niet meer proberen
    else:
        OM_BLOCK["day"] = today
    try:
        d = forecast_met()
        d["provider"] = "MET Norway (ECMWF)"
        return d
    except Exception as e:
        errors["met.no"] = f"{type(e).__name__}: {e}"[:300]
        if om_err:
            errors["open-meteo"] = om_err
    return None


SYM = {"clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45, "lightrain": 61, "rain": 63,
       "heavyrain": 65, "lightsnow": 71, "snow": 73, "heavysnow": 75, "sleet": 67, "lightsleet": 66,
       "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82, "lightsnowshowers": 85,
       "snowshowers": 85, "heavysnowshowers": 86, "sleetshowers": 85, "thunder": 95}


def wmo(sym):
    base = (sym or "").split("_")[0]
    if "thunder" in base:
        return 95
    return SYM.get(base, 3)


def forecast_met():
    d = json.loads(get("https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=%.2f&lon=%.2f" % (LAT, LON)))
    ts = d["properties"]["timeseries"]
    loc = lambda t: dt.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(TZ)
    hourly = {"time": [], "temperature_2m": [], "precipitation": [], "snowfall": [], "wind_speed_10m": [], "cloud_cover": []}
    days = {}
    for e in ts:
        t = loc(e["time"]); det = e["data"]["instant"]["details"]
        temp = det.get("air_temperature")
        n1 = e["data"].get("next_1_hours") or {}
        n6 = e["data"].get("next_6_hours") or {}
        pr = (n1.get("details") or {}).get("precipitation_amount")
        sym = (n1.get("summary") or n6.get("summary") or {}).get("symbol_code")
        hourly["time"].append(t.strftime("%Y-%m-%dT%H:00"))
        hourly["temperature_2m"].append(temp)
        hourly["precipitation"].append(pr)
        hourly["snowfall"].append(None)
        hourly["wind_speed_10m"].append(round(det.get("wind_speed", 0) * 3.6, 1))
        hourly["cloud_cover"].append(det.get("cloud_area_fraction"))
        dd = days.setdefault(t.date().isoformat(), {"t": [], "p": 0.0, "w": [], "sym": []})
        dd["t"].append(temp); dd["w"].append(det.get("wind_speed", 0) * 3.6)
        if pr is not None:
            dd["p"] += pr
        elif n1 == {} and (n6.get("details") or {}).get("precipitation_amount") is not None:
            dd["p"] += n6["details"]["precipitation_amount"]
        if sym:
            dd["sym"].append(wmo(sym))
    daily = {k: [] for k in ("time", "temperature_2m_min", "temperature_2m_max", "temperature_2m_mean",
                             "precipitation_sum", "snowfall_sum", "wind_speed_10m_max", "weather_code")}
    for day, v in sorted(days.items()):
        if len(v["t"]) < 3:
            continue
        daily["time"].append(day); daily["temperature_2m_min"].append(min(v["t"]))
        daily["temperature_2m_max"].append(max(v["t"])); daily["temperature_2m_mean"].append(round(sum(v["t"]) / len(v["t"]), 1))
        daily["precipitation_sum"].append(round(v["p"], 1)); daily["snowfall_sum"].append(None)
        daily["wind_speed_10m_max"].append(round(max(v["w"]), 0))
        daily["weather_code"].append(max(v["sym"]) if v["sym"] else 3)
    first = ts[0]["data"]["instant"]["details"]
    cur = {"time": loc(ts[0]["time"]).strftime("%Y-%m-%dT%H:%M"), "temperature_2m": first.get("air_temperature"),
           "wind_speed_10m": round(first.get("wind_speed", 0) * 3.6, 1), "wind_direction_10m": first.get("wind_from_direction"),
           "weather_code": wmo(((ts[0]["data"].get("next_1_hours") or {}).get("summary") or {}).get("symbol_code"))}
    return {"current": cur, "hourly": hourly, "daily": daily}


def forecast_openmeteo():
    base = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
            "&timezone=Europe%%2FAmsterdam" % (LAT, LON))
    d = json.loads(get(base +
        "&current=temperature_2m,apparent_temperature,wind_speed_10m,wind_direction_10m,weather_code,snow_depth"
        "&hourly=temperature_2m,precipitation,snowfall,wind_speed_10m,cloud_cover"
        "&daily=temperature_2m_min,temperature_2m_max,temperature_2m_mean,precipitation_sum,snowfall_sum,wind_speed_10m_max,weather_code"
        "&past_days=21&forecast_days=16&wind_speed_unit=kmh"))
    return d


@safe("buienradar")
def buienradar():
    d = json.loads(get("https://data.buienradar.nl/2.0/feed/json"))
    st = [s for s in d["actual"]["stationmeasurements"]
          if any(k in s.get("stationname", "") for k in ("De Bilt", "Hilversum", "Utrecht", "Lelystad", "Soesterberg"))]
    rep = d.get("forecast", {}).get("weatherreport", {})
    short = d.get("forecast", {}).get("shortterm", {})
    longt = d.get("forecast", {}).get("longterm", {})
    return {
        "stations": [{"name": s["stationname"].replace("Meetstation ", ""), "temp": s.get("temperature"),
                      "ground": s.get("groundtemperature"), "feel": s.get("feeltemperature"),
                      "wind": s.get("windspeedBft"), "winddir": s.get("winddirection"),
                      "desc": s.get("weatherdescription"), "time": s.get("timestamp")} for s in st],
        "report": {"title": rep.get("title"), "summary": rep.get("summary"),
                   "text": re.sub(r"([a-z])\.([A-Z])", r"\1. \2", text_of(rep.get("text", "")))[:2500], "published": rep.get("published"),
                   "author": rep.get("author")},
        "shortterm": short.get("forecast"), "longterm": longt.get("forecast"),
    }


def point_in_poly(lat, lon, poly):
    pts = [tuple(map(float, p.split(","))) for p in poly.split()]
    inside = False
    for i in range(len(pts)):
        (a1, b1), (a2, b2) = pts[i], pts[i - 1]
        if (b1 > lon) != (b2 > lon) and lat < (a2 - a1) * (lon - b1) / (b2 - b1) + a1:
            inside = not inside
    return inside


@safe("meteoalarm")
def warnings():
    d = json.loads(get("https://feeds.meteoalarm.org/api/v1/warnings/feeds-netherlands"))
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for w in d.get("warnings", []):
        for info in w["alert"].get("info", []):
            if not info.get("language", "").lower().startswith("nl"):
                continue
            try:
                exp = dt.datetime.fromisoformat(info.get("expires"))
                if exp < now:
                    continue
            except Exception:
                pass
            hit = any(point_in_poly(LAT, LON, p) or point_in_poly(52.24, 5.10, p)
                      for a in info.get("area", []) for p in a.get("polygon", []))
            if not hit:
                continue
            p = {x["valueName"]: x["value"] for x in info.get("parameter", [])}
            lvl = p.get("awareness_level", "")
            out.append({"event": info.get("event"), "headline": info.get("headline"),
                        "description": info.get("description"), "level": lvl.split(";")[-1].strip(),
                        "level_n": int(lvl.split(";")[0]) if lvl[:1].isdigit() else 0,
                        "onset": info.get("onset"), "expires": info.get("expires")})
    uniq = {}
    for o in out:
        uniq[(o["event"], o["onset"], o["level"])] = o
    return sorted(uniq.values(), key=lambda o: (o["onset"] or ""))


# ---------------------------------------------------------------- berichten
def parse_feed(xml, source, url, limit=8):
    root = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
          "slash": "http://purl.org/rss/1.0/modules/slash/", "content": "http://purl.org/rss/1.0/modules/content/"}
    items = []
    for it in root.iter("item"):
        when = it.findtext("pubDate")
        try:
            when = iso(parsedate_to_datetime(when))
        except Exception:
            when = None
        desc = text_of(it.findtext("description") or "")
        desc = re.sub(r"The post .*? appeared first on .*$", "", desc).strip()
        com = it.findtext("slash:comments", namespaces=ns)
        rawhtml = (it.findtext("content:encoded", namespaces=ns) or "") + (it.findtext("description") or "")
        im = re.search(r'<img[^>]+src="([^"]+)"', rawhtml)
        enc = it.find("enclosure")
        img = im.group(1) if im else (enc.get("url") if enc is not None and "image" in (enc.get("type") or "") else None)
        items.append({"source": source, "title": (it.findtext("title") or "").strip(),
                      "url": it.findtext("link"), "time": when, "summary": desc[:400], "img_src": img,
                      "comments": int(com) if com and com.isdigit() else None})
    for e in root.findall("a:entry", ns):
        link = e.find("a:link", ns)
        desc = e.findtext("media:group/media:description", namespaces=ns) or ""
        th = e.find("media:group/media:thumbnail", ns)
        items.append({"source": source, "title": (e.findtext("a:title", namespaces=ns) or "").strip(),
                      "img_src": th.get("url") if th is not None else None,
                      "url": link.get("href") if link is not None else url,
                      "time": iso(dt.datetime.fromisoformat(e.findtext("a:published", namespaces=ns))),
                      "summary": desc.strip()[:400], "comments": None})
    items.sort(key=lambda i: i["time"] or "", reverse=True)
    return items[:limit]


FEEDS = [
    ("noodweer", "NoodweerBenelux", "https://www.noodweer.be/feed/", "https://www.noodweer.be"),
    ("wintersportweerman", "Wintersportweerman", "https://wintersportweerman.nl/feed", "https://wintersportweerman.nl"),
    ("kaizorn", "Kai Zorn Wetter (YouTube)", "https://www.youtube.com/feeds/videos.xml?channel_id=UCfZhCLT9UmzRl1byZguPoHA",
     "https://www.youtube.com/@KaiZornWetter"),
    ("dearend-feed", "Meteo Kortenhoef (De Arend)", "https://weerstationdearend.nl/feed/", "https://weerstationdearend.nl"),
]


def feeds():
    out = []
    for key, name, url, home in FEEDS:
        try:
            out += parse_feed(get(url), name, home)
        except Exception as e:
            errors[key] = f"{type(e).__name__}: {e}"[:300]
    return out


FORUM_PREFIX = "weerbericht-komende-dagen"


@safe("noodweer-forum")
def noodweer_forum():
    """Actuele kaartendraad van NoodweerBenelux.

    1. Zoek via de WordPress-API de artikelen met 'weerbericht komende dagen'; houd alleen
       slugs die beginnen met 'weerbericht-komende-dagen-' (andere artikelen vallen af).
    2. Neem de nieuwste die in Disqus niet op slot staat (isClosed=False).
    3. Haal de 50 nieuwste reacties op (Disqus geeft ze nieuwste eerst).
    Waarschuwing in 'check' als de draad op slot staat of ouder is dan 10 dagen."""
    lst = json.loads(get("https://www.noodweer.be/wp-json/wp/v2/posts?search=weerbericht%20komende%20dagen"
                         "&per_page=10&orderby=date&order=desc&_fields=id,slug,date,link,title"))
    cands = [a for a in lst if a.get("slug", "").startswith(FORUM_PREFIX)]
    if not cands:
        return {"check": "Geen artikel 'Weerbericht komende dagen' gevonden op noodweer.be", "posts": []}
    chosen, thread, posts, check = None, None, [], None
    for a in cands[:3]:
        tu = urllib.parse.quote("https://www.noodweer.be/?p=%d" % a["id"], safe="")
        raw = get("https://disqus.com/embed/comments/?base=default&f=noodweer&t_i=%d%%20%s&t_u=%s" % (a["id"], tu, tu))
        m = re.search(r'id="disqus-threadData">(.*?)</script>', raw, re.S)
        d = json.loads(html.unescape(m.group(1)) if "&quot;" in m.group(1)[:50] else m.group(1))
        th = d["response"]["thread"]
        if chosen is None or not th.get("isClosed"):
            chosen, thread, posts = a, th, d["response"]["posts"]
        if not th.get("isClosed"):
            break
    age = (dt.datetime.now() - dt.datetime.fromisoformat(chosen["date"])).days
    if thread.get("isClosed"):
        check = "Let op: de nieuwste kaartendraad staat op slot; mogelijk is er nog geen nieuwe draad."
    elif age > 10:
        check = f"Let op: de kaartendraad is al {age} dagen oud; mogelijk is er een nieuwe die nog niet gevonden wordt."
    out = []
    for p in posts:
        if p.get("isDeleted") or p.get("isSpam") or not p.get("isApproved", True):
            continue
        imgs = []
        for md in p.get("media") or []:
            u = md.get("resolvedUrl") or md.get("thumbnailUrl")
            if u and len(imgs) < 2 and re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", u, re.I):
                imgs.append({"src": u, "img": thumb(u, 640)})
        msg = re.sub(r'<a [^>]*href="https://uploads\.disquscdn\.com[^"]*"[^>]*>.*?</a>', "", p.get("message") or "", flags=re.S)
        out.append({"author": (p.get("author") or {}).get("name") or "Anoniem",
                    "time": p["createdAt"] + "Z", "text": text_of(msg)[:1200], "likes": p.get("likes", 0),
                    "reply": bool(p.get("parent")), "images": imgs, "id": p.get("id")})
    out.sort(key=lambda x: x["time"], reverse=True)
    title = html.unescape((chosen.get("title") or {}).get("rendered") or chosen["slug"])
    return {"title": title, "url": chosen["link"], "closed": bool(thread.get("isClosed")),
            "total": thread.get("posts"), "started": chosen["date"], "check": check, "posts": out}


@safe("dearend")
def dearend():
    raw = get("https://weerstationdearend.nl/")
    t = text_of(raw)
    flat = re.sub(r"\s+", " ", t)
    warn = re.search(r"Waarschuwingen (.*?)(Schaatsnieuws|15daagse)", flat)
    news = re.search(r"Schaatsnieuws (.*?)(15daagse|Weerpluim|❄️)", flat[flat.find("Waarschuwingen"):] if "Waarschuwingen" in flat else flat)
    ice = []
    for m in re.finditer(r"❄️\s*([^❄️🏞⛸]+?)\s+((?:(?:🏞️|⛸️)[^❄]*?)+)(?=❄️|Home|$)", flat):
        place = m.group(1).strip()
        for s in re.finditer(r"(🏞️|⛸️)\s*(.+?)\s+(❌|✅|🔒|🔓|⚠️|🟢|🟡|🔴)\s*([^🏞⛸❄]+?)(?=\s*(?:🏞️|⛸️|$))", m.group(2)):
            ice.append({"place": place, "spot": s.group(2).strip(), "status": s.group(4).strip(),
                        "icon": s.group(3), "kind": "ijsclub" if s.group(1) == "⛸️" else "water"})
    return {"warning": warn.group(1).strip() if warn else None,
            "news": news.group(1).strip() if news else None, "ice": ice,
            "url": "https://weerstationdearend.nl/"}


MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]


@safe("schaatsnieuws")
def schaatsnieuws():
    """Gemeten ijsdikte uit 'Schaatsnieuws' van Weerstation De Arend (Kortenhoef), plus de KNMI-ijspluim."""
    url = "https://weerstationdearend.nl/schaatsnieuws/"
    raw = get(url)
    t = text_of(raw)
    body = t.split("Schaatsnieuws", 3)[-1]
    now = dt.datetime.now(TZ)
    # blokken per datum ("26 november ...")
    parts = re.split(r"(?m)^\s*(\d{1,2}) (" + "|".join(MAANDEN) + r")\b", body)
    measurements = []
    for i in range(1, len(parts) - 2, 3):
        day, month, block = int(parts[i]), MAANDEN.index(parts[i + 1]) + 1, parts[i + 2]
        year = now.year - (1 if month > now.month else 0)
        cur_time = "00:00"
        for line in block.split("\n"):
            em = re.search(r"Edit:?\s*(\d{1,2})\s*[:.]\s*(\d{2})", line)
            if em:
                cur_time = f"{int(em.group(1)):02d}:{em.group(2)}"
            for sent in re.split(r"(?<=[.!?])\s+", line):
                cm = re.search(r"(\d+(?:[.,]\d+)?)\s*cm", sent)
                if not cm or not re.search(r"ijs|dik|aangegroeid|sloot", sent, re.I) or re.search(r"staan|aanbevolen|veilig", sent, re.I):
                    continue
                # bij "van 1 naar 2,1 cm" telt het laatste getal
                nums = re.findall(r"(\d+(?:[.,]\d+)?)\s*cm", sent)
                measurements.append({"cm": float(nums[-1].replace(",", ".")), "text": sent.strip(),
                                     "time": f"{year}-{month:02d}-{day:02d}T{cur_time}"})
    latest = max(measurements, key=lambda m: m["time"]) if measurements else None
    knmi = re.findall(r"https://cdn\.knmi\.nl/[^\"' ]+PLUIM_(\d+)_IJS\.png", raw)
    pluim = "https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/extra/PLUIM_06260_IJS.png"
    return {"url": url, "latest": latest, "history": sorted(measurements, key=lambda m: m["time"])[-8:],
            "knmi_pluim_src": pluim if "06260" in knmi or not knmi else pluim,
            "knmi_url": "https://www.knmi.nl/nederland-nu/weer/waarschuwingen-en-verwachtingen/extra/ijsdikte-watertemperatuur"}


@safe("sneeuwhoogte")
def sneeuwhoogte():
    raw = get("https://www.sneeuwhoogte.nl/")
    flat = re.sub(r"\s+", " ", text_of(raw))
    m = re.search(r"Meer (\d{1,2} \w+ 20\d\d) (.*?)(?:Lees verder|360°|Verwachte sneeuw)", flat)
    if not m:
        return None
    body = m.group(2).strip()
    title, _, rest = body.partition(" ")
    # De kop is het eerste korte stuk vóór de lopende tekst
    hm = re.match(r"(.{3,60}?) ([A-Z][a-z].*)", body)
    if hm:
        title, rest = hm.group(1), hm.group(2)
    im = re.search(r'(https://d3mvaf8qqycz4r\.cloudfront\.net/[^"\' )]+\.(?:jpe?g|png|webp))', raw)
    return {"source": "Sneeuwhoogte.nl", "title": title, "summary": rest[:500], "img_src": im.group(1) if im else None,
            "date": m.group(1), "url": "https://www.sneeuwhoogte.nl/", "time": None, "comments": None}


# ---------------------------------------------------------------- ijs
# Modellen voor de ijsindicator, in volgorde van voorkeur (fijnmazig eerst). Per dag tellen de eerste 3
# die die dag volledig dekken. Fijnmazige modellen reiken maar ~2 dagen; daarna nemen de beste
# middelfijne en wereldmodellen het over.
ICE_MODELS = [
    ("knmi_harmonie_arome_netherlands", "HARMONIE (KNMI, 2 km)"),
    ("dwd_icon_d2", "ICON-D2 (DWD, 2 km)"),
    ("meteofrance_arome_france_hd", "AROME (Météo-France, 1,5 km)"),
    ("ecmwf_ifs", "ECMWF IFS (9 km)"),
    ("icon_eu", "ICON-EU (DWD, 7 km)"),
    ("ukmo_seamless", "UKMO (Met Office, 10 km)"),
    ("dwd_icon", "ICON (DWD, 13 km)"),
    ("gfs_seamless", "GFS (NOAA, 13-25 km)"),
]


def ice_ensemble():
    """Daggemiddelde/min/max per dag als gemiddelde van de 3 beste beschikbare modellen, plus spreiding."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%.2f&longitude=%.2f&hourly=temperature_2m"
           "&timezone=Europe%%2FAmsterdam&past_days=1&forecast_days=10&models=%s") % (LAT, LON, ",".join(m for m, _ in ICE_MODELS))
    for attempt in range(3):
        try:
            h = json.loads(get(url, timeout=40))["hourly"]
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    per = {}   # dag -> model -> [temps]
    for m, _ in ICE_MODELS:
        vals = h.get("temperature_2m_" + m) or []
        for t, v in zip(h["time"], vals):
            if v is not None:
                per.setdefault(t[:10], {}).setdefault(m, []).append(v)
    out = {}
    names = dict(ICE_MODELS)
    for day, ms in per.items():
        full = [m for m, _ in ICE_MODELS if len(ms.get(m, [])) >= 22][:3]
        if not full:
            continue
        stats = [(min(ms[m]), max(ms[m]), sum(ms[m]) / len(ms[m])) for m in full]
        means = [x[2] for x in stats]
        out[day] = {
            "tmin": round(sum(x[0] for x in stats) / len(stats), 1),
            "tmax": round(sum(x[1] for x in stats) / len(stats), 1),
            "tmean": round(sum(means) / len(means), 1),
            "spread": round(max(means) - min(means), 1),
            "models": [names[m] for m in full],
            "per_model": {names[m]: round(x[2], 1) for m, x in zip(full, stats)},
            "min_per_model": {names[m]: round(x[0], 1) for m, x in zip(full, stats)},
        }
    return out


def ice_model(fc, prev=None, ens=None):
    """Ruwe natuurijs-indicator uit daggemiddelde temperatuur (graaddagen vorst).

    Aanname: vorstsom stijgt met -Tgem op vriesdagen en zakt met Tgem op dooidagen.
    Ijsdikte ≈ 1.5 * sqrt(vorstsom) cm (voorzichtige Stefan-benadering voor
    stilstaand, ondiep water zonder sneeuwdek). Geen meting; altijd ijsmeester checken.
    """
    d = fc["daily"]
    today = dt.datetime.now(TZ).date().isoformat()
    series = {}
    # verleden dagen uit vorige runs bewaren (MET Norway geeft geen verleden)
    for r in ((prev or {}).get("ice") or {}).get("rows") or []:
        if r["date"] < today:
            series[r["date"]] = (r["tmin"], r["tmax"], r["tmean"])
    for day, tmin, tmax, tmean in zip(d["time"], d["temperature_2m_min"], d["temperature_2m_max"], d["temperature_2m_mean"]):
        if tmean is not None and (day >= today or day not in series):
            series[day] = (tmin, tmax, tmean)
    for day, e in (ens or {}).items():   # modelgemiddelde gaat voor
        if day >= today or day not in series:
            series[day] = (e["tmin"], e["tmax"], e["tmean"])
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=30)).isoformat()
    s, rows = 0.0, []
    for day in sorted(series):
        if day < cutoff:
            continue
        tmin, tmax, tmean = series[day]
        s = max(0.0, s - tmean) if tmean < 0 else max(0.0, s - tmean * 1.5)
        cm = round(1.5 * math.sqrt(s), 1)
        row = {"date": day, "tmin": tmin, "tmax": tmax, "tmean": tmean,
               "fdd": round(s, 1), "cm": cm, "forecast": day >= today}
        if day in (ens or {}) and day >= today:
            row.update({k: ens[day][k] for k in ("spread", "models", "per_model", "min_per_model")})
        rows.append(row)
    def level(cm):
        if cm < 2: return 0
        if cm < 5: return 1
        if cm < 8: return 2
        if cm < 12: return 3
        return 4
    now = next((r for r in rows if r["date"] == today), rows[-1] if rows else None)
    peak = max((r for r in rows if r["forecast"]), key=lambda r: r["cm"], default=None)
    labels = ["Geen ijs", "Dun laagje, niet op", "Landijsbanen mogelijk", "Ondiep natuurijs mogelijk", "Kans op toertochten"]
    for r in rows:
        r["level"] = level(r["cm"])
    return {"rows": rows, "today": now, "peak": peak, "labels": labels,
            "level": level(now["cm"]) if now else 0, "peak_level": level(peak["cm"]) if peak else 0}


DAGDELEN = [(0, "nacht"), (6, "ochtend"), (12, "middag"), (18, "avond")]


COLD_WORDS = ["vorst", "vries", "bevr", "ijs", "schaats", "koud", "kou ", "kou,", "kou.", "winter", "sneeuw", "oostenwind",
              "oosten", "noordoost", "ijzig", "elfsteden", "toertocht", "ijsdag", "strenge", "scandinavisch", "siberi",
              "blocking", "hoog boven scandinavi", "graaddag", "onder nul", "min ", "-5", "-6", "-7", "-8", "-9", "-10"]
MILD_WORDS = ["dooi", "zacht", "mild", "westenwind", "zuidwest", "zuidwesten", "opwarming", "warmer", "regen", "storm",
              "atlantisch", "boven nul", "voorjaar", "doorbraak", "einde vorst", "geen ijs", "niet koud", "valt tegen",
              "teleurstell", "jammer", "helaas"]


def message_mood(data):
    """Grove 'stemming' in de berichten van de laatste 6 uur: hoeveel berichten gaan over kou/ijs en hoeveel over zacht weer.
    Telt woorden; geen echte taalanalyse."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)).isoformat()[:19]
    texts = []
    for p in data.get("posts") or []:
        if (p.get("time") or "")[:19] >= since:
            texts.append(" ".join(str(p.get(k) or "") for k in ("title", "summary", "text")))
    for p in ((data.get("forum") or {}).get("posts") or []) + (data.get("comments") or []):
        if (p.get("time") or "")[:19] >= since:
            texts.append(str(p.get("text") or p.get("summary") or ""))
    cold = mild = 0
    for t in texts:
        t = " " + t.lower() + " "
        c = sum(t.count(w) for w in COLD_WORDS)
        m = sum(t.count(w) for w in MILD_WORDS)
        if c > m: cold += 1
        elif m > c: mild += 1
    n = len(texts)
    return {"n": n, "cold": cold, "mild": mild, "index": round((cold - mild) / n, 2) if n else 0}


def ice_trend(ice, prev, mood=None):
    """Per dagdeel één momentopname van de ijsverwachting, om te zien of het de goede kant op gaat.
    Binnen hetzelfde dagdeel wordt de momentopname steeds overschreven door de nieuwste run."""
    now = dt.datetime.now(TZ)
    part = [n for h, n in DAGDELEN if now.hour >= h][-1]
    key = f"{now.date().isoformat()} {part}"
    fc = [r for r in ice["rows"] if r["forecast"]]
    snap = {
        "key": key, "part": part, "date": now.date().isoformat(), "at": now.isoformat(timespec="minutes"),
        "peak_cm": ice["peak"]["cm"] if ice.get("peak") else 0,
        "peak_date": ice["peak"]["date"] if ice.get("peak") else None,
        # vorstsom: opgetelde graden onder nul (daggemiddelde) over alle voorspelde dagen
        "frost": round(sum(-r["tmean"] for r in fc if r["tmean"] is not None and r["tmean"] < 0), 1),
        "coldest": min((r["tmin"] for r in fc if r["tmin"] is not None), default=None),
        "frost_nights": sum(1 for r in fc if r["tmin"] is not None and r["tmin"] < 0),
        "days": len(fc),
        "mood": mood or {"n": 0, "cold": 0, "mild": 0, "index": 0},
    }
    hist = [h for h in ((prev or {}).get("ice_trend") or []) if h.get("key") != key]
    hist.append(snap)
    hist = sorted(hist, key=lambda h: h["at"])[-12:]   # laatste 3 dagen
    for i, h in enumerate(hist):
        if i == 0:
            h["dir"] = None
            continue
        p = hist[i - 1]
        # score: ijsdikte weegt zwaarst, dan vorstsom, dan koudste nacht
        d = (h["peak_cm"] - p["peak_cm"]) * 2 + (h["frost"] - p["frost"]) \
            + ((p["coldest"] - h["coldest"]) * 0.5 if h["coldest"] is not None and p["coldest"] is not None else 0)
        h["score"] = round(d, 1)
        h["dir"] = "beter" if d >= 0.5 else "slechter" if d <= -0.5 else "gelijk"
        pm, hm = p.get("mood") or {}, h.get("mood") or {}
        if hm.get("n", 0) >= 3 and pm.get("n", 0) >= 3:
            dm = hm["index"] - pm["index"]
            h["mood_dir"] = "beter" if dm >= 0.1 else "slechter" if dm <= -0.1 else "gelijk"
        else:
            h["mood_dir"] = None
    return hist


# ---------------------------------------------------------------- X-accounts
X_ACCOUNTS = [
    ("WeermanMichael", "eigen keuze"), ("Weerprimeur", "eigen keuze"), ("PvForecast", "eigen keuze"),
    ("MeteoVoorne", "eigen keuze"), ("weerdearend", "Meteo Kortenhoef / De Arend"),
    ("natuurijs", "voorstel"), ("ijsvermaak", "voorstel"), ("erikekkel", "voorstel"),
    ("WeermanSjors", "voorstel"), ("HVweerNL", "voorstel"), ("KNMI", "voorstel"), ("KNSB", "voorstel"),
]


def x_posts(prev):
    """X-berichten via de officiële X API (pay-per-use). Alleen als X_BEARER_TOKEN gezet is.
    Haalt per account alleen posts op die nieuwer zijn dan de vorige run (since_id) om kosten laag te houden."""
    import os
    tok = os.environ.get("X_BEARER_TOKEN")
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()[:19]
    old = [p for p in (prev or {}).get("posts") or [] if p.get("source", "").startswith("@") and (p.get("time") or "") >= cutoff]
    state = dict(((prev or {}).get("x_state") or {}))
    if not tok:
        return old, state
    hdr = {"Authorization": "Bearer " + tok, **UA}
    def api(path):
        req = urllib.request.Request("https://api.x.com/2/" + path, headers=hdr)
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())
    try:
        if not state.get("ids"):
            names = ",".join(h for h, _ in X_ACCOUNTS)
            state["ids"] = {u["username"]: u["id"] for u in api("users/by?usernames=" + names).get("data", [])}
        new = []
        for handle, uid in state["ids"].items():
            q = ("users/%s/tweets?max_results=5&exclude=retweets&tweet.fields=created_at,attachments"
                 "&expansions=attachments.media_keys&media.fields=url,preview_image_url,type" % uid)
            if state.get("since", {}).get(handle) and state.get("media_v") == 1:
                q += "&since_id=" + state["since"][handle]
            res = api(q)
            media = {m["media_key"]: (m.get("url") or m.get("preview_image_url")) for m in res.get("includes", {}).get("media", [])}
            for t in res.get("data", []):
                keys = (t.get("attachments") or {}).get("media_keys") or []
                img = next((media.get(k) for k in keys if media.get(k)), None)
                new.append({"source": "@" + handle, "title": t["text"][:280], "summary": "", "img_src": img,
                            "url": f"https://x.com/{handle}/status/{t['id']}", "comments": None,
                            "time": t.get("created_at", "").replace(".000Z", "Z")})
            if res.get("meta", {}).get("newest_id"):
                state.setdefault("since", {})[handle] = res["meta"]["newest_id"]
        state["media_v"] = 1
    except Exception as e:
        errors["x"] = f"{type(e).__name__}: {e}"[:300]
        new = []
    newurls = {p["url"] for p in new}
    old = [p for p in old if p["url"] not in newurls]
    allp = sorted([p for p in new + old if (p["time"] or "") >= cutoff], key=lambda p: p["time"] or "", reverse=True)
    keep, per = [], {}
    for p in allp:
        per[p["source"]] = per.get(p["source"], 0) + 1
        if per[p["source"]] <= 5:
            keep.append(p)
    return keep, state


# ---------------------------------------------------------------- drukte-alarm
BUZZ_FORUM_PER_HOUR = 30     # reacties per uur in de kaartendraad
BUZZ_FORUM_FACTOR = 3        # of: zoveel keer drukker dan normaal (gemiddelde van 24 uur)
BUZZ_X_POSTS_2H = 8          # X-posts in 2 uur van de gevolgde accounts...
BUZZ_X_ACCOUNTS = 3          # ...van minstens zoveel verschillende accounts
BUZZ_PAUSE_H = 3             # niet vaker dan eens per 3 uur per soort


def buzz(cur, prev):
    """Meld als het 'los gaat': veel forumreacties of veel X-posts in korte tijd."""
    now = dt.datetime.now(dt.timezone.utc)
    hist = [h for h in (prev.get("buzz_hist") or []) if h["t"] >= (now - dt.timedelta(hours=26)).isoformat()]
    f = cur.get("forum") or {}
    hist.append({"t": now.isoformat(), "url": f.get("url"), "total": f.get("total")})
    cur["buzz_hist"] = hist
    last = dict(prev.get("buzz_last") or {})
    cur["buzz_last"] = last
    msgs = []
    def may(kind):
        t = last.get(kind)
        return not t or t < (now - dt.timedelta(hours=BUZZ_PAUSE_H)).isoformat()
    # forum: reacties per uur in dezelfde draad
    same = [h for h in hist if h["url"] == f.get("url") and h["total"] is not None]
    hour_ago = [h for h in same if h["t"] <= (now - dt.timedelta(minutes=55)).isoformat()]
    if f.get("total") is not None and hour_ago:
        rate = f["total"] - hour_ago[-1]["total"]
        span_h = max(1.0, (now - dt.datetime.fromisoformat(same[0]["t"])).total_seconds() / 3600)
        avg = (f["total"] - same[0]["total"]) / span_h
        cur["forum_rate"] = rate
        if rate >= BUZZ_FORUM_PER_HOUR or (span_h >= 6 and avg > 0 and rate >= BUZZ_FORUM_FACTOR * avg and rate >= 12):
            if may("forum"):
                msgs.append(f"Het gaat los op het Noodweer-forum: {rate} reacties in het afgelopen uur.")
                last["forum"] = now.isoformat()
    # X: veel posts in 2 uur van verschillende accounts
    two_h = (now - dt.timedelta(hours=2)).isoformat()[:19]
    xs = [p for p in cur.get("posts") or [] if p.get("source", "").startswith("@") and (p.get("time") or "") >= two_h]
    accts = {p["source"] for p in xs}
    if len(xs) >= BUZZ_X_POSTS_2H and len(accts) >= BUZZ_X_ACCOUNTS and may("x"):
        msgs.append(f"Drukte op X: {len(xs)} posts in 2 uur van {len(accts)} weermannen ({', '.join(sorted(accts)[:5])}).")
        last["x"] = now.isoformat()
    return msgs


# ---------------------------------------------------------------- alerts
def alerts(cur, prev):
    out, links = [], []   # links[i]: waar een tik op alert i naartoe gaat (bron-URL of #tab)
    cur["alert_links"] = links
    if not prev:
        cur["buzz_hist"] = []
        return out
    pw = {(w["event"], w["onset"]) for w in (prev.get("warnings") or [])}
    for w in cur.get("warnings") or []:
        if (w["event"], w["onset"]) not in pw:
            out.append(f"Nieuwe waarschuwing ({w['level']}): {w['headline'] or w['event']}")
            links.append("#overzicht")
    ci, pi = cur.get("ice") or {}, prev.get("ice") or {}
    if ci and pi and ci.get("peak_level", 0) != pi.get("peak_level", 0) and max(ci.get("peak_level", 0), pi.get("peak_level", 0)) >= 2:
        lab = ci["labels"][ci["peak_level"]]
        out.append(f"IJsverwachting veranderd: piek nu '{lab}' (~{ci['peak']['cm']} cm rond {ci['peak']['date']})")
        links.append("#overzicht")
    def first_frost(x):
        rows = (x.get("ice") or {}).get("rows") or []
        return next((r["date"] for r in rows if r["forecast"] and r["tmin"] is not None and r["tmin"] <= -5), None)
    a, b = first_frost(cur), first_frost(prev)
    if a and a != b:
        out.append(f"Matige/strenge nachtvorst (≤ -5 °C) verwacht vanaf {a}")
        links.append("#overzicht")
    pe = {(i["place"], i["spot"]): i["status"] for i in ((prev.get("dearend") or {}).get("ice") or [])}
    for i in (cur.get("dearend") or {}).get("ice") or []:
        old = pe.get((i["place"], i["spot"]))
        if old and old != i["status"]:
            out.append(f"De Arend: {i['place']} {i['spot']} nu '{i['status']}' (was '{old}')")
            links.append((cur.get("dearend") or {}).get("url") or "#overzicht")
    pn = (prev.get("dearend") or {}).get("news")
    cn = (cur.get("dearend") or {}).get("news")
    if cn and pn and cn != pn:
        out.append(f"Nieuw schaatsnieuws Wijdemeren: {cn[:160]}")
        links.append("https://weerstationdearend.nl/schaatsnieuws/")
    bz = buzz(cur, prev)
    out += bz
    links += [("#forum" if "orum" in b else "#berichten") for b in bz]
    pf, cf = prev.get("forum") or {}, cur.get("forum") or {}
    if cf.get("url") and pf.get("url") and cf["url"] != pf["url"]:
        out.append(f"Nieuwe kaartendraad op Noodweer: {cf.get('title')}")
        links.append("#forum")
    skate = re.compile(r"schaats|natuurijs|ijsvloer|elfsteden|ijsbaan|Eis\b|Glatteis", re.I)
    seen = {i.get("url") for i in prev.get("posts") or []}
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)).isoformat()[:19]
    for p in cur.get("posts") or []:
        if p.get("url") not in seen and (p.get("time") or "") >= recent and skate.search((p.get("title") or "") + " " + (p.get("summary") or "")):
            out.append(f"Nieuw schaatsbericht bij {p['source']}: {p['title']}")
            links.append(p.get("url") or "#berichten")
    cur["alert_links"] = links
    return out


def main():
    outp = sys.argv[1]
    prev = None
    if len(sys.argv) > 2:
        try:
            prev = json.load(open(sys.argv[2]))
        except Exception:
            prev = None
    for p in (prev or {}).get("posts") or []:
        if p.get("img_src") and p.get("img"):
            IMG_CACHE[p["img_src"]] = p["img"]
    for fp in ((prev or {}).get("forum") or {}).get("posts") or []:
        for im in fp.get("images") or []:
            if im.get("img"):
                IMG_CACHE[im["src"]] = im["img"]
    fc = forecast(prev)
    posts = feeds()
    xp, xstate = x_posts(prev)
    data = {
        "updated": iso(dt.datetime.now(dt.timezone.utc)),
        "location": {"name": "De Bilt (Midden-Nederland)", "lat": LAT, "lon": LON},
        "forecast": None, "ice": None,
        "buienradar": buienradar(), "warnings": warnings(), "dearend": dearend(), "schaatsnieuws": schaatsnieuws(),
        "sneeuwhoogte": sneeuwhoogte(), "posts": posts + xp, "x_state": xstate, "forum": noodweer_forum(),
        "x_connected": bool(__import__("os").environ.get("X_BEARER_TOKEN")), "comments": [],
        "x_accounts": [{"handle": h, "why": w, "url": f"https://x.com/{h}"} for h, w in X_ACCOUNTS],
    }
    if fc:
        data["forecast"] = {"current": fc.get("current"),
                            "hourly": {k: v[:] for k, v in fc["hourly"].items()},
                            "daily": fc["daily"]}
        # alleen komende 48 uur bewaren
        h = data["forecast"]["hourly"]
        now = dt.datetime.now().strftime("%Y-%m-%dT%H:00")
        i0 = next((i for i, t in enumerate(h["time"]) if t >= now), 0)
        for k in h:
            h[k] = h[k][i0:i0 + 48]
        try:
            ens = ice_ensemble()
        except Exception as e:
            ens = None
            errors["ijsmodellen"] = f"{type(e).__name__}: {e}"[:300]
        data["ice"] = ice_model(fc, prev, ens)
        data["ice"]["source"] = "gemiddelde van 3 modellen per dag" if ens else data["forecast"].get("provider")
        data["forecast"]["provider"] = fc.get("provider")
    if data.get("sneeuwhoogte"):
        data["sneeuwhoogte"]["img"] = thumb(data["sneeuwhoogte"].get("img_src"))
    if data.get("schaatsnieuws"):
        data["schaatsnieuws"]["knmi_pluim"] = thumb(data["schaatsnieuws"].get("knmi_pluim_src"), size=900)
    add_images(data["posts"], (prev or {}).get("posts"))
    data["ai"] = (prev or {}).get("ai")   # Claude-beoordeling (assess.py) bewaren tot de volgende
    data["om_blocked"] = OM_BLOCK.get("day")
    data["errors"] = errors
    if data.get("ice"):
        data["ice_trend"] = ice_trend(data["ice"], prev, message_mood(data))
    try:
        import ijsmetingen
        data["ijskaart"] = ijsmetingen.build(prev, data.get("schaatsnieuws"))
        for k, v in data["ijskaart"].pop("errors", {}).items():
            errors["ijskaart " + k] = v
    except Exception as e:
        errors["ijskaart"] = f"{type(e).__name__}: {e}"[:300]
        data["ijskaart"] = (prev or {}).get("ijskaart")
    data["alerts"] = alerts(data, prev)
    if prev and (prev.get("ijskaart") or {}).get("measurements") is not None and data.get("ijskaart"):
        oldk = {(m["url"], m["place"], m["min"], m["max"]) for m in prev["ijskaart"]["measurements"]}
        new = [m for m in data["ijskaart"]["measurements"] if (m["url"], m["place"], m["min"], m["max"]) not in oldk]
        for m in new[:3]:
            val = (f'{m["min"]:g}' if m["min"] == m["max"] else f'{m["min"]:g}-{m["max"]:g}').replace(".", ",")
            data["alerts"].append(f'Nieuwe ijsmeting: {m["place"]} {val} cm ({m["source"]})')
            data["alert_links"].append("#kaart")
    if prev and prev.get("summary"):
        data["summary"] = prev["summary"]   # wordt door de geplande taak vernieuwd
    json.dump(data, open(outp, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"alerts": data["alerts"], "errors": errors,
                      "posts": len(posts), "warnings": len(data["warnings"] or [])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
