import csv
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from market import views

ALIASES = {
    'date':   ['date', 'businessdate', 'business date', 'time', 'day'],
    'open':   ['open', 'openprice', 'open price'],
    'high':   ['high', 'highprice', 'high price', 'maxprice', 'max price'],
    'low':    ['low', 'lowprice', 'low price', 'minprice', 'min price'],
    'close':  ['close', 'closeprice', 'close price', 'ltp', 'last traded price'],
    'volume': ['volume', 'vol', 'qty', 'traded quantity', 'totaltradedquantity'],
}
DATE_FORMATS = ['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y']


def to_float(text):
    try:
        return float(str(text).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def to_date(text):
    text = str(text).strip()[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class Command(BaseCommand):
    help = "Import daily prices from a CSV file: date, open, high, low, close, volume."

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='Path to the CSV file')
        parser.add_argument('symbol', help='Symbol the file belongs to, for example NABIL')

    def handle(self, *args, **opts):
        symbol = opts['symbol'].upper()
        try:
            f = open(opts['csv_path'], newline='', encoding='utf-8-sig')
        except OSError as e:
            raise CommandError(f'Cannot open file: {e}')

        with f:
            reader = csv.DictReader(f)
            headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}

            def col(name):
                for alias in ALIASES[name]:
                    if alias in headers:
                        return headers[alias]
                return None

            c_date, c_close = col('date'), col('close')
            if not c_date or not c_close:
                raise CommandError('The CSV needs at least a date column and a close column.')
            c_open, c_high, c_low, c_vol = col('open'), col('high'), col('low'), col('volume')

            candles, volumes, skipped = [], [], 0
            for r in reader:
                d = to_date(r.get(c_date))
                close = to_float(r.get(c_close))
                if not d or not close or close <= 0:
                    skipped += 1
                    continue
                o = to_float(r.get(c_open)) if c_open else None
                h = to_float(r.get(c_high)) if c_high else None
                l = to_float(r.get(c_low)) if c_low else None
                o = o or close
                h = max(h or close, o, close)
                l = min(l or close, o, close)
                v = (to_float(r.get(c_vol)) if c_vol else 0) or 0
                candles.append({'time': d, 'open': o, 'high': h, 'low': l, 'close': close})
                volumes.append({'time': d, 'value': v, 'color': ''})

        views.save_bars(symbol, candles, volumes)
        self.stdout.write(self.style.SUCCESS(
            f'{symbol}: imported {len(candles)} days, skipped {skipped} rows.'))