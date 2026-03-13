import asyncio
import aiohttp
import json
import time

async def test():
    async with aiohttp.ClientSession() as session:
        # Test 1: Events endpoint
        url = "https://gamma-api.polymarket.com/events?limit=5&active=true&closed=false"
        async with session.get(url) as resp:
            data = await resp.json()
            print("Events endpoint sample:")
            if data:
                print(json.dumps(data[0].get('title', 'No title')))
        
        # Test 2: Slug calculation
        now = int(time.time())
        period_start = (now // 900) * 900
        slug = f"btc-updown-15m-{period_start}"
        print(f"\nTesting slug: {slug}")
        url_slug = f"https://gamma-api.polymarket.com/events?slug={slug}"
        async with session.get(url_slug) as resp:
            data = await resp.json()
            if data:
                print("Found slug market!")
                print(json.dumps(data[0].get('title', 'No title')))
                if 'markets' in data[0]:
                    print("Markets in event:")
                    for m in data[0]['markets']:
                        print(f" - {m.get('question')} (Token: {m.get('clobTokenIds', [''])[0]})")
            else:
                print("Slug not found or empty.")

asyncio.run(test())
