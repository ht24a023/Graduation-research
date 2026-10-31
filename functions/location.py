"""現在地の推定や位置情報の取得を行う関数群で、天気や経路案内の精度を上げます。"""

import json
import os
import time
from urllib.request import Request, urlopen


_USER_AGENT = "Mozilla/5.0"
_TIMEOUT_SECONDS = 5
_CACHE_TTL_SECONDS = max(0, int(os.getenv("LOCATION_CACHE_TTL_SECONDS", "300")))
_LOCATION_CACHE: dict[str, object] = {
    "details": None,
    "expires_at": 0.0,
}


def _fetch_json(url: str):
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _parse_ipapi(payload):
    return {
        "city": payload.get("city") or "不明",
        "region": payload.get("region") or "",
        "country": payload.get("country_name") or payload.get("country") or "",
        "latitude": _to_float(payload.get("latitude")),
        "longitude": _to_float(payload.get("longitude")),
    }


def _parse_ipwho(payload):
    if payload.get("success") is False:
        return None
    return {
        "city": payload.get("city") or "不明",
        "region": payload.get("region") or payload.get("region_name") or "",
        "country": payload.get("country") or "",
        "latitude": _to_float(payload.get("latitude")),
        "longitude": _to_float(payload.get("longitude")),
    }


def _parse_ipinfo(payload):
    raw_loc = payload.get("loc") or ","
    lat_str, lon_str = raw_loc.split(",", 1)
    return {
        "city": payload.get("city") or "不明",
        "region": payload.get("region") or "",
        "country": payload.get("country") or "",
        "latitude": _to_float(lat_str),
        "longitude": _to_float(lon_str),
    }


def _cache_valid() -> bool:
    if _CACHE_TTL_SECONDS <= 0:
        return False
    return bool(_LOCATION_CACHE.get("details")) and float(_LOCATION_CACHE.get("expires_at") or 0.0) > time.time()


def _cache_get():
    details = _LOCATION_CACHE.get("details")
    if isinstance(details, dict):
        return dict(details)
    return None


def _cache_set(details):
    if not isinstance(details, dict):
        return
    _LOCATION_CACHE["details"] = dict(details)
    _LOCATION_CACHE["expires_at"] = time.time() + _CACHE_TTL_SECONDS


def get_location_details(use_cache: bool = True):

    """Return a rough, non-exact IP-based location estimate.

    This result is only an approximation from public IP geo-location and may be wrong.
    When the user provides a more reliable manual location, that manual value should be
    treated as the authoritative source instead of this estimate.
    """

    if use_cache and _cache_valid():
        cached = _cache_get()
        if cached:
            cached["cache_hit"] = True
            return cached

    providers = [
        # provider 1: ipapi.co
        (
            "ipapi.co",
            "https://ipapi.co/json/",
            _parse_ipapi,
        ),
        # provider 2: ipwho.is
        (
            "ipwho.is",
            "https://ipwho.is/",
            _parse_ipwho,
        ),
        # provider 3: ipinfo.io (loc="lat,lon")
        (
            "ipinfo.io",
            "https://ipinfo.io/json",
            _parse_ipinfo,
        ),
    ]

    for provider_name, url, parser in providers:
        try:
            payload = _fetch_json(url)
            details = parser(payload)
            if not details:
                continue
            if details.get("city") or details.get("country"):
                details["provider"] = provider_name
                details["provider_url"] = url
                details["cache_hit"] = False
                details["fetched_at"] = int(time.time())
                _cache_set(details)
                return details
        except Exception:
            continue

    return None


def get_current_location():

    """Return a rough current location estimate from public IP geolocation.

    This is not exact and may be incorrect; user-entered location should take precedence
    when available.
    """

    details = get_location_details()

    if details:

        pieces = [piece for piece in [details.get("city"), details.get("region"), details.get("country")] if piece]
        if pieces:
            provider = details.get("provider") or "unknown"
            return "現在地の推定(IP概算): " + " / ".join(pieces) + f" (provider: {provider})"

    return "現在地の推定: 取得できませんでした。ネットワーク接続を確認してください。"