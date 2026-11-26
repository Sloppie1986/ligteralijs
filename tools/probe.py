import re, sys, urllib.request
sys.path.insert(0, ".")
import ijsmetingen as m
UA = {"User-Agent": "Mozilla/5.0 (schaatsmonitor)"}
raw = m.get("https://www.weerwoord.be/")
ps = m.weerwoord_posts(raw)
print("posts", len(ps))
for p in ps:
    if re.search(r"ijs|mm|cm", p["title"] + p["text"], re.I):
        print(p["id"], p["author"], "|", p["loc"], "|", p["title"], "|", p["text"][:300], "=>", m.measurements_in(p["title"] + ". " + p["text"]))
r = m.get("https://www.weerwoord.be/api/getmessage?messageid=3357447")
print("GETMESSAGE len", len(r))
print(re.sub(r"\s+", " ", m.text_of(r))[:2500])
print("RAW", re.sub(r"\s+", " ", r)[:1500])
