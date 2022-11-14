import base64
import io
import json
import os
import random
import re
import zipfile
from datetime import datetime
from functools import cache
from string import ascii_lowercase
from time import sleep

import numpy
import requests
import websocket
from termcolor import cprint

from tv.utils import round_floats, ts_to_dt, create_message, prepend_header


class TVStudyTester:

    code_base_dir = "../cache/code"

    ws_url = "wss://prodata.tradingview.com/socket.io/websocket"
    pine_facade_url = "https://pine-facade.tradingview.com/pine-facade"

    symbol = None
    timeframe = None
    pine_id = None
    _symbol_index = 0

    deposit = 1_000_000

    def __init__(self, token, strategies, output, force=False):
        self.ws = None
        self.sid = None

        self.connected = False

        self.start_dt = datetime.now()
        self.auth_token = token

        # Стратегии по uid
        self.by_uid = {}
        with open(strategies) as f:
            for ln in f.readlines():
                strategy = json.loads(ln.strip().strip(","))
                uid = strategy["imageUrl"]
                self.by_uid[uid] = strategy

        self.output = output

        # Посмотреть, что уже загружено
        self.done = []
        if os.path.isfile(self.output) and not force:
            with open(self.output, "r+") as f:
                for line in f.read().strip().splitlines():
                    j = json.loads(line)
                    test_id = "{imageUrl}_{instrument}_{timeframe}".format(**j)
                    self.done.append(test_id)

    @property
    def symbol_id(self):
        return f"sds_sym_{self._symbol_index}"

    def generate_chart_session_id(self):
        return "cs_" + "".join(random.choice(ascii_lowercase) for _ in range(12))

    def is_done(self, uid, symbol, tf):
        test_id = f"{uid}_{symbol}_{tf}"
        return test_id in self.done

    def send_msg(self, func, args):
        msg = create_message(func, args)
        # cprint(msg[:200], "yellow")
        self.ws.send(msg)

    def send_raw_msg(self, message):
        msg = prepend_header(message)
        # cprint(msg[:200], "green")
        self.ws.send(msg)

    def connect(self):
        self.ws = websocket.create_connection(self.ws_url, timeout=15)
        self.sid = self.generate_chart_session_id()
        self.send_msg("set_auth_token", [self.auth_token])
        self.send_msg("chart_create_session", [self.sid, ""])
        self.connected = True

        # Reset current state
        self.symbol = None
        self.timeframe = None
        self.pine_id = None
        self._symbol_index = 0

    def get_strategy_info(self, uid):
        return self.by_uid[uid]

    def resolve_symbol(self, symbol):
        if "!" in symbol:
            # Товарные фьючерсы
            param = '={"adjustment":"splits","currency-id":"XTVUSX","session":"us_regular","symbol":"%s"}' % symbol
        else:
            # Акции и другое говно
            param = '={"adjustment":"splits","currency-id":"USD","session":"us_regular","symbol":"%s"}' % symbol
        self._symbol_index += 1
        self.send_msg("resolve_symbol", [self.sid, self.symbol_id, param])

    def update_setting(self, strategy, symbol, timeframe, inputs):

        pine_id = strategy["scriptIdPart"]

        # Если нужно будет менять стратегию,
        # то ей лучше удалить перед другими изменениями
        if self.pine_id and self.pine_id != pine_id:
            self.send_msg("remove_study", [self.sid, "st1"])
            self.pine_id = None

        if self.symbol != symbol:
            self.resolve_symbol(symbol)
            param = [self.sid, "sds_1", "s1", self.symbol_id, timeframe]
            if self.symbol:
                self.send_msg("modify_series", [*param, ""])
            else:
                self.send_msg("create_series", [*param, 1, ""])
            self.timeframe = timeframe
            self.symbol = symbol

        if self.timeframe != timeframe:
            param = [self.sid, "sds_1", "s1", self.symbol_id, timeframe]
            self.send_msg("modify_series", [*param, ""])
            self.timeframe = timeframe

        # Если стратегия изменилась
        if self.pine_id != pine_id:
            st_params = ["st1", "st1", "sds_1", "StrategyScript@tv-scripting-101!"]
            self.send_msg("create_study", [self.sid, *st_params, inputs])
            self.pine_id = pine_id

    @cache
    def fetch_inputs(self, pine_id):
        url = f"{self.pine_facade_url}/translate/{pine_id}/last/"
        r = requests.get(url, timeout=5)
        return r.json()

    def get_inputs(self, strategy):
        """
        Пробует загрузить инпуты из файла.
        Если не получилось, грузит из интернета.
        """
        name = strategy["scriptName"]
        uid = strategy["imageUrl"]
        pine_id = strategy["scriptIdPart"]

        file_name = re.sub("[^a-zA-Z0-9]+", "-", name).strip("-")
        file_path = f"{self.code_base_dir}/{uid}-{file_name}/translate.json"

        try:
            data = json.load(open(file_path))
        except Exception as e:
            cprint(f"GetFileInputsError: {e}", "yellow")
            data = self.fetch_inputs(pine_id)

        return data

    def modify_inputs(self, data):
        """
        Стандартизация общих параметров бэктеста.
        Кастомизация параметров стратегии.
        """
        inputs = data["result"]["metaInfo"]["inputs"]

        for var in inputs:
            var_id = var.get("internalID")
            if not var_id:
                continue
            if var_id in ["initial_capital", "default_qty_value"]:
                var["defval"] = self.deposit
            if var_id == "currency":
                var["defval"] = "USD"
            if var_id == "default_qty_type":
                var["defval"] = "cash_per_order"
            if var_id == "commission_value":
                var["defval"] = 0
            if var_id == "slippage":
                var["defval"] = 0

        # # HULL SUITE DIRECTION
        # for var in inputs:
        #     name = var.get("name")
        #     if name == "Strategy Direction":
        #         var["defval"] = "all"

        return data

    def format_inputs(self, data):
        inputs = data["result"]["metaInfo"]["inputs"]
        pine_id = data["result"]["metaInfo"]["scriptIdPart"]

        res = {
            "pineId": pine_id,
        }
        for inp in inputs:
            in_id = inp["id"]
            if "in_" in in_id:
                res[in_id] = {
                    "v": inp["defval"],
                    "f": inp["isFake"],
                    "t": inp["type"],
                }
            elif in_id == "text":
                res[in_id] = inp["defval"]

        return res

    def test_strategy(self, uid, symbol, timeframe):
        """
        Поменять настройки и стратегию, если надо.
        Распарсить результат.
        """
        try:
            strategy = self.get_strategy_info(uid)
        except KeyError:
            cprint(f"Unknown Strategy: {uid}", "red")
            return

        try:
            # Получить параметры стратегии (inputs)
            # и поставить значения по умолчанию.
            inputs = self.get_inputs(strategy)

            # Кастомизация значений параметров.
            inputs = self.modify_inputs(inputs)

            inputs = self.format_inputs(inputs)

        except Exception as e:
            cprint(f"GetInputsError: {e}", "red")
            raise Exception("GetInputsError")

        while not self.connected:
            try:
                self.connect()
            except Exception as e:
                cprint(f"ConnectError: {e}", "red")
                sleep(5)

        try:
            self.update_setting(strategy, symbol, timeframe, inputs)
        except Exception as e:
            self.connected = False
            cprint(f"UpdateSettingsError: {e}", "red")
            raise Exception("UpdateSettingsError")

        self.wait_for_result(strategy, symbol, timeframe)

    def parse_result(self, result, strategy, symbol, timeframe):

        res = re.findall(r'"ns":{"d":"({\\"data.*})","indexes"', result)
        result = json.loads(res[0].replace('\\"', '"'))

        if "dataCompressed" in result:
            bbb = result["dataCompressed"]
            fp = io.BytesIO(base64.b64decode(bbb))
            zfp = zipfile.ZipFile(fp, "r")
            decompressed = zfp.read("").decode()
            jjj = json.loads(decompressed)

        elif "data" in result:
            jjj = result["data"]

        else:
            cprint("NO DATA", "red")
            return

        performance = jjj["report"]["performance"]
        trades = jjj["report"]["trades"]
        settings = jjj["report"]["settings"]

        self.report(strategy, symbol, timeframe, performance, trades, settings)

    def wait_for_result(self, strategy, symbol, timeframe):

        uid = strategy["imageUrl"]
        test_id = f"{uid}_{symbol}_{timeframe}"
        dt_0 = datetime.utcnow()

        while True:
            if (datetime.utcnow() - dt_0).total_seconds() > 15:
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
                #     cprint(msg[:200], "white")

                # Health Check
                if rx := re.search(r"~h~(\d+)$", msg):
                    self.send_raw_msg(f"~h~{rx.group(1)}")
                    continue

                # Data update
                if 'm":"du"' in msg and ('ns":{"d":"{' in msg or 'ns":{"d":{' in msg):
                    self.parse_result(msg, strategy, symbol, timeframe)
                    return True

                if "study_completed" in msg:
                    cprint(f"NO DATA, {test_id}", "yellow")
                    return

                if "study_error" in msg:
                    cprint(f"STUDY ERROR, {test_id}, {msg[:200]}", "red")
                    return

                if "critical_error" in msg:
                    cprint(f"CRITICAL ERROR, {test_id}, {msg[:200]}", "magenta")
                    return

    def report(self, strategy, symbol, timeframe, perf, trades, settings):

        long = perf.pop("long")
        short = perf.pop("short")
        perf.update(perf.pop("all"))

        perf["totalTradesLong"] = long["totalTrades"]
        perf["netProfitLong"] = long["netProfit"]
        perf["netProfitPercentLong"] = long["netProfitPercent"]
        perf["profitFactorLong"] = long["profitFactor"]
        perf["percentProfitableLong"] = long["percentProfitable"]

        perf["totalTradesShort"] = short["totalTrades"]
        perf["netProfitShort"] = short["netProfit"]
        perf["netProfitPercentShort"] = short["netProfitPercent"]
        perf["profitFactorShort"] = short["profitFactor"]
        perf["percentProfitableShort"] = short["percentProfitable"]

        # perf["lookaheadFutureData"] = study._metaInfo.lookaheadFutureData

        # Интервалы сделок
        intervals = sorted([[t["e"]["tm"], t["x"]["tm"]] for t in trades])
        sum_all = sum([i[1] - i[0] for i in intervals])

        # Слить пересекающиеся интервалы
        merged = [intervals[0]] if intervals else []
        for current in intervals:
            previous = merged[-1]
            if current[0] <= previous[1]:
                previous[1] = max(previous[1], current[1])
            else:
                merged.append(current)

        # Интервалы с хотябы одной сделкой, сумма длин
        sum_merged = sum([i[1] - i[0] for i in merged])

        bt_range = settings["dateRange"]["backtest"]
        length = bt_range["to"] - bt_range["from"]

        perf["avgSimTrade"] = sum_all / sum_merged if sum_merged else float("nan")
        perf["inTradeTimePercent"] = sum_merged / length if length else float("nan")

        # Максимальная просадка внутри одной сделки
        if trades:
            perf["maxTradeDrawDown"] = max([t["dd"]["v"] for t in trades])
            perf["maxTradeDrawDownPercent"] = max([t["dd"]["p"] or 0 for t in trades])
        else:
            perf["maxTradeDrawDown"] = float("nan")
            perf["maxTradeDrawDownPercent"] = float("nan")

        # Максимальная просадка с учетом движений внутри сделки
        max_pf = 0  # абсолютный максимум профита
        max_dd = 0  # максимальный DD
        for trade in trades:
            v1 = trade["cp"]["v"] - trade["pf"]  # профит на начало сделки
            local_min_pf = v1 - trade["dd"]["v"]  # локальный минимум сделки
            dd = max_pf - local_min_pf
            max_dd = max([max_dd, dd])
            max_pf = max([max_pf, v1 + trade["rn"]["v"]])  # новый максимум профита

        perf["altMaxDrawDown"] = max_dd
        perf["altMaxDrawDownPercent"] = max_dd / self.deposit

        # R^2
        if trades:
            x = []
            y = []
            for trade in trades:
                x.append(trade["x"]["tm"])
                y.append(trade["cp"]["v"])
            corr = numpy.corrcoef(x, y)[0, 1]
            perf["r2"] = corr**2
        else:
            perf["r2"] = float("nan")

        # Объем первой сделки в USD (должен быть в районе размера депозита)
        try:
            perf["firstTradeSize"] = trades[0]["e"]["p"] * trades[0]["q"]
        except (KeyError, IndexError):
            perf["firstTradeSize"] = float("nan")

        duration = int((datetime.now() - self.start_dt).total_seconds())
        print(
            "{0:>5}s".format(duration),
            strategy["imageUrl"],
            "{0:>3}".format(timeframe),
            symbol,
            (
                " "
                f"from: {ts_to_dt(bt_range['from']).date()}  "
                "trades: {totalTrades:>4}  "
                "profit: {netProfitPercent:+0.2f}  "
                "r2: {r2:0.2f}  "
                # "first trade: {firstTradeSize:8.0f}"
            ).format(**perf),
        )

        perf = round_floats(perf)

        result = dict(
            {
                "scriptName": strategy["scriptName"],
                "imageUrl": strategy["imageUrl"],
                "pineId": strategy["scriptIdPart"],
                "timeframe": timeframe,
                "instrument": symbol,
            },
            **perf,
        )

        with open(self.output, "a") as f:
            res = json.dumps(result, indent=None, default=str) + "\n"
            f.write(res)
