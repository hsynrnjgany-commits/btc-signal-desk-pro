from dataclasses import dataclass
from typing import List, Optional, Dict
import numpy as np
from indicators import sma, rsi, macd, atr
from toobit_client import Candle


@dataclass
class SignalResult:
    ts: int
    close: float
    signal: str
    score: float
    trend: str
    momentum: str
    volume_state: str
    ma10: float
    ma20: float
    ma40: float
    ma50: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    atr: float
    vol_ratio: float


class ProStrategy:

    def compute_indicators(self, candles: List[Candle]) -> Dict[str, np.ndarray]:
        c = np.array([x.close for x in candles], float)
        h = np.array([x.high for x in candles], float)
        l = np.array([x.low for x in candles], float)
        v = np.array([x.volume for x in candles], float)
        m_l, m_s, m_h = macd(c)
        return {
            "close": c, "high": h, "low": l, "volume": v,
            "ma10": sma(c, 10), "ma20": sma(c, 20),
            "ma40": sma(c, 40), "ma50": sma(c, 50),
            "rsi": rsi(c, 14),
            "macd": m_l, "macd_signal": m_s, "macd_hist": m_h,
            "atr": atr(h, l, c, 14),
            "vol_ma": sma(v, 20),
        }

    def evaluate_at(self, candles, ind, i: int) -> Optional[SignalResult]:
        if i < 55:
            return None
        if any(np.isnan(ind[k][i]) for k in ("ma50", "rsi", "atr")):
            return None

        p = ind["close"][i]
        ma10 = ind["ma10"][i]
        ma20 = ind["ma20"][i]
        ma40 = ind["ma40"][i]
        ma50 = ind["ma50"][i]
        rv = ind["rsi"][i]
        m = ind["macd"][i]
        ms = ind["macd_signal"][i]
        mh = ind["macd_hist"][i]
        av = ind["atr"][i]

        score = 0.0

        if p > ma10 > ma20 > ma50:
            score += 2.0
            trend = "BULLISH"
        elif p < ma10 < ma20 < ma50:
            score -= 2.0
            trend = "BEARISH"
        elif ma20 > ma50:
            score += 0.5
            trend = "MILD_BULL"
        else:
            score -= 0.5
            trend = "MILD_BEAR"

        if rv < 30:
            score += 1.0
            momentum = "OVERSOLD"
        elif rv > 70:
            score -= 1.0
            momentum = "OVERBOUGHT"
        elif 50 < rv < 70:
            score += 0.5
            momentum = "STRONG"
        elif 30 < rv < 50:
            score -= 0.5
            momentum = "WEAK"
        else:
            momentum = "NEUTRAL"

        if m > ms and mh > 0:
            score += 1.0
        elif m < ms and mh < 0:
            score -= 1.0

        vm = ind["vol_ma"][i]
        vr = ind["volume"][i] / vm if vm > 0 else 1.0
        vs = "HIGH" if vr > 1.5 else "LOW" if vr < 0.7 else "NORMAL"

        sig = "BUY" if score >= 2.5 else "SELL" if score <= -2.5 else "HOLD"

        return SignalResult(
            ts=candles[i].ts, close=p, signal=sig, score=round(score, 2),
            trend=trend, momentum=momentum, volume_state=vs,
            ma10=ma10, ma20=ma20, ma40=ma40, ma50=ma50,
            rsi=rv, macd=m, macd_signal=ms, macd_hist=mh,
            atr=av, vol_ratio=vr,
        )

    def latest_signal(self, candles):
        if len(candles) < 60:
            return None
        return self.evaluate_at(
            candles, self.compute_indicators(candles), len(candles) - 1
        )


def auto_leverage(sig: SignalResult, account, user_max: float = 20.0) -> dict:
    s = abs(sig.score)

    signal_mult = 2.0 if s >= 6 else 1.5 if s >= 5 else 1.1 if s >= 4 else 1.0

    atr_pct = (sig.atr / sig.close) * 100 if sig.close else 1.0
    if atr_pct < 0.3:
        vol_mult = 2.0
    elif atr_pct < 0.6:
        vol_mult = 1.3
    elif atr_pct < 1.0:
        vol_mult = 1.0
    else:
        vol_mult = 0.2

    if sig.ma10 > sig.ma20 > sig.ma40 > sig.ma50:
        trend_mult = 1.5
    elif sig.ma10 < sig.ma20 < sig.ma40 < sig.ma50:
        trend_mult = 1.5
    elif sig.ma20 > sig.ma50 or sig.ma20 < sig.ma50:
        trend_mult = 1.0
    else:
        trend_mult = 0.7

    dd = account.max_drawdown
    dd_mult = 1.0 if dd < 10 else 0.75 if dd < 20 else 0.4

    last = account.trades[-3:]
    losses = sum(1 for t in last if t.pnl < 0)
    loss_mult = 1.0 if losses <= 1 else 0.7 if losses == 2 else 0.4

    raw = signal_mult * vol_mult * trend_mult * dd_mult * loss_mult
    final = max(1.0, min(user_max, round(raw, 2)))

    if final > 20:
        golden = (s >= 6 and atr_pct < 0.5 and trend_mult == 1.5
                  and dd < 5 and losses == 0)
        if not golden:
            final = 20.0

    return {
        "leverage": final,
        "signal_mult": signal_mult,
        "vol_mult": vol_mult,
        "trend_mult": trend_mult,
        "dd_mult": dd_mult,
        "loss_mult": loss_mult,
        "atr_pct": round(atr_pct, 3),
    }
