/* VisionX technical indicators (works in the browser and in Node).
   Every function takes plain arrays and returns arrays of the same length,
   with null where there is not enough history yet. */
(function (root) {
    "use strict";

    function blank(n) {
        var out = new Array(n);
        for (var i = 0; i < n; i++) { out[i] = null; }
        return out;
    }

    function sma(values, period) {
        var out = blank(values.length);
        if (period <= 0 || values.length < period) { return out; }
        var win = 0, i;
        for (i = 0; i < period; i++) { win += values[i]; }
        out[period - 1] = win / period;
        for (i = period; i < values.length; i++) {
            win += values[i] - values[i - period];
            out[i] = win / period;
        }
        return out;
    }

    // seeded with the simple average of the first `period` values
    function ema(values, period) {
        var out = blank(values.length);
        if (period <= 0 || values.length < period) { return out; }
        var k = 2 / (period + 1), i;
        var prev = 0;
        for (i = 0; i < period; i++) { prev += values[i]; }
        prev = prev / period;
        out[period - 1] = prev;
        for (i = period; i < values.length; i++) {
            prev = values[i] * k + prev * (1 - k);
            out[i] = prev;
        }
        return out;
    }

    function rsiValue(avgGain, avgLoss) {
        if (avgLoss === 0) { return avgGain === 0 ? 50 : 100; }
        return 100 - 100 / (1 + avgGain / avgLoss);
    }

    // Wilder's RSI
    function rsi(closes, period) {
        var n = closes.length, out = blank(n), i, change;
        if (n <= period || period <= 0) { return out; }
        var gains = 0, losses = 0;
        for (i = 1; i <= period; i++) {
            change = closes[i] - closes[i - 1];
            gains += Math.max(change, 0);
            losses += Math.max(-change, 0);
        }
        var avgGain = gains / period, avgLoss = losses / period;
        out[period] = rsiValue(avgGain, avgLoss);
        for (i = period + 1; i < n; i++) {
            change = closes[i] - closes[i - 1];
            avgGain = (avgGain * (period - 1) + Math.max(change, 0)) / period;
            avgLoss = (avgLoss * (period - 1) + Math.max(-change, 0)) / period;
            out[i] = rsiValue(avgGain, avgLoss);
        }
        return out;
    }

    function macd(closes, fast, slow, signal) {
        var n = closes.length, i;
        var f = ema(closes, fast), s = ema(closes, slow);
        var line = blank(n), sig = blank(n), hist = blank(n), valid = [];
        for (i = 0; i < n; i++) {
            if (f[i] !== null && s[i] !== null) {
                line[i] = f[i] - s[i];
                valid.push(i);
            }
        }
        if (valid.length >= signal) {
            var sv = ema(valid.map(function (idx) { return line[idx]; }), signal);
            valid.forEach(function (idx, pos) {
                if (sv[pos] !== null) {
                    sig[idx] = sv[pos];
                    hist[idx] = line[idx] - sv[pos];
                }
            });
        }
        return { line: line, signal: sig, hist: hist };
    }

    function bollinger(closes, period, mult) {
        var n = closes.length, i, j;
        var mid = sma(closes, period), upper = blank(n), lower = blank(n);
        for (i = 0; i < n; i++) {
            if (mid[i] === null) { continue; }
            var variance = 0;
            for (j = i - period + 1; j <= i; j++) {
                variance += Math.pow(closes[j] - mid[i], 2);
            }
            var dev = Math.sqrt(variance / period);
            upper[i] = mid[i] + mult * dev;
            lower[i] = mid[i] - mult * dev;
        }
        return { upper: upper, mid: mid, lower: lower };
    }

    // trend: 1 = uptrend, -1 = downtrend
    function supertrend(highs, lows, closes, period, mult) {
        var n = closes.length, i;
        var values = blank(n), trends = blank(n);
        if (n < period || period <= 0) { return { values: values, trends: trends }; }

        var tr = [highs[0] - lows[0]];
        for (i = 1; i < n; i++) {
            tr.push(Math.max(
                highs[i] - lows[i],
                Math.abs(highs[i] - closes[i - 1]),
                Math.abs(lows[i] - closes[i - 1])
            ));
        }
        var atr = blank(n), seed = 0;
        for (i = 0; i < period; i++) { seed += tr[i]; }
        atr[period - 1] = seed / period;
        for (i = period; i < n; i++) {
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period;
        }

        var start = period - 1;
        var mid = (highs[start] + lows[start]) / 2;
        var finalUpper = mid + mult * atr[start];
        var finalLower = mid - mult * atr[start];
        var trend = closes[start] >= mid ? 1 : -1;
        values[start] = trend === 1 ? finalLower : finalUpper;
        trends[start] = trend;

        for (i = start + 1; i < n; i++) {
            mid = (highs[i] + lows[i]) / 2;
            var basicUpper = mid + mult * atr[i];
            var basicLower = mid - mult * atr[i];

            if (basicUpper < finalUpper || closes[i - 1] > finalUpper) { finalUpper = basicUpper; }
            if (basicLower > finalLower || closes[i - 1] < finalLower) { finalLower = basicLower; }

            if (trend === 1 && closes[i] < finalLower) { trend = -1; }
            else if (trend === -1 && closes[i] > finalUpper) { trend = 1; }

            values[i] = trend === 1 ? finalLower : finalUpper;
            trends[i] = trend;
        }
        return { values: values, trends: trends };
    }

    // p = { rsi:{length}, macd:{fast,slow,signal}, bb:{length,mult}, st:{length,factor} }
    function compute(candles, p) {
        var closes = candles.map(function (c) { return c.close; });
        var highs = candles.map(function (c) { return c.high; });
        var lows = candles.map(function (c) { return c.low; });
        var m = macd(closes, p.macd.fast, p.macd.slow, p.macd.signal);
        var b = bollinger(closes, p.bb.length, p.bb.mult);
        var s = supertrend(highs, lows, closes, p.st.length, p.st.factor);
        return {
            rsi: rsi(closes, p.rsi.length),
            macd: m.line, macdSignal: m.signal, macdHist: m.hist,
            bbUpper: b.upper, bbMid: b.mid, bbLower: b.lower,
            stValue: s.values, stTrend: s.trends
        };
    }

    var api = {
        sma: sma, ema: ema, rsi: rsi, macd: macd,
        bollinger: bollinger, supertrend: supertrend, compute: compute
    };
    root.VXIndicators = api;
    if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})(typeof window !== "undefined" ? window : globalThis);
