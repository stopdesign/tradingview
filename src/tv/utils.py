import json
import math
from datetime import datetime, timezone


def round_floats(o):
    if isinstance(o, float):
        if math.isnan(o):
            return None
        res = round(o, 4)
        int_res = int(res)
        return int_res if res == int_res else res
    if isinstance(o, dict):
        return {k: round_floats(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [round_floats(x) for x in o]
    return o


def ts_to_dt(ts):
    return datetime.utcfromtimestamp(ts / 1000)


def dt_to_ts(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def prepend_header(st):
    return "~m~" + str(len(st)) + "~m~" + st


def construct_message(func, param_list):
    return json.dumps({"m": func, "p": param_list}, separators=(",", ":"))


def create_message(func, param_list):
    return prepend_header(construct_message(func, param_list))

