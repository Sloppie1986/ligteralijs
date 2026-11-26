import urllib.request, json, re
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
def get(u, h=None, data=None):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={**UA,**(h or {})},data=data),timeout=25)
        b=r.read(); print("==",u,r.status,len(b),r.headers.get("content-type")); return b
    except Exception as e: print("==",u,"ERR",e); return b""
def urls(t, pat): 
    s=sorted(set(re.findall(r'''["'(]((?:https?:)?/[^"'()\s]*(?:%s)[^"'()\s]*)["')]'''%pat,t))); print(s[:40]); return s
t=get("https://www.hetweeractueel.nl/actueel-temperatuurkaartje/").decode("utf8","replace")
urls(t,"json|api|ajax|data|\\.php|\\.txt|\\.csv|kaart|map")
i=t.find("temperatuurkaart"); print(re.sub(r"\s+"," ",t[t.find("<main"):t.find("<main")+3000]))
t=get("https://wow.knmi.nl/en/map/").decode("utf8","replace")
urls(t,"json|api|\\.js|observ|map")
t=get("https://www.weerplaza.nl/nederland/temperatuur-10-cm/").decode("utf8","replace")
urls(t,"infoplaza|wxdata|\\.png|\\.jpg|\\.webp|10cm|10-cm|api")
for m in re.finditer(r"10 ?cm",t): print(re.sub(r"\s+"," ",t[max(0,m.start()-300):m.start()+300])); break
