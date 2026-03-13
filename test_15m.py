import asyncio
import aiohttp
import time
import json

async def test():
    now = int(time.time())
    period_start = (now // 900) * 900
    
    # Check current, previous, and next periods to see what's active
    periods = [
        ("Previous", period_start - 900),
        ("Current", period_start),
        ("Next", period_start + 900)
    ]
    
    async with aiohttp.ClientSession() as session:
        for name, ts in periods:
            slug = f"btc-updown-15m-{ts}"
            url = f"https://gamma-api.polymarket.com/events?slug={slug}"
            print(f"\nTesting {name} ({slug}):")
            async with session.get(url) as resp:
                data = await resp.json()
                if data:
                    print(f"Found! Title: {data[0].get('title')}")
                    print(f"Active: {data[0].get('active')}, Closed: {data[0].get('closed')}")
                    if 'markets' in data[0] and data[0]['markets']:
                        m = data[0]['markets'][0]
                        print(f"Market Active: {m.get('active')}, Closed: {m.get('closed')}")
                        print(f"End Date: {m.get('endDate')}")
                else:
                    print("Not found")

asyncio.run(test())
