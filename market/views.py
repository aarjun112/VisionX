import traceback

from django.core.cache import cache
from django.shortcuts import render
from nepsepy import NepseClient


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


def extract_rows(data):
    if isinstance(data, dict):
        rows = data.get('content') or data.get('data') or []
        if not rows:
            rows = next((v for v in data.values() if isinstance(v, list)), [])
        return rows
    return data or []


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
    with NepseClient() as client:
        data = client.today_price(page=1, size=500)
    rows = extract_rows(data)
    print('NEPSE rows received:', len(rows))

    companies, turnover, volume = [], 0.0, 0.0
    for r in rows:
        symbol = pick(r, 'symbol', 'stockSymbol')
        if not symbol:
            continue

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
            'price': f"{price:,.2f}" if price is not None else "—",
            'change': f"{change:+.2f}%" if change is not None else "—",
            'change_val': change,
            'up': change is not None and change >= 0,
        })

    gainers, losers = tops(companies, 15)
    print('companies loaded:', len(companies),
          '| gainers:', len(gainers), '| losers:', len(losers))

    return {
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

    try:
        market = load_market()
        if market['connected']:
            cache.set('nepse_market', market, 120)          # fresh for 2 minutes
            cache.set('nepse_market_stale', market, 86400)  # fallback for a day
            return market
    except Exception:
        print('NEPSE fetch failed:')
        traceback.print_exc()

    stale = cache.get('nepse_market_stale')
    if stale:
        return stale
    return {
        'gainers': [], 'losers': [], 'total_companies': 0,
        'turnover': '—', 'volume': '—', 'connected': False,
    }


def dashboard(request):
    return render(request, 'market/dashboard.html', {'market': get_market()})