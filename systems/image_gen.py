import aiohttp
from urllib.parse import quote
from config import POLLINATIONS_URL


async def generate_image(prompt: str):
    try:
        encoded = quote(f"medieval fantasy {prompt}, dark atmospheric, oil painting, highly detailed")
        url = POLLINATIONS_URL.format(prompt=encoded)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return url
    except Exception:
        pass
    return None

