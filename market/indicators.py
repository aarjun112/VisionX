"""Technical indicators computed from daily candles.

Each calculation takes plain Python lists and returns a list of the same
length, with None where there is not enough history yet.
Change the numbers below to tune the indicators.
"""

RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BB_PERIOD, BB_MULT = 20, 2.0
ST_PERIOD, ST_MULT = 10, 3.0


# ---------- building blocks ----------

def sma(values, period):
    out = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def ema(values, period):
    """Exponential moving average, seeded with the simple average of the first `period` values."""
    out = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


# ---------- RSI (Wilder) ----------

def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def rsi(closes, period=RSI_PERIOD):
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


# ---------- MACD ----------

def macd(closes, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL):
    n = len(closes)
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [None] * n
    for i in range(n):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            line[i] = fast_ema[i] - slow_ema[i]

    sig = [None] * n
    hist = [None] * n
    valid = [i for i in range(n) if line[i] is not None]
    if len(valid) >= signal:
        sig_vals = ema([line[i] for i in valid], signal)
        for pos, i in enumerate(valid):
            sig[i] = sig_vals[pos]
            if sig[i] is not None:
                hist[i] = line[i] - sig[i]
    return line, sig, hist


# ---------- Bollinger Bands ----------

def bollinger(closes, period=BB_PERIOD, mult=BB_MULT):
    n = len(closes)
    mid = sma(closes, period)
    upper, lower = [None] * n, [None] * n
    for i in range(n):
        if mid[i] is None:
            continue
        window = closes[i - period + 1:i + 1]
        variance = sum((x - mid[i]) ** 2 for x in window) / period
        dev = variance ** 0.5
        upper[i] = mid[i] + mult * dev
        lower[i] = mid[i] - mult * dev
    return upper, mid, lower


# ---------- Supertrend ----------

def supertrend(highs, lows, closes, period=ST_PERIOD, mult=ST_MULT):
    """Returns (values, trends). trend is 1 for an uptrend and -1 for a downtrend."""
    n = len(closes)
    values, trends = [None] * n, [None] * n
    if n < period:
        return values, trends

    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))

    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    start = period - 1
    mid = (highs[start] + lows[start]) / 2.0
    final_upper = mid + mult * atr[start]
    final_lower = mid - mult * atr[start]
    trend = 1 if closes[start] >= mid else -1
    values[start] = final_lower if trend == 1 else final_upper
    trends[start] = trend

    for i in range(start + 1, n):
        mid = (highs[i] + lows[i]) / 2.0
        basic_upper = mid + mult * atr[i]
        basic_lower = mid - mult * atr[i]

        if basic_upper < final_upper or closes[i - 1] > final_upper:
            final_upper = basic_upper
        if basic_lower > final_lower or closes[i - 1] < final_lower:
            final_lower = basic_lower

        if trend == 1 and closes[i] < final_lower:
            trend = -1
        elif trend == -1 and closes[i] > final_upper:
            trend = 1

        values[i] = final_lower if trend == 1 else final_upper
        trends[i] = trend
    return values, trends


# ---------- everything at once, ready for the chart ----------

def _points(times, values, digits=4):
    return [{'time': t, 'value': round(v, digits)}
            for t, v in zip(times, values) if v is not None]


def _last(values):
    for v in reversed(values):
        if v is not None:
            return v
    return None


def compute_all(candles):
    """candles: [{'time','open','high','low','close'}, ...] oldest first."""
    empty = {
        'bb_upper': [], 'bb_mid': [], 'bb_lower': [],
        'rsi': [], 'macd': [], 'macd_signal': [], 'macd_hist': [],
        'supertrend': [], 'latest': {},
        'params': {
            'rsi': RSI_PERIOD,
            'macd': [MACD_FAST, MACD_SLOW, MACD_SIGNAL],
            'bb': [BB_PERIOD, BB_MULT],
            'st': [ST_PERIOD, ST_MULT],
        },
    }
    if len(candles) < 2:
        return empty

    times = [c['time'] for c in candles]
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]

    rsi_v = rsi(closes)
    macd_l, macd_s, macd_h = macd(closes)
    bb_u, bb_m, bb_l = bollinger(closes)
    st_v, st_t = supertrend(highs, lows, closes)

    out = dict(empty)
    out['bb_upper'] = _points(times, bb_u)
    out['bb_mid'] = _points(times, bb_m)
    out['bb_lower'] = _points(times, bb_l)
    out['rsi'] = _points(times, rsi_v, 2)
    out['macd'] = _points(times, macd_l)
    out['macd_signal'] = _points(times, macd_s)
    out['macd_hist'] = _points(times, macd_h)
    out['supertrend'] = [
        {'time': t, 'value': round(v, 4), 'trend': tr}
        for t, v, tr in zip(times, st_v, st_t) if v is not None
    ]

    # plain-language readings of the latest bar
    latest = {}
    r = _last(rsi_v)
    if r is not None:
        latest['rsi'] = round(r, 1)
        latest['rsi_label'] = 'Overbought' if r >= 70 else 'Oversold' if r <= 30 else 'Neutral'
    m, s = _last(macd_l), _last(macd_s)
    if m is not None and s is not None:
        latest['macd_label'] = 'Bullish' if m > s else 'Bearish'
    t = _last(st_t)
    if t is not None:
        latest['st_label'] = 'Uptrend' if t == 1 else 'Downtrend'
    u, lo = _last(bb_u), _last(bb_l)
    if u is not None and lo is not None:
        c = closes[-1]
        latest['bb_label'] = ('Above upper band' if c > u
                              else 'Below lower band' if c < lo else 'Inside the bands')
    out['latest'] = latest
    return out