import urllib.request, json, re
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
def get(u, h=None, data=None):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={**UA,**(h or {})},data=data),timeout=25)
        b=r.read(); print("==",u,r.status,len(b),r.headers.get("content-type")); return b
    except Exception as e: print("==",u,"ERR",e); return b""
js=get("https://www.hetweeractueel.nl/wp-content/plugins/sln-hwa/js/hwa-live-data.js?ver=7.1.2").decode("utf8","replace")
print(js[:2500])
print(re.findall(r"action['\"]?\s*[:=]\s*['\"]([\w-]+)",js))
t=get("https://www.hetweeractueel.nl/actueel-temperatuurkaartje/").decode("utf8","replace")
for k in ["hwa_","ajax","stations","lat"]:
    for m in list(re.finditer(k,t))[:3]: print(k,"::",re.sub(r"\s+"," ",t[max(0,m.start()-150):m.start()+250]))
t=get("https://www.weerplaza.nl/nederland/temperatuur-10-cm/").decode("utf8","replace")
print(re.findall(r'<script[^>]*src="([^"]+)"',t)[:30])
for k in ["Temperatuur 10","grondtemp","10cm","wxdata","mapUrl","imageUrl","tiles"]:
    for m in list(re.finditer(k,t,re.I))[:2]: print(k,"::",re.sub(r"\s+"," ",t[max(0,m.start()-200):m.start()+400]))
t=get("https://wow.knmi.nl/en/map/").decode("utf8","replace")
print(re.findall(r'<script[^>]*src="([^"]+)"',t)); print(re.findall(r'<iframe[^>]*src="([^"]+)"',t))
for k in ["map","api"]:
    for m in list(re.finditer(r'id="%s|%s\.'%(k,k),t))[:3]: print(k,"::",re.sub(r"\s+"," ",t[max(0,m.start()-150):m.start()+300]))
