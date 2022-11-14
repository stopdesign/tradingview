"""
Загрузка данных из TV.

python get_data.py ZO1! 1H --session=us_regular

"""

from datetime import datetime

import click

from settings import *
from tv.data_loader import TVDataLoader


@click.command()
@click.argument("symbol")
@click.argument("timeframe")
@click.option("--session", type=str)
def main(**kwargs):

    symbol = kwargs.get("symbol")
    timeframe = kwargs.get("timeframe")
    session = kwargs.get("session")

    dl = TVDataLoader(AUTH_TOKEN, symbol, timeframe, session)
    dl.run()


if __name__ == "__main__":
    dt = datetime.now()
    try:
        main()
        print("DONE")
    except KeyboardInterrupt:
        print("BREAK")
    print(f"Done in {str(datetime.now() - dt)[:-7]}")
