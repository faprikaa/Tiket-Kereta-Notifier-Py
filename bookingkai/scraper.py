"""BookingKAI scraper using curl_cffi to bypass Cloudflare."""

from __future__ import annotations

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
    "sec-ch-ua": '"Not:A-Brand";v="99", "Brave";v="133", "Chromium";v="133"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "sec-gpc": "1",
    "upgrade-insecure-requests": "1",
    "referer": "https://booking.kai.id/",
}


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


async def fetch_trains(
    search_url: str,
    proxy_url: str = "",
) -> list[Train]:
    """Fetch and parse train data from booking.kai.id using curl_cffi.

    Uses browser impersonation to bypass Cloudflare protection.

    Args:
        search_url: The full booking.kai.id search URL
        proxy_url: Optional SOCKS5/HTTP proxy URL

    Returns:
        List of Train objects parsed from the HTML response

    Raises:
        RuntimeError: If blocked by Cloudflare or request fails
    """
    from curl_cffi.requests import AsyncSession

    async with AsyncSession() as session:
        kwargs = {
            "url": search_url,
            "headers": HEADERS,
            "impersonate": "chrome",
            "timeout": 60,
            "allow_redirects": True,
        }

        if proxy_url:
            kwargs["proxy"] = proxy_url

        logger.debug("Fetching booking.kai.id: %s", search_url)

        response = await session.get(**kwargs)

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
        logger.info("BookingKAI fetch successful, trains found: %d", len(trains))
        return trains


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
