#!/usr/bin/env python3
"""Проверка наших статей в Википедии: живы ли правки, не откатили ли.

Зачем: мы правим статьи о деревнях рода, а Википедия живая — правки откатывают,
факты переписывают, ссылки гниют. Скрипт показывает, что изменилось ПОСЛЕ нашей
последней правки, и жив ли внесённый текст.

    uv run bin/wiki-check.py            # проверить все статьи реестра
    uv run bin/wiki-check.py --user     # заодно подтянуть новые статьи из вклада

Рядом удобно держать реестр правок (что, когда и из какого источника внесли).
"""
import json
import sys
import time
import urllib.error  # ловим HTTPError явно: urllib.request тянет его лишь как побочный эффект
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://{lang}.wikipedia.org/w/api.php"
USER: str  # заполняется из конфига ниже, см. load_config()
# Wikimedia просит в User-Agent контакт и просит не долбить API: без пауз
# несколько статей подряд ловят HTTP 429.
UA = "wiki-check/1.0 (personal research)"  # Wikimedia просит контакт в UA
PAUSE = 2.0  # секунды между запросами; при 20+ статьях API отдаёт 429 уже на 1.0
RETRIES = 6

# Что должно быть в статье после наших правок. Если фразы нет — правку откатили
# или переписали, и это главное, что скрипт должен ловить.
def load_config():
    """Личные данные — в конфиге, метод — в скрипте.

    Скрипт живёт в скилле и одинаков для всех; список статей и имя участника
    у каждого свои. Ищем конфиг там, где обычно лежит база, затем рядом со
    скриптом. Формат: {"user": "…", "watch": {"Статья": ["опорная фраза", …]}}
    """
    here = Path(__file__).resolve().parent
    for p in (Path.cwd() / "family" / "wiki-watch.json",
              Path.cwd() / "wiki-watch.json",
              here / "wiki-watch.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")), p
    sys.exit("Не найден wiki-watch.json — положите его в family/ рядом с базой.\n"
             'Формат: {"user": "ИмяУчастника", "watch": {"Статья": ["фраза"]}}')


CONFIG, CONFIG_PATH = load_config()
WATCH = CONFIG["watch"]
USER = CONFIG["user"]
UA = f"wiki-check/1.0 (personal research; User:{USER})"


def api(lang="ru", **params):
    params.update(format="json", formatversion="2")
    url = API.format(lang=lang) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == RETRIES - 1:
                raise
            wait = PAUSE * 2 ** (attempt + 2)
            print(f"  … 429 от {lang}.wikipedia, ждём {wait:.0f} с")
            time.sleep(wait)


def split_lang(title):
    """'ba:Буранғол' → ('ba', 'Буранғол'). Без префикса — русский раздел."""
    if ":" in title and len(title.split(":", 1)[0]) == 2:
        lang, rest = title.split(":", 1)
        return lang, rest
    return "ru", title


# Признаки того, что нашу правку отменили. Ищем по комментарию, потому что
# отмена и откат — обычные правки, ничем иначе от прочих не отличающиеся.
REVERT_MARKS = ("отмен", "откат", "вп:×", "rollback", "undo", "revert")
# Претензия к правке может быть высказана и без слова «отмена»: комментарий
# «не АИ» вырезает абзац ровно так же. Проверено 12.09.2026 — по словам отмены
# такой случай не ловится вовсе.
COMPLAINT_MARKS = ("не аи", "неавторитет", "орисс", "без источник", "нет источник",
                   "самиздат", "реклам", "копивио", "нарушение ап")


def last_own_edit(title):
    """Дата нашей последней правки, правки после неё и найденные отмены.

    ⚠️ Мерить только «что было после последней нашей правки» недостаточно:
    если нас откатили, а потом мы сами что-то дописали, откат оказывается
    ПОСЕРЕДИНЕ и в такой мерке не виден вовсе. Проверено 12.09.2026: скрипт
    написал «после нас никто не правил» про статью, где за восемь минут до
    этого вырезали наш абзац. Поэтому отмены ищутся по всей доступной истории,
    независимо от того, где стоит наша последняя правка.
    """
    lang, title = split_lang(title)
    d = api(lang, action="query", prop="revisions", titles=title,
            rvlimit=50, rvprop="timestamp|user|comment|size")
    pages = d.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None, None, None, []
    revs = pages[0].get("revisions", [])

    # Отмены и урезания НАШИХ правок — по всей истории, а не только после
    # последней нашей. Три независимых признака, потому что ни один не полон:
    #   1) комментарий говорит «отмена/откат» И называет нас;
    #   2) комментарий содержит претензию к источнику («не АИ», ОРИСС…);
    #   3) правка чужая и УМЕНЬШИЛА размер сразу после нашей — самый надёжный
    #      признак, он не зависит от того, что человек написал в комментарии.
    reverts = []
    for i, r in enumerate(revs):
        if r.get("user") == USER:
            continue
        c = (r.get("comment") or "").lower()
        why = None
        if any(m in c for m in REVERT_MARKS) and USER.lower() in c:
            why = "отмена нашей правки"
        elif any(m in c for m in COMPLAINT_MARKS):
            why = "претензия к источнику"
        else:
            prev = revs[i + 1] if i + 1 < len(revs) else None
            if (prev and prev.get("user") == USER
                    and isinstance(r.get("size"), int) and isinstance(prev.get("size"), int)
                    and r["size"] < prev["size"]):
                why = f"урезал наш текст на {prev['size'] - r['size']} б"
        if why:
            reverts.append({**r, "_why": why})

    after = []
    for r in revs:
        if r.get("user") == USER:
            return r["timestamp"], after, revs[0]["timestamp"], reverts
        after.append(r)
    return None, after, (revs[0]["timestamp"] if revs else None), reverts


def page_text(title):
    lang, title = split_lang(title)
    d = api(lang, action="parse", page=title, prop="wikitext")
    return d.get("parse", {}).get("wikitext", "")


def check(title, phrases):
    ours, after, _latest, reverts = last_own_edit(title)
    print(f"\n=== {title} ===")
    for r in reverts:
        print(f"  🔴 {r['_why'].upper()}: {r['timestamp'][:10]} {r.get('user')}")
        print(f"      {(r.get('comment') or '')[:150]}")
    if ours is None and after is None:
        print("  ⚠️  СТАТЬИ НЕТ")
        return 1
    if ours is None:
        print("  ⚠️  наших правок в последних 50 не найдено")
    else:
        print(f"  наша последняя правка: {ours[:10]}")

    if after:
        print(f"  ⚠️  ПОСЛЕ НЕЁ ПРАВОК: {len(after)}")
        for r in after[:5]:
            print(f"      {r['timestamp'][:10]} {r.get('user','?')}: {r.get('comment','')[:70]}")
    else:
        print("  после нас никто не правил")

    text = page_text(title)
    lost = [p for p in phrases if p not in text]
    if lost:
        print(f"  ❌ ПРОПАЛО ИЗ ТЕКСТА: {', '.join(lost)}")
        return 1
    print(f"  ✅ все {len(phrases)} наших фактов на месте")
    return 0


def own_articles():
    out = []
    for lang in ("ru", "ba"):
        d = api(lang, action="query", list="usercontribs", ucuser=USER,
                uclimit=500, ucprop="title|timestamp")
        pref = "" if lang == "ru" else lang + ":"
        out += [pref + c["title"] for c in d.get("query", {}).get("usercontribs", [])]
    return sorted(set(out))


def main():
    if "--user" in sys.argv:
        arts = own_articles()
        print("Статьи, которые мы правили:", ", ".join(arts) or "(нет)")
        unknown = [a for a in arts if a not in WATCH]
        if unknown:
            print(f"⚠️  не в реестре WATCH: {', '.join(unknown)} — добавь в скрипт")
        print()

    bad = sum(check(t, p) for t, p in WATCH.items())
    print("\n" + ("⚠️  есть проблемы, смотри выше" if bad else "Всё в порядке"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
