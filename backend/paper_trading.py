import json
import os
import time
from dataclasses import dataclass, asdict
from typing import List, Optional


STATE_FILE = "paper_state.json"


@dataclass
class Position:
    side: str
    entry_price: float
    size: float
    stop_loss: float
    take_profit: float
    tp_partial: float
    partial_taken: bool
    entry_ts: int
    entry_fee: float
    highest_price: float
    lowest_price: float
    trailing_active: bool
    leverage: float = 1.0
    margin: float = 0.0
    liquidation: float = 0.0
    max_leverage: float = 20.0
    auto_lev_info: dict = None


@dataclass
class Trade:
    side: str
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    fees: float
    reason: str


class PaperAccount:

    def __init__(self, starting_balance=1000.0, risk_pct=1.0,
                 fee_pct=0.1, slippage_pct=0.05,
                 atr_stop_mult=1.5, atr_tp_mult=3.0,
                 partial_tp_atr=1.5, partial_tp_size=0.5,
                 max_leverage=20.0, use_auto_leverage=True):
        self.starting_balance = starting_balance
        self.balance = starting_balance
        self.risk_pct = risk_pct
        self.fee_pct = fee_pct / 100.0
        self.slippage_pct = slippage_pct / 100.0
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult
        self.partial_tp_atr = partial_tp_atr
        self.partial_tp_size = partial_tp_size
        self.max_leverage = max_leverage
        self.use_auto_leverage = use_auto_leverage
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve = []
        self.max_drawdown = 0.0
        self._peak = starting_balance
        self.load()

    def _persist(self):
        state = {
            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "risk_pct": self.risk_pct,
            "fee_pct": self.fee_pct,
            "slippage_pct": self.slippage_pct,
            "atr_stop_mult": self.atr_stop_mult,
            "atr_tp_mult": self.atr_tp_mult,
            "partial_tp_atr": self.partial_tp_atr,
            "partial_tp_size": self.partial_tp_size,
            "max_leverage": self.max_leverage,
            "use_auto_leverage": self.use_auto_leverage,
            "max_drawdown": self.max_drawdown,
            "position": asdict(self.position) if self.position else None,
            "trades": [asdict(t) for t in self.trades],
            "equity_curve": self.equity_curve[-1000:],
            "_peak": self._peak,
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)

    def load(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            s = json.load(open(STATE_FILE))
        except Exception:
            return
        for k in ("starting_balance", "balance", "risk_pct", "fee_pct",
                  "slippage_pct", "atr_stop_mult", "atr_tp_mult",
                  "partial_tp_atr", "partial_tp_size", "max_drawdown",
                  "max_leverage", "use_auto_leverage"):
            if k in s:
                setattr(self, k, s[k])
        self.position = Position(**s["position"]) if s.get("position") else None
        self.trades = [Trade(**t) for t in s.get("trades", [])]
        self.equity_curve = s.get("equity_curve", [])
        self._peak = s.get("_peak", self.balance)

    def _slip(self, price, is_buy):
        if is_buy:
            return price * (1 + self.slippage_pct)
        return price * (1 - self.slippage_pct)

    def open_position(self, side, price, atr, ts, sig=None):
        if self.position:
            return

        if self.use_auto_leverage and sig is not None:
            from strategy import auto_leverage
            info = auto_leverage(sig, self, user_max=self.max_leverage)
            lev = info["leverage"]
        else:
            lev = 1.0
            info = {"leverage": 1.0}

        risk = self.balance * (self.risk_pct / 100.0)
        stop_dist = atr * self.atr_stop_mult
        if stop_dist <= 0:
            return
        size = risk / stop_dist

        fill = self._slip(price, is_buy=(side == "LONG"))

        notional = fill * size
        margin = notional / lev

        if margin > self.balance * 0.95:
            need_lev = notional / (self.balance * 0.95)
            if need_lev > self.max_leverage:
                return
            lev = need_lev
            margin = notional / lev

        mm = 0.005
        if side == "LONG":
            liq = fill * (1 - (1 / lev) + mm)
            sl = fill - stop_dist
            tp = fill + atr * self.atr_tp_mult
            tpp = fill + atr * self.partial_tp_atr
        else:
            liq = fill * (1 + (1 / lev) - mm)
            sl = fill + stop_dist
            tp = fill - atr * self.atr_tp_mult
            tpp = fill - atr * self.partial_tp_atr

        if side == "LONG" and sl <= liq:
            return
        if side == "SHORT" and sl >= liq:
            return

        fee = notional * self.fee_pct
        self.balance -= fee
        self.position = Position(
            side, fill, size, sl, tp, tpp, False, ts, fee,
            fill, fill, False,
            leverage=lev, margin=margin, liquidation=liq,
            max_leverage=self.max_leverage, auto_lev_info=info,
        )
        self._persist()

    def _close(self, price, size, ts, reason):
        pos = self.position
        if not pos:
            return
        fill = self._slip(price, is_buy=(pos.side == "SHORT"))
        if pos.side == "LONG":
            pnl = (fill - pos.entry_price) * size
        else:
            pnl = (pos.entry_price - fill) * size
        exit_fee = fill * size * self.fee_pct
        self.balance += pnl - exit_fee
        self.trades.append(Trade(
            pos.side, pos.entry_ts, ts, pos.entry_price, fill,
            size, pnl - exit_fee, exit_fee, reason,
        ))

    def update_price(self, price, ts):
        pos = self.position
        if not pos:
            return

        if pos.side == "LONG" and price <= pos.liquidation:
            self._close(pos.liquidation, pos.size, ts, "LIQUIDATION")
            self.balance -= pos.margin
            self.position = None
            self._record(price)
            self._persist()
            return
        if pos.side == "SHORT" and price >= pos.liquidation:
            self._close(pos.liquidation, pos.size, ts, "LIQUIDATION")
            self.balance -= pos.margin
            self.position = None
            self._record(price)
            self._persist()
            return

        pos.highest_price = max(pos.highest_price, price)
        pos.lowest_price = min(pos.lowest_price, price)

        if pos.side == "LONG":
            if not pos.partial_taken and price >= pos.tp_partial:
                part = pos.size * self.partial_tp_size
                self._close(price, part, ts, "PARTIAL_TP")
                pos.size -= part
                pos.partial_taken = True
                pos.stop_loss = max(pos.stop_loss, pos.entry_price)
            if price >= pos.tp_partial:
                pos.trailing_active = True
            if pos.trailing_active:
                trail = pos.highest_price * 0.99
                pos.stop_loss = max(pos.stop_loss, trail)
            if price <= pos.stop_loss:
                self._close(price, pos.size, ts, "STOP")
                self.position = None
                self._record(price)
                self._persist()
                return
            if price >= pos.take_profit:
                self._close(price, pos.size, ts, "TP")
                self.position = None
                self._record(price)
                self._persist()
                return
        else:
            if not pos.partial_taken and price <= pos.tp_partial:
                part = pos.size * self.partial_tp_size
                self._close(price, part, ts, "PARTIAL_TP")
                pos.size -= part
                pos.partial_taken = True
                pos.stop_loss = min(pos.stop_loss, pos.entry_price)
            if price <= pos.tp_partial:
                pos.trailing_active = True
            if pos.trailing_active:
                trail = pos.lowest_price * 1.01
                pos.stop_loss = min(pos.stop_loss, trail)
            if price >= pos.stop_loss:
                self._close(price, pos.size, ts, "STOP")
                self.position = None
                self._record(price)
                self._persist()
                return
            if price <= pos.take_profit:
                self._close(price, pos.size, ts, "TP")
                self.position = None
                self._record(price)
                self._persist()
                return

        self._record(price)
        self._persist()

    def _record(self, price):
        eq = self.equity(price)
        self._peak = max(self._peak, eq)
        dd = (self._peak - eq) / self._peak * 100 if self._peak else 0
        self.max_drawdown = max(self.max_drawdown, dd)
        self.equity_curve.append({"t": int(time.time()), "equity": eq})

    def equity(self, price):
        eq = self.balance
        if self.position:
            p = self.position
            if p.side == "LONG":
                eq += (price - p.entry_price) * p.size
            else:
                eq += (p.entry_price - price) * p.size
        return eq

    def unrealized_pnl(self, price):
        if not self.position:
            return 0.0
        p = self.position
        if p.side == "LONG":
            return (price - p.entry_price) * p.size
        return (p.entry_price - price) * p.size

    def realized_pnl(self):
        return sum(t.pnl for t in self.trades)

    def stats(self, price):
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl < 0]
        gp = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in losses))
        if gl > 0:
            pf = gp / gl
        elif gp > 0:
            pf = 999.0
        else:
            pf = 0.0
        return {
            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "equity": self.equity(price),
            "unrealized_pnl": self.unrealized_pnl(price),
            "realized_pnl": self.realized_pnl(),
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(self.trades) * 100) if self.trades else 0.0,
            "profit_factor": pf,
            "max_drawdown": self.max_drawdown,
            "max_leverage": self.max_leverage,
            "use_auto_leverage": self.use_auto_leverage,
        }

    def reset(self, balance=None):
        if balance is not None:
            self.starting_balance = balance
        self.balance = self.starting_balance
        self.position = None
        self.trades = []
        self.equity_curve = []
        self.max_drawdown = 0.0
        self._peak = self.starting_balance
        self._persist()
