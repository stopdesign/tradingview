import json
import os
import re
from time import sleep

import requests
from termcolor import cprint

PINE_FACADE_URL = "https://pine-facade.tradingview.com/pine-facade"
PINE_URL = f"{PINE_FACADE_URL}/get/%s/last?no_4xx=false"
TRANSLATE_URL = f"{PINE_FACADE_URL}/translate/%s/last/"
IMG_BASE_URL = "https://s3.tradingview.com"
HTML_URL = "https://www.tradingview.com/script/%s/"


ERR_CNT = 0

DELAY = 0.5


def get_source(strategy, dir_name):
    global ERR_CNT
    url = PINE_URL % strategy["scriptIdPart"]
    r = requests.get(url, timeout=15)
    try:
        res_json = r.json()
        file_name = os.path.join(dir_name, "pine.json")
        f = open(file_name, "w")
        f.write(json.dumps(res_json, indent=2, ensure_ascii=False))
        f.close()
    except Exception as e:
        cprint(f"error: {e}", "red")
        ERR_CNT += 1


def get_html(file_name, dir_name):
    global ERR_CNT

    url = HTML_URL % file_name

    r = requests.get(url, timeout=15)

    txt = r.text

    readme = ""

    rx = re.search(r'({[\s\r\n]+"viewChartOptions": .*)', txt, re.M)
    if rx and (groups := rx.groups()):
        try:
            options = json.loads(groups[0])["viewChartOptions"]
            content = json.loads(options["content"])

            readme += f"## {options['name']}\n\n"
            readme += f"{url}\n\n"

            if "charts" in content:
                content = content["charts"][0]

            for pane in content["panes"]:
                state = pane["sources"][0]["state"]
                # print(json.dumps(state, indent=2, default=str))
                if "symbol" in state:
                    readme += f"Symbol: {state['symbol']}\n\n"
                    readme += f"Interval: {state['interval']}\n\n"
                    break
        except:
            cprint(f"error in groups: {groups}", "red")
            ERR_CNT += 1
            return
    else:
        cprint(f"error: {txt[:100]}", "red")
        ERR_CNT += 1
        return

    tags = re.findall('tag-label--rounded " href="/scripts/(.*?)/">', txt)
    if tags:
        tags_str = '\n* '.join(tags)
        readme += f"Tags:\n* {tags_str}\n\n"

    rx = re.search('name="description" content="(.*?)" />', txt, re.DOTALL)
    if rx and (groups := rx.groups()):
        descr = str(groups[0]).strip()
        readme += f"{descr}\n\n"
    else:
        cprint(f"error: {txt[:100]}", "red")
        ERR_CNT += 1
        return

    if options:
        uid = options["chartId"]
        readme += f"![preview]({IMG_BASE_URL}/{uid[0].lower()}/{uid}.png)\n\n"

    file_name = os.path.join(dir_name, "readme.md")
    f = open(file_name, "w")
    f.write(readme)
    f.close()


def get_inputs(strategy, dir_name):
    global ERR_CNT
    url = TRANSLATE_URL % strategy["scriptIdPart"]
    try:
        r = requests.get(url, timeout=10)
        res_json = r.json()
        file_name = os.path.join(dir_name, "translate.json")
        f = open(file_name, "w")
        f.write(json.dumps(res_json, indent=2, ensure_ascii=False))
        f.close()
    except Exception as e:
        cprint(f"get_inputs error: {e}", "red")
        ERR_CNT += 1


def main():
    global ERR_CNT

    strategies_list = "../cache/strategies.jsonl"
    code_dir = "../cache/code"

    f = open(strategies_list)

    for i, ln in list(enumerate(f.readlines())):
        if ERR_CNT > 5:
            cprint("Too many errors", "red")
            return

        strategy = json.loads(ln.strip().strip(","))
        name = strategy["scriptName"]
        uid = strategy["imageUrl"]

        file_name = re.sub('[^a-zA-Z0-9]+', '-', name).strip("-")
        file_name = f"{uid}-{file_name}"
        file_path = f"{code_dir}/{file_name}"

        print(flush=True)

        if not os.path.exists(file_path):
            os.mkdir(file_path)

        try:

            if not os.path.isfile(os.path.join(file_path, "readme.md")):
                print(i, "README", file_name)
                get_html(file_name, file_path)
                sleep(DELAY)
            else:
                print(i, "SKIP README", file_name)

            if not os.path.isfile(os.path.join(file_path, "pine.json")):
                print(i, "PINE", file_name)
                get_source(strategy, file_path)
                sleep(DELAY)
            else:
                print(i, "SKIP PINE", file_name)

            if not os.path.isfile(os.path.join(file_path, "translate.json")):
                print(i, "INPUT", file_name)
                get_inputs(strategy, file_path)
                sleep(DELAY)
            else:
                print(i, "SKIP INPUT", file_name)

            # при успехе немного уменьшаю количество ошибок
            ERR_CNT -= 0.2
    
        except Exception as e:
            cprint(f"Error: {e}", "red")
            ERR_CNT += 1
        

if __name__ == "__main__":
    main()
