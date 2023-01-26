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
    max_dd  = trades['max_daily_drawdown'].iloc[-1]
    roi = trades['cumulative_profit'].iloc[-1]/100000
    risk_metric = -trades[trades['profit'] > 0]['profit'].sum()/trades[trades['profit'] < 0]['profit'].sum()
    for test_start_date in pd.period_range(start=start_date, periods=tested_periods + 1, freq='M'):
        test_start_date = test_start_date.to_timestamp()
        test_end_date = test_start_date + pd.tseries.offsets.MonthEnd(months)
        if test_start_date <= start_date + pd.tseries.offsets.MonthEnd(months + offset_months):
            continue
        print(f'Tested period from {test_start_date} to {test_end_date}')
        accumulated_trades = trades[trades['enter_tm'] < test_start_date]
        tested_trades = trades[(trades['enter_tm'] >= test_start_date) & (trades['enter_tm'] < (test_end_date))]
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
    return (None, None, roi/max_dd, None, max_dd, None, risk_metric, None, 1.0)


def run_tests(trades_df, months=2, offset_months=4, p=0.05, duration_test=False):
    """Run tests for each strategy in the dataframe with specified parameters"""
    results = []
    months = 2
    for i in range(len(trades_df)):
        #print(trades_df.iloc[i][["scriptName", "imageUrl", "timeframe", "instrument"]])
        trades = preprocess_raw_trades(trades_df.iloc[i])
        try:
            criteria_results = mann_whitneyu_stop_criteria(trades, months, offset_months, p, duration_test)
        except ValueError as e:
            print(f'Not enough data for {months} months')
            continue
        result = list(trades_df.iloc[i][["scriptName", "imageUrl", "timeframe", "instrument"]].values)
        result.extend(criteria_results)
        results.append(result)

    return pd.DataFrame(results, columns=["scriptName", "imageUrl", "timeframe",
                                          "instrument", "start_test",
                                          "stop_test", "roi_mdd",
                                          "roi_mdd_stopped", "max_dd",
                                          "max_dd_stopped", "risk_metric",
                                          "risk_metric_stopped", "prct_run"])

if __name__ == "__main__":
    trades_df = pd.read_json("../res/res.jsonl", orient="records", lines=True)
    run_tests(trades_df, 2, 4, 0.05, False).to_csv("two_months_profit_0_05.csv", index=False)
