import urllib.request, json, re
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
def get(u, h=None, data=None):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={**UA,**(h or {})},data=data),timeout=25)
        b=r.read(); print("==",u,r.status,len(b),r.headers.get("content-type")); return b
    except Exception as e: print("==",u,"ERR",e); return b""
t=get("https://www.meteo.be/services/wow-be/index.php?lang=en&version=nl").decode("utf8","replace")
print(re.findall(r'<script[^>]*src="([^"]+)"',t))
for m in list(re.finditer(r"\.php|json|api|fetch\(|ajax|url\s*[:=]",t))[:15]: print("::",re.sub(r"\s+"," ",t[max(0,m.start()-120):m.start()+200]))
for s in re.findall(r'<script[^>]*src="([^"]+)"',t):
    if "jquery" in s.lower() or "leaflet" in s.lower(): continue
    u=s if s.startswith("http") else "https://www.meteo.be/services/wow-be/"+s.lstrip("./")
    j=get(u).decode("utf8","replace")
    for m in list(re.finditer(r"\.php|\.json|api/|fetch\(|ajax\(|\$\.get|url\s*:",j))[:12]: print("  ::",re.sub(r"\s+"," ",j[max(0,m.start()-150):m.start()+200]))
