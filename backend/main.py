import logging
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from toobit_client import ToobitClient
from strategy import ProStrategy, auto_leverage
from paper_trading import PaperAccount
from backtest import run_backtest

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="BTC Signal Desk PRO")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
STATIC_DIR = os.path.abspath(STATIC_DIR)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

client = ToobitClient(symbol="BTCUSDT", interval="1h")
strategy = ProStrategy()
account = PaperAccount()


class Config(BaseModel):
    starting_balance: float | None = None
    risk_pct: float | None = None
    fee_pct: float | None = None
    slippage_pct: float | None = None
    atr_stop_mult: float | None = None
    atr_tp_mult: float | None = None


class LevConfig(BaseModel):
    max_leverage: float | None = None
    use_auto_leverage: bool | None = None


@app.get("/api/market")
def market():
    try:
        candles = client.get_closed_candles(limit=300)
        price = client.get_price()
        return {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "price": price,
            "last_closed_ts": candles[-1].ts if candles else None,
            "candles_count": len(candles),
            "connected": client.connected,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/signal")
def signal():
    try:
        candles = client.get_closed_candles(limit=300)
        if not candles:
            return JSONResponse({"error": "no candles"}, status_code=503)
        sig = strategy.latest_signal(candles)
        price = client.get_price()

        if account.position:
            account.update_price(price, candles[-1].ts)

        if sig and account.position is None:
            if sig.signal == "BUY":
                account.open_position("LONG", candles[-1].close, sig.atr,
                                      candles[-1].ts, sig=sig)
            elif sig.signal == "SELL":
                account.open_position("SHORT", candles[-1].close, sig.atr,
                                      candles[-1].ts, sig=sig)

        return {
            "signal": sig.__dict__ if sig else None,
            "signal_on": "LAST_CLOSED_CANDLE",
            "price": price,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/paper")
def paper():
    try:
        price = client.get_price()
        return account.stats(price)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/paper/position")
def pos():
    return {"position": account.position.__dict__ if account.position else None}


@app.get("/api/paper/trades")
def trades():
    return {"trades": [t.__dict__ for t in account.trades[-100:]]}


@app.post("/api/paper/config")
def cfg(c: Config):
    if c.starting_balance is not None:
        account.starting_balance = c.starting_balance
    if c.risk_pct is not None:
        account.risk_pct = c.risk_pct
    if c.fee_pct is not None:
        account.fee_pct = c.fee_pct / 100.0
    if c.slippage_pct is not None:
        account.slippage_pct = c.slippage_pct / 100.0
    if c.atr_stop_mult is not None:
        account.atr_stop_mult = c.atr_stop_mult
    if c.atr_tp_mult is not None:
        account.atr_tp_mult = c.atr_tp_mult
    account._persist()
    return {"ok": True}


@app.post("/api/paper/leverage")
def set_lev(c: LevConfig):
    if c.max_leverage is not None:
        account.max_leverage = max(1.0, min(200.0, c.max_leverage))
    if c.use_auto_leverage is not None:
        account.use_auto_leverage = c.use_auto_leverage
    account._persist()
    return {
        "max_leverage": account.max_leverage,
        "use_auto_leverage": account.use_auto_leverage,
    }


@app.get("/api/leverage/preview")
def lev_preview():
    try:
        candles = client.get_closed_candles(limit=300)
        sig = strategy.latest_signal(candles)
        if not sig:
            return {"error": "no signal yet"}
        return auto_leverage(sig, account, user_max=account.max_leverage)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/paper/reset")
def reset():
    account.reset()
    return {"ok": True}


@app.get("/api/backtest")
def backtest():
    try:
        candles = client.get_closed_candles(limit=1000)
        bt = PaperAccount(
            starting_balance=account.starting_balance,
            risk_pct=account.risk_pct,
            fee_pct=account.fee_pct * 100,
            slippage_pct=account.slippage_pct * 100,
            atr_stop_mult=account.atr_stop_mult,
            atr_tp_mult=account.atr_tp_mult,
            max_leverage=account.max_leverage,
            use_auto_leverage=account.use_auto_leverage,
        )
        return run_backtest(candles, strategy, bt)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/", response_class=HTMLResponse)
def index():
    p = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read()
    return "<h1>BTC Signal Desk PRO — index.html not found</h1>"
