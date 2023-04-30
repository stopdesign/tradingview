from datetime import datetime
from time import sleep

import click
from termcolor import cprint

from settings import *
from tv.study_tester import TVStudyTester


@click.command()
@click.option("--force", is_flag=True)
def main(**kwargs):

    force = kwargs.get("force", False)

    tv = TVStudyTester(
        token=AUTH_TOKEN,
        strategies="../cache/strategies.jsonl",
        output="../res/res.jsonl",
        force=force
    )

    # study error
    # tv.test_strategy("Dxqv8ftu", "AMEX:ROBO", "30")

    # print("STRATEGIES", len(STRATEGIES))
    # print("INSTRUMENTS", len(INSTRUMENTS))

    # Разные стратегии и таймфреймы
    # symbol = "ES1!"
    for symbol in INSTRUMENTS:
        # print("\n========")
        # print(symbol)
        # print("========\n")
        for uid in STRATEGIES:
            try:
                strategy = tv.get_strategy_info(uid)
            except KeyError:
                cprint(f"Unknown Strategy: {uid}", "red")
                continue
            print()
            print(strategy["scriptName"], "//", strategy["author"]["username"])
            for tf in TIMEFRAMES:
                if tv.is_done(uid, symbol, tf):
                    continue
                try:
                    tv.test_strategy(uid, symbol, tf)
                except Exception as e:
                    cprint(f"TestStrategyError: {e}", "red")
                    raise e
                sleep(0.3)


if __name__ == "__main__":
    dt = datetime.now()
    try:
        main()
        print("DONE")
    except KeyboardInterrupt:
        print("BREAK")
    print(f"Done in {str(datetime.now() - dt)[:-7]}")
