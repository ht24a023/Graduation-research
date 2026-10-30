import unittest
from urllib.parse import parse_qs, urlparse

from functions import transit


class TransitUrlTests(unittest.TestCase):
    def test_google_maps_url_encodes_slashes_in_origin_and_destination(self):
        url = transit._build_google_maps_directions_url(
            "Kyoto / Kyoto Prefecture / Japan",
            "東京駅",
            travelmode="driving",
        )

        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "www.google.com")
        self.assertEqual(parsed.path, "/maps/dir/")
        self.assertEqual(query["api"], ["1"])
        self.assertEqual(query["origin"], ["Kyoto / Kyoto Prefecture / Japan"])
        self.assertEqual(query["destination"], ["東京駅"])
        self.assertEqual(query["travelmode"], ["driving"])

    def test_resolve_navigation_uses_clickable_google_maps_query_url(self):
        original_geocode = transit._geocode
        original_resolve_origin = transit._resolve_origin
        original_yahoo_summary = transit._yahoo_transit_summary
        original_osrm_route_data = transit._osrm_route_data
        try:
            transit._resolve_origin = lambda origin, current_location="", current_location_details=None: (
                "Kyoto / Kyoto Prefecture / Japan",
                (35.0116, 135.7681),
                None,
            )
            transit._geocode = lambda destination: (35.6812, 139.7671)
            transit._yahoo_transit_summary = lambda origin, destination: "公共交通機関: 取得できませんでした。"
            transit._osrm_route_data = lambda origin, dest, profile="driving": {
                "duration_min": 331,
                "distance_km": 454.6,
                "steps": [],
            } if profile == "driving" else None

            result = transit.resolve_navigation("ここから東京駅まで")
        finally:
            transit._geocode = original_geocode
            transit._resolve_origin = original_resolve_origin
            transit._yahoo_transit_summary = original_yahoo_summary
            transit._osrm_route_data = original_osrm_route_data

        self.assertIn("https://www.google.com/maps/dir/?api=1", result)
        self.assertIn("origin=Kyoto+%2F+Kyoto+Prefecture+%2F+Japan", result)
        self.assertIn("destination=%E6%9D%B1%E4%BA%AC%E9%A7%85", result)


if __name__ == "__main__":
    unittest.main()
