import re, urllib.request, sys
UA = {"User-Agent": "Mozilla/5.0 (schaatsmonitor)"}
h = urllib.request.urlopen(urllib.request.Request("https://www.weerwoord.be/", headers=UA), timeout=30).read().decode("utf-8", "ignore")
print("len", len(h))
for m in list(re.finditer(r"(?i)ijsdikte|42 mm|Rijnsburg", h))[:4]:
    print("-----", m.start()); print(h[max(0, m.start()-1500):m.start()+600])
print("===== m-links", len(re.findall(r'href="/m/\d+', h)))
i = h.find('href="/m/'); print(h[i-800:i+1200])
print("===== scripts", re.findall(r'<script[^>]+src="([^"]+)"', h)[:10])
print("===== api", sorted(set(re.findall(r'["\'](/(?:api|ajax|json)[^"\']*)', h)))[:20])
