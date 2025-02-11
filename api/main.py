import os
import json
import threading
import requests
from datetime import datetime, time, timedelta
import pytz
import finnhub
import websocket
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

FINNHUB_TOKEN = os.environ.get("FINNHUB_TOKEN")

# 时区设置：美国东部时间和中国北京时间
tz_us_eastern = pytz.timezone("America/New_York")
tz_china = pytz.timezone("Asia/Shanghai")

# 全局缓存，用于存储行情数据和假日信息
trade_data_cache = {}  # 存储通过 WebSocket 接收到的行情数据
holidays_cache = {}    # 存储 Finnhub 返回的美国休市假日数据
holidays_cache_timestamp = None

def update_holidays_cache():
    """
    从 Finnhub 获取美国市场假日数据，将 tradingHour 为空的视为全天休市，
    并缓存到 holidays_cache 中。
    """
    global holidays_cache, holidays_cache_timestamp
    try:
        finnhub_client = finnhub.Client(api_key=FINNHUB_TOKEN)
        res = finnhub_client.market_holiday(exchange='US')
        holidays_cache = {}
        for event in res.get("data", []):
            event_date = event.get("atDate")
            holidays_cache[event_date] = event
        holidays_cache_timestamp = datetime.now()
        print("Updated holidays cache:", holidays_cache)
    except Exception as e:
        print("Error updating holidays cache:", e)

def is_market_holiday(dt: datetime) -> bool:
    """
    判断指定日期是否为全天休市假日（即 tradingHour 为空）。
    """
    date_str = dt.strftime("%Y-%m-%d")
    event = holidays_cache.get(date_str)
    if event:
        trading_hour = event.get("tradingHour", "")
        if trading_hour.strip() == "":
            return True
    return False

def get_next_open_time(now_us: datetime) -> datetime:
    """
    从当前时间开始，寻找下一个既非周末又非休市假日的交易日，并返回该日 9:30（美国东部时间）。
    """
    tmp = now_us
    while True:
        tmp += timedelta(days=1)
        if tmp.weekday() < 5 and not is_market_holiday(tmp):
            return datetime(tmp.year, tmp.month, tmp.day, 9, 30, 0, tzinfo=tz_us_eastern)

def calc_market_state(now_us: datetime):
    """
    根据美国东部时间判断市场状态：
      - Overnight：美东时间周日晚上 20:00 至次日凌晨 3:50（适用于周日及周一至周四凌晨）
      - 盘前：04:00 - 09:30
      - 盘中：09:30 - 16:00
      - 盘后：16:00 - 20:00
      - 休市：其他时段（例如 03:50 - 04:00，或周末/假日）
    返回当前状态、下一个状态及距离下个状态的秒数。
    """
    t = now_us.time()
    weekday = now_us.weekday()  # Monday=0, ..., Sunday=6

    # 判断 Overnight：若为周日晚上20:00之后，或周一至周四凌晨03:50之前，均为 Overnight
    if (weekday == 6 and t >= time(20, 0)) or (weekday in [0, 1, 2, 3, 4] and t < time(3, 50)):
        current_state = "Overnight"
        if t < time(3, 50):
            next_time = now_us.replace(hour=3, minute=50, second=0, microsecond=0)
        else:
            next_day = now_us + timedelta(days=1)
            next_time = next_day.replace(hour=3, minute=50, second=0, microsecond=0)
        next_state = "盘前"
        time_to_next_state = (next_time - now_us).total_seconds()
        return current_state, next_state, time_to_next_state

    # 非 Overnight 状态下的其他时段
    if t >= time(4, 0) and t < time(9, 30):
        current_state = "盘前"
        next_state = "盘中"
        next_time = now_us.replace(hour=9, minute=30, second=0, microsecond=0)
    elif t >= time(9, 30) and t < time(16, 0):
        current_state = "盘中"
        next_state = "盘后"
        next_time = now_us.replace(hour=16, minute=0, second=0, microsecond=0)
    elif t >= time(16, 0) and t < time(20, 0):
        current_state = "盘后"
        next_state = "Overnight"
        next_time = now_us.replace(hour=20, minute=0, second=0, microsecond=0)
    elif t >= time(3, 50) and t < time(4, 0):
        current_state = "休市"
        next_state = "盘前"
        next_time = now_us.replace(hour=4, minute=0, second=0, microsecond=0)
    else:
        current_state = "休市"
        next_open_time = get_next_open_time(now_us)
        next_state = "盘前"
        next_time = next_open_time
    time_to_next_state = (next_time - now_us).total_seconds()
    return current_state, next_state, time_to_next_state

@app.get("/api/time_status")
def get_market_time_status():
    """
    返回当前美国东部时间（不含秒，含周几）、中国北京时间（不含秒，含周几）、市场状态及距离下个状态的倒计时（秒）。
    """
    now_us = datetime.now(tz_us_eastern)
    now_cn = datetime.now(tz_china)

    if now_us.weekday() >= 5 or is_market_holiday(now_us):
        current_state = "休市"
        next_open_time = get_next_open_time(now_us)
        next_state = "盘前"
        time_to_next_state = (next_open_time - now_us).total_seconds()
    else:
        current_state, next_state, time_to_next_state = calc_market_state(now_us)

    data = {
        "us_time": now_us.strftime("%Y-%m-%d %H:%M %A"),
        "china_time": now_cn.strftime("%Y-%m-%d %H:%M %A"),
        "current_state": current_state,
        "next_state": next_state,
        "time_to_next_state_seconds": time_to_next_state
    }
    return JSONResponse(content=data)

def on_message(ws, message):
    global trade_data_cache
    try:
        data = json.loads(message)
        if data.get("type") == "trade":
            for trade in data.get("data", []):
                symbol = trade.get("s")
                trade_data_cache[symbol] = trade
                print(f"Updated trade data for {symbol}: {trade}")
    except Exception as e:
        print("Error in on_message:", e)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws):
    print("WebSocket closed.")

def on_open(ws):
    # 由于 Finnhub WebSocket 不支持指数或自选股票订阅，
    # 连接建立时不发送订阅请求，只打印提示信息。
    print("WebSocket connection opened. (No index subscriptions)")

def start_websocket():
    websocket.enableTrace(True)
    ws = websocket.WebSocketApp(
        "wss://ws.finnhub.io?token=" + FINNHUB_TOKEN,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.on_open = on_open
    ws.run_forever()

@app.on_event("startup")
def startup_event():
    ws_thread = threading.Thread(target=start_websocket, daemon=True)
    ws_thread.start()
    update_holidays_cache()

async def get_holidays_data():
    """
    直接从 Finnhub 获取假日数据
    """
    try:
        finnhub_client = finnhub.Client(api_key=FINNHUB_TOKEN)
        res = finnhub_client.market_holiday(exchange='US')
        if not res or 'data' not in res:
            print("No holiday data received from Finnhub")
            return {}
            
        holidays_data = {}
        for event in res.get("data", []):
            event_date = event.get("atDate")
            if event_date:
                holidays_data[event_date] = event
        return holidays_data
    except Exception as e:
        print("Error fetching holidays data:", str(e))
        return {}

@app.get("/api/recent_holidays")
async def recent_holidays():
    """
    返回最近的休市假日（今天及之后的第一个休市假日）。
    每次请求时直接从 Finnhub 获取最新数据。
    """
    try:
        holidays_data = await get_holidays_data()
        now = datetime.now(tz_us_eastern).date()
        upcoming = []
        
        for date_str, event in holidays_data.items():
            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if event_date >= now:
                    upcoming.append(event)
            except Exception as e:
                print(f"Error processing holiday date: {date_str}, error: {str(e)}")
                continue
                
        if upcoming:
            upcoming.sort(key=lambda e: e["atDate"])
            nearest = upcoming[0]
        else:
            nearest = None
            
        return JSONResponse(content={"upcoming_holiday": nearest})
    except Exception as e:
        print("Error in recent_holidays:", str(e))
        return JSONResponse(
            content={"error": "Failed to fetch holiday data"},
            status_code=500
        )

@app.get("/api/quote")
def get_quote(symbol: str):
    """
    返回指定股票代码的最新行情数据，包括当前价格和与前日相比的涨跌幅。
    采用 Finnhub /quote 接口（REST方式）。
    """
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol, "token": FINNHUB_TOKEN}
    r = requests.get(url, params=params)
    if r.status_code == 200:
        data = r.json()
        current_price = data.get("c")
        previous_close = data.get("pc")
        if current_price is not None and previous_close is not None:
            change = current_price - previous_close
            percent_change = (change / previous_close * 100) if previous_close != 0 else 0
        else:
            change = None
            percent_change = None
        return JSONResponse(content={
            "symbol": symbol,
            "current_price": current_price,
            "previous_close": previous_close,
            "change": round(change, 2) if change is not None else None,
            "percent_change": round(percent_change, 2) if percent_change is not None else None,
            "source": "REST"
        })
    else:
        return JSONResponse(content={"error": "Failed to fetch quote"})

if __name__ == "__main__":
    import uvicorn
    # 仅在本地开发时使用 StaticFiles
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="web", html=True), name="static")
    uvicorn.run(app, host="0.0.0.0", port=8000)
