from django.core.management.base import BaseCommand
from nepsepy import NepseClient

from market import views


class Command(BaseCommand):
    help = "Download daily history from NEPSE and store it in the database."

    def add_arguments(self, parser):
        parser.add_argument('--symbol', help='Only this symbol, for example NABIL')

    def handle(self, *args, **opts):
        rows = views.get_today_rows()
        if not rows:
            self.stderr.write('Could not load the company list from NEPSE.')
            return

        if opts['symbol']:
            sym = opts['symbol'].upper()
            if sym not in rows:
                self.stderr.write(f'{sym} not found.')
                return
            symbols = [sym]
        else:
            symbols = sorted(rows)

        total = len(symbols)
        with NepseClient() as client:
            # the NEPSE index first
            try:
                idx_rows = views.fetch_index_rows(client)
                candles, volumes, _ = views.index_to_candles(idx_rows)
                views.save_bars(views.INDEX_SYMBOL, candles, volumes)
                self.stdout.write(f'NEPSE index: {len(candles)} days saved')
            except Exception as e:
                self.stderr.write(f'NEPSE index failed: {e!r}')

            for i, sym in enumerate(symbols, 1):
                row = rows[sym]
                try:
                    data = views.fetch_daily_rows(client, row.get('securityId'))
                    candles, volumes = views.to_candles(data)
                    merged = views.merge_today(
                        {'candles': candles, 'volumes': volumes}, row)
                    views.save_bars(sym, merged['candles'], merged['volumes'])
                    self.stdout.write(f'[{i}/{total}] {sym}: {len(merged["candles"])} days')
                except Exception as e:
                    self.stderr.write(f'[{i}/{total}] {sym} failed: {e!r}')

        self.stdout.write(self.style.SUCCESS('Done.'))