"""
Сохраняет список публично доступных стратегий.
"""

import json
from datetime import datetime
from time import sleep

import requests

URL = "https://www.tradingview.com/pubscripts-suggest-json/?search=%s&offset=%s"


def get_list(query="a", offset=0):

    results = []

    while offset < 1000:
        url = URL % (query, offset)
        r = requests.get(url)
        if r.status_code != 200:
            break

        results += r.json()["results"]

        print(r.status_code, len(r.text), end=" ")
        try:
            next_link = r.json()["next"]
            # print(next_link)
            offset = int(next_link.split("=")[1])
            if offset == 1000:
                offset = 999
        except Exception as e:
            print("ERROR", e)
            print(r.text)
            break
        print()
        sleep(0.5)

    # print("done")
    # print(len(results))

    return results


def main():
    queries = ["strat"]
    queries += list("abcdefghijklmnopqrstuvwxyz0123456789")
    queries += ["th", "er", "on", "an", "the", "ss", "ee", "tt", "ff"]

    results = []

    for query in queries:
        print()
        print(query)
        results += get_list(query)
        print(len(results))

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
