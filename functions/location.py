import json
from urllib.request import Request, urlopen


_USER_AGENT = "Mozilla/5.0"
_TIMEOUT_SECONDS = 5


def _fetch_json(url: str):
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def get_location_details():

    """Return rough IP-based location details as a dictionary."""

    providers = [
        # provider 1: ipapi.co
        (
            "https://ipapi.co/json/",
            lambda payload: {
                "city": payload.get("city") or "不明",
                "region": payload.get("region") or "",
                "country": payload.get("country_name") or payload.get("country") or "",
                "latitude": _to_float(payload.get("latitude")),
                "longitude": _to_float(payload.get("longitude")),
            },
        ),
        # provider 2: ipwho.is
        (
            "https://ipwho.is/",
            lambda payload: {
                "city": payload.get("city") or "不明",
                "region": payload.get("region") or payload.get("region_name") or "",
                "country": payload.get("country") or "",
                "latitude": _to_float(payload.get("latitude")),
                "longitude": _to_float(payload.get("longitude")),
            },
        ),
        # provider 3: ipinfo.io (loc="lat,lon")
        (
            "https://ipinfo.io/json",
            lambda payload: {
                "city": payload.get("city") or "不明",
                "region": payload.get("region") or "",
                "country": payload.get("country") or "",
                "latitude": _to_float((payload.get("loc") or ",").split(",", 1)[0]),
                "longitude": _to_float((payload.get("loc") or ",").split(",", 1)[1]),
            },
        ),
    ]

    for url, parser in providers:
        try:
            payload = _fetch_json(url)
            details = parser(payload)
            if details.get("city") or details.get("country"):
                return details
        except Exception:
            continue

    return None


def get_current_location():

    """Return a rough current location based on public IP geolocation.

    Falls back to a fixed placeholder when the network lookup fails.
    """

    details = get_location_details()

    if details:

        pieces = [piece for piece in [details.get("city"), details.get("region"), details.get("country")] if piece]
        if pieces:
            return "現在地の推定: " + " / ".join(pieces)

    return "現在地の推定: 取得できませんでした。ネットワーク接続を確認してください。"