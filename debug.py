import requests, re

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "DNT": "1"})

uuid_re = re.compile(r"/(?:en/)?buy/opportunity/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})")
base = "https://www.aqarexit.com/en/opportunities?areas=%D8%A7%D9%84%D8%AA%D8%AC%D9%85%D8%B9+%D8%A7%D9%84%D8%AE%D8%A7%D9%85%D8%B3&beds=3"

all_uuids = set()
for page in range(1, 10):
    url = base if page == 1 else f"{base}&page={page}"
    r = s.get(url, timeout=20)
    uuids = uuid_re.findall(r.text)
    new = [u for u in uuids if u not in all_uuids]
    all_uuids.update(uuids)
    print(f"Page {page}: {len(uuids)} total, {len(new)} new | running total: {len(all_uuids)}")
    if not uuids or not new:
        break
    import time; time.sleep(2)