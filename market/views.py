import inspect
import traceback
from datetime import date

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from nepsepy import NepseClient

from .forms import SignUpForm
from .models import DailyBar


# ---------- helpers ----------

def pick(row, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None:
            return v
    return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt_big(n):
    if n >= 1e9:
        return f"Rs. {n/1e9:.2f}B"
    if n >= 1e6:
        return f"Rs. {n/1e6:.2f}M"
    return f"Rs. {n:,.0f}"


def fmt_num(v, decimals=2):
    return f"{v:,.{decimals}f}" if v is not None else "—"


def extract_rows(data):
    if isinstance(data, dict):
        rows = data.get('content') or data.get('data') or []
        if not rows:
            rows = next((v for v in data.values() if isinstance(v, list)), [])
        return rows
    return data or []


NEPAL_OFFSET = 5 * 3600 + 45 * 60  # chart shows UTC, so shift to Nepal time (UTC+5:45)


# ---------- stored history (database) ----------

INDEX_SYMBOL = 'INDEX:NEPSE'


def save_bars(symbol, candles, volumes):
    """Save daily candles to the database (insert new days, update existing ones)."""
    if not candles:
        return
    vol_by_date = {v['time']: v['value'] for v in volumes}
    bars = []
    for c in candles:
        try:
            d = date.fromisoformat(c['time'])
        except (ValueError, TypeError):
            continue
        bars.append(DailyBar(
            symbol=symbol, date=d,
            open=c['open'], high=c['high'], low=c['low'], close=c['close'],
            volume=vol_by_date.get(c['time'], 0),
        ))
    try:
        DailyBar.objects.bulk_create(
            bars, batch_size=500,
            update_conflicts=True,
            unique_fields=['symbol', 'date'],
            update_fields=['open', 'high', 'low', 'close', 'volume'],
        )
    except Exception:
        print('Saving history failed (did you run makemigrations and migrate?):')
        traceback.print_exc()


def load_bars(symbol):
    """Load every stored day for a symbol, oldest first."""
    candles, volumes = [], []
    try:
        for b in DailyBar.objects.filter(symbol=symbol).order_by('date'):
            d = b.date.isoformat()
            candles.append({'time': d, 'open': b.open, 'high': b.high,
                            'low': b.low, 'close': b.close})
            volumes.append({
                'time': d,
                'value': b.volume,
                'color': 'rgba(34,197,94,0.5)' if b.close >= b.open else 'rgba(239,68,68,0.5)',
            })
    except Exception:
        print('Loading stored history failed:')
        traceback.print_exc()
    return {'candles': candles, 'volumes': volumes}


# ---------- today's prices (shared by dashboard and company page) ----------

def get_today_rows():
    """Return {symbol: row} for every listed company."""
    rows = cache.get('nepse_rows')
    if rows:
        return rows
    try:
        with NepseClient() as client:
            data = client.today_price(page=1, size=500)
        raw = extract_rows(data)
        print('NEPSE rows received:', len(raw))
        rows = {r.get('symbol'): r for r in raw if r.get('symbol')}
        if rows:
            cache.set('nepse_rows', rows, 120)
            cache.set('nepse_rows_stale', rows, 86400)
            return rows
    except Exception:
        print('NEPSE fetch failed:')
        traceback.print_exc()
    return cache.get('nepse_rows_stale') or {}


# ---------- NEPSE index (dashboard chart) ----------

INDEX_ID = 58                  # NEPSE index id used by NEPSE
INDEX_CACHE_SECONDS = 600      # 10 minutes
INDEX_INTRADAY_SECONDS = 120   # 2 minutes


def fetch_index_rows(client, size=500, max_pages=20):
    """Fetch every page of NEPSE index history."""
    all_rows, seen, page = [], set(), 1
    while page <= max_pages:
        data = client.index_history(index_id=INDEX_ID, page=page, size=size)
        rows = extract_rows(data)
        if not rows:
            break

        new = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            key = r.get('businessDate') or id(r)
            if key not in seen:
                seen.add(key)
                all_rows.append(r)
                new += 1
        if new == 0:
            break

        total_pages = data.get('totalPages') if isinstance(data, dict) else None
        if total_pages is not None and page >= int(total_pages):
            break
        if total_pages is None and len(rows) < size:
            break
        page += 1
    return all_rows


def index_to_candles(rows):
    by_date = {}
    latest = None
    for r in rows:
        d = str(r.get('businessDate') or '')[:10]
        c = num(r.get('closingIndex'))
        if not d or c is None:
            continue
        o = num(r.get('openIndex')) or c
        h = num(r.get('highIndex')) or max(o, c)
        l = num(r.get('lowIndex')) or min(o, c)
        v = num(r.get('turnoverVolume')) or 0
        by_date[d] = (o, max(h, o, c), min(l, o, c), c, v)
        if latest is None or d > latest[0]:
            latest = (d, r)

    candles, volumes = [], []
    for d in sorted(by_date):
        o, h, l, c, v = by_date[d]
        candles.append({'time': d, 'open': o, 'high': h, 'low': l, 'close': c})
        volumes.append({
            'time': d,
            'value': v,
            'color': 'rgba(34,197,94,0.5)' if c >= o else 'rgba(239,68,68,0.5)',
        })
    return candles, volumes, latest


def get_index():
    cached = cache.get('nepse_index')
    if cached:
        return cached

    result = {'candles': [], 'volumes': [], 'latest': None}
    try:
        with NepseClient() as client:
            rows = fetch_index_rows(client)
        candles, volumes, latest = index_to_candles(rows)
        print(f'index_history: {len(rows)} rows -> {len(candles)} candles',
              (candles[0]['time'], candles[-1]['time']) if candles else '')

        # keep growing the stored index history, and chart everything stored
        save_bars(INDEX_SYMBOL, candles, volumes)
        stored = load_bars(INDEX_SYMBOL)
        if len(stored['candles']) > len(candles):
            candles, volumes = stored['candles'], stored['volumes']

        info = None
        if latest:
            d, r = latest
            pct = num(r.get('percentageChange'))
            pts = num(r.get('absChange'))
            info = {
                'value': fmt_num(num(r.get('closingIndex'))),
                'change': f"{pct:+.2f}%" if pct is not None else "—",
                'change_pts': f"{pts:+,.2f}" if pts is not None else "—",
                'up': pct is not None and pct >= 0,
                'date': d,
            }
        result = {'candles': candles, 'volumes': volumes, 'latest': info}
    except Exception:
        print('Index fetch failed:')
        traceback.print_exc()
        stored = load_bars(INDEX_SYMBOL)        # still show what we saved earlier
        if stored['candles']:
            result['candles'] = stored['candles']
            result['volumes'] = stored['volumes']

    if len(result['candles']) >= 2:
        cache.set('nepse_index', result, INDEX_CACHE_SECONDS)
        cache.set('nepse_index_stale', result, 86400)
        return result
    return cache.get('nepse_index_stale') or result


def index_intraday_methods(client):
    """Find client methods that look like the NEPSE index intraday graph."""
    names = []
    for n in dir(client):
        low = n.lower()
        if n.startswith('_') or not callable(getattr(client, n, None)):
            continue
        if 'index' not in low:
            continue
        if not any(h in low for h in ('graph', 'intraday', 'chart')):
            continue
        if 'history' in low:
            continue
        if any(s in low for s in ('sensitive', 'float', 'sub', 'sector')):
            continue
        names.append(n)

    def rank(n):
        low = n.lower()
        return (0 if 'nepse' in low else 1,
                0 if ('intraday' in low or 'daily' in low) else 1)

    return sorted(names, key=rank)


def call_index_method(client, name):
    fn = getattr(client, name)
    kwargs = {}
    for p in inspect.signature(fn).parameters.values():
        pn = p.name.lower()
        if pn in ('index_id', 'indexid', 'index', 'id'):
            kwargs[p.name] = INDEX_ID
        elif p.default is p.empty and p.kind in (p.POSITIONAL_OR_KEYWORD,
                                                  p.KEYWORD_ONLY):
            kwargs[p.name] = INDEX_ID
    return fn(**kwargs)


def parse_intraday_rows(rows):
    """Accept [time, value] pairs or dicts; return chart points in Nepal time."""
    points, seen = [], set()
    for r in rows or []:
        t = v = None
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            t, v = r[0], r[1]
        elif isinstance(r, dict):
            t = pick(r, 'time', 'timestamp')
            v = pick(r, 'contractRate', 'value', 'index', 'closingIndex',
                     'currentValue', 'close', 'closePrice')
        t, v = num(t), num(v)
        if t is None or v is None:
            continue
        if t > 1e11:       # milliseconds -> seconds
            t = t / 1000
        t = int(t)
        if t in seen:
            continue
        seen.add(t)
        points.append({'time': t + NEPAL_OFFSET, 'value': v})
    points.sort(key=lambda p: p['time'])
    return points


def get_index_intraday():
    cached = cache.get('nepse_index_intraday')
    if cached is not None:
        return cached

    points = []
    try:
        with NepseClient() as client:
            methods = index_intraday_methods(client)
            print('Index intraday methods found:', methods)
            for name in methods:
                try:
                    data = call_index_method(client, name)
                    rows = extract_rows(data)
                    print(f'{name}: {len(rows)} rows | sample:',
                          rows[0] if rows else None)
                    pts = parse_intraday_rows(rows)
                    if len(pts) >= 2:
                        points = pts
                        print(f'Using {name}: {len(points)} intraday points')
                        break
                except Exception as e:
                    print(f'{name} failed:', repr(e))
    except Exception:
        print('Index intraday fetch failed:')
        traceback.print_exc()

    if points:
        cache.set('nepse_index_intraday', points, INDEX_INTRADAY_SECONDS)
    return points


# ---------- dashboard ----------

def tops(companies, n=15):
    """Return the top n gainers and top n losers from a list of companies."""
    valid = [c for c in companies if c['change_val'] is not None]

    gainers = sorted(
        (c for c in valid if c['change_val'] > 0),
        key=lambda c: c['change_val'],
        reverse=True,
    )[:n]

    losers = sorted(
        (c for c in valid if c['change_val'] < 0),
        key=lambda c: c['change_val'],
    )[:n]

    return gainers, losers


def load_market():
    rows = get_today_rows()

    companies, turnover, volume = [], 0.0, 0.0
    for symbol, r in rows.items():
        price = num(pick(r, 'lastUpdatedPrice', 'lastTradedPrice', 'closePrice'))
        prev = num(pick(r, 'previousDayClosePrice', 'previousClose'))
        change = None
        pts = None
        if price is not None and prev:
            change = (price - prev) / prev * 100
            pts = price - prev

        turnover += num(r.get('totalTradedValue')) or 0
        volume += num(r.get('totalTradedQuantity')) or 0

        companies.append({
            'name': pick(r, 'securityName', 'companyName') or symbol,
            'symbol': symbol,
            'price': fmt_num(price),
            'change': f"{change:+.2f}%" if change is not None else "—",
            'change_val': change,
            'change_pts': f"{pts:+,.2f}" if pts is not None else "—",
            'up': change is not None and change >= 0,
        })

    all_companies = sorted(companies, key=lambda c: c['symbol'])
    gainers, losers = tops(companies, 15)
    print('companies loaded:', len(companies),
          '| gainers:', len(gainers), '| losers:', len(losers))

    return {
        'companies': all_companies,
        'gainers': gainers,
        'losers': losers,
        'total_companies': len(companies),
        'turnover': fmt_big(turnover) if turnover else "—",
        'volume': f"{volume/1e6:.2f}M" if volume else "—",
        'connected': bool(companies),
    }


def get_market():
    market = cache.get('nepse_market')
    if market:
        return market
    market = load_market()
    if market['connected']:
        cache.set('nepse_market', market, 120)
    return market


@login_required
def dashboard(request):
    index = get_index()
    return render(request, 'market/dashboard.html', {
        'market': get_market(),
        'index': index['latest'],
        'index_candles': index['candles'],
        'index_volumes': index['volumes'],
        'index_intraday': get_index_intraday(),
    })


# ---------- company page ----------

HISTORY_CACHE_SECONDS = 3600     # daily history from NEPSE: 1 hour
INTRADAY_CACHE_SECONDS = 120     # intraday: 2 minutes
SAVE_THROTTLE_SECONDS = 120      # save to the database at most every 2 minutes per company


def fetch_daily_rows(client, security_id, size=500, max_pages=20):
    """Fetch every page of a company's daily history (NEPSE paginates)."""
    all_rows, seen, page = [], set(), 1
    while page <= max_pages:
        data = client.security_price_history(security_id, page=page, size=size)
        rows = extract_rows(data)
        if not rows:
            break

        new = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            key = r.get('businessDate') or id(r)
            if key not in seen:
                seen.add(key)
                all_rows.append(r)
                new += 1
        if new == 0:
            break

        total_pages = data.get('totalPages') if isinstance(data, dict) else None
        if total_pages is not None and page >= int(total_pages):
            break
        if total_pages is None and len(rows) < size:
            break
        page += 1
    return all_rows


def to_candles(rows):
    """Convert daily rows into candlestick and volume lists."""
    by_date = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = pick(r, 'businessDate', 'date')
        c = num(pick(r, 'closePrice', 'lastTradedPrice', 'lastUpdatedPrice'))
        if not d or c is None or c <= 0:
            continue
        o = num(r.get('openPrice')) or c
        h = num(r.get('highPrice')) or max(o, c)
        l = num(r.get('lowPrice')) or min(o, c)
        v = num(r.get('totalTradedQuantity')) or 0
        by_date[str(d)[:10]] = (o, max(h, o, c), min(l, o, c), c, v)

    candles, volumes = [], []
    for d in sorted(by_date):
        o, h, l, c, v = by_date[d]
        candles.append({'time': d, 'open': o, 'high': h, 'low': l, 'close': c})
        volumes.append({
            'time': d,
            'value': v,
            'color': 'rgba(34,197,94,0.5)' if c >= o else 'rgba(239,68,68,0.5)',
        })
    return candles, volumes


def get_history(security_id):
    """Daily candles from NEPSE (about the last year)."""
    if security_id is None:
        return {'candles': [], 'volumes': []}

    key = f'nepse_daily_{security_id}'
    cached = cache.get(key)
    if cached:
        return cached

    result = {'candles': [], 'volumes': []}
    try:
        with NepseClient() as client:
            try:
                rows = fetch_daily_rows(client, security_id)
                candles, volumes = to_candles(rows)
                print(f'security_price_history: {len(rows)} rows -> {len(candles)} candles',
                      (candles[0]['time'], candles[-1]['time']) if candles else '')
                result = {'candles': candles, 'volumes': volumes}
            except Exception as e:
                print('security_price_history failed:', repr(e))

            if len(result['candles']) < 2:  # fallback source
                try:
                    rows = client.company_graph(security_id)
                    candles, volumes = to_candles(rows or [])
                    print(f'company_graph fallback: {len(candles)} candles')
                    result = {'candles': candles, 'volumes': volumes}
                except Exception as e:
                    print('company_graph failed:', repr(e))
    except Exception:
        print('History fetch failed:')
        traceback.print_exc()

    if len(result['candles']) >= 2:
        cache.set(key, result, HISTORY_CACHE_SECONDS)
    return result


def merge_today(history, row):
    """Add (or update) today's live session as the newest candle."""
    candles = list(history['candles'])
    volumes = list(history['volumes'])

    d = str(row.get('businessDate') or '')[:10]
    c = num(pick(row, 'lastUpdatedPrice', 'lastTradedPrice', 'closePrice'))
    if not d or not c:
        return {'candles': candles, 'volumes': volumes}

    o = num(row.get('openPrice')) or c
    h = num(row.get('highPrice')) or max(o, c)
    l = num(row.get('lowPrice')) or min(o, c)
    v = num(row.get('totalTradedQuantity')) or 0

    candle = {'time': d, 'open': o, 'high': max(h, o, c),
              'low': min(l, o, c), 'close': c}
    volume = {'time': d, 'value': v,
              'color': 'rgba(34,197,94,0.5)' if c >= o else 'rgba(239,68,68,0.5)'}

    if candles and candles[-1]['time'] == d:      # today already in history
        candles[-1], volumes[-1] = candle, volume
    elif not candles or d > candles[-1]['time']:  # history is behind today
        candles.append(candle)
        volumes.append(volume)
    return {'candles': candles, 'volumes': volumes}


def get_intraday(security_id):
    """Minute-by-minute prices for the latest trading session."""
    if security_id is None:
        return []

    key = f'nepse_intraday_{security_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    points = []
    try:
        with NepseClient() as client:
            rows = client.company_graph_intraday(security_id)
        points = parse_intraday_rows(rows)
        print('intraday points:', len(points))
    except Exception:
        print('Intraday fetch failed:')
        traceback.print_exc()

    if points:
        cache.set(key, points, INTRADAY_CACHE_SECONDS)
    return points


@login_required
def company_detail(request, symbol):
    symbol = symbol.upper()
    row = get_today_rows().get(symbol)
    if not row:
        raise Http404('Company not found')

    price = num(pick(row, 'lastUpdatedPrice', 'lastTradedPrice', 'closePrice'))
    prev = num(pick(row, 'previousDayClosePrice', 'previousClose'))
    change = (price - prev) / prev * 100 if price is not None and prev else None
    pts = price - prev if price is not None and prev else None

    info = {
        'symbol': symbol,
        'name': pick(row, 'securityName', 'companyName') or symbol,
        'price': fmt_num(price),
        'change': f"{change:+.2f}%" if change is not None else "—",
        'change_pts': f"{pts:+,.2f}" if pts is not None else "—",
        'up': change is not None and change >= 0,
        'open': fmt_num(num(row.get('openPrice'))),
        'high': fmt_num(num(row.get('highPrice'))),
        'low': fmt_num(num(row.get('lowPrice'))),
        'prev': fmt_num(prev),
        'high52': fmt_num(num(row.get('fiftyTwoWeekHigh'))),
        'low52': fmt_num(num(row.get('fiftyTwoWeekLow'))),
        'volume': fmt_num(num(row.get('totalTradedQuantity')), 0),
        'turnover': fmt_big(num(row.get('totalTradedValue')) or 0),
        'trades': fmt_num(num(row.get('totalTrades')), 0),
        'date': row.get('businessDate') or '',
    }

    security_id = row.get('securityId')

    # 1) newest data from NEPSE (last ~year + today's live candle)
    fresh = merge_today(get_history(security_id), row)

    # 2) save it, so history keeps growing and survives NEPSE problems
    safe = ''.join(ch if ch.isalnum() else '_' for ch in symbol)
    skey = 'bars_saved_' + safe
    if fresh['candles'] and not cache.get(skey):
        save_bars(symbol, fresh['candles'], fresh['volumes'])
        cache.set(skey, 1, SAVE_THROTTLE_SECONDS)

    # 3) chart everything stored (falls back to the fresh data if nothing is stored)
    stored = load_bars(symbol)
    history = stored if len(stored['candles']) >= len(fresh['candles']) else fresh

    return render(request, 'market/company.html', {
        'c': info,
        'candles': history['candles'],
        'volumes': history['volumes'],
        'intraday': get_intraday(security_id),
    })


# ---------- sign up ----------

def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = SignUpForm()
    return render(request, 'market/signup.html', {'form': form})