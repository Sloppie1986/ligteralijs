import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (schaatsmonitor)"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read().decode("utf-8", "ignore")
c = lambda s: re.sub(r"\s+", " ", s)
for src in ["/build/app.cab8c772.js", "/build/runtime.7576e7bf.js"]:
    js = get("https://www.weerwoord.be" + src)
    for k in ["getmessage", "loadMessageByAjax", "threadid", "message-thread"]:
        for m in list(re.finditer(k, js))[:2]:
            print(src, k, ":", c(js[max(0, m.start()-300):m.start()+300]))
h = get("https://www.weerwoord.be/")
for m in list(re.finditer(r"function loadMessageByAjax|getmessage|/thread", h))[:4]:
    print("HTML:", c(h[max(0, m.start()-300):m.start()+700]))
