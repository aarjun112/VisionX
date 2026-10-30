from django import template

from market.watchlist_models import WatchlistItem

register = template.Library()


@register.simple_tag
def in_watchlist(user, symbol):
    if not user.is_authenticated:
        return False
    return WatchlistItem.objects.filter(user=user, symbol=symbol).exists()