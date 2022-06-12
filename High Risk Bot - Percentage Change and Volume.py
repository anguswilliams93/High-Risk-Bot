#!/usr/bin/env python
# coding: utf-8

# In[1]:


from binance import Client
import sqlalchemy
import pandas as pd
import time
import ta
from datetime import datetime
from scipy.stats import zscore
import math
import warnings
warnings.filterwarnings('ignore')


# In[2]:


client = Client()


# In[3]:


engine = sqlalchemy.create_engine('sqlite:///C:\\Path\\BotTransactions.db')


# In[4]:


def get_top_symbol():
    all_pairs = pd.DataFrame(client.get_ticker())
    relev = all_pairs[all_pairs.symbol.str.contains('USDT')]
    relev['priceChangePercent'] = relev['priceChangePercent'].astype(float)
    relev['volume'] = relev['volume'].astype(float)
    relev['nVolume'] = round(relev['volume'] / 1000000, 1)
    non_lev = relev[~((relev.symbol.str.contains('UP')) | (relev.symbol.str.contains('DOWN')) | (relev.symbol.str.contains('ZEC')) | (relev.symbol.str.contains('ZEN')))]
    non_lev = non_lev[non_lev['nVolume'] >= 100.0]
    all_pairs_sorted = non_lev.sort_values(['priceChangePercent', 'volume'], ascending=[False, False])
    #top_symbol = all_pairs_sorted[non_lev.priceChangePercent == all_pairs.priceChangePercent[0]]
    top_symbol = all_pairs_sorted.symbol.values[0]
    return top_symbol


# In[5]:


def getminutedata(symbol, interval, lookback): # symbol, time intercal (mintues), lookback (how far back)
    frame = pd.DataFrame(client.get_historical_klines(symbol,
                                                     interval,
                                                     lookback + ' min ago UTC'))
    frame = frame.iloc[:,:6]
    frame.columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']
    frame = frame.set_index('Time')
    frame.index = pd.to_datetime(frame.index, unit='ms')
    frame = frame.astype(float)
    return frame


# In[6]:


def applytechnicals(frame):
    frame['%K'] = ta.momentum.stoch(frame.High, frame.Low, frame.Close, window = 14,
                                smooth_window=3)
    frame['%D'] = frame['%K'].rolling(3).mean()
    frame['rsi'] = ta.momentum.rsi(frame.Close, window= 5) # was 5 using more by and trade signals
    frame['sma30'] = frame.Close.rolling(30).mean()
    frame['sma60'] = frame.Close.rolling(60).mean()
    frame['sma190'] = frame.Close.rolling(90).mean()
    frame['macd'] = ta.trend.macd_diff(frame.Close)
    frame.dropna(inplace=True)
    return frame


# In[7]:


def get_lot_size(symbol):
    x = client.get_symbol_info(symbol)
    step_size = float(x['filters'][2]['stepSize'])
    decimal_places = abs(int(f'{step_size:e}'.split('e')[-1]))
    return decimal_places


# In[8]:


def round_decimals_down(number, decimal_places):
    if not isinstance(decimal_places, int):
        raise TypeError("decimal places must be an integer")
    elif decimal_places < 0:
        raise ValueError("decimal places has to be 0 or more")
    elif decimal_places == 0:
        return math.floor(number)
    factor = 10 ** decimal_places
    return math.floor(number * factor) / factor


# In[9]:


def strategy(buy_amt, SL=0.985, Target = 1.02, open_position = False):
    try:
        asset = get_top_symbol()
        df = getminutedata(asset, '1m', '120')
        df = applytechnicals(df)
        decimal_places = get_lot_size(asset)
    except:
        print('Somethings gone wrong, script continues in 1m... unless youve stopped it automatically...')
        time.sleep(61)
        asset = get_top_symbol()
        df = getminutedata(asset, '1m', '120')
        df = applytechnicals(df)
        decimal_places = get_lot_size(asset)
    
    
    qty = round(buy_amt/df.Close.iloc[-1], decimal_places)
    
    print('Waiting for buy signal in binance trading pair: ' + str(asset))
    
    
    #if ((df.Close.pct_change() + 1).cumprod()).iloc[-1] > 1:  # buying condition if the percentage increasing by >1 in 1min
    if df.rsi[-1] < 30:
        order = client.create_order(symbol = asset,
                                   side = 'BUY',
                                   type = 'MARKET',
                                    quantity = qty)
        #print(order)
        buyprice = float(order['fills'][0]['price'])
        open_position = True
        for k,v in order.items():
            if k == 'clientOrderId':
                clientOrderId = v
            if k == 'symbol':
                tradingPair = v
            if k == 'type':
                spotType = v
            if k == 'side':
                buyOrSell = v
            if k == 'fills':
                transaction = v[0]
                transaction['timestamp'] = datetime.now()
                transaction['tradingPair'] = tradingPair
                transaction['spotType'] = spotType
                transaction['buyOrSell'] = buyOrSell
                transaction['clientOrderId'] = clientOrderId
                transaction['profit'] = 0
                transaction['rsi'] = float(df.rsi.iloc[-1])
                #transaction['sma28'] = float(df.sma28.iloc[-1])
                transaction['macd'] = float(df.macd.iloc[-1])
                
                transaction_array.append(transaction)
                print(transaction)
                
        trailing_stop_loss = buyprice * SL # set global variable starting at the buy price * the stop loss
                
        time.sleep(0.5)
        while open_position:
            try:
                df = getminutedata(asset, '1m', '120')
                df = applytechnicals(df)
            except:
                print('Somethings gone wrong, script continues in 1m... unless youve stopped it automatically...')
                time.sleep(61)
                df = getminutedata(asset, '1m', '120')
                df = applytechnicals(df)
                
            commission = float(order['fills'][0]['commission'])
            print(f'Open Position in: ' +str(asset))
            print(f'current Close Price: $'+ str(df.Close.iloc[-1]))
            print(f'Buy Price: $' + str(buyprice))
            #print(f'current Target '+ str(buyprice * Target))
            #print(f'qty : ' + str(qty - commission))
            
            #stop_loss = buyprice * SL
            if (df.Close.iloc[-1] * SL) > trailing_stop_loss:
                trailing_stop_loss = df.Close.iloc[-1] * SL  # create new trailing stop loss variable     
                
            tradingFee = 0.001
            profit = ((df.Close.iloc[-1] * qty) - (buyprice * qty)) - (df.Close.iloc[-1] * qty * tradingFee)
            print(f'Profit: $'+ str(round(profit, 2)))
            roi = round(((df.Close.iloc[-1]-buyprice)/buyprice)*100, 2)
            print(f'Current ROI: '+ str(roi) + '%')
            #print(f'First Stop Loss: $'+ str(buyprice * SL))
            print(f'Trailing Stop Loss: $' + str(round(trailing_stop_loss, 4)))
            print('----------------------------------------')
            time.sleep(0.5)
            if ( df.Close[-1] <= trailing_stop_loss ): #or df.Close[-1] >= buyprice * Target: # sell only on trailing stop loss
                    
                    
                    qty = round_decimals_down((qty - commission), decimal_places)
                    
                    order = client.create_order(symbol = asset,
                                    side = 'SELL',
                                    type = 'MARKET',
                                    quantity = qty)
                    #print(order)
                    for k,v in order.items():
                        if k == 'clientOrderId':
                            clientOrderId = v
                        if k == 'symbol':
                            tradingPair = v
                        if k == 'type':
                            spotType = v
                        if k == 'side':
                            buyOrSell = v
                        if k == 'fills':
                            transaction = v[0]
                            transaction['timestamp'] = datetime.now()
                            transaction['tradingPair'] = tradingPair
                            transaction['spotType'] = spotType
                            transaction['buyOrSell'] = buyOrSell
                            transaction['clientOrderId'] = clientOrderId
                            transaction['profit'] = profit
                            transaction['rsi'] = float(df.rsi.iloc[-1])
                            #transaction['sma28'] = float(df.sma28.iloc[-1])
                            transaction['macd'] = float(df.macd.iloc[-1])
                            transaction['roi'] = float(roi)
                            transaction_array.append(transaction)
                            print(transaction)
                    break


# In[10]:


while True:
    transaction_array = []
    strategy(70)
    botTrades = pd.DataFrame(transaction_array)
    botTrades.to_sql('bot_transactions', engine, if_exists='append', index=True)
    time.sleep(0.5)


# In[ ]:




