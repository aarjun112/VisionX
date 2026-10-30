from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .views import get_today_rows, num, pick, fmt_num
from .watchlist_models import WatchlistItem


def _next_url(request, default):
    """Where to go after add/remove (only on this site)."""
    nxt = request.POST.get('next', '')
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return default


@login_required
def watchlist(request):
    rows = get_today_rows()

    # only this user's items
    mine = list(WatchlistItem.objects.filter(user=request.user))
    saved = {it.symbol for it in mine}

    items = []
    for it in mine:
        r = rows.get(it.symbol)
        entry = {'symbol': it.symbol, 'name': it.symbol, 'price': '—',
                 'change': '—', 'change_pts': '—', 'up': True, 'found': False}
        if r:
            price = num(pick(r, 'lastUpdatedPrice', 'lastTradedPrice', 'closePrice'))
            prev = num(pick(r, 'previousDayClosePrice', 'previousClose'))
            entry.update({
                'name': pick(r, 'securityName', 'companyName') or it.symbol,
                'price': fmt_num(price),
                'found': True,
            })
            if price is not None and prev:
                pct = (price - prev) / prev * 100
                entry.update({
                    'change': f"{pct:+.2f}%",
                    'change_pts': f"{price - prev:+,.2f}",
                    'up': pct >= 0,
                })
        items.append(entry)

    companies = [
        {'symbol': s,
         'name': pick(r, 'securityName', 'companyName') or s,
         'saved': s in saved}
        for s, r in sorted(rows.items())
    ]

    return render(request, 'market/watchlist.html', {
        'items': items,
        'companies': companies,
    })


@login_required
@require_POST
def watchlist_add(request):
    symbol = request.POST.get('symbol', '').strip().upper()
    if symbol and symbol in get_today_rows():
        WatchlistItem.objects.get_or_create(user=request.user, symbol=symbol)
    return redirect(_next_url(request, reverse('watchlist')))


@login_required
@require_POST
def watchlist_remove(request):
    symbol = request.POST.get('symbol', '').strip().upper()
    WatchlistItem.objects.filter(user=request.user, symbol=symbol).delete()
    return redirect(_next_url(request, reverse('watchlist')))