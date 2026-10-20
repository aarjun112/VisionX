from django.core.cache import cache
from django.shortcuts import render
from nepsepy import NepseClient


def pick(row, *keys):
    """Return the first non-empty value among several possible key names."""
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


def load_market():
    client = NepseClient()
    data = client.today_price()

    # Find the list of stock rows, whatever shape the library returns
    if isinstance(data, dict):
        print('today_price keys:', list(data.keys()))
        rows = data.get('content') or data.get('data') or []
        if not rows:
            rows = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        rows = data or []

    if rows:
        print('sample row:', rows[0])

    companies, turnover, volume = [], 0.0, 0.0
    for r in rows:
        symbol = pick(r, 'symbol', 'stockSymbol')
        if not symbol:
            continue
        price = num(pick(r, 'lastTradedPrice', 'lastUpdatedPrice', 'closePrice', 'ltp'))
        prev = num(pick(r, 'previousClose', 'previousDayClosePrice'))
        change = num(pick(r, 'percentageChange', 'percentChange'))
        if change is None and price is not None and prev:
            change = (price - prev) / prev * 100

        turnover += num(pick(r, 'totalTradedValue', 'turnover')) or 0
        volume += num(pick(r, 'totalTradedQuantity', 'volume')) or 0

        companies.append({
            'name': pick(r, 'securityName', 'companyName', 'name') or symbol,
            'symbol': symbol,
            'price': f"{price:,.2f}" if price is not None else "—",
            'change': f"{change:+.2f}%" if change is not None else "—",
            'up': change is not None and change >= 0,
        })

    companies.sort(key=lambda c: c['symbol'])
    return {
        'companies': companies,
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
    except Exception as e:
        print('NEPSE fetch failed:', repr(e))
        market = {'companies': [], 'turnover': '—', 'volume': '—', 'connected': False}
    if market['connected']:
        cache.set('nepse_market', market, 60)
    return market


def dashboard(request):
    return render(request, 'market/dashboard.html', {'market': get_market()})