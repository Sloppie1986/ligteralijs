import re, sys
sys.path.insert(0, ".")
import ijsmetingen as m
r = m.get("https://www.weerwoord.be/api/getmessage?messageid=3357447")
c = lambda s: re.sub(r"\s+", " ", s)
i = r.find("antwoorden")
print("IDS", re.findall(r"/m/(\d+)|messageid[=:]\s*(\d+)|data-message-id=\"(\d+)\"", r)[:30])
print("AFTER", c(r[i:i+5000]))
