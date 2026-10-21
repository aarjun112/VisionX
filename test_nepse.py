from nepsepy import NepseClient

with NepseClient() as client:
    for size in (500, 100, 20):
        try:
            data = client.today_price(page=1, size=size)
            rows = data.get('content', []) if isinstance(data, dict) else data
            print(f"size={size}: OK, {len(rows)} rows")
            if rows:
                print(rows[0])
            if isinstance(data, dict):
                print({k: v for k, v in data.items() if k != 'content'})
            break
        except Exception as e:
            print(f"size={size}: FAILED -> {e!r}")