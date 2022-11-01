"""
Сохраняет список публично доступных стратегий.

Все результаты выгрузить нельзя, поэтому приходится запрашивать части списка
через поиск, перебирая комбинации букв.

Загрузка занимает примерно час, если хорошо перекрывать все буквы.
"""

import itertools
import json
import string
from datetime import datetime
from time import sleep

import requests

URL = "https://www.tradingview.com/pubscripts-suggest-json/?search=%s&offset=%s"
TIMEOUT = 5


def too_many_results(query="a"):
    for _ in range(10):
        try:
            url = URL % (query, 999)
            r = requests.get(url, timeout=TIMEOUT)
            return bool(r.json().get("next"))
        except Exception as e:
            print(f"ERROR at {url}: {e}")
            sleep(5)
    raise Exception("Too many errors")


def get_list(query="a", offset=0):

    results = []

    while offset < 1000:
        url = URL % (query, offset)

        try:
            r = requests.get(url, timeout=TIMEOUT)
            res_json = r.json()
            print(len(res_json.get("results", "")), end=", ", flush=True)
        except Exception as e:
            print(f"ERROR at {url}: {e}")
            sleep(5)
            continue

        results += res_json["results"]

        if next_link := res_json.get("next"):
            offset = int(next_link.split("=")[1])
            if offset == 1000:
                offset = 999
        else:
            break

        sleep(0.5)

    return results


def main():

    queries = []

    # NORMAL MODE, 45 queries
    # queries += list("abcdefghijklmnopqrstuvwxyz0123456789")
    # queries += ["th", "er", "on", "an", "the", "ss", "ee", "tt", "ff"]

    # HARDCORE MODE, 677 or 1297 queries
    alphanum = string.ascii_lowercase  # + string.digits
    for l1, l2 in itertools.product(alphanum, alphanum):
        queries.append(f"{l1}{l2}")

    print(f"Total queries: {len(queries)}")

    results = []

    queries_plus = []
    
    for query in queries:
        # Проверить, можно ли получить все результаты
        if too_many_results(query):
            print(query, "many")
            # добавить перебор еще одной буквы
            for l1, l2 in itertools.product([query], alphanum):
                queries_plus.append(f"{l1}{l2}")
        else:
            print(query, "OK")
            queries_plus.append(query)
        sleep(0.3)

    queries_plus += ["strat"]
    queries_plus += list("0123456789")

    print(f"Total queries_plus: {len(queries_plus)}")

    for query in queries_plus:
        print(query)
        results += get_list(query)
        print(f"\nResults: {len(results)}\n")

        txt = ""
        ids = {}
        for r in results:
            old_strategy = not r["extra"] and "strategy" in r["scriptName"].lower()
            new_strategy = r["extra"].get("kind") == "strategy"
            if old_strategy or new_strategy:
                if r["scriptIdPart"] not in ids:
                    ids[r["scriptIdPart"]] = 1
                    r["scriptSource"] = ""
                    r["weight"] = 0
                    txt += json.dumps(r, ensure_ascii=False) + ",\n"

        f = open("../cache/strategies.jsonl", "w")
        f.write(txt)


if __name__ == "__main__":
    dt = datetime.now()
    try:
        main()
        print("DONE")
    except KeyboardInterrupt:
        print("BREAK")
    print(f"Done in {str(datetime.now() - dt)[:-7]}")
