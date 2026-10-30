from datetime import date

from django.core.management.base import BaseCommand
from nepsepy import NepseClient

from market import views
from market.models import DailyBar


class Command(BaseCommand):
    help = "Try to download older history, one year at a time, and store it."

    def add_arguments(self, parser):
        parser.add_argument('symbol', help='for example NABIL')
        parser.add_argument('--from-year', type=int, default=2010)

    def handle(self, *args, **opts):
        sym = opts['symbol'].upper()
        today_rows = views.get_today_rows()
        row = today_rows.get(sym)
        if not row:
            self.stderr.write(f'{sym} not found.')
            return
        security_id = row.get('securityId')

        first = DailyBar.objects.filter(symbol=sym).order_by('date').first()
        cutoff = first.date.isoformat() if first else None
        today = date.today()

        found = {}
        with NepseClient() as client:
            for year in range(opts['from_year'], today.year + 1):
                start = f'{year}-01-01'
                end = today.isoformat() if year == today.year else f'{year}-12-31'
                page, got = 1, 0
                while page <= 20:
                    try:
                        data = client.stock_trading_history(
                            security_id, page=page, size=500, start=start, end=end)
                    except Exception as e:
                        self.stderr.write(f'{year}: failed {e!r}')
                        break
                    items = views.extract_rows(data)
                    if not items:
                        break
                    for r in items:
                        d = str(r.get('businessDate') or '')[:10]
                        close = views.num(r.get('closePrice'))
                        if not d or not close or close <= 0:
                            continue
                        found[d] = (
                            close,
                            views.num(r.get('highPrice')) or close,
                            views.num(r.get('lowPrice')) or close,
                            views.num(r.get('totalTradedQuantity')) or 0,
                        )
                    got += len(items)
                    total = data.get('totalPages') if isinstance(data, dict) else None
                    if total is None or page >= int(total):
                        break
                    page += 1
                self.stdout.write(f'{year}: {got} rows')

        if not found:
            self.stdout.write('NEPSE returned no history at all.')
            return

        dates = sorted(found)
        self.stdout.write(f'Found {len(dates)} days: {dates[0]} -> {dates[-1]}')

        # this source has no open price, so each day opens at the previous close
        candles, volumes, prev_close = [], [], None
        for d in dates:
            close, high, low, vol = found[d]
            open_ = prev_close if prev_close else close
            high, low = max(high, open_, close), min(low, open_, close)
            prev_close = close
            if cutoff and d >= cutoff:      # keep the real data already stored
                continue
            candles.append({'time': d, 'open': open_, 'high': high,
                            'low': low, 'close': close})
            volumes.append({'time': d, 'value': vol, 'color': ''})

        views.save_bars(sym, candles, volumes)
        self.stdout.write(self.style.SUCCESS(
            f'{sym}: saved {len(candles)} older days.'))