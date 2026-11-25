"""Beoordeling van berichten en weerkaarten door Claude: gaat de ijsverwachting de goede kant op?

Gebruik: python3 assess.py site/data.json
Draait alleen als ANTHROPIC_API_KEY gezet is, en hooguit één keer per dagdeel
(nacht/ochtend/middag/avond), zodat de kosten laag blijven. Schrijft het resultaat
in data["ai"] en in de momentopname van dat dagdeel in data["ice_trend"].
"""
import base64
import datetime as dt
import json
import os
import sys

MODEL = os.environ.get("ASSESS_MODEL", "claude-haiku-5-5")
MAX_IMAGES = 10
HOURS = 12

SYSTEM = """Je bent een nuchtere Nederlandse weerkundige die schaatsers helpt.
Je krijgt de nieuwste berichten van weermannen, nieuwsbronnen en een weerforum (noodweer.be),
plus weerkaarten die daarbij geplaatst zijn, en de modelverwachting voor Midden-Nederland.
Beoordeel per bericht en per kaart of de inhoud wijst op meer kans op natuurijs (kouder, langer vorst,
oostelijke stroming, hogedruk boven Scandinavië) of minder (zachter, westelijke/zuidwestelijke stroming,
dooi). Weeg sensationele of zeer lange-termijnberichten lichter dan korte-termijnverwachtingen en
modeldata. Wees eerlijk over onzekerheid. Schrijf kort en in gewoon Nederlands."""

SCHEMA = {
    "type": "object",
    "properties": {
        "richting": {"type": "string", "enum": ["beter", "gelijk", "slechter"],
                     "description": "Wijst het geheel op meer of minder ijs dan de vorige beoordeling (of t.o.v. de huidige verwachting als er geen vorige is)?"},
        "effect_ijsdikte": {"type": "string", "enum": ["positief", "neutraal", "negatief"]},
        "zekerheid": {"type": "string", "enum": ["laag", "middel", "hoog"]},
        "samenvatting": {"type": "string", "description": "2-4 zinnen: wat zeggen berichten en kaarten samen over ijs in de komende 10 dagen"},
        "berichten": {"type": "array", "items": {
            "type": "object",
            "properties": {"bron": {"type": "string"}, "kern": {"type": "string"},
                           "effect": {"type": "string", "enum": ["positief", "neutraal", "negatief"]}},
            "required": ["bron", "kern", "effect"], "additionalProperties": False}},
        "kaarten": {"type": "array", "items": {
            "type": "object",
            "properties": {"nr": {"type": "integer"}, "wat": {"type": "string"},
                           "effect": {"type": "string", "enum": ["positief", "neutraal", "negatief"]}},
            "required": ["nr", "wat", "effect"], "additionalProperties": False}},
    },
    "required": ["richting", "effect_ijsdikte", "zekerheid", "samenvatting", "berichten", "kaarten"],
    "additionalProperties": False,
}


def collect(data):
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=HOURS)).isoformat()[:19]
    items, images = [], []
    forum = (data.get("forum") or {}).get("posts") or []
    for p in sorted(forum, key=lambda p: p.get("time") or "", reverse=True):
        if (p.get("time") or "")[:19] < since:
            continue
        line = {"bron": "Forum noodweer: " + (p.get("author") or "?"), "tijd": p.get("time"), "tekst": (p.get("text") or "")[:600]}
        for im in p.get("images") or []:
            if im.get("img") and len(images) < MAX_IMAGES:
                images.append(im["img"])
                line.setdefault("kaarten", []).append(len(images))
        items.append(line)
    for p in data.get("posts") or []:
        if (p.get("time") or "")[:19] < since:
            continue
        line = {"bron": p.get("source"), "tijd": p.get("time"),
                "tekst": " ".join(str(p.get(k) or "") for k in ("title", "summary"))[:600]}
        if p.get("img") and len(images) < MAX_IMAGES:
            images.append(p["img"])
            line["kaarten"] = [len(images)]
        items.append(line)
    return items, images


def model_context(data):
    ice = data.get("ice") or {}
    rows = [{k: r[k] for k in ("date", "tmin", "tmax", "cm")} for r in ice.get("rows") or [] if r.get("forecast")]
    return {"ijsmodel_per_dag": rows, "piek": ice.get("peak")}


def main(path):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("geen ANTHROPIC_API_KEY; beoordeling overgeslagen")
        return
    data = json.load(open(path))
    trend = data.get("ice_trend") or []
    if not trend:
        return
    cur = trend[-1]
    prev_ai = data.get("ai") or {}
    if prev_ai.get("key") == cur["key"] and not os.environ.get("ASSESS_FORCE"):
        cur["ai"] = {k: prev_ai.get(k) for k in ("richting", "effect_ijsdikte", "zekerheid", "samenvatting")}
        json.dump(data, open(path, "w"), ensure_ascii=False)
        print("dit dagdeel al beoordeeld")
        return
    items, images = collect(data)
    if not items:
        print("geen nieuwe berichten")
        return

    import anthropic
    content = []
    for i, uri in enumerate(images, 1):
        head, b64 = uri.split(",", 1)
        content.append({"type": "text", "text": f"Kaart {i}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": head[5:].split(";")[0], "data": b64}})
    vorige = {k: prev_ai.get(k) for k in ("richting", "effect_ijsdikte", "samenvatting", "at")} if prev_ai else None
    content.append({"type": "text", "text": json.dumps({
        "vorige_beoordeling": vorige,
        "modelverwachting": model_context(data),
        "berichten_laatste_12_uur": items,
    }, ensure_ascii=False)})

    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIStatusError as e:
        print("Claude-fout", e.status_code, e.message)
        return
    except anthropic.APIConnectionError:
        print("Claude niet bereikbaar")
        return
    if resp.stop_reason != "end_turn":
        print("geen bruikbaar antwoord:", resp.stop_reason)
        return
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    out.update({"key": cur["key"], "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                "model": resp.model, "n_berichten": len(items), "n_kaarten": len(images)})
    data["ai"] = out
    cur["ai"] = {k: out[k] for k in ("richting", "effect_ijsdikte", "zekerheid", "samenvatting")}
    json.dump(data, open(path, "w"), ensure_ascii=False)
    print("beoordeeld:", out["richting"], out["effect_ijsdikte"], resp.usage.input_tokens, "in /", resp.usage.output_tokens, "uit")


if __name__ == "__main__":
    main(sys.argv[1])
