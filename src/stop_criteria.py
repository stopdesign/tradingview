import os
import argparse
import logging
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
from sklearn.model_selection import ParameterGrid
from ml.processing_utils import PolygonNYSEDataProcessor


logging.basicConfig(format='%(asctime)s\t%(pathname)s:%(lineno)d - %(levelname)s - %(message)s', level="INFO")

def preprocess_raw_trades(data_directory, raw_trades, initial_capital=100000):
    """Prepare dataframe with trades for testing
    """
    #Seems like data from Trading View comes 10x bigger than it is displayed on the website
    trade_records = [{
        'price': x['e']['p'], 'enter_tm': x['e']['tm'], 'exit_price': x['x']['p'],
        'exit_tm': x['x']['tm'], 'profit': x['pf']/10,
        'cumulative_profit': x['cp']['v']/10, 'amount': x['q'],
        'side': 'buy' if 'long' in x['e']['c'] or 'LONG' in x['e']['c'] else 'sell'
    } for x in raw_trades["trades"]]
    trades = pd.DataFrame(trade_records)
    trades['enter_tm'] = pd.to_datetime(trades['enter_tm'], unit='ms')
    trades['tm'] = trades['enter_tm']
    trades['exit_tm'] = pd.to_datetime(trades['exit_tm'], unit='ms')
    trades['trade_duration'] = trades['exit_tm'] - trades['enter_tm']
    trades['trade_duration'] = trades['trade_duration'].apply(lambda x: x/pd.Timedelta('1 hour'))
    trades['capital'] = initial_capital + trades['cumulative_profit']
    trades['roll_max'] = trades['capital'].cummax()
    trades['daily_drawdown'] = trades['capital']/trades['roll_max'] - 1.0
    trades['max_daily_drawdown'] = -trades['daily_drawdown'].cummin()
    trades['cash'] = trades['amount'].shift(1)*trades['price'].shift(1)
    trades['cash'] = trades['cash'].bfill()
    trades['profit_rel'] = 100*trades['profit']/trades['cash']

    ohlc = PolygonNYSEDataProcessor(data_directory, raw_trades['instrument'].split(':')[-1]).run()
    trades = trades[trades['enter_tm'] >= ohlc.index[0]]
    trades['tm'] = trades['enter_tm']
    ohlc = ohlc.join(trades.set_index("enter_tm"))
    ohlc['tm'] = ohlc.index
    ohlc['amount'] = ohlc['amount'].ffill()
    ohlc['side'] = ohlc['side'].ffill()
    ohlc['price'] = ohlc['price'].ffill()
    ohlc = ohlc.dropna(subset=['price', 'amount', 'side', 'h', 'l'])
    ohlc['signed_enter_price'] = ohlc.apply(lambda x: x['price'] if x['side'] == 'sell' else -x['price'], axis=1)
    ohlc['signed_tm_exit_price'] = ohlc.apply(lambda x: -x['h'] if x['side'] == 'sell' else x['l'], axis=1)
    ohlc['trades_profit'] = ohlc['profit'].fillna(0)
    ohlc['cash'] = ohlc['amount'].shift(1)*ohlc['price'].shift(1)
    ohlc['cash'] = ohlc['cash'].bfill()
    ohlc['profit'] = (ohlc['signed_enter_price'] + ohlc['signed_tm_exit_price'])*ohlc['amount'] + ohlc['trades_profit'].cumsum()
    ohlc['profit_rel'] = 100*ohlc['profit']/ohlc['cash']
    ohlc['tm_pnl'] = (ohlc['profit_rel'] - ohlc['profit_rel'].shift(1)).fillna(0)

    return trades, ohlc

def std_dev(data):
    n = len(data)
    mean = sum(data) / n
    deviations = sum([(x - mean)**2 for x in data])
    variance = deviations / (n - 1)
    std = variance**(1/2)
    return std

def sharpe_ratio(data, risk_free_rate=0.0):
    mean_daily_return = sum(data) / len(data)
    std = std_dev(data)
    if std:
        daily_sharpe_ratio = (mean_daily_return - risk_free_rate) / std
        return 252**(1/2) * daily_sharpe_ratio

    return 0.0

def get_stats(ohlc):
    if len(ohlc) == 0:
        raise Exception("Empty ohlc")
    max_dd = max((ohlc['profit_rel'].cummax() - ohlc['profit_rel']) * 1)
    if max_dd == 0:
        raise Exception("Zero division")
    sr = sharpe_ratio(ohlc.tm_pnl)
    profit_rel = ohlc['profit_rel'][-1]
    roi_mdd = profit_rel/max_dd
    profit_rel_series = ohlc['profit_rel']/(ohlc['profit_rel'].cummax() - ohlc['profit_rel'])
    return max_dd, sr, profit_rel, roi_mdd, profit_rel_series

def trades_profit_months_stop_criteria(trades, months=2, offset_months=6, p=0.05):
    """Use non-parametric Mann Whitney U test for checking if distributions match
    """
    start_date, end_date = trades['enter_tm'].iloc[0], trades['enter_tm'].iloc[-1]
    tested_periods = int((end_date - start_date)/pd.Timedelta(days=30))
    for test_start_date in pd.period_range(start=start_date + pd.tseries.offsets.MonthEnd(offset_months),
                                           periods=tested_periods + 1 - offset_months, freq='M'):
        test_start_date = test_start_date.to_timestamp()
        test_end_date = test_start_date + pd.tseries.offsets.MonthEnd(months)
        accumulated_trades = trades[trades['enter_tm'] < test_start_date]
        tested_trades = trades[(trades['enter_tm'] >= test_start_date) & (trades['enter_tm'] < (test_end_date))]
        if accumulated_trades.empty or tested_trades.empty:
            continue
        method = "asymptotic" if len(accumulated_trades) > 200 or len(tested_trades) > 30 else "exact"
        _, p_profit = mannwhitneyu(accumulated_trades['profit'], tested_trades['profit'], alternative="greater", method=method)

        if p_profit < p:
            return tested_trades['tm'].dt.to_pydatetime()[-1]
    return None

def trades_profit_stop_criteria(trades, window=20, p=0.05):
    for right_border in range(3*window, len(trades) + 1):
        accumulated_trades = trades[:right_border-window]
        tested_trades = trades[right_border-window:right_border]
        if accumulated_trades.empty or tested_trades.empty:
            continue
        method = "asymptotic" if len(accumulated_trades) > 200 or len(tested_trades) > 30 else "exact"
        _, p_profit = mannwhitneyu(accumulated_trades['profit'], tested_trades['profit'], alternative="greater", method=method)

        if p_profit < p:
            return tested_trades['tm'].dt.to_pydatetime()[-1]
    return None

def trades_duration_stop_criteria(trades, window=20, p=0.05):
    for right_border in range(3*window, len(trades) + 1):
        accumulated_trades = trades[:right_border-window]
        tested_trades = trades[right_border-window:right_border]
        if accumulated_trades.empty or tested_trades.empty:
            continue
        method = "asymptotic" if len(accumulated_trades) > 200 or len(tested_trades) > 30 else "exact"
        _, p_profit = mannwhitneyu(accumulated_trades['trade_duration'], tested_trades['trade_duration'], alternative="greater", method=method)

        if p_profit < p:
            return tested_trades['tm'].dt.to_pydatetime()[-1]
    return None

def trades_daily_profit_stop_criteria(ohlc, window=20, p=0.05):
    df = ohlc.resample("1D").apply({
        "tm": "first",
        "profit_rel": "last",
    })
    df.dropna(inplace=True)
    df["pnl"] = (df["profit_rel"] - df["profit_rel"].shift(1)).fillna(0)

    for right_border in range(3*window, len(df) + 1):
        accumulated = df[:right_border-window]
        tested = df[right_border-window:right_border]
        if accumulated.empty or tested.empty:
            continue
        method = "asymptotic" if len(accumulated) > 200 or len(tested) > 30 else "exact"
        _, p_profit = mannwhitneyu(accumulated['pnl'], tested['pnl'], alternative="greater", method=method)

        if p_profit < p:
            return tested.index.to_pydatetime()[-1]
    return None

def trades_distribution_parameters_stop_criteria(trades, window=20):
    df = trades[trades["profit_rel"] != 0]
    if len(df) < window + 10:
        return None

    df = df.assign(median=df["profit_rel"].rolling(window).median())
    df = df.assign(skew=df["profit_rel"].rolling(window + 10).skew())
    df_out = df[(df['skew'] < 0.8) & (df['median'] < -1)]

    return not df_out.empty and df_out["tm"].dt.to_pydatetime()[0] or None

def trades_daily_distribution_parameters_stop_criteria(ohlc):
    df = ohlc.resample("1D").apply({
        "tm": "first",
        "profit_rel": "last",
    })
    df.dropna(inplace=True)
    if len(df) < 60:
        return None
    df["pnl"] = (df["profit_rel"] - df["profit_rel"].shift(1)).fillna(0)
    df['rsr'] = df.pnl.rolling(60).apply(lambda x: x.mean() / x.std(), raw = True)
    df_out = df[(df["rsr"] < -0.2)]

    return not df_out.empty and df_out["tm"].dt.to_pydatetime()[0] or None


criteria_parameters = {
        'trades_profit_months_stop_criteria': {
            'months': [1, 2, 3],
            'offset_months': [6],
            'p': [0.1, 0.05],
        },
        'trades_profit_stop_criteria': {
            'window': [20, 30, 40],
            'p': [0.1, 0.05],
        },
        'trades_duration_stop_criteria': {
            'window': [20, 30, 40],
            'p': [0.1, 0.05],
        },
        'trades_daily_profit_stop_criteria': {
            'window': [20, 30, 40],
            'p': [0.1, 0.05],
        },
        'trades_distribution_parameters_stop_criteria': {
            'window': [20, 30, 40],
        },
        'trades_daily_distribution_parameters_stop_criteria': {},
}


def run_tests(data_directory, run_directory, filename, trades_df, initial_capital):
    """Run tests for each strategy in the dataframe with specified parameters"""
    results = []
    for i in range(len(trades_df)):
        record = trades_df.iloc[i]
        try:
            if not record["trades"]:
                logging.info("Skipping empty {} for {} with {} timeframe".format(record['scriptName'],
                                                                                 record["instrument"],
                                                                                 record["timeframe"]))
                continue
            logging.info("Preprocessing {} for {} with {} timeframe".format(record['scriptName'],
                                                                            record["instrument"],
                                                                            record["timeframe"]))
            trades, ohlc = preprocess_raw_trades(data_directory, record, initial_capital)
            logging.info("Preprocessed {} for {} with {} timeframe".format(record['scriptName'],
                                                                           record["instrument"],
                                                                           record["timeframe"]))
            max_dd, sr, profit_rel, roi_mdd, _ = get_stats(ohlc)
            logging.info("Calculated stats {} for {} with {} timeframe".format(record['scriptName'],
                                                                               record["instrument"],
                                                                               record["timeframe"]))
        except Exception as e:
            logging.exception(e)
            continue

        for criteria_name, parameters_grid in criteria_parameters.items():
            for parameters in ParameterGrid(parameters_grid):
                try:
                    criteria = globals()[criteria_name]
                    df = ohlc if criteria_name.startswith('trades_daily') else trades
                    logging.info("Started running {} with  {}".format(criteria_name, parameters))
                    strategy_last_date = criteria(df, **parameters)
                    logging.info("Run {} with {}".format(criteria_name, parameters))
                    # to check
                    last_not_inclusive_index = ohlc.index.searchsorted(strategy_last_date, side='right')
                    if last_not_inclusive_index == 0:
                        raise Exception("Last not inclusive index is out of ohlc")
                    max_dd_stopped, sr_stopped, profit_rel_stopped, roi_mdd_stopped, _ = get_stats(ohlc[:last_not_inclusive_index])
                    prct_run = last_not_inclusive_index / len(ohlc)
                    logging.info("Calculated stats for {} with {}".format(criteria_name, parameters))

                    result = list(record[['scriptName', 'timeframe', 'instrument']].values)
                    result.extend([f"{criteria_name}_{''.join([f'{key}:{value},' for key, value in parameters.items()])[:-1]}", parameters])
                    result.extend([max_dd, sr, profit_rel, roi_mdd])
                    result.extend([max_dd_stopped, sr_stopped, profit_rel_stopped, roi_mdd_stopped, prct_run, strategy_last_date])
                    results.append(result)
                except Exception as e:
                    logging.exception(e)
                    continue

    pd.DataFrame(results, columns=['scriptName', 'timeframe', 'instrument',
                                   'criteria', 'parameters', 'max_dd', 'sr',
                                   'profit_rel', 'roi_mdd',
                                   'max_dd_stopped', 'sr_stopped',
                                   'profit_rel_stopped', 'roi_mdd_stopped',
                                   'prct_run',
                                   'strategy_last_date']).to_csv(f"{run_directory}/{os.path.basename(filename).split('.')[0]}_results.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('run_directory')
    parser.add_argument('data_directory')
    args = parser.parse_args()

    for filename, capital in [('../res/res.jsonl', 100000),
                              ('../res/wheat_futures.jsonl', 10000000)]:
        logging.info("Reading {}".format(filename))
        trades_df = pd.read_json(filename, orient="records", lines=True)
        logging.info("Finished reading {}".format(filename))
        trades_df = trades_df.drop_duplicates(subset=['scriptName', 'instrument', 'timeframe'])
        trades_df = trades_df.reset_index()
        run_tests(args.data_directory, args.run_directory, filename, trades_df, capital)
