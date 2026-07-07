import httpx, json, asyncio
from bs4 import BeautifulSoup

async def fetch():
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=30) as c:
        for page in range(1, 6):
            url = f"https://www.falabella.com.pe/falabella-pe/category/cat7180470/Lavadora-Secadora?currentPage={page}"
            r = await c.get(url)
            soup = BeautifulSoup(r.content, "html.parser")
            tag = soup.find("script", id="__NEXT_DATA__")
            if not tag:
                break
            data = json.loads(tag.string)
            results = data.get("props", {}).get("pageProps", {}).get("results") or []
            if not results:
                print(f"Pag {page}: sin resultados")
                break
            print(f"Pag {page}: {len(results)} productos")
            for item in results:
                badge = (item.get("discountBadge") or {}).get("label", "") or ""
                pct = int(badge.replace("-", "").replace("%", "")) if badge else 0
                name = item.get("displayName", "")
                brand = item.get("brand", "")
                if "indurama" in name.lower() or "lri" in name.lower() or pct >= 60:
                    prices = item.get("prices") or []
                    stickers = item.get("meatStickers") or []
                    print(f"  [{brand}] {name} | {badge} | stickers={len(stickers)}")
                    for p in prices:
                        print(f"    type={p.get('type')} price={p.get('price')} crossed={p.get('crossed')}")

asyncio.run(fetch())
