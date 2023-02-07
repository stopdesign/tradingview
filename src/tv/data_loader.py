import json
import random
from datetime import datetime
from string import ascii_letters

import pandas as pd
import websocket
from termcolor import cprint
from tv.utils import create_message, dt_to_ts, ts_to_dt


class TVDataLoader:

    ws_url = "wss://prodata.tradingview.com/socket.io/websocket"
    pine_facade_url = "https://pine-facade.tradingview.com/pine-facade"

    symbol = None
    timeframe = None

    def __init__(self, token, symbol, timeframe, session):
        self.ws = None
        self.sid = None

        self.connected = False

        self.start_dt = datetime.now()
        self.auth_token = token

        self.symbol = symbol
        self.timeframe = timeframe
        self.session = session or "regular"

    @property
    def symbol_id(self):
        return f"sds_sym_{self._symbol_index}"

    def send_msg(self, func, args):
        for i, arg in enumerate(args):
            if type(arg) is dict:
                args[i] = "=%s" % json.dumps(arg)
        msg = create_message(func, args)
        # cprint(msg[:200], "yellow")
        self.ws.send(msg)

    def generate_session_id(self, prefix=""):
        sid = "".join(random.choice(ascii_letters) for _ in range(12))
        return prefix + "_" + sid

    def connect(self):
        self.ws = websocket.create_connection(self.ws_url, timeout=5)

        self.connected = True
        self._symbol_index = 0

        self._first_ts = dt_to_ts(datetime.utcnow())
        self._status = "start"

        self.sid = self.generate_session_id(prefix="cs")
        self.rid = self.generate_session_id(prefix="rs")

        self.send_msg("set_auth_token", [self.auth_token])
        self.send_msg("chart_create_session", [self.sid, ""])

    def wait_for_result(self, msg_type=None):

        dt_0 = datetime.utcnow()

        while True:
            if (datetime.utcnow() - dt_0).total_seconds() > 10:
                cprint("TIMEOUT", "red")
                return

            try:
                results = self.ws.recv()
            except Exception as e:
                cprint(e, "red")
                return

            for msg in results.split("~m~"):
                # Разбор сообщений разного типа

                # if len(msg) > 10:
                #     cprint(f"{len(msg):>7} {msg[:100]}", "white")

                if "timescale_update" in msg:
                    self.parse_result(msg)
                    # return True

                if "error" in msg:
                    cprint(f"SOME ERROR, {msg[:200]}", "red")
                    self._status = "error"
                    return

                if msg_type and msg_type in msg:
                    return msg

    def parse_result(self, msg):

        res = json.loads(msg)

        series = res["p"][1]["sds_1"]["s"]

        if len(series) > 0:
            a = len(series)
            b = json.dumps(series[:1])
            c = json.dumps(series[-1:])
            # cprint(f"Data: {a}, {b} .. {c}", "blue")

            self._first_ts = int(series[0]["v"][0])

            self.result += [row["v"] for row in series]

    def format_result(self):

        if not self.result:
            return

        # Колонки в данных TV
        columns = self._symbol_info["columns"]

        # Почему-то данные close присылают в 4 одинаковых колонках
        columns = "cccc" if columns == "c" else columns

        columns = ["ts"] + list(columns)

        df = pd.DataFrame(self.result, columns=columns)

        if "v" in columns:
            df["v"] = df["v"].astype("Int64")

        df["ts"] = df["ts"].astype("Int64")
        df["dt"] = pd.to_datetime(df["ts"], unit="s")

        df = df.set_index("dt", drop=True).sort_index(ascending=True)

        return df

    def parse_symbol_info(self, msg):

        res_raw = json.loads(msg)
        symbol_info = res_raw["p"][2]

        # cprint(json.dumps(res_raw, indent=2), "white")

        res = {
            "full_name": symbol_info["full_name"],
            "description": symbol_info["description"],
            "currency_id": symbol_info.get("currency_id"),
            "exchange": symbol_info["exchange"],
            "type": symbol_info["type"],
            "timezone": symbol_info["timezone"],
            "columns": symbol_info["visible_plots_set"],
            "subsessions": [],
            "ss_str": "",
        }
        for ss in symbol_info["subsessions"]:
            res["subsessions"].append(
                {"id": ss["id"], "description": ss["description"]}
            )
            res["ss_str"] += ss["id"] + ", "
        res["ss_str"] = res["ss_str"].strip().strip(",")

        txt = (
            "Symbol: {full_name}\n"
            "Description: {description}\n"
            "Type: {type}\n"
            "Currency: {currency_id}\n"
            "Exchange: {exchange}\n"
            "Timezone: {timezone}\n"
            "Sessions: {ss_str}\n"
            "Columns: {columns}\n".format(**res)
        ).strip()

        cprint(f"\n{txt}\n", "blue")

        return res

    def run(self):

        self.result = []

        self.connect()

        symbol = self.symbol
        timeframe = self.timeframe

        # Получение параметров инструмента для валидации
        params = [self.sid, self.symbol_id, {"symbol": symbol}]
        self.send_msg("resolve_symbol", params)
        if msg := self.wait_for_result("symbol_resolved"):
            self._symbol_info = self.parse_symbol_info(msg)
        else:
            cprint("resolve_symbol error", "red")
            return

        # Каждый новый символ должен иметь свой ID при вызове resolve_symbol
        self._symbol_index += 1

        # Данные Replay становятся наблюдаемым инструментом
        # TODO: можно взять resolve_symbol
        # вместо symbol передается replay, внутри которого лежит symbol
        # после этого можно делать replay_reset и смещать дату конца данных
        params = {
            "replay": self.rid,
            "symbol": {
                "backadjustment": "default",
                "adjustment": "splits",
                "session": self.session,
                "symbol": self._symbol_info["full_name"],
            },
        }
        if currency_id := self._symbol_info["currency_id"]:
            params["symbol"]["currency-id"] = currency_id
        params = [self.sid, self.symbol_id, params]
        self.send_msg("resolve_symbol", params)

        # Инструмент Replay добавляется на график, данные начинают загружаться
        # TODO: взять update_setting() ???
        params = [self.sid, "sds_1", "s1", self.symbol_id, timeframe, 50000]
        self.send_msg("create_series", params)

        # Входим в режим Replay
        self.send_msg("replay_create_session", [self.rid])
        self.wait_for_result("replay_instance_id")

        # Несколько итераций смещения Replay,
        # пока не вернутся все доступные данные
        while self._status in ["start", "limit"]:

            cprint(f"\n{ts_to_dt(self._first_ts * 1000)}\n", "green")

            # Передвинуть дату конца Replay
            self.send_msg("replay_reset", [self.rid, "step-1", self._first_ts])
            msg = self.wait_for_result("series_completed") or ""
            if '"data_completed":"end"' in msg:
                self._status = "end"
            elif "limit" in msg:
                self._status = "limit"
            else:
                self._status = "done"

        cprint(f"\n{ts_to_dt(self._first_ts * 1000)}\n", "blue")

        return self.format_result()
