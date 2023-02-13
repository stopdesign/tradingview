from scipy.stats import mannwhitneyu
import pandas as pd
import numpy as np


def preprocess_raw_trades(raw_trades, start_date=None):
    """Prepare dataframe with trades for testing
    """
    #Seems like data from Trading View comes 10x bigger than it is displayed on the website
    trades = pd.DataFrame([{'enter_price': x['e']['p'], 'enter_tm': x['e']['tm'],
                            'exit_price': x['x']['p'], 'exit_tm': x['x']['tm'],
                            'profit': x['pf']/10,
                            'cumulative_profit': x['cp']['v']/10} for x in raw_trades["trades"]])
    trades['sign'] = (trades['profit'] > 0).apply(lambda x: int(x > 0))
    trades['enter_tm'] = pd.to_datetime(trades['enter_tm'], unit='ms')
    trades['exit_tm'] = pd.to_datetime(trades['exit_tm'], unit='ms')
    trades['trade_duration'] = trades['exit_tm'] - trades['enter_tm']
    trades['trade_duration'] = trades['trade_duration'].apply(lambda x: x/pd.Timedelta('1 hour'))
    if start_date is not None:
        trades['cumulative_profit'] = trades['cumulative_profit'] - trades[trades['enter_tm'] < start_date]['cumulative_profit'].iloc[-1]
        trades = trades[trades['enter_tm'] >= start_date]
    trades['num'] = 1
    trades['capital'] = 100000 + trades['cumulative_profit']
    trades['roll_max'] = trades['capital'].cummax()
    trades['daily_drawdown'] = trades['capital']/trades['roll_max'] - 1.0
    trades['max_daily_drawdown'] = -trades['daily_drawdown'].cummin()
    return trades


def mann_whitneyu_stop_criteria(trades, months, offset_months, p, duration_test):
    """Use non-parametric Mann Whitney U test for checking if distributions match
    """
    start_date, end_date = trades['enter_tm'].iloc[0], trades['enter_tm'].iloc[-1]
    tested_periods = int((end_date - start_date)/pd.Timedelta(days=30))
    max_dd = trades['max_daily_drawdown'].iloc[-1]
    roi = trades['cumulative_profit'].iloc[-1]/100000
    risk_metric = -trades[trades['profit'] > 0]['profit'].sum()/trades[trades['profit'] < 0]['profit'].sum()
    for test_start_date in pd.period_range(start=start_date + pd.tseries.offsets.MonthEnd(offset_months),
                                           periods=tested_periods + 1 - offset_months, freq='M'):
        test_start_date = test_start_date.to_timestamp()
        test_end_date = test_start_date + pd.tseries.offsets.MonthEnd(months)
        print(f'Tested period from {test_start_date} to {test_end_date}')
        accumulated_trades = trades[trades['enter_tm'] < test_start_date]
        tested_trades = trades[(trades['enter_tm'] >= test_start_date) & (trades['enter_tm'] < (test_end_date))]
        if not len(accumulated_trades) or not len(tested_trades):
            continue
        print(f'Accumulated length: {len(accumulated_trades)}, tested length: {len(tested_trades)}')
        method = "asymptotic" if len(accumulated_trades) > 200 or len(tested_trades) > 30 else "exact"
        _, p_profit = mannwhitneyu(accumulated_trades['profit'], tested_trades['profit'], alternative="greater", method=method)
        if duration_test:
            _, p_duration = mannwhitneyu(accumulated_trades['trade_duration'], tested_trades['trade_duration'], method=method)
            print(f'Profit test p-value: {p_profit}, duration test p-value: {p_duration}')
        else:
            print(f'Profit test p-value: {p_profit}')

        if p_profit < p and (not duration_test or p_duration < p):
            roi_stopped = tested_trades['cumulative_profit'].iloc[-1]/100000
            max_dd_stopped = tested_trades['max_daily_drawdown'].iloc[-1]
            risk_metric_stopped = -trades[(trades['profit'] > 0) & (trades['enter_tm'] < test_end_date)]['profit'].sum()/trades[(trades['profit'] < 0) & (trades['enter_tm'] < test_end_date)]['profit'].sum()
            return (test_start_date, test_end_date, roi/max_dd,
                    roi_stopped/max_dd_stopped, max_dd, max_dd_stopped,
                    risk_metric, risk_metric_stopped, (test_end_date - start_date)/(end_date - start_date))
    return (start_date, end_date, roi/max_dd, roi/max_dd, max_dd, max_dd, risk_metric, risk_metric, 1.0)


def mann_whitneyu_stop_criteria_per_trades(trades, window, p, duration_test):
    max_dd = trades['max_daily_drawdown'].iloc[-1]
    roi = trades['cumulative_profit'].iloc[-1]/100000
    risk_metric = -trades[trades['profit'] > 0]['profit'].sum()/trades[trades['profit'] < 0]['profit'].sum()
    for right_border in range(3*window, len(trades) + 1):
        print(right_border/len(trades))
        accumulated_trades = trades[:right_border-window]
        tested_trades = trades[right_border-window:right_border]
        print(f'Accumulated length: {len(accumulated_trades)}, tested length: {len(tested_trades)}')
        method = "asymptotic" if len(accumulated_trades) > 200 or len(tested_trades) > 30 else "exact"
        _, p_profit = mannwhitneyu(accumulated_trades['profit'], tested_trades['profit'], alternative="greater", method=method)
        if duration_test:
            _, p_duration = mannwhitneyu(accumulated_trades['trade_duration'], tested_trades['trade_duration'], method=method)
            print(f'Profit test p-value: {p_profit}, duration test p-value: {p_duration}')
        else:
            print(f'Profit test p-value: {p_profit}')

        if p_profit < p and (not duration_test or p_duration < p):
            roi_tested = tested_trades['cumulative_profit'].iloc[-1]/100000
            max_dd_tested = tested_trades['max_daily_drawdown'].iloc[-1]
            stopped = trades[:right_border]
            risk_metric_tested = -stopped[(stopped['profit'] > 0)]['profit'].sum()/stopped[stopped['profit'] < 0]['profit'].sum()
            return (roi/max_dd, roi_tested/max_dd_tested,
                    max_dd, max_dd_tested, risk_metric,
                    risk_metric_tested, right_border/len(trades))
    return (roi/max_dd, roi/max_dd, max_dd, max_dd, risk_metric, risk_metric, 1.0)


def distribution_parameters_criteria(trades, window=20):
    #Criteria 5
    max_dd = trades['max_daily_drawdown'].iloc[-1]
    roi = trades['cumulative_profit'].iloc[-1]/100000
    risk_metric = -trades[trades['profit'] > 0]['profit'].sum()/trades[trades['profit'] < 0]['profit'].sum()
    trades['profit'] = trades['profit'] * 100 / 100000
    for right_border in range(window, len(trades) + 1):
        tested_trades = trades[right_border-window:right_border]
        median, skew = tested_trades['profit'].median(), tested_trades['profit'].skew()
        if skew < 0.8 and median < -1:
            roi_tested = tested_trades['cumulative_profit'].iloc[-1]/100000
            max_dd_tested = tested_trades['max_daily_drawdown'].iloc[-1]
            stopped = trades[:right_border]
            risk_metric_tested = -stopped[(stopped['profit'] > 0)]['profit'].sum()/stopped[stopped['profit'] < 0]['profit'].sum()
            return (roi/max_dd, roi_tested/max_dd_tested, max_dd, max_dd_tested, risk_metric,
                    risk_metric_tested, right_border/len(trades))
    return (roi/max_dd, roi/max_dd, max_dd, max_dd, risk_metric, risk_metric, 1.0)


def run_tests(trades_df, q=30, months=2):
    """Run tests for each strategy in the dataframe with specified parameters"""
    results = []
    for i in range(len(trades_df)):
        try:
            trades = preprocess_raw_trades(trades_df.iloc[i])
        #criteria_results = mann_whitneyu_stop_criteria(trades, months, 6 - months,
        #            0.01, True)
            criteria_results = mann_whitneyu_stop_criteria_per_trades(trades, q, 0.01, False)
        #criteria_results = distribution_parameters_criteria(trades)
        except Exception as e:
            print(f"Exception {e} at {trades_df.iloc[i][['scriptName', 'timeframe', 'instrument']]}")
            continue
        result = list(trades_df.iloc[i][["scriptName", "imageUrl", "timeframe", "instrument"]].values)
        result.extend(criteria_results)
        results.append(result)

    return pd.DataFrame(results, columns=["scriptName", "imageUrl", "timeframe",
                                          "instrument",
                                          #"start_test","stop_test",
                                          "roi_mdd",
                                          "roi_mdd_stopped", "max_dd",
                                          "max_dd_stopped", "risk_metric",
                                          "risk_metric_stopped", "prct_run"])

if __name__ == "__main__":
    trades_df = pd.read_json("../res/res.jsonl", orient="records", lines=True)
    trades_df = trades_df.drop_duplicates(subset=['scriptName', 'instrument', 'timeframe'])
    trades_df = trades_df.reset_index()
    trades_df = trades_df[trades_df['scriptName'].apply(lambda x: ('trend' in x) or ('Trend' in x))]
    run_tests(trades_df).to_csv("trend_thirty_trades_0.01.csv", index=False)
    #for m, name in [(2, "two"), (3, "three"), (4, "four"), (1, "one")]:
    #    run_tests(trades_df, m).to_csv(f"{name}_months_profit_duration_0_01.csv", index=False)
