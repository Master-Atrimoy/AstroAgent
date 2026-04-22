"""Geocoder — Open-Meteo geocoding API with local fallback table."""
from __future__ import annotations

CITY_TABLE: dict[str, tuple[float, float, int]] = {
    "kolkata": (22.5726, 88.3639, 5), "calcutta": (22.5726, 88.3639, 5),
    "mumbai": (19.0760, 72.8777, 5), "bombay": (19.0760, 72.8777, 5),
    "delhi": (28.7041, 77.1025, 5), "new delhi": (28.6139, 77.2090, 5),
    "bangalore": (12.9716, 77.5946, 5), "bengaluru": (12.9716, 77.5946, 5),
    "chennai": (13.0827, 80.2707, 5), "madras": (13.0827, 80.2707, 5),
    "hyderabad": (17.3850, 78.4867, 5), "pune": (18.5204, 73.8567, 5),
    "ahmedabad": (23.0225, 72.5714, 5), "jaipur": (26.9124, 75.7873, 5),
    "london": (51.5074, -0.1278, 0), "manchester": (53.4808, -2.2426, 0),
    "new york": (40.7128, -74.0060, -5), "los angeles": (34.0522, -118.2437, -8),
    "chicago": (41.8781, -87.6298, -6), "san francisco": (37.7749, -122.4194, -8),
    "sydney": (-33.8688, 151.2093, 11), "melbourne": (-37.8136, 144.9631, 11),
    "tokyo": (35.6762, 139.6503, 9), "osaka": (34.6937, 135.5023, 9),
    "paris": (48.8566, 2.3522, 1), "berlin": (52.5200, 13.4050, 1),
    "madrid": (40.4168, -3.7038, 1), "rome": (41.9028, 12.4964, 1),
    "dubai": (25.2048, 55.2708, 4), "singapore": (1.3521, 103.8198, 8),
    "hong kong": (22.3193, 114.1694, 8), "shanghai": (31.2304, 121.4737, 8),
    "beijing": (39.9042, 116.4074, 8), "moscow": (55.7558, 37.6173, 3),
    "cape town": (-33.9249, 18.4241, 2), "nairobi": (-1.2921, 36.8219, 3),
    "cairo": (30.0444, 31.2357, 2), "toronto": (43.6532, -79.3832, -5),
    "vancouver": (49.2827, -123.1207, -8), "sydney": (-33.8688, 151.2093, 11),
}


def geocode(query: str) -> tuple[float, float, int]:
    q = query.strip().lower()
    # Lat,lon passthrough
    parts = q.split(",")
    if len(parts) == 2:
        try:
            return float(parts[0].strip()), float(parts[1].strip()), 0
        except ValueError:
            pass
    # Local table
    for key, val in CITY_TABLE.items():
        if key == q or key in q or q in key:
            return val
    # Open-Meteo geocoding API
    try:
        import httpx
        r = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "en", "format": "json"},
            timeout=8,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            res = results[0]
            return float(res["latitude"]), float(res["longitude"]), int(res.get("utc_offset_seconds",0)//3600)
    except Exception:
        pass
    raise ValueError(f"Could not geocode '{query}'. Try city name or lat,lon.")


async def search_locations(query: str, limit: int = 8) -> list[dict]:
    """Search for locations — used by the frontend autocomplete."""
    if not query or len(query) < 2:
        return []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": query, "count": limit, "language": "en", "format": "json"},
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            return [
                {
                    "name": res.get("name",""),
                    "display": f"{res.get('name','')}, {res.get('admin1','')} {res.get('country','')}".strip(", "),
                    "lat": res["latitude"],
                    "lon": res["longitude"],
                    "tz_offset": res.get("utc_offset_seconds",0)//3600,
                    "country": res.get("country",""),
                }
                for res in results
            ]
    except Exception:
        # Fallback: search local table
        q = query.lower()
        matches = []
        for key, (lat, lon, tz) in CITY_TABLE.items():
            if q in key:
                matches.append({"name":key.title(),"display":key.title(),"lat":lat,"lon":lon,"tz_offset":tz,"country":""})
        return matches[:limit]
