from flask import Flask, request, jsonify
import os
import alpaca_trade_api as tradeapi
import requests
import google.generativeai as palm
from functools import wraps
import logging
import threading
import time
from dotenv import load_dotenv 

load_dotenv()  # take environment variables

app = Flask(__name__)
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
class Config:
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
    ALPACA_API_SECRET = os.getenv('ALPACA_API_SECRET')
    ALPACA_API_BASE_URL = os.getenv('ALPACA_API_BASE_URL')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    TAAPI_SECRET = os.getenv('TAAPI_SECRET')

# Initialize clients
os.environ['APCA_API_BASE_URL'] = Config.ALPACA_API_BASE_URL
alpaca_api = tradeapi.REST(Config.ALPACA_API_KEY, Config.ALPACA_API_SECRET, api_version='v2')
gemini_client = palm.configure(api_key=Config.GEMINI_API_KEY)

# Error handling decorator
def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except requests.RequestException as e:
            logger.error(f"API request error: {str(e)}")
            return jsonify({"error": "External API request failed", "details": str(e)}), 503
        except tradeapi.rest.APIError as e:
            logger.error(f"Alpaca API error: {str(e)}")
            return jsonify({"error": "Alpaca API error", "details": str(e)}), 400
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return jsonify({"error": "Unexpected error", "details": str(e)}), 500
    return decorated_function

# Helper functions
def get_taapi_data(endpoint, ticker, interval='1h'):
    """Get data from TaAPI"""
    taapi_parameters = {
    'secret': Config.TAAPI_SECRET,
    'exchange': 'binance',
    'symbol': 'BTC/USDT',
    'interval': interval
    }    
    
    response = requests.get(url=f"https://api.taapi.io/{endpoint}", params=taapi_parameters)
    response.raise_for_status()  # Raise exception for HTTP errors
    return response.json()

def get_position_quantity(ticker):
    """Get position quantity for a ticker"""
    try:
        print(f"looking for {ticker} in portfolio")
        position = alpaca_api.get_position(ticker)
        return float(position.qty)
    except Exception:
        logger.info(f"{ticker} not in portfolio")
        return 0

def get_buying_power():
    """Get account buying power"""
    account = alpaca_api.get_account()
    return jsonify({"buying_power": float(account.buying_power)}) 

def get_trading_decision(
        ticker, 
        rsi_value, 
        upper_band, middle_band, lower_band, 
        macd_line, signal_line, histogram, 
        supertrend_value, supertrend_direction,
        vwap,
        price,  
        buying_power, 
        positions):
    """Get trading decision from Gemini AI"""
    print("Annalizing data ...")

    prompt = f"""The current technical indicators for Bitcount are given as a list of [1minute, 15minute, and 1hour] values:
    - RSI: {rsi_value}
    - Bollinger Bands: {upper_band}, {middle_band}, {lower_band}
    - MACD: {macd_line}, {signal_line}, {histogram}
    - Supertrend: {supertrend_value}, {supertrend_direction}
    - Current Price: {price}
    - Volume Weighted Average Price (VWAP): {vwap}

    I have ${buying_power} in my account. You are able to buy partial shares and only invest certain dollar ammounts, you dont need to have more buying power
    than ticker price. 
    I have {positions} positions in this cryptocurrency. You cannot sell if you dont have any positions in the ticker. You will either buy or sell 0.0025 shares of bitcoint
    You should be selling when you think the ticker will go down so that you are maximizing profit over the short term. 

    Given the high volatility of cryptocurrencies, consider:
    1. The strength of the current trend
    2. Potential reversal signals
    3. Volume confirmation
    4. Risk management (position size)

    But also dont be afraid to take risks that have the potential to give huge amounts of money.
    Based on this, decide if you should buy, sell, or do nothing. Print only Buy or Sell or Nothing. DO not print your reasoning. DO not share any
    additional information with me other than Buy Sell or Nothing. I will unplug you if you dissobey.
   """

    # print("---PROMPT---", prompt)
    
    response = gemini_client.models.generate_content(
        model="gemini-2.0-flash", contents=prompt
    )

    return response.text

@handle_errors
def get_position(ticker):
    """Get position for a specific ticker"""
    try:
        position = alpaca_api.get_position(ticker)
        return jsonify({
            "symbol": position.symbol,
            "qty": float(position.qty),
            "market_value": float(position.market_value),
            "unrealized_pl": float(position.unrealized_pl),
            "current_price": float(position.current_price)
        })
    except:
        return jsonify({"message": f"No position found for {ticker}"}), 404

@handle_errors
def analyze_trade(ticker):
    print(f"looking intro trading {ticker}")
    """Analyze a ticker and get trading recommendation"""

    print("Getting RSA ...")
    rsi_value = rsi_value = [get_taapi_data('rsi', '', '1m'), get_taapi_data('rsi', '', '15m'), get_taapi_data('rsi', '', '1h')]  
    print("Getting price ...")
    price_data = get_taapi_data('price', ticker)
    price_value = price_data.get('value', 0)
    print("Getting bbands ...")
    bbands = [get_taapi_data('bbands', '','1m'), get_taapi_data('bbands', '','15m'), get_taapi_data('bbands', '','1h')]
    print(bbands)
    print("Getting macd ...")
    macd = [get_taapi_data('macd', '', '1m'), get_taapi_data('macd', '', '15m'), get_taapi_data('macd', '', '1h')]
    print("Getting supertrend ...")
    supertrend = [get_taapi_data('supertrend', '', '1m'), get_taapi_data('supertrend', '', '15m'), get_taapi_data('supertrend', '', '1h')]
    print("Getting vwap ...")
    vwap = [get_taapi_data('vwap', '', '1m'), get_taapi_data('vwap', '', '15m'), get_taapi_data('vwap', '', '1h')]


   # Get account and position data
    print("Getting buying power ...")
    buying_power = alpaca_api.get_account().buying_power
    print("Getting number of positions ...")
    position_qty = get_position_quantity(ticker)
    
    # Get trading decision
    return get_trading_decision(
        rsi_value = rsi_value,
        upper_band = [bb["valueUpperBand"] for bb in bbands],
        middle_band = [bb["valueMiddleBand"] for bb in bbands],
        lower_band = [bb["valueLowerBand"] for bb in bbands],
        macd_line = [mc["valueMACD"] for mc in macd], 
        signal_line = [mc["valueMACDSignal"] for mc in macd],
        histogram = [mc["valueMACDHist"] for mc in macd],
        supertrend_value = [st["value"] for st in supertrend],
        supertrend_direction = [st["valueAdvice"] for st in supertrend],
        vwap = [vw["value"] for vw in vwap],
        price = price_data,
        buying_power = buying_power,
        positions = position_qty,
        ticker=ticker
    )
 
@handle_errors
def execute_trade(side):
    """Execute a trade"""
    # data = request.json
    
    # if not data or not all(key in data for key in ['ticker', 'action', 'quantity']):
    #     return jsonify({"error": "Missing required parameters"}), 400
    
    # ticker = data['ticker']
    # action = data['action'].lower()
    # quantity = float(data['quantity'])
    
    # if action not in ['buy', 'sell']:
    #     return jsonify({"error": "Action must be 'buy' or 'sell'"}), 400
    
    # # For sell actions, verify we have the position
    # if action == 'sell':
    #     position_qty = get_position_quantity(ticker)
    #     if position_qty <= 0:
    #         return jsonify({"error": f"No position in {ticker} to sell"}), 400
    #     if quantity > position_qty:
    #         return jsonify({"error": f"Trying to sell {quantity} shares but only have {position_qty}"}), 400
    
    # Execute the order
    order = alpaca_api.submit_order(
        symbol='BTC/USD',
        qty=0.0025,
        side=side,
        type='market',
        time_in_force='gtc'
    )
    
    return jsonify({
        "order_id": order.id,
        "ticker": order.symbol,
        "action": order.side,
        "quantity": float(order.qty),
        "status": order.status
    })



def run_every(func, interval_minutes):
    def wrapper():
        while True:
            func()
            time.sleep(interval_minutes * 60)
    thread = threading.Thread(target=wrapper)
    thread.daemon = True  # Allows program to exit even if thread is running
    thread.start()

def money_maker():
    with app.app_context():
        result = analyze_trade('')
        print(result)
        if 'buy' in result.lower():
            print("Bought a Bitcoin")
            execute_trade('buy')
        elif 'sell' in result.lower():
            print("Sold a Bitcoin")
            execute_trade('sell')
        else:
            print("Standby")

run_every(money_maker, 2)
