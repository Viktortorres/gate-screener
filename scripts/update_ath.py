import concurrent.futures
import datetime
import json
import math
import pathlib
import time
import urllib.parse
import urllib.request

BASE = "https://api.gateio.ws/api/v4/futures/usdt/"
PATH = pathlib.Path("docs/data/ath.json")
DAY = 86400


def get(endpoint, **params):
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                return json.load(response)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def scan(contract, previous, now):
    name = contract["name"]
    created = int(contract.get("create_time") or 0)
    if not created:
        raise ValueError("Нет даты создания контракта")

    if previous.get("created") != created:
        previous = {}

    cursor = int(previous.get("through", created)) // DAY * DAY
    high = float(previous.get("ath", 0))
    first = previous.get("first_candle")

    while cursor <= now:
        end = min(now, cursor + 1999 * DAY - 1)
        candles = get(
            "candlesticks",
            contract=name,
            interval="1d",
            **{"from": cursor, "to": end},
        )
        if not candles:
            raise ValueError("История недоступна: ATH не подтверждён")

        values = [float(c["h"]) for c in candles]
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("Некорректные цены в истории")

        earliest = min(int(c["t"]) for c in candles)
        if first is None:
            if earliest > cursor + DAY:
                raise ValueError("История не доходит до создания контракта")
            first = earliest

        high = max(high, *values)
        cursor = end + 1

    return name, {
        "ath": high,
        "created": created,
        "first_candle": first,
        "through": now,
    }


def main():
    now = int(time.time())
    old = (
        json.loads(PATH.read_text())
        if PATH.exists()
        else {"contracts": {}}
    )
    contracts = [
        c for c in get("contracts")
        if not c.get("in_delisting")
    ]
    output, errors = {}, {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {
            pool.submit(
                scan, c, old["contracts"].get(c["name"], {}), now
            ): c["name"]
            for c in contracts
        }

        for future in concurrent.futures.as_completed(tasks):
            name = tasks[future]
            try:
                key, value = future.result()
                output[key] = value
            except Exception as error:
                errors[name] = str(error)
                if name in old["contracts"]:
                    output[name] = old["contracts"][name]
                print(name, error, flush=True)

    if not output:
        raise RuntimeError("Нет проверенных данных ATH")

    data = {
        "updated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "contracts": output,
        "errors": errors,
    }

    PATH.parent
