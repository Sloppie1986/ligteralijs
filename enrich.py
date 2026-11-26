"""Verrijkt data.json met Claude (Haiku): vertaling naar het Nederlands en een uitleg bij weerkaarten.

Gebruik: python3 enrich.py site/data.json prev.json
- Alleen nieuwe berichten en nieuwe kaarten gaan naar Claude; eerdere vertalingen en uitleg
  komen uit de vorige data.json (cache), zodat de kosten klein blijven.
- Zonder ANTHROPIC_API_KEY worden alleen de bewaarde vertalingen/uitleg teruggezet.
"""
import hashlib
import json
import os
import re
import sys

MODEL = os.environ.get("ENRICH_MODEL", "claude-haiku-5-5")
MAX_NEW_IMAGES = 12      # per run
MAX_TRANSLATE = 40       # per run
CACHE_KEEP = 600

NL = set("de het een en van is niet met op voor dat die er ook nog wel maar naar bij als te zijn wordt worden komt vorst ijs koud morgen".split())
EN = set("the and is of to with for this that are be will from it on at as cold snow weather".split())
DE = set("der die und das nicht mit ist ein eine für auf den dem des von wird kalt schnee wetter heute morgen bleibt".split())


def key(*parts):
    return hashlib.sha1("|".join(str(p or "") for p in parts).encode()).hexdigest()[:16]


def lang(text):
    clean = re.sub(r"https?://\S+|[#@]\w+", " ", (text or "").lower())
    words = re.findall(r"[a-zäöüß]+", clean)
    if len(words) < 4:
        return "nl"
    n, e, d = (sum(w in s for w in words) for s in (NL, EN, DE))
    if n >= max(e, d) or max(e, d) < 2:
        return "nl"
    return "en" if e >= d else "de"


def text_items(data):
    """(cache-sleutel, object, velden) voor alles wat vertaald kan worden."""
    for p in data.get("posts") or []:
        yield key("post", p.get("url"), p.get("title")), p, ("title", "summary")
    for p in ((data.get("forum") or {}).get("posts") or []):
        yield key("forum", p.get("id"), p.get("text")), p, ("text",)


def image_items(data):
    """(cache-sleutel, object om uitleg in te zetten, data-uri, context)."""
    for p in ((data.get("forum") or {}).get("posts") or []):
        for im in p.get("images") or []:
            if im.get("img"):
                yield key("img", im.get("src")), im, im["img"], p.get("text") or ""
    for p in data.get("posts") or []:
        if p.get("img"):
            yield key("img", p.get("img_src") or p.get("url")), p, p["img"], " ".join(str(p.get(k) or "") for k in ("title", "summary"))


def client():
    import anthropic
    return anthropic.Anthropic()


def ask_json(cl, content, schema, system):
    import anthropic
    try:
        r = cl.messages.create(
            model=MODEL, max_tokens=8000, system=system,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        print("Claude-fout:", getattr(e, "status_code", ""), getattr(e, "message", e))
        return None
    if r.stop_reason != "end_turn":
        print("geen bruikbaar antwoord:", r.stop_reason)
        return None
    return json.loads(next(b.text for b in r.content if b.type == "text"))


TR_SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"i": {"type": "integer"}, "nl": {"type": "string"}},
    "required": ["i", "nl"], "additionalProperties": False}}}, "required": ["items"], "additionalProperties": False}

IMG_SCHEMA = {"type": "object", "properties": {
    "is_kaart": {"type": "boolean", "description": "Is dit een weerkaart, modelgrafiek of pluim (geen foto/meme)?"},
    "wat": {"type": "string", "description": "Eén zin: wat voor kaart of grafiek is dit (model, grootheid, tijdstip als zichtbaar)"},
    "uitleg": {"type": "string", "description": "3-6 korte zinnen in gewone taal: hoe lees je dit en wat laat het zien"},
    "ijs": {"type": "string", "enum": ["goed voor ijs", "slecht voor ijs", "neutraal", "niet van toepassing"]}},
    "required": ["is_kaart", "wat", "uitleg", "ijs"], "additionalProperties": False}

IMG_SYSTEM = """Je legt weerkaarten en modelgrafieken uit aan schaatsliefhebbers zonder meteorologische kennis.
Gebruik gewone Nederlandse woorden. Leg vaktermen kort uit als je ze noemt (bijvoorbeeld: 850 hPa = temperatuur op ongeveer 1,5 km hoogte,
pluim = alle varianten van één weermodel naast elkaar, hogedruk boven Scandinavië = vaak oostenwind en kou bij ons).
Zeg wat de kaart betekent voor kou en natuurijs in Nederland. Verzin niets dat je niet kunt zien; zeg het als iets onleesbaar is."""


def main(path, prev_path=None):
    data = json.load(open(path))
    prev = {}
    if prev_path and os.path.exists(prev_path):
        try:
            prev = json.load(open(prev_path))
        except ValueError:
            prev = {}
    tr = dict(prev.get("tr_cache") or {})
    ex = dict(prev.get("img_cache") or {})
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    cl = client() if has_key else None

    # 1. vertalen
    todo = []
    for k, obj, fields in text_items(data):
        for f in fields:
            t = obj.get(f)
            if not t or lang(t) == "nl":
                continue
            ck = k + f
            obj["lang"] = lang(t)
            if ck in tr:
                obj[f + "_nl"] = tr[ck]["nl"]
                obj["lang"] = tr[ck]["lang"]
            elif len(todo) < MAX_TRANSLATE:
                todo.append((ck, obj, f, t, lang(t)))
    if todo and cl:
        res = ask_json(cl, json.dumps([{"i": i, "tekst": t[:1500]} for i, (_, _, _, t, _) in enumerate(todo)], ensure_ascii=False),
                       TR_SCHEMA, "Vertaal elke tekst naar natuurlijk Nederlands. Behoud namen, getallen, hashtags en links. "
                                  "Geef alleen de vertaling terug, met hetzelfde nummer i.")
        for it in (res or {}).get("items") or []:
            if 0 <= it["i"] < len(todo):
                ck, obj, f, _, lg = todo[it["i"]]
                tr[ck] = {"nl": it["nl"], "lang": lg}
                obj[f + "_nl"] = it["nl"]
                obj["lang"] = lg
        print("vertaald:", len((res or {}).get("items") or []))

    # 2. uitleg bij kaarten
    new = 0
    for k, obj, uri, ctx in image_items(data):
        if k in ex:
            obj["uitleg"] = ex[k]
            continue
        if not cl or new >= MAX_NEW_IMAGES:
            continue
        head, b64 = uri.split(",", 1)
        res = ask_json(cl, [
            {"type": "image", "source": {"type": "base64", "media_type": head[5:].split(";")[0], "data": b64}},
            {"type": "text", "text": "Tekst bij deze afbeelding (ter context): " + ctx[:800]},
        ], IMG_SCHEMA, IMG_SYSTEM)
        new += 1
        if res:
            ex[k] = res
            obj["uitleg"] = res
    if new:
        print("kaarten uitgelegd:", new)

    data["tr_cache"] = dict(list(tr.items())[-CACHE_KEEP:])
    data["img_cache"] = dict(list(ex.items())[-CACHE_KEEP:])
    json.dump(data, open(path, "w"), ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
