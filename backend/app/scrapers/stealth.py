"""Stealth helpers to reduce bot-detection risk when using Playwright."""
from __future__ import annotations

import random

# BrowserContext and Page imported lazily so this module doesn't require
# Playwright to be installed when only random_user_agent() is used.
try:
    from playwright.async_api import BrowserContext, Page
except ImportError:
    BrowserContext = None  # type: ignore[assignment,misc]
    Page = None  # type: ignore[assignment,misc]

# Pool of realistic desktop user agents
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

# JS injected before every page load to hide automation fingerprints
_STEALTH_SCRIPT = """
() => {
    // Hide webdriver property
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Fake plugins list
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Fake languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['es-PE', 'es', 'en-US', 'en'],
    });

    // Stub chrome runtime so the site thinks it's a real Chrome
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };

    // Prevent permission fingerprinting
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(p);
}
"""


def random_user_agent() -> str:
    return random.choice(_USER_AGENTS)


def random_viewport() -> dict[str, int]:
    widths = [1280, 1366, 1440, 1536, 1920]
    w = random.choice(widths)
    return {"width": w, "height": int(w * 0.5625)}  # 16:9 ratio


async def apply_stealth(context: BrowserContext) -> None:
    """Inject stealth script and set realistic extra HTTP headers."""
    await context.add_init_script(_STEALTH_SCRIPT)
    await context.set_extra_http_headers({
        "Accept-Language": "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    })


async def human_delay(page: Page, min_ms: int = 1500, max_ms: int = 4000) -> None:
    """Random delay to mimic human browsing pace."""
    await page.wait_for_timeout(random.randint(min_ms, max_ms))
