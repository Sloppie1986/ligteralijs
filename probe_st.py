import urllib.request, json, re, sys
UA={"User-Agent":"Mozilla/5.0 (ligt-er-al-ijs probe)"}
def get(u, h=None, data=None, n=1500):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={**UA,**(h or {})},data=data),timeout=25)
        b=r.read(); print("==",u,r.status,len(b),r.headers.get("content-type")); return b
    except Exception as e: print("==",u,"ERR",e); return b""
b=get("https://data.buienradar.nl/2.0/feed/json")
if b:
    st=json.loads(b)["actual"]["stationmeasurements"]; print("buienradar stations",len(st),"met grond",sum(1 for s in st if s.get("groundtemperature") is not None))
K="eyJvcmciOiI1ZTU1NGUxOTI3NGE5NjAwMDEyYTNlYjEiLCJpZCI6IjUzYTg1ZDBhMmQ5YzRkYzJiYWNlNzQ4NTQ2Zjk4ODExIiwiaCI6Im11cm11cjEyOCJ9"
b=get("https://api.dataplatform.knmi.nl/open-data/v1/datasets/10-minute-in-situ-meteorological-observations/versions/1.0/files?orderBy=created&sorting=desc&maxKeys=2",{"Authorization":K})
print(b[:400])
try:
    fn=json.loads(b)["files"][0]["filename"]
    u=json.loads(get(f"https://api.dataplatform.knmi.nl/open-data/v1/datasets/10-minute-in-situ-meteorological-observations/versions/1.0/files/{fn}/url",{"Authorization":K}))["temporaryDownloadUrl"]
    nc=get(u); open("knmi.nc","wb").write(nc)
except Exception as e: print("knmi ERR",e)
for u in ["https://www.rijkswaterstaatstrooit.nl/","https://wow.knmi.nl/","https://www.hetweeractueel.nl/","https://www.weerplaza.nl/nederland/temperatuur-10-cm/","https://www.weerplaza.nl/weerkaarten/nederland/temperatuur/"]:
    b=get(u); t=b.decode("utf8","replace")
    print(re.findall(r'(?:src|href)="([^"]*(?:api|json|\.png|\.jpg|kaart|map|temp)[^"]*)"',t)[:25])
# RWS DDL
body=json.dumps({"LocatieLijst":[{"Code":"HOEKVHLD"}],"AquoPlusWaarnemingMetadataLijst":[{"AquoMetadata":{"Compartiment":{"Code":"OW"},"Grootheid":{"Code":"T"}}}]}).encode()
for u in ["https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenLaatsteWaarnemingen","https://waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES_DBO/OphalenLaatsteWaarnemingen"]:
    print(get(u,{"Content-Type":"application/json"},body)[:600])
