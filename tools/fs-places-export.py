#!/usr/bin/env python3
"""Выгрузка населённых пунктов уезда из справочника мест FamilySearch.

Открытый эндпоинт, без авторизации:
  https://api.familysearch.org/platform/places/description/<ID>/children?flag=fsh
"""
import datetime
import json
import os
import subprocess
import sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
OUT = os.environ.get("OUT", ".")  # куда писать выгрузку

UEZDY = {
    "orskiy": {"id": "12320215", "ru": "Орский уезд, Оренбургская губерния",
                    "en": "Orsk, Orenburg, Russian Empire"},
    "orenburgskiy": {"id": "11879389", "ru": "Оренбургский уезд, Оренбургская губерния",
                          "en": "Orenburg, Orenburg, Russian Empire"},
    "sterlitamakskiy": {"id": "12320378", "ru": "Стерлитамакский уезд, Уфимская губерния",
                             "en": "Sterlitamak, Ufa, Russian Empire"},
}

# Наши деревни — сопоставление ПО ID, а не по написанию: в одном уезде три `bikberdina`
# и две `barangulova`, и только по имени они неразличимы. Отождествление сделано по
# координатам (сверка с OSM/Nominatim 11.09.2026).
OURS_BY_ID = {
    "12986558": "Бикберда (Верхняя + Нижняя, один пункт)",
    "12986556": "Бикбау (у FS искажено в «Бикасова»)",
    "12986545": "Байдавлетово",
    "12986639": "Мало-Байдавлетово",
    "12986685": "Салихово",
    "12986695": "Сулейманово",
    "12986686": "Сарыгулово",
}

# Написания, которые ловятся на наши фамилии/деревни, но нашими НЕ являются.
# Нужны в таблице отдельно: без них легко записать чужую деревню как свою.
TRAPS = ("bikberdina", "barangulova", "burangulova", "salikhova",
         "suleimanova", "sarigulova", "baidevletova", "bikasova", "mukach")

# Чего в имперском слое справочника НЕТ — проверено поиском 11.09.2026.
GAPS = {
    "orskiy": [
        ("**Трушино** и **Карадыган** в имперском слое отсутствуют — FamilySearch знает их "
        "только в современном слое (`trushino, Bashkortostan` [1420221], "
        "`karadygan, Bashkortostan` [1372845])."),
        ("**«Бурангулово»** как второе имя нашей деревни их справочник не знает: обе "
        "`barangulova` в этом уезде — другие деревни, южнее."),
        ("`bikasova` (Бикасова) — это **Бикбау**: координаты совпадают с OSM до пятого знака "
        "(52.207691 / 56.744034). Имя у FS искажено, место верное."),
        ("Трёх `bikberdina` различает только широта: наша — **12986558** (52.27808 = Верхняя "
        "Бикберда; Нижняя в 2,15 км, FS держит их одним пунктом)."),
    ],
    "orenburgskiy": [
        "Выгружен как соседний уезд — для контроля однофамильных деревень. Наших пунктов здесь нет.",
    ],
    "sterlitamakskiy": [
        ("**Большемукачево (папина линия) в имперском слое отсутствует.** FamilySearch знает "
        "Мукачево только в советском и современном слоях: `Mukachevo, Kugarchinsky, "
        "Bashkortostan` [1344842], `Mukachevo, Bashkir, Russia, Soviet Union` [6551538] — "
        "причём в **Кугарчинском**, а не Мелеузовском районе, так что это может быть другая "
        "деревня `[гип]`."),
        ("Мелеуз у них записан как `meneuz, Sterlitamak, Ufa, Russian Empire` [12947787] — "
        "опечатка в транслитерации, искать по ней бесполезно."),
    ],
}

def fetch(pid):
    url = f"https://api.familysearch.org/platform/places/description/{pid}/children?flag=fsh"
    r = subprocess.run(["curl", "-sS", "-A", UA, "-H", "Accept: application/json",
                        "--max-time", "60", "--fail", url],
                       capture_output=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"curl {pid}: {r.stderr.decode()[:200]}")
    return json.loads(r.stdout)

def norm(p):
    disp = p.get("display", {})
    names = [n.get("value") for n in p.get("names", []) if n.get("value")]
    prim = p.get("identifiers", {}).get("http://gedcomx.org/Primary", [])
    return {
        "id": p["id"],
        "primary_place_id": prim[0].rsplit("/", 1)[-1] if prim else None,
        "name_latin": disp.get("name"),
        "names": names,
        "full_name": disp.get("fullName"),
        "type": disp.get("type"),
        "latitude": p.get("latitude"),
        "longitude": p.get("longitude"),
        "period": (p.get("temporalDescription") or {}).get("formal"),
        "parent_id": (p.get("jurisdiction") or {}).get("resourceId"),
    }

def ours_note(rec):
    return OURS_BY_ID.get(rec["id"], "")

def is_trap(rec):
    nl = (rec["name_latin"] or "").lower()
    return (not ours_note(rec)) and any(t in nl for t in TRAPS)

def main():
    today = datetime.date.today().isoformat()
    for slug, meta in UEZDY.items():
        try:
            raw = fetch(meta["id"])
        except Exception as e:  # noqa: BLE001 — сеть и разбор ответа: любой сбой пропускает уезд, не роняя выгрузку
            print(f"FAIL {slug}: {e}", file=sys.stderr)
            continue
        places = [norm(p) for p in raw.get("places", [])]
        if not places:
            print(f"FAIL {slug}: пустая выгрузка, файл не создаю", file=sys.stderr)
            continue
        places.sort(key=lambda r: (r["name_latin"] or ""))

        doc = {
            "source": "FamilySearch Places API (открыт без авторизации)",
            "endpoint": f"https://api.familysearch.org/platform/places/description/{meta['id']}/children?flag=fsh",
            "uezd": meta["ru"],
            "uezd_fs_name": meta["en"],
            "uezd_place_id": meta["id"],
            "fetched": today,
            "count": len(places),
            "places": places,
        }
        jp = f"{OUT}/fs-places-{slug}-uezd.json"
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)

        mp = f"{OUT}/fs-places-{slug}-uezd.md"
        with open(mp, "w", encoding="utf-8") as f:
            f.write(f"# Населённые пункты: {meta['ru']} — справочник мест FamilySearch\n\n")
            f.write(f"Выгружено {today} из открытого Places API (без авторизации).\n"
                    f"Уезд у FamilySearch: `{meta['en']}`, place id **{meta['id']}**. "
                    f"Всего пунктов: **{len(places)}**.\n\n"
                    f"Машиночитаемая копия — `fs-places-{slug}-uezd.json`. "
                    f"Как повторить выгрузку — [[2026-09-11_familysearch-razvedka]] §9.\n\n")
            f.write("⚠️ Наличие пункта в справочнике **не значит**, что у FamilySearch есть по нему\n"
                    "документы: справочник мест строится по географическим источникам, а не по их\n"
                    "фондам. Ценность выгрузки — точное написание, которое понимает их каталог,\n"
                    "и координаты, по которым деревня отождествляется без споров о транслитерации.\n\n")
            for note in GAPS.get(slug, []):
                f.write(f"- {note}\n")
            if GAPS.get(slug):
                f.write("\n")
            marked = [r for r in places if ours_note(r)]
            if marked:
                f.write("## Наши деревни (отождествлены по координатам)\n\n")
                f.write("| Наше название | У FS латиницей | Кириллицей | place id | тип | широта | долгота |\n")
                f.write("|---|---|---|---|---|---|---|\n")
                for r in marked:
                    cyr = ", ".join(r["names"]) or "—"
                    f.write(f"| **{ours_note(r)}** | {r['name_latin']} | {cyr} | {r['id']} | {r['type']} | "
                            f"{r['latitude']} | {r['longitude']} |\n")
                f.write("\n")
            traps = [r for r in places if is_trap(r)]
            if traps:
                f.write("## ⚠️ Однофамильные ловушки — НЕ наши\n\n")
                f.write("Совпадают по написанию с нашими деревнями, но это другие пункты. "
                        "Различитель — широта.\n\n")
                f.write("| У FS латиницей | Кириллицей | place id | тип | широта | долгота |\n")
                f.write("|---|---|---|---|---|---|\n")
                for r in traps:
                    cyr = ", ".join(r["names"]) or "—"
                    f.write(f"| {r['name_latin']} | {cyr} | {r['id']} | {r['type']} | "
                            f"{r['latitude']} | {r['longitude']} |\n")
                f.write("\n")
            f.write("## Все пункты\n\n| № | Латиницей (как ищет каталог) | Кириллицей | place id | тип | широта | долгота |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for i, r in enumerate(places, 1):
                cyr = ", ".join(r["names"]) or "—"
                mark = " ⬅️" if ours_note(r) else (" ⚠️" if is_trap(r) else "")
                f.write(f"| {i} | {r['name_latin']}{mark} | {cyr} | {r['id']} | {r['type']} | "
                        f"{r['latitude']} | {r['longitude']} |\n")
        print(f"OK {slug}: {len(places)} пунктов -> {jp} ({os.path.getsize(jp)} б), {mp}")

if __name__ == "__main__":
    main()
