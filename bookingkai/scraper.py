"""BookingKAI scraper with Cloudflare bypass.

Primary: curl_cffi with browser impersonation and persistent session cookies.
Fallback: nodriver (undetected Chrome via CDP) when Cloudflare blocks curl_cffi.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from bs4 import BeautifulSoup

from models import Train
from utils import format_number

logger = logging.getLogger(__name__)

# Indonesian month names for date formatting
MONTH_NAMES = [
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]

# Request headers mimicking a real browser
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "sec-gpc": "1",
    "upgrade-insecure-requests": "1",
    "referer": "https://booking.kai.id/",
}

# ---------- Shared state for nodriver browser ----------
_nodriver_browser = None
_nodriver_lock = asyncio.Lock()


def format_date_indo(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' to 'DD-Month-YYYY' (Indonesian month names).
    e.g. '2026-04-02' -> '02-April-2026'
    """
    from datetime import datetime

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month = MONTH_NAMES[dt.month]
    return f"{dt.day:02d}-{month}-{dt.year}"


def build_search_url(origin: str, destination: str, date: str) -> str:
    """Build the booking.kai.id search URL.

    Args:
        origin: Station code (e.g. 'PSE')
        destination: Station code (e.g. 'LPN')
        date: Date in YYYY-MM-DD format
    """
    date_indo = format_date_indo(date)
    return (
        f"https://booking.kai.id/"
        f"?origination={origin}"
        f"&destination={destination}"
        f"&tanggal={quote(date_indo)}"
        f"&adult=1&infant=0"
        f"&submit=Cari+%26+Pesan+Tiket"
    )


def is_cloudflare_challenge(html_content: str) -> bool:
    """Check if the HTML indicates a Cloudflare challenge page."""
    markers = [
        "cf_chl_opt",
        "challenge-platform",
        "Just a moment",
        "cf-browser-verification",
    ]
    return any(marker in html_content for marker in markers)


# ========== Primary: curl_cffi with persistent session ==========

async def _fetch_with_curl_cffi(
    search_url: str,
    proxy_url: str = "",
) -> list[Train]:
    """Fetch trains using curl_cffi with browser impersonation.

    Uses a persistent session to maintain cookies across requests.
    First visits the homepage to obtain cf_clearance cookies, then
    hits the search URL.
    """
    from curl_cffi.requests import AsyncSession

    async with AsyncSession(impersonate="chrome") as session:
        base_kwargs: dict = {
            "headers": HEADERS,
            "timeout": 60,
            "allow_redirects": True,
        }
        if proxy_url:
            base_kwargs["proxy"] = proxy_url

        # Step 1: Visit homepage to establish cookies / pass initial CF check
        logger.debug("curl_cffi: visiting homepage for cookies...")
        try:
            home_resp = await session.get(
                "https://booking.kai.id/", **base_kwargs
            )
            if home_resp.status_code == 200 and not is_cloudflare_challenge(home_resp.text):
                logger.debug("curl_cffi: homepage OK, cookies obtained")
            else:
                logger.debug(
                    "curl_cffi: homepage returned CF challenge or non-200 (%s)",
                    home_resp.status_code,
                )
        except Exception as e:
            logger.debug("curl_cffi: homepage visit failed: %s", e)

        # Step 2: Fetch the search results
        logger.debug("curl_cffi: fetching search URL: %s", search_url)
        response = await session.get(url=search_url, **base_kwargs)
        html_content = response.text

        # Check for Cloudflare blocks
        if response.status_code == 403 or is_cloudflare_challenge(html_content):
            raise RuntimeError(
                f"Blocked by Cloudflare (status {response.status_code})"
            )

        if "cfwaitingroom" in html_content or "Waiting Room" in html_content:
            raise RuntimeError("Blocked by Cloudflare Waiting Room")

        if response.status_code != 200:
            raise RuntimeError(f"Unexpected status code: {response.status_code}")

        trains = parse_html(html_content)
        logger.info("curl_cffi: fetch successful, trains found: %d", len(trains))
        return trains


# ========== Fallback: nodriver (headless Chrome via CDP) ==========

async def _get_nodriver_browser():
    """Get or create the shared nodriver browser instance."""
    global _nodriver_browser

    async with _nodriver_lock:
        if _nodriver_browser is not None and not _nodriver_browser.stopped:
            return _nodriver_browser

        try:
            import nodriver as uc
        except ImportError:
            raise RuntimeError(
                "nodriver is not installed. Install with: pip install nodriver"
            )

        logger.info("nodriver: starting headless Chrome browser...")
        _nodriver_browser = await uc.start(
            headless=True,
            browser_args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
        )
        return _nodriver_browser


async def close_nodriver_browser() -> None:
    """Close the shared nodriver browser (for cleanup)."""
    global _nodriver_browser

    async with _nodriver_lock:
        if _nodriver_browser is not None:
            try:
                _nodriver_browser.stop()
            except Exception:
                pass
            _nodriver_browser = None
            logger.info("nodriver: browser closed")


async def _fetch_with_nodriver(search_url: str) -> list[Train]:
    """Fetch trains using nodriver (undetected headless Chrome).

    This can solve Cloudflare JS challenges since it runs a real browser.
    """
    browser = await _get_nodriver_browser()

    logger.info("nodriver: navigating to %s", search_url)
    tab = await browser.get(search_url)

    # Wait for page to load and any CF challenge to resolve
    await tab.sleep(5)

    # Try verify_cf() in case there's a Turnstile challenge
    try:
        await tab.verify_cf()
        await tab.sleep(3)
    except Exception:
        pass  # No CF challenge present, that's fine

    # Wait and ensure the page is loaded
    await tab

    html_content = await tab.get_content()

    # Close the tab to free resources (keep browser alive)
    try:
        await tab.close()
    except Exception:
        pass

    # Verify we got past Cloudflare
    if is_cloudflare_challenge(html_content):
        raise RuntimeError("nodriver: still blocked by Cloudflare after challenge")

    trains = parse_html(html_content)
    logger.info("nodriver: fetch successful, trains found: %d", len(trains))
    return trains


# ========== Public API ==========

async def fetch_trains(
    search_url: str,
    proxy_url: str = "",
) -> list[Train]:
    """Fetch and parse train data from booking.kai.id.

    Strategy:
    1. Try curl_cffi with browser impersonation (fast, lightweight)
    2. If blocked by Cloudflare, fall back to nodriver (headless Chrome)

    Args:
        search_url: The full booking.kai.id search URL
        proxy_url: Optional SOCKS5/HTTP proxy URL

    Returns:
        List of Train objects parsed from the HTML response

    Raises:
        RuntimeError: If both methods fail
    """
    # --- Primary: curl_cffi ---
    try:
        return await _fetch_with_curl_cffi(search_url, proxy_url)
    except RuntimeError as e:
        if "Cloudflare" in str(e):
            logger.warning(
                "curl_cffi blocked by Cloudflare, falling back to nodriver: %s", e
            )
        else:
            raise

    # --- Fallback: nodriver ---
    try:
        return await _fetch_with_nodriver(search_url)
    except Exception as e:
        raise RuntimeError(
            f"Both curl_cffi and nodriver failed. Last error: {e}"
        ) from e


# ========== HTML Parsing ==========

def parse_html(raw_html: str) -> list[Train]:
    """Extract train information from the booking.kai.id search results page.

    Looks for div elements with classes 'data-block list-kereta', then
    extracts train data from hidden input fields and availability indicators.
    """
    soup = BeautifulSoup(raw_html, "lxml")
    trains: list[Train] = []

    # Find all data-block list-kereta divs
    data_blocks = soup.find_all("div", class_=lambda c: c and "data-block" in c and "list-kereta" in c)

    for block in data_blocks:
        train = extract_train_from_block(block)
        if train.name:
            trains.append(train)

    return trains


def extract_train_from_block(block) -> Train:
    """Extract train data from a data-block div.

    Reads hidden inputs for train details and checks availability
    via CSS classes and text content.
    """
    # Collect all hidden input values
    inputs: dict[str, str] = {}
    for inp in block.find_all("input", type="hidden"):
        name = inp.get("name", "")
        value = inp.get("value", "")
        if name:
            inputs[name] = value

    # Determine availability
    availability = "AVAILABLE"
    seats_left = "1"

    # Check for <a class="habis"> (sold out link)
    habis_link = block.find("a", class_=lambda c: c and "habis" in c)
    if habis_link:
        availability = "FULL"
        seats_left = "0"

    # Check for <small class="sisa-kursi"> text
    sisa_kursi = block.find("small", class_=lambda c: c and "sisa-kursi" in c)
    if sisa_kursi:
        text = sisa_kursi.get_text(strip=True)
        if text == "Habis":
            availability = "FULL"
            seats_left = "0"
        elif text == "Tersedia":
            availability = "AVAILABLE"
            seats_left = "1"  # KAI doesn't show exact count

    # Build class string from kelas_gerbong + subkelas
    class_str = inputs.get("kelas_gerbong", "")
    sub = inputs.get("subkelas", "")
    if sub:
        class_str += f" ({sub})"

    # Format price
    price = inputs.get("harga", "")
    if price:
        price = f"Rp{format_number(price)}"

    return Train(
        name=inputs.get("kereta", ""),
        class_=class_str,
        price=price,
        departure_time=inputs.get("timestart", ""),
        arrival_time=inputs.get("timeend", ""),
        availability=availability,
        seats_left=seats_left,
    )
