import numpy as np

def sma(v, p):
    a = np.asarray(v, float); out = np.full_like(a, np.nan)
    if len(a) < p: return out
    c = np.cumsum(np.insert(a, 0, 0))
    out[p-1:] = (c[p:] - c[:-p]) / p
    return out

def ema(v, p):
    a = np.asarray(v, float); out = np.full_like(a, np.nan)
    if len(a) < p: return out
    k = 2 / (p + 1)
    out[p-1] = a[:p].mean()
    for i in range(p, len(a)):
        out[i] = a[i]*k + out[i-1]*(1-k)
    return out

def rsi(c, p=14):
    a = np.asarray(c, float); out = np.full_like(a, np.nan)
    if len(a) <= p: return out
    d = np.diff(a); g = np.where(d>0, d, 0); l = np.where(d<0, -d, 0)
    ag, al = g[:p].mean(), l[:p].mean()
    rs = ag/al if al else np.inf
    out[p] = 100 - 100/(1+rs)
    for i in range(p+1, len(a)):
        ag = (ag*(p-1) + g[i-1]) / p
        al = (al*(p-1) + l[i-1]) / p
        rs = ag/al if al else np.inf
        out[i] = 100 - 100/(1+rs)
    return out

def macd(c, fast=12, slow=26, sig=9):
    a = np.asarray(c, float)
    ef, es = ema(a, fast), ema(a, slow)
    line = ef - es
    seed = np.where(np.isnan(line), 0, line)
    sl = ema(seed, sig)
    sl[:slow+sig-2] = np.nan
    return line, sl, line - sl

def atr(h, l, c, p=14):
    h, l, c = map(lambda x: np.asarray(x, float), (h, l, c))
    n = len(h); tr = np.full(n, np.nan)
    tr[0] = h[0]-l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.full(n, np.nan)
    if n < p: return out
    out[p-1] = tr[:p].mean()
    for i in range(p, n):
        out[i] = (out[i-1]*(p-1) + tr[i]) / p
    return out
