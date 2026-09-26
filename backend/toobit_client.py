import httpx
import time
import logging
from dataclasses import dataclass
from typing import List

log = logging.getLogger(__name__)


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class ToobitClient:
    BASE = "https://api.toobit.com"

    def __init__(self, symbol="BTCUSDT", interval="1h", timeout=10.0):
        self.symbol = symbol
        self.interval = interval
        self.client = httpx.Client(timeout=timeout)
        self._last_call = 0.0
        self._min_interval = 0.25
        self.connected = False

    def _throttle(self):
        delta = time.time() - self._last_call
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last_call = time.time()

    def _get(self, path, params, retries=4):
        url = f"{self.BASE}{path}"
        backoff = 1.0
        for attempt in range(retries):
            self._throttle()
            try:
                r = self.client.get(url, params=params)
                if r.status_code == 429:
                    log.warning("Toobit rate limit - backoff %.1fs", backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                r.raise_for_status()
                self.connected = True
                return r.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                self.connected = False
                log.warning("Toobit req fail (%s/%s): %s", attempt+1, retries, e)
                if attempt == retries - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
        raise RuntimeError("unreachable")

    def get_klines(self, limit=500) -> List[Candle]:
        data = self._get("/quote/v1/klines", {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": limit,
        })
        return [
            Candle(int(r[0]), float(r[1]), float(r[2]),
                   float(r[3]), float(r[4]), float(r[5]))
            for r in data
        ]

    def get_closed_candles(self, limit=500) -> List[Candle]:
        raw = self.get_klines(limit=limit + 1)
        return raw[:-1] if raw else []

    def get_price(self) -> float:
        d = self._get("/quote/v1/ticker/price", {"symbol": self.symbol})
        return float(d["price"])
