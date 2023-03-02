import glob
from datetime import datetime
import pandas as pd


class IBKRDataProcessor():
    def __init__(self, path: str, exchange: str, symbol: str, currency=False):
        self.currency = currency
        self.path = f'{path}/{exchange}/{symbol}' if not self.currency else f'{path}/{symbol}'
        self.exchange = exchange
        self.symbol = symbol

    def _extract_date(self, x):
        return datetime.fromisoformat(x.split('/')[-1].split('.')[0])

    def _get_bidask(self):
        self.bidask_list = []
        for filename in sorted(glob.glob(f'{self.path}/BIDASK/*.txt'),
                               key=lambda x: self._extract_date(x)):
            self.bidask_list.append(pd.read_csv(filename, sep='\t', parse_dates=['date']))
        self.bidask = pd.concat(self.bidask_list)\
                .drop(['volume', 'average', 'barCount', 'rth'], axis=1).set_index('date')
        return self.bidask

    def _get_trades(self):
        self.trades_list = []
        for filename in sorted(glob.glob(f'{self.path}/TRADES/*.txt'),
                               key=self._extract_date(x)):
            self.trades_list.append(pd.read_csv(filename, sep='\t', parse_dates=['date']))
        self.trades = pd.concat(self.trades_list).set_index('date')
        return self.trades

    def _get_midpoint(self):
        self.midpoint_list = []
        for filename in sorted(glob.glob(f'{self.path}/MIDPOINT/*.txt'),
                               key=lambda x: self._extract_date(x)):
            self.midpoint_list.append(pd.read_csv(filename, sep='\t', parse_dates=['date']))
        self.midpoint = pd.concat(self.midpoint_list)\
                .drop(['volume', 'average', 'barCount', 'rth'], axis=1).set_index('date')
        return self.midpoint

    def _join(self):
        """
        Joins two dataframes with time points - bidask and trades.
        Rows with any missing values are omitted which is around 18% (45622 + 122944). To be fixed.
        """
        self.data = self.bidask.join(self.trades).dropna()
        return self.data

    def run(self, interpolate_method=None):
        if not self.currency:
            #self._get_bidask()
            return self._get_trades()
            #return self._join()
        else:
            return self._get_midpoint()


class PolygonNYSEDataProcessor():
    def __init__(self, path: str, symbol: str):
        self.path = f'{path}'
        self.symbol = symbol

    def _get_trades(self):
        self.trades_list = []
        for filename in [f'{self.path}/pre_2022/{self.symbol}.csv',
                         f'{self.path}/2022/{self.symbol}.csv']:
            self.trades_list.append(pd.read_csv(filename))
        self.trades = pd.concat(self.trades_list).set_index('t')
        self.trades.index = pd.to_datetime(self.trades.index, unit='s')
        return self.trades

    def run(self, interpolate_method=None):
        return self._get_trades()
