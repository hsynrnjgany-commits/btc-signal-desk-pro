from strategy import ProStrategy
from paper_trading import PaperAccount


def run_backtest(candles, strategy: ProStrategy, account: PaperAccount):
    ind = strategy.compute_indicators(candles)
    for i in range(55, len(candles)):
        sig = strategy.evaluate_at(candles, ind, i)
        if sig is None:
            continue
        price = candles[i].close
        ts = candles[i].ts

        if account.position:
            account.update_price(price, ts)

        if account.position is None:
            if sig.signal == "BUY":
                account.open_position("LONG", price, sig.atr, ts, sig=sig)
            elif sig.signal == "SELL":
                account.open_position("SHORT", price, sig.atr, ts, sig=sig)
        else:
            pos = account.position
            if pos.side == "LONG" and sig.signal == "SELL":
                account._close(price, pos.size, ts, "REVERSE")
                account.position = None
                account.open_position("SHORT", price, sig.atr, ts, sig=sig)
            elif pos.side == "SHORT" and sig.signal == "BUY":
                account._close(price, pos.size, ts, "REVERSE")
                account.position = None
                account.open_position("LONG", price, sig.atr, ts, sig=sig)

    return account.stats(candles[-1].close)
