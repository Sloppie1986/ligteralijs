"""Instagram-voorstellen bij belangrijk ijsnieuws.

Gebruik: python3 insta.py site/data.json prev.json
Kijkt naar de 'alerts' van deze run. Zit daar belangrijk nieuws tussen (ijsverwachting
omhoog/omlaag, strenge nachtvorst, ijsstatus bij De Arend, nieuwe ijsmeting, code oranje/rood),
dan schrijft het een voorstelbericht (bijschrift + plaatje van 1080x1080) naar insta_out/.
De workflow zet dat in een GitHub-issue (en optioneel als ntfy-melding met plaatje).
Er wordt nooit iets automatisch op Instagram gezet: de beheerder keurt het goed en post zelf.

Om spam te voorkomen hooguit één voorstel per COOLDOWN_H uur, behalve als de ijsverwachting
zelf verandert. De status staat in data["insta"].
"""
import datetime as dt
import json
import os
import re
import sys

APP_LINK = "is.gd/ligteralijs"   # korte link: het github.io-adres nooit in berichten tonen
COOLDOWN_H = 6
MODEL = os.environ.get("INSTA_MODEL", "claude-haiku-5-5")
OUT = "insta_out"

IMPORTANT = [
    (re.compile(r"^IJsverwachting veranderd"), 3),
    (re.compile(r"^Nieuwe ijsmeting"), 2),
    (re.compile(r"^De Arend: .* nu '(?!Geen ijs)"), 2),
    (re.compile(r"^Matige/strenge nachtvorst"), 1),
    (re.compile(r"^Nieuwe waarschuwing \((orange|red|oranje|rood)", re.I), 1),
]

HASHTAGS = ("#natuurijs #schaatsen #ligteralijs #ijs #winter #vorst #schaatsweer #weerbericht "
            "#nederland #friesland #drenthe #overijssel #noordholland #utrecht #gelderland "
            "#wijdemeren #loosdrecht #elfsteden #elfstedentocht #toertocht #schaatsliefde "
            "#koudeweer #winterweer #weer #ijspret")

SYSTEM = f"""Je schrijft Instagram-bijschriften voor 'Ligt er al ijs?' (@ligteralijs), een account over natuurijs
in heel Nederland, gerund door een schaatsliefhebber. Het moet klinken alsof een gewone schaatser het snel even
op z'n telefoon tikt, niet als marketing en zeker niet als AI-tekst.
Stijl:
- Korte, gewone zinnen in spreektaal. Geen opsommingstekens, geen kopjes, geen dubbele punten-lijstjes.
- Hooguit 1 of 2 emoji in het hele bericht. Geen gedachtestreepjes, geen woorden als "hét", "ontdek", "mis het niet".
- Begin met een korte, positieve eerste regel (bijv. "Het kan ergens vandaag").
- Noem 2 tot 4 plekken met hun gemeten dikte in een lopende zin, en waar al geschaatst wordt. Alleen getallen uit de data.
- 1 zin over het weer van de komende dagen.
- Eindig met "Alle metingen staan op de kaart, link in bio." en een korte vraag zoals "Wie gaat er mee?".
- Noem nooit een webadres.
- Zet daarna een witregel en precies deze hashtags: {HASHTAGS}
Geef alleen het bijschrift terug."""


def important(alerts):
    hits = []
    for a in alerts:
        a = re.sub(r"\b(\d{4}-\d{2}-\d{2})\b", lambda m: nl_date(m.group(1)), a)
        for rx, w in IMPORTANT:
            if rx.search(a):
                hits.append((w, a))
                break
    return sorted(hits, key=lambda x: -x[0])


def headline(top, ice):
    a = top[1]
    if a.startswith("IJsverwachting"):
        return ice["labels"][ice.get("peak_level", 0)], f"~{str(ice['peak']['cm']).replace('.', ',')} cm ijs rond {nl_date(ice['peak']['date'])}"
    if a.startswith("Nieuwe ijsmeting"):
        m = re.match(r"Nieuwe ijsmeting: (.*) ([\d,\-]+) cm", a)
        return ("Nieuwe ijsmeting", f"{m.group(1)}: {m.group(2)} cm" if m else a[17:])
    if a.startswith("De Arend"):
        return ("IJsstatus gewijzigd", a[10:].split(" (was")[0])
    if a.startswith("Matige"):
        return ("Strenge nachtvorst", "≤ -5 °C vanaf " + a.split("vanaf ", 1)[-1])
    return ("Weerwaarschuwing", a.split(": ", 1)[-1][:60])


def nl_date(iso):
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    mnd = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
    dag = ["ma", "di", "wo", "do", "vr", "za", "zo"]
    return f"{dag[d.weekday()]} {d.day} {mnd[d.month - 1]}"


def recent_measurements(data, hours=36, n=6):
    """Gemeten ijs van de afgelopen uren: per plaats de nieuwste meting plus de prognose voor nu."""
    k = data.get("ijskaart") or {}
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()[:19]
    now_cm = {p.get("place"): p.get("morning_cm") for p in k.get("points") or []}
    best = {}
    for m in sorted(k.get("measurements") or [], key=lambda m: m.get("time") or ""):
        if (m.get("time") or "")[:19] >= since and m.get("cm"):
            best[m["place"]] = m
    out = []
    for m in best.values():
        out.append({"place": m["place"].split(" (")[0], "cm": m["cm"], "max": m.get("max") or m["cm"], "now": now_cm.get(m["place"]),
                    "source": m.get("source"), "quote": m.get("quote"), "kind": m.get("kind")})
    return sorted(out, key=lambda x: -(x["now"] or x["cm"]))[:n]


def cm(x):
    return f"{x:.1f}".replace(".", ",").replace(",0", "")


def template_caption(hits, ice, meas=None):
    if meas:
        plekken = [f"{m['place']} {cm(m['max'])} cm" for m in meas[:4]]
        lines = ["Het kan ergens vandaag ⛸️", "",
                 "Gemeten in " + ", ".join(plekken[:-1]) + " en " + plekken[-1] + ".", "",
                 "Alle metingen staan op de kaart, link in bio.", "Wie gaat er mee?", "", HASHTAGS]
        return "\n".join(lines)

    lines = ["❄️ Natuurijsnieuws! ⛸️", ""]
    lines += ["• " + a for _, a in hits[:4]]
    if ice:
        lines += ["", f"IJsverwachting nu: {ice['labels'][ice.get('level', 0)]}, piek ~{str(ice['peak']['cm']).replace('.', ',')} cm rond {nl_date(ice['peak']['date'])}."]
        if ice.get("peak_level", 0) < 3:
            lines.append("Het ijs is nog niet betrouwbaar: ga er niet op!")
    lines += ["", f"Alle weermannen, ijsmetingen en verwachtingen op één plek 👉 link in bio ({APP_LINK})",
              "Tag een schaatsmaatje die dit moet weten 👇", "", HASHTAGS]
    return "\n".join(lines)


def claude_caption(hits, data):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        ice = data.get("ice") or {}
        ctx = {
            "nieuws": [a for _, a in hits],
            "ijsverwachting": {"nu": ice.get("labels", ["?"])[ice.get("level", 0)] if ice else None,
                               "piek": ice.get("peak"), "piek_label": ice["labels"][ice.get("peak_level", 0)] if ice else None},
            "dagen": [{k: r.get(k) for k in ("date", "tmin", "tmax", "cm")} for r in ice.get("rows") or [] if r.get("forecast")][:8],
            "beoordeling_berichten": (data.get("ai") or {}).get("samenvatting"),
            "gemeten_ijs_laatste_36_uur": recent_measurements(data),
        }
        resp = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}])
        text = next(b.text for b in resp.content if b.type == "text").strip()
        if "github" in text.lower():
            return None
        return text
    except Exception as e:
        print("Claude-bijschrift mislukt:", type(e).__name__, e)
        return None


def notify(title, caption, png):
    """Stuur het voorstel met plaatje naar je eigen ntfy-topic (secret NTFY_INSTA_TOPIC)."""
    topic = os.environ.get("NTFY_INSTA_TOPIC")
    if not topic:
        return
    import base64
    import urllib.request

    def enc(t):  # RFC 2047, zodat emoji en accenten in headers mogen
        return "=?UTF-8?B?" + base64.b64encode(t.encode()).decode() + "?="
    req = urllib.request.Request(
        "https://ntfy.sh/" + topic, data=open(png, "rb").read(), method="PUT",
        headers={"Title": enc("Instagram-voorstel: " + title), "Message": enc(caption[:3500]),
                 "Filename": "ligteralijs-voorstel.png", "Tags": "camera,ice_skate"})
    try:
        urllib.request.urlopen(req, timeout=30)
        print("ntfy-melding met plaatje verstuurd")
    except Exception as e:
        print("ntfy mislukt:", e)


def font(size, bold=True):
    from PIL import ImageFont
    for f in (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
              if bold else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def wrap(d, text, fnt, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + [cur] if cur else lines


def image(title, sub, hits, path):
    from PIL import Image, ImageDraw
    S = 1080
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=(int(12 + 40 * t), int(50 + 90 * t), int(100 + 110 * t)))
    d.text((70, 70), "LIGT ER AL IJS?", font=font(44), fill=(190, 225, 250))
    d.text((70, 125), dt.date.today().strftime("%d-%m-%Y"), font=font(34, False), fill=(190, 225, 250))
    y = 300
    for ln in wrap(d, title, font(96), S - 140)[:3]:
        d.text((70, y), ln, font=font(96), fill="white")
        y += 112
    y += 20
    for ln in wrap(d, sub, font(56, False), S - 140)[:2]:
        d.text((70, y), ln, font=font(56, False), fill=(225, 242, 255))
        y += 70
    y += 40
    for _, a in hits[1:3]:
        for ln in wrap(d, "• " + a, font(34, False), S - 140)[:2]:
            d.text((70, y), ln, font=font(34, False), fill=(200, 230, 250))
            y += 44
    d.text((70, S - 120), f"Alles over natuurijs → {APP_LINK}", font=font(40), fill="white")
    img.save(path)


def measured_image(meas, path):
    """Plaatje 'Gemeten ijs': per plaats een balk met de gemeten dikte en de verwachting voor nu."""
    from PIL import Image, ImageDraw
    import random
    S = 1080
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=(int(10 + 35 * t), int(45 + 85 * t), int(95 + 110 * t)))
    rnd = random.Random(7)
    for _ in range(10):   # ijsscheurtjes
        x, y = rnd.randint(0, S), rnd.randint(0, S)
        for _ in range(4):
            nx, ny = x + rnd.randint(-90, 90), y + rnd.randint(-90, 90)
            d.line([(x, y), (nx, ny)], fill=(60, 110, 160), width=2)
            x, y = nx, ny
    d.text((70, 60), "LIGT ER AL IJS?", font=font(40), fill=(190, 225, 250))
    d.text((70, 110), "Gemeten ijs", font=font(92), fill="white")
    d.text((72, 220), nl_date(dt.date.today().isoformat()) + " · heel Nederland", font=font(38, False), fill=(205, 232, 252))
    top, row = 320, 100
    scale = 560 / max(6.0, max((m.get("now") or m["max"]) for m in meas))
    for i, m in enumerate(meas[:6]):
        y = top + i * row
        d.text((70, y), m["place"][:20], font=font(40), fill="white")
        bx, by = 70, y + 52
        d.rounded_rectangle([bx, by, bx + 560, by + 24], radius=12, fill=(30, 70, 120))
        if m.get("now"):
            d.rounded_rectangle([bx, by, bx + int(m["now"] * scale), by + 24], radius=12, fill=(120, 185, 235))
        d.rounded_rectangle([bx, by, bx + max(24, int(m["max"] * scale)), by + 24], radius=12, fill=(235, 248, 255))
        d.text((660, y + 6), f"{cm(m['max'])} cm", font=font(56), fill="white")
        if m.get("now"):
            d.text((880, y + 20), f"nu ~{cm(m['now'])}", font=font(32, False), fill=(170, 215, 245))
    y = top + 6 * row + 4
    d.rounded_rectangle([70, y, 94, y + 20], radius=8, fill=(235, 248, 255))
    d.text((104, y - 6), "gemeten", font=font(28, False), fill=(205, 232, 252))
    d.rounded_rectangle([260, y, 284, y + 20], radius=8, fill=(120, 185, 235))
    d.text((294, y - 6), "verwachting nu (Ligt er al ijs?-model)", font=font(28, False), fill=(205, 232, 252))
    d.text((70, S - 110), f"Alle metingen op de kaart → {APP_LINK}", font=font(40), fill="white")
    img.save(path)


def main(path, prev_path):
    data = json.load(open(path))
    try:
        prev = json.load(open(prev_path))
    except Exception:
        prev = {}
    state = dict(prev.get("insta") or {})
    data["insta"] = state
    hits = important(data.get("alerts") or [])
    if os.environ.get("INSTA_TEST"):
        hits = hits or [(1, a) for a in (data.get("alerts") or ["Matige/strenge nachtvorst (≤ -5 °C) verwacht vanaf " + dt.date.today().isoformat()])]
    if not hits:
        json.dump(data, open(path, "w"), ensure_ascii=False)
        print("geen belangrijk nieuws voor Instagram")
        return
    now = dt.datetime.now(dt.timezone.utc)
    last = state.get("last")
    ice_change = any(a.startswith("IJsverwachting") for _, a in hits)
    if last and not ice_change and not os.environ.get("INSTA_TEST"):
        if now - dt.datetime.fromisoformat(last) < dt.timedelta(hours=COOLDOWN_H):
            json.dump(data, open(path, "w"), ensure_ascii=False)
            print("belangrijk nieuws, maar laatste voorstel is minder dan", COOLDOWN_H, "uur oud")
            return
    ice = data.get("ice") or {}
    title, sub = headline(hits[0], ice)
    meas = recent_measurements(data)
    caption = claude_caption(hits, data) or template_caption(hits, ice, meas)
    os.makedirs(OUT, exist_ok=True)
    if len(meas) >= 3:
        measured_image(meas, os.path.join(OUT, "voorstel.png"))
        title = "Gemeten ijs"
    else:
        image(title, sub, hits, os.path.join(OUT, "voorstel.png"))
    stamp = now.strftime("%Y-%m-%d %H:%M")
    open(os.path.join(OUT, "caption.txt"), "w").write(caption)
    open(os.path.join(OUT, "title.txt"), "w").write(f"Instagram-voorstel {stamp} UTC: {title}")
    open(os.path.join(OUT, "issue.md"), "w").write(
        "Nieuw voorstelbericht voor **@ligteralijs**. Niets is gepost: keur het goed, pas het eventueel aan en post het zelf.\n\n"
        "**Aanleiding**\n" + "\n".join(f"- {a}" for _, a in hits) + "\n\n"
        "**Afbeelding:** zie hieronder (ook in de ntfy-melding, als die is ingesteld).\n\n"
        "**Bijschrift** (kopiëren):\n\n```\n" + caption + "\n```\n")
    notify(title, caption, os.path.join(OUT, "voorstel.png"))
    state["last"] = now.isoformat(timespec="minutes")
    state["title"] = title
    json.dump(data, open(path, "w"), ensure_ascii=False)
    print("Instagram-voorstel gemaakt:", title, "|", sub)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
