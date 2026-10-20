import html
import re
import sys
import time

import requests

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
U="https://www.stsg.de/cms/dokstelle/content/auskuenfte/sowjetische-buerger/kriegsgefangene/datenbank/db-kriegsgefangene"
S=requests.Session(); S.headers.update({"User-Agent":UA})
KEYS=["Nachname","Vorname","Vatersname","Geburtsdatum","Todestag","Geburtsort","Nationalität","Identifikationsnr"]
def q(word, mode="teil"):
    p={"suchwort":word}
    p["teil" if mode=="teil" else "beginn"]="Name enthält" if mode=="teil" else "Name beginnt mit"
    r=S.get(U, params=p, timeout=90)
    t=re.sub(r'<script.*?</script>','',r.text,flags=re.S); t=re.sub(r'<style.*?</style>','',t,flags=re.S)
    t=html.unescape(re.sub(r'<[^>]+>','\n',t))
    L=[x.strip() for x in t.split('\n') if x.strip()]
    recs=[]; cur=None
    for i,ln in enumerate(L):
        k=ln.rstrip(':.').strip()
        if k=="Nachname" and ln.endswith(':'):
            if cur: recs.append(cur)
            cur={}
        if cur is not None and ln.endswith(':'):
            key=ln.rstrip(':').rstrip('.')
            val=L[i+1] if i+1<len(L) and not L[i+1].endswith(':') else ""
            if key in ("Identifikationsnr","Identifikationsnr."): key="ID"
            cur[key]=val
    if cur: recs.append(cur)
    return recs, r.url
if __name__=="__main__":
    for w in sys.argv[1:]:
        recs,u=q(w)
        print(f"\n## {w}  -> записей на странице: {len(recs)}")
        for r in recs[:60]:
            print("   ", " | ".join(f"{r.get(k,'')}" for k in ["Nachname","Vorname","Vatersname","Geburtsdatum","Todestag","Geburtsort","Nationalität","ID"]))
        time.sleep(0.4)
