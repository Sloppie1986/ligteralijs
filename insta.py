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

SYSTEM = f"""Je schrijft Instagram-bijschriften voor 'Ligt er al ijs?' (@ligteralijs), dé verbinder voor
al het nieuws en de achtergrond rondom natuurijs in heel Nederland. De gratis app bundelt weermannen,
ijsmetingen, modelverwachtingen en natuurijsberichten. Schrijf in gewoon, enthousiast maar eerlijk Nederlands.
Regels:
- Begin met een pakkende eerste regel met 1-2 emoji.
- 3-6 korte zinnen over het nieuws, met concrete getallen uit de data. Overdrijf niet.
- Als het ijs nog niet betrouwbaar is: zeg duidelijk dat erop gaan nog gevaarlijk is.
- Verwijs naar de app met: 👉 link in bio ({APP_LINK}). Noem nooit een ander webadres.
- Sluit af met een vraag of oproep om een schaatsmaatje te taggen.
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


def template_caption(hits, ice):
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
    caption = claude_caption(hits, data) or template_caption(hits, ice)
    os.makedirs(OUT, exist_ok=True)
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
