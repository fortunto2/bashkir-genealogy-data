#!/usr/bin/env python3
"""ОБД-Мемориал: программный поиск и выгрузка сканов. Без регистрации."""
import hashlib
import html
import re
import sys
import time
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
BASE = "https://obd-memorial.ru/html/"
SALT = 'db76xdlrtxcxcghn7yusxjcdxsbtq1hnicnaspohh5tzbtgqjixzc5nmhybeh'

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

def warm():
    S.get(BASE, timeout=30)

def get(url, **kw):
    """Антибот отдаёт страницу с location.reload() — повторяем, пока не уйдёт."""
    for _ in range(6):
        r = S.get(url, timeout=60, **kw)
        if "location.reload" not in r.text:
            return r
        time.sleep(0.6)
    return r

def search(**params):
    """params: f=фамилия n=имя s=отчество pb=место рожд. entities='27' и т.д."""
    params.setdefault("ps", "100")     # результатов на странице (макс 100)
    params.setdefault("p", "1")        # номер страницы
    r = get(BASE + "search.htm", params=params,
            headers={"Referer": BASE + "advanced-search.htm"})
    h = r.text
    total = None
    m = re.search(r'Запис\w+ с \d+ по \d+ из (\d+)', h)
    if m: total = int(m.group(1))
    elif 'Ничего не найдено' in h or 'не найдено' in h: total = 0
    rows = []
    for blk in re.findall(r'<div id="(\d+)"\s*\n?\s*class="row search-result">(.*?)(?=<div id="\d+"\s*\n?\s*class="row search-result">|<!-- bottom paginator)', h, re.S):
        rid, body = blk
        def f(cls, body=body):  # body связываем здесь: без этого замыкание берёт последний виток
            m = re.search(rf'search-result__col-{cls}">\s*<span>(.*?)</span>', body, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        img = re.search(r'id_image="([^"]*)"', body)
        icon = re.search(r'icons/[\w-]+\.png" title="([^"]*)"', body)
        rows.append({"id": rid, "fio": f("name"), "born": f("date-birth"),
                     "place": f("place"), "out": f("date-out"),
                     "doc": icon.group(1) if icon else "",
                     "img": img.group(1) if img else ""})
    return total, rows, r.url

def card(rid):
    r = get(BASE + "info.htm", params={"id": rid})
    t = re.sub(r'<script.*?</script>', '', r.text, flags=re.S)
    t = re.sub(r'<style.*?</style>', '', t, flags=re.S)
    t = re.sub(r'<!--.*?-->', '', t, flags=re.S)
    # поля идут парами span/span в .card-info
    pairs = re.findall(r'<div class="card-info__name">\s*<span>(.*?)</span>.*?<div class="card-info__value">\s*<span>(.*?)</span>', t, re.S)
    if not pairs:
        txt = html.unescape(re.sub(r'<[^>]+>', '\n', t))
        lines = [ln.strip() for ln in txt.split('\n') if ln.strip()]
        try:
            i = lines.index('Фамилия'); j = lines.index('Включить Книги Памяти')
            seq = lines[i:j]
            pairs = list(zip(seq[0::2], seq[1::2], strict=False))
        except ValueError:
            pairs = []
    title = re.search(r'<title>(.*?)</title>', r.text, re.S)
    return {"id": rid, "title": html.unescape(title.group(1)).strip() if title else "",
            "fields": dict(pairs)}

def images(rid):
    r = get(BASE + "getimageinfo", params={"id": rid},
            headers={"X-Requested-With": "XMLHttpRequest",
                     "Referer": BASE + "info.htm?id=" + str(rid)})
    try: return r.json()
    except ValueError: return []   # не-JSON от антибота; requests кидает подкласс ValueError

def download(image_id, path, out):
    # md5 здесь — подпись запроса по правилам самого портала, не защита
    h = hashlib.md5((str(image_id) + SALT).encode(), usedforsecurity=False).hexdigest()
    r = S.get(BASE + "images3", params={"id": image_id, "id1": h, "path": path},
              headers={"Referer": BASE + "info.htm"}, allow_redirects=True, timeout=120)
    if r.headers.get("content-type","").startswith("image"):
        Path(out).write_bytes(r.content); return len(r.content)
    return 0

if __name__ == "__main__":
    warm()
    args = dict(a.split("=", 1) for a in sys.argv[1:])
    total, rows, url = search(**args)
    print(f"# {args}  ->  всего: {total}")
    for r in rows:
        print(f"{r['id']}\t{r['fio']}\t{r['born']}\t{r['place']}\t[{r['doc']}]\t{r['img']}")
