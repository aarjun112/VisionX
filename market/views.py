import inspect
import traceback
from datetime import date, timedelta

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from .forms import SignUpForm
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from nepsepy import NepseClient


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
        if price is not None and prev:
            change = (price - prev) / prev * 100

        turnover += num(r.get('totalTradedValue')) or 0
        volume += num(r.get('totalTradedQuantity')) or 0

        companies.append({
            'name': pick(r, 'securityName', 'companyName') or symbol,
            'symbol': symbol,
            'price': fmt_num(price),
            'change': f"{change:+.2f}%" if change is not None else "—",
            'change_val': change,
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
    return render(request, 'market/dashboard.html', {'market': get_market()})


# ---------- company page ----------

SKIP_WORDS = ('index', 'sensitive', 'float', 'sector', 'market', 'trade',
              'floor', 'depth', 'news', 'dividend', 'agm', 'notice')


def history_methods(client):
    """Find client methods that look like a company price history/chart."""
    names = []
    for n in dir(client):
        low = n.lower()
        if n.startswith('_') or not callable(getattr(client, n, None)):
            continue
        if not any(h in low for h in ('history', 'graph', 'chart')):
            continue
        if any(s in low for s in SKIP_WORDS):
            continue
        names.append(n)

    def rank(n):
        low = n.lower()
        if 'price' in low and 'history' in low:
            return 0
        if 'history' in low:
            return 1
        return 2

    return sorted(names, key=rank)


def call_history(client, name, symbol, security_id):
    """Call a history method, filling its parameters by name."""
    fn = getattr(client, name)
    end = date.today()
    start = end - timedelta(days=365)
    kwargs = {}
    for p in inspect.signature(fn).parameters.values():
        pn = p.name.lower()
        if pn in ('symbol', 'stock_symbol', 'ticker'):
            kwargs[p.name] = symbol
        elif pn in ('stock_id', 'security_id', 'securityid', 'company_id',
                    'scrip_id', 'id'):
            kwargs[p.name] = security_id
        elif pn in ('start_date', 'from_date', 'start', 'from_'):
            kwargs[p.name] = start.isoformat()
        elif pn in ('end_date', 'to_date', 'end', 'to'):
            kwargs[p.name] = end.isoformat()
        elif pn == 'page':
            kwargs[p.name] = 1
        elif pn == 'size':
            kwargs[p.name] = 500
        elif p.default is p.empty and p.kind in (p.POSITIONAL_OR_KEYWORD,
                                                  p.KEYWORD_ONLY):
            kwargs[p.name] = security_id if 'id' in pn else symbol
    return fn(**kwargs)


def to_candles(rows):
    """Convert history rows into candlestick and volume lists."""
    by_date = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = pick(r, 'businessDate', 'date', 'tradeDate')
        c = num(pick(r, 'closePrice', 'close', 'lastUpdatedPrice', 'lastTradedPrice'))
        if not d or c is None:
            continue
        o = num(pick(r, 'openPrice', 'open')) or c
        h = num(pick(r, 'highPrice', 'high', 'maxPrice')) or max(o, c)
        l = num(pick(r, 'lowPrice', 'low', 'minPrice')) or min(o, c)
        v = num(pick(r, 'totalTradedQuantity', 'volume', 'totalTradeQuantity')) or 0
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


def get_history(symbol, security_id):
    key = 'nepse_hist_' + ''.join(ch if ch.isalnum() else '_' for ch in symbol)
    cached = cache.get(key)
    if cached:
        return cached

    result = {'candles': [], 'volumes': []}
    try:
        with NepseClient() as client:
            methods = history_methods(client)
            print('History methods found:', methods)
            for name in methods:
                try:
                    data = call_history(client, name, symbol, security_id)
                    rows = extract_rows(data)
                    print(f'{name}: {len(rows)} rows | sample:',
                          rows[0] if rows else None)
                    candles, volumes = to_candles(rows)
                    if len(candles) >= 2:
                        result = {'candles': candles, 'volumes': volumes}
                        print(f'Using {name}: {len(candles)} candles')
                        break
                except Exception as e:
                    print(f'{name} failed:', repr(e))
    except Exception:
        print('History fetch failed:')
        traceback.print_exc()

    if result['candles']:
        cache.set(key, result, 600)
    return result


@login_required
def company_detail(request, symbol):
    symbol = symbol.upper()
    row = get_today_rows().get(symbol)
    if not row:
        raise Http404('Company not found')

    price = num(pick(row, 'lastUpdatedPrice', 'lastTradedPrice', 'closePrice'))
    prev = num(pick(row, 'previousDayClosePrice', 'previousClose'))
    change = (price - prev) / prev * 100 if price is not None and prev else None

    info = {
        'symbol': symbol,
        'name': pick(row, 'securityName', 'companyName') or symbol,
        'price': fmt_num(price),
        'change': f"{change:+.2f}%" if change is not None else "—",
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

    history = get_history(symbol, row.get('securityId'))
    return render(request, 'market/company.html', {
        'c': info,
        'candles': history['candles'],
        'volumes': history['volumes'],
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