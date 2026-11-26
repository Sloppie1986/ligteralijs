import urllib.request, json, re
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36","Referer":"https://www.meteo.be/services/wow-be/index.php?lang=en&version=nl"}
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40); b=r.read(); print("==",u,r.status,len(b),r.headers.get("content-type")); return b
    except Exception as e: print("==",u,"ERR",e); return b""
src=""
for f in ["index.php?lang=en&version=nl","scripts/wow.core.js","scripts/wow.layers.js","scripts/initMap.js"]:
    t=get("https://www.meteo.be/services/wow-be/"+f).decode("utf8","replace"); src+=t
    for m in re.finditer(r"apiBaseUrl\s*=\s*([^;\n]+)",t): print("BASE",f,m.group(1))
m=re.search(r"apiBaseUrl\s*=\s*['\"]([^'\"]+)",src)
if m:
    b=m.group(1); d=get(b+"/v2/observation")
    try:
        j=json.loads(d); print(type(j), list(j)[:10] if isinstance(j,dict) else len(j))
        print(json.dumps(j)[:1500])
    except Exception as e: print("parse",e, d[:300])
i=src.find("/v2/observation"); print(re.sub(r"\s+"," ",src[i-200:i+1500]))
