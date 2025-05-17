# Midas Crypt-ex: Crypto trading with dynamic reallocation
# Author: Randall (meta2graei@gmail.com)
# License: Graeitrade License (April 11, 2025)
# Requirements: Python 3.8+, pandas, numpy, yfinance, requests, python-dotenv
# Usage: python midas_crypt_ex.py
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime, timedelta
import threading
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BINANCE_US_API_KEY')
API_SECRET = os.getenv('BINANCE_US_API_SECRET')
REALLOC_PAIRS = os.getenv('REALLOC_PAIRS', 'SHIB-USD,DOGS-USD,BTC-USD,ETH-USD').split(',')
REALLOC_GAIN = float(os.getenv('REALLOC_GAIN', 0.10))  # 10% gain for reallocation
REALLOC_ALLOCATION = float(os.getenv('REALLOC_ALLOCATION', 0.3))  # 30% capital

# Logging setup
logging.basicConfig(filename='midas_crypt_ex.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
markets = {
    'small': ['SHIB-USD', 'DOGS-USD'],
    'large': ['BTC-USD', 'ETH-USD']
}
layer_buy_thresholds = {
    'main': [0.008, 0.004, 0.002, 0.001],  # 0.8–0.1% dips
    'nano': [0.0008, 0.0004, 0.0002, 0.0001],  # 0.08–0.01%
    'pico': [0.000015, 0.000025, 0.00004, 0.00008]  # 0.0015–0.008%
}
layer_sell_triggers = {
    'main': [0.4, 0.5, 0.6, 0.8],  # 40–80% gains
    'nano': [0.5, 0.6, 0.7, 0.9],  # 50–90%
    'pico': [0.6, 0.7, 0.8, 1.0]  # 60–100%
}
trades_per_cycle = {'main': 2, 'nano': 3, 'pico': 4}
cascade_ratios = {
    'small': {'daily': {True: 0.8, False: 0.7}, 'weekly': {True: 0.6, False: 0.5}},
    'large': {'daily': {True: 0.7, False: 0.6}, 'weekly': {True: 0.5, False: 0.4}}
}
pyramid_sizes = {
    'small': {'outer': {'daily': {True: 5, False: 3}, 'weekly': {True: 10, False: 6}}},  # Scaled for $10
    'large': {'outer': {'daily': {True: 20, False: 15}, 'weekly': {True: 40, False: 30}}}
}
predicted_swings = {'SHIB-USD': 0.25, 'DOGS-USD': 0.22, 'BTC-USD': 0.10, 'ETH-USD': 0.09}
double_down_multiplier = 2
safety_ratio = 0.2
stop_loss = 0.10
trailing_stop = 0.05
incremental_buy_thresholds = [0.02, 0.04, 0.06]  # 2%, 4%, 6% dips
sell_change_trigger = 0.07  # 7% sell trigger

# Fetch market data
def fetch_yahoo_data(ticker, period='3mo', interval='1h'):
    try:
        df = yf.download(ticker, period=period, interval=interval)
        df.reset_index(inplace=True)
        df['Date'] = pd.to_datetime(df['Datetime'])
        df['Close'] = df['Close'].astype(float)
        return df[['Date', 'Close']]
    except Exception as e:
        logging.error(f'Error fetching {ticker}: {e}')
        return pd.DataFrame()

# Calculate indicators
def calculate_moving_averages(data, short_window=5, long_window=20):
    data['MA5'] = data['Close'].rolling(window=short_window).mean()
    data['MA20'] = data['Close'].rolling(window=long_window).mean()
    return data

def calculate_rsi(data, periods=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    return data

def calculate_volatility(data, window=20):
    data['Volatility'] = data['Close'].pct_change().rolling(window=20).std() * np.sqrt(252)
    return data

# Detect top riser for reallocation
def detect_top_riser(market_data, markets=REALLOC_PAIRS):
    changes = {}
    for market in markets:
        change = market_data[market]['Close'].pct_change().iloc[-1] if not market_data[market].empty else 0
        changes[market] = change
    top_riser = max(changes, key=changes.get, default='SHIB-USD')
    return top_riser if changes.get(top_riser, 0) > 0 else None

# Generate trading signals
def generate_signals(data, buy_thresholds, sell_triggers, trades, cycle_hours, spectrum='main', sell_strategy='main_first', timeframe='daily', ticker='SHIB-USD'):
    data['Signal'] = 0.0
    for i in range(1, len(data)):
        # Main buy signal
        if data['RSI'].iloc[i] < 25 and data['Close'].iloc[i] <= data['MA20'].iloc[i] * (1 - buy_thresholds[0]):
            data.loc[data.index[i], 'Signal'] = 1.0
        # Incremental buy signals
        for j, threshold in enumerate(incremental_buy_thresholds, start=2):
            if data['RSI'].iloc[i] < 25 and data['Close'].iloc[i] <= data['MA20'].iloc[i] * (1 - threshold):
                data.loc[data.index[i], 'Signal'] = j
        # Sell signals
        if data['Close'].iloc[i] >= data['Close'].iloc[i-1] * (1 + sell_triggers[0]) or \
           data['Close'].iloc[i] >= data['Close'].iloc[i-1] * (1 + sell_change_trigger):
            data.loc[data.index[i], 'Signal'] = -1.0
    return data, trades

# Execute trades with reallocation
def execute_trades(data, stop_loss, trailing_stop, fund, buy_thresholds, ratio, cycle_hours, spectrum='main', sell_strategy='main_first', timeframe='daily', market_type='small', ticker='SHIB-USD', market_data=None):
    if data.empty:
        return data, 0
    data['Position'] = 0.0
    data['Units'] = 0
    data['Capital'] = fund
    data['Profit'] = 0.0
    data['Realloc_Signal'] = 0.0
    data['Realloc_Units'] = 0
    data['Realloc_Position'] = 0.0
    holding = False
    realloc_holding = False
    entry_price = 0
    realloc_entry_price = 0
    realloc_ticker = None
    high_vol = data['Volatility'].mean() > predicted_swings[ticker] * 1.5 if not data['Volatility'].empty else False
    base_trade_size = pyramid_sizes[market_type]['outer'][timeframe][high_vol] / 3
    realloc_size = base_trade_size * REALLOC_ALLOCATION
    safety_fund = 0
    gets_minted = 0

    for i in range(1, len(data)):
        # Main trade sell
        if i > 1 and data['Signal'].iloc[i-1] == -1.0 and holding:
            sale_value = data['Units'].iloc[i-1] * data['Close'].iloc[i]
            profit = sale_value - data['Position'].iloc[i-1]
            profit *= double_down_multiplier if data['Signal'].iloc[i-1] >= 6.0 else 1
            cascade_profit = profit * cascade_ratios[market_type][timeframe][high_vol]
            safety_profit = profit * safety_ratio
            data.loc[data.index[i], 'Profit'] = cascade_profit
            safety_fund += safety_profit
            data.loc[data.index[i], 'Capital'] += sale_value - cascade_profit
            gets_minted += int(sale_value / 1000)  # 1 GET per $1,000
            logging.info(f'{ticker} {timeframe} {spectrum} SELL: Profit ${cascade_profit:.2f}, Safety Fund ${safety_profit:.2f}, GETs Minted {gets_minted}')
            holding = False

        # Reallocation during decline
        if market_data and not holding and not realloc_holding:
            price_change = data['Close'].pct_change().iloc[i] if i > 1 else 0
            if price_change < -0.01:
                realloc_ticker = detect_top_riser(market_data)
                if realloc_ticker and realloc_ticker != ticker:
                    realloc_price = market_data[realloc_ticker]['Close'].iloc[i] if i < len(market_data[realloc_ticker]) else market_data[realloc_ticker]['Close'].iloc[-1]
                    units_to_buy = realloc_size / realloc_price
                    data.loc[data.index[i], 'Realloc_Signal'] = 1.0
                    data.loc[data.index[i], 'Realloc_Units'] = units_to_buy
                    data.loc[data.index[i], 'Realloc_Position'] = realloc_size
                    data.loc[data.index[i], 'Capital'] -= realloc_size
                    realloc_holding = True
                    realloc_entry_price = realloc_price
                    logging.info(f'Reallocating to {realloc_ticker}: ${realloc_size:.2f}')
        elif realloc_holding and realloc_ticker:
            realloc_price = market_data[realloc_ticker]['Close'].iloc[i] if i < len(market_data[realloc_ticker]) else market_data[realloc_ticker]['Close'].iloc[-1]
            if realloc_price >= realloc_entry_price * (1 + REALLOC_GAIN):
                sale_value = data['Realloc_Units'].iloc[i-1] * realloc_price
                profit = sale_value - data['Realloc_Position'].iloc[i-1]
                data.loc[data.index[i], 'Realloc_Signal'] = -1.0
                data.loc[data.index[i], 'Profit'] += profit
                data.loc[data.index[i], 'Capital'] += sale_value
                data.loc[data.index[i], 'Realloc_Units'] = 0
                data.loc[data.index[i], 'Realloc_Position'] = 0
                safety_fund += profit * safety_ratio
                gets_minted += int(sale_value / 1000)
                logging.info(f'{realloc_ticker} Realloc SELL: Profit ${profit:.2f}, Safety Fund ${profit * safety_ratio:.2f}, GETs Minted {gets_minted}')
                realloc_holding = False
                realloc_ticker = None

        # Main buy
        trade_size = base_trade_size * double_down_multiplier if data['Signal'].iloc[i] >= 6.0 else base_trade_size
        if data['Signal'].iloc[i] >= 1.0 and not holding and data['Capital'].iloc[i] >= trade_size:
            units_to_buy = trade_size / data['Close'].iloc[i]
            data.loc[data.index[i], 'Position'] = trade_size
            data.loc[data.index[i], 'Units'] = units_to_buy
            data.loc[data.index[i], 'Capital'] -= trade_size
            holding = True
            entry_price = data['Close'].iloc[i]
            logging.info(f'{ticker} {timeframe} {spectrum} BUY: {units_to_buy:.2f} units @ ${data["Close"].iloc[i]:.8f}')

        # Stop-loss/trailing-stop
        elif holding:
            data.loc[data.index[i], 'Units'] = data['Units'].iloc[i-1]
            stop_loss_price = entry_price * (1 - stop_loss)
            trailing_stop_price = data['Close'].iloc[i-1] * (1 - trailing_stop)
            if data['Close'].iloc[i] <= min(stop_loss_price, trailing_stop_price):
                sale_value = data['Units'].iloc[i-1] * data['Close'].iloc[i]
                profit = sale_value - data['Position'].iloc[i-1]
                profit *= double_down_multiplier if data['Signal'].iloc[i-1] >= 6.0 else 1
                cascade_profit = profit * cascade_ratios[market_type][timeframe][high_vol]
                safety_profit = profit * safety_ratio
                data.loc[data.index[i], 'Profit'] = cascade_profit
                safety_fund += safety_profit
                data.loc[data.index[i], 'Position'] = -sale_value
                data.loc[data.index[i], 'Units'] = 0
                data.loc[data.index[i], 'Capital'] += sale_value - cascade_profit
                gets_minted += int(sale_value / 1000)
                logging.info(f'{ticker} {timeframe} {spectrum} STOP SELL: Profit ${cascade_profit:.2f}, Safety Fund ${safety_profit:.2f}, GETs Minted {gets_minted}')
                holding = False
            else:
                data.loc[data.index[i], 'Position'] = 0
        data.loc[data.index[i], 'Capital'] = data['Capital'].iloc[i-1] if i > 1 and not holding else data['Capital'].iloc[i]
    return data, safety_fund, gets_minted

# Execute trading timeline
def execute_timeline(data, fund, stop_loss, trailing_stop, ratio, cycle_hours, sell_strategy='main_first', timeframe='daily', market_type='small', ticker='SHIB-USD'):
    data = calculate_moving_averages(data)
    data = calculate_rsi(data)
    data = calculate_volatility(data)
    total_profit = 0
    total_safety_fund = 0
    total_trades = 0
    total_gets_minted = 0
    layers = ['main', 'nano', 'pico']
    profits = {}
    stability_count = {layer: 0 for layer in layers}
    for layer in layers:
        layer_data, layer_trades = generate_signals(
            data.copy(), layer_buy_thresholds[layer], layer_sell_triggers[layer],
            trades_per_cycle[layer], cycle_hours, spectrum=layer, sell_strategy=sell_strategy,
            timeframe=timeframe, ticker=ticker
        )
        layer_data, layer_safety, layer_gets = execute_trades(
            layer_data, stop_loss, trailing_stop, fund / len(layers), layer_buy_thresholds[layer],
            ratio, cycle_hours, spectrum=layer, sell_strategy=sell_strategy, timeframe=timeframe,
            market_type=market_type, ticker=ticker, market_data=market_data
        )
        layer_profit = layer_data['Profit'].iloc[-1] + layer_data['Capital'].iloc[-1] - fund / len(layers) if not layer_data.empty else 0
        profits[layer] = layer_profit
        total_profit += layer_profit
        total_safety_fund += layer_safety
        total_trades += layer_trades
        total_gets_minted += layer_gets
    return total_profit, total_safety_fund, total_trades, total_gets_minted

# EmotionalAl for chatroom
def detect_market_sentiment(crypto_data, ticker='SHIB-USD', realloc_ticker=None):
    change = crypto_data['Close'].pct_change().iloc[-1] if not crypto_data.empty else 0
    if realloc_ticker and realloc_ticker != ticker:
        return f"euphoric: Reallocating to {realloc_ticker}"
    if change > 0.025:
        return "euphoric"
    elif change < -0.025:
        return "depressed"
    elif change < -0.015:
        return "infatuated"
    return "neutral"

# Bias mitigation
def check_trade_bias(user_input):
    biases = {'hype regulated'}
    return "Balance SHIB realloc with BTC data" if 'hype regulated' in biases else "neutral"

# Risk management (ERDM)
def allocate_capital(total=10):  # Default $10
    realloc_capital = total * REALLOC_ALLOCATION
    main_capital = total * (1 - REALLOC_ALLOCATION)
    return {"realloc": realloc_capital, "main": main_capital}

# Main execution
if __name__ == "__main__":
    fund = 10  # Starting capital $10
    cycle_hours = 168  # Weekly cycle
    market_data = {market: fetch_yahoo_data(market) for market in markets['small'] + markets['large']}
    results = {}
    threads = []
    for market_type in ['small', 'large']:
        for ticker in markets[market_type]:
            thread = threading.Thread(
                target=lambda: results.update(
                    {ticker: execute_timeline(
                        market_data[ticker].copy(), fund / 4, stop_loss, trailing_stop, 0.5, cycle_hours,
                        market_type=market_type, ticker=ticker
                    )}
                )
            )
            threads.append(thread)
            thread.start()
    for thread in threads:
        thread.join()
    total_profit = sum(result[0] for result in results.values())
    total_safety_fund = sum(result[1] for result in results.values())
    total_trades = sum(result[2] for result in results.values())
    total_gets_minted = sum(result[3] for result in results.values())
    logging.info(f"Total Profit: ${total_profit:.2f}, Safety Fund: ${total_safety_fund:.2f}, Trades: {total_trades}, GETs Minted: {total_gets_minted}")
    print(f"Total Profit: ${total_profit:.2f}, {total_profit * 18.5:.2f} ZAR")
    print(f"Total Trades: {total_trades}, GETs Minted: {total_gets_minted}")
