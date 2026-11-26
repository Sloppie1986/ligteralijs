import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (schaatsmonitor)"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read().decode("utf-8", "ignore")
h = get("https://www.weerwoord.be/")
c = lambda s: re.sub(r"\s+", " ", s)
i = h.find("Job (Rijnsburg)")
print(c(h[i-3500:i+1800]))
print("=====")
j = h.find("Kraakloos")
print(c(h[j-600:j+1500]))
print("===== counts", {k: len(re.findall(k, h)) for k in ["msg-altitude", "data-id=", "data-msgid", "data-message", "msgid", "/m/"]})
js = get("https://www.weerwoord.be/build/app.cab8c772.js")
for m in re.finditer(r"getmessage", js):
    print("JS:", c(js[max(0, m.start()-500):m.start()+400]))
