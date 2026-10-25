import inspect
from nepsepy import NepseClient

SYMBOL = 'NABIL'

with NepseClient() as client:
    data = client.today_price(page=1, size=500)
    sec_id = next(r['securityId'] for r in data['content'] if r['symbol'] == SYMBOL)
    print('securityId for', SYMBOL, '=', sec_id)

    for name in dir(client):
        low = name.lower()
        if name.startswith('_') or not callable(getattr(client, name)):
            continue
        if not any(h in low for h in ('history', 'graph', 'chart')):
            continue

        fn = getattr(client, name)
        print('\n==', name, inspect.signature(fn))
        kwargs = {}
        for p in inspect.signature(fn).parameters.values():
            pn = p.name.lower()
            if pn in ('symbol', 'stock_symbol', 'ticker'):
                kwargs[p.name] = SYMBOL
            elif pn in ('stock_id', 'security_id', 'securityid', 'company_id', 'scrip_id', 'id'):
                kwargs[p.name] = sec_id
            elif pn in ('start_date', 'from_date', 'start', 'from_'):
                kwargs[p.name] = '2010-01-01'
            elif pn in ('end_date', 'to_date', 'end', 'to'):
                kwargs[p.name] = '2026-10-24'
            elif pn == 'page':
                kwargs[p.name] = 1
            elif pn == 'size':
                kwargs[p.name] = 500
            elif p.default is p.empty:
                kwargs[p.name] = sec_id if 'id' in pn else SYMBOL
        try:
            out = fn(**kwargs)
            if isinstance(out, dict):
                print('keys:', list(out.keys()))
                print({k: v for k, v in out.items() if k in ('totalPages', 'totalElements', 'size')})
                rows = out.get('content') or next((v for v in out.values() if isinstance(v, list)), [])
            else:
                rows = out
            print('rows:', len(rows))
            if rows:
                print('first:', rows[0])
                print('last: ', rows[-1])
        except Exception as e:
            print('FAILED:', repr(e))