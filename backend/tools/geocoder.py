"""Location search and geocoding via Open-Meteo (free, no API key)."""
from __future__ import annotations
import httpx
from backend.schemas.astro import LocationResult
from backend.config.loader import get_config


async def search_locations(query: str, limit: int = 6) -> list[LocationResult]:
    """Search for city names and return lat/lon results."""
    cfg = get_config()
    url = cfg.tools.open_meteo.geocoding_url
    timeout = cfg.tools.open_meteo.timeout_sec

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params={
                "name": query,
                "count": limit,
                "language": "en",
                "format": "json",
            })
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return []

    results = []
    for r in data.get("results", []):
        admin = r.get("admin1", "")
        country = r.get("country", "")
        display_parts = [r["name"]]
        if admin:
            display_parts.append(admin)
        display_parts.append(country)
        results.append(LocationResult(
            name=r["name"],
            country=country,
            lat=round(r["latitude"], 4),
            lon=round(r["longitude"], 4),
            display=", ".join(display_parts),
        ))
    return results
