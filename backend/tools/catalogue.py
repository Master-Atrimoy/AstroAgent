"""
Live astronomical catalogue manager.
Serves fallback instantly; fetches live data from Vizier/ephem/JPL in background.
"""
from __future__ import annotations
import json
import math
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.schemas.astro import CatalogueObject
from backend.tools.horizons import get_altitude
from backend.config.loader import get_config

log = logging.getLogger(__name__)

# ── Shared state ───────────────────────────────────────────────────────────

_catalogue: list[CatalogueObject] = []
_catalogue_meta: dict = {
    "status": "building",
    "source": "fallback",
    "generated_at": "",
    "object_count": 0,
    "location": None,
    "progress": 0,
}


def get_status() -> dict:
    return dict(_catalogue_meta)


def get_catalogue() -> list[CatalogueObject]:
    return list(_catalogue)


def get_catalogue_by_category() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for obj in _catalogue:
        cat = obj.category
        result.setdefault(cat, [])
        result[cat].append(obj.model_dump())
    return result


# ── Fallback catalogue (always available instantly) ────────────────────────

FALLBACK_OBJECTS: list[dict] = [
    # Planets
    {"id":"SOL","name":"Sun","aliases":["Sol"],"category":"planet","ra_deg":0,"dec_deg":0,"magnitude":-26.7,"angular_size_arcmin":31.6,"description":"Our star","imaging_notes":"Use solar filter only","min_aperture_mm":60,"source":"fallback"},
    {"id":"MOO","name":"Moon","aliases":[],"category":"planet","ra_deg":0,"dec_deg":10,"magnitude":-12.6,"angular_size_arcmin":30.0,"description":"Earth's moon","imaging_notes":"Use moon filter to reduce glare","min_aperture_mm":60,"source":"fallback"},
    {"id":"JUP","name":"Jupiter","aliases":[],"category":"planet","ra_deg":35.0,"dec_deg":10.0,"magnitude":-2.3,"angular_size_arcmin":0.7,"description":"Largest planet, visible cloud bands and Galilean moons","imaging_notes":"High magnification needed; image during good seeing","min_aperture_mm":60,"source":"fallback"},
    {"id":"SAT","name":"Saturn","aliases":[],"category":"planet","ra_deg":310.0,"dec_deg":-17.0,"magnitude":0.6,"angular_size_arcmin":0.3,"description":"Ringed giant","imaging_notes":"60x shows rings; 150x reveals Cassini Division","min_aperture_mm":60,"source":"fallback"},
    {"id":"MAR","name":"Mars","aliases":[],"category":"planet","ra_deg":200.0,"dec_deg":-15.0,"magnitude":1.0,"angular_size_arcmin":0.1,"description":"Red planet — best near opposition","imaging_notes":"Surface detail needs excellent seeing and 6\"+","min_aperture_mm":100,"source":"fallback"},
    {"id":"VEN","name":"Venus","aliases":[],"category":"planet","ra_deg":60.0,"dec_deg":15.0,"magnitude":-4.0,"angular_size_arcmin":0.4,"description":"Brilliant evening/morning star, shows phases","imaging_notes":"Best observed in twilight to reduce glare","min_aperture_mm":60,"source":"fallback"},
    {"id":"MER","name":"Mercury","aliases":[],"category":"planet","ra_deg":20.0,"dec_deg":5.0,"magnitude":0.0,"angular_size_arcmin":0.1,"description":"Elusive inner planet, seen near horizon","imaging_notes":"Observe near greatest elongation","min_aperture_mm":60,"source":"fallback"},
    {"id":"URA","name":"Uranus","aliases":[],"category":"planet","ra_deg":45.0,"dec_deg":15.0,"magnitude":5.7,"angular_size_arcmin":0.06,"description":"Ice giant, appears as blue-green disk","imaging_notes":"200x+ needed for disk; easily confused with a star","min_aperture_mm":100,"source":"fallback"},
    {"id":"NEP","name":"Neptune","aliases":[],"category":"planet","ra_deg":355.0,"dec_deg":-2.0,"magnitude":7.8,"angular_size_arcmin":0.04,"description":"Blue disk, Triton moon challenging","imaging_notes":"Appears as tiny blue-grey disk at 200x","min_aperture_mm":150,"source":"fallback"},
    # Galaxies
    {"id":"M31","name":"Andromeda Galaxy","aliases":["NGC 224"],"category":"galaxy","ra_deg":10.68,"dec_deg":41.27,"magnitude":3.4,"angular_size_arcmin":190,"constellation":"Andromeda","description":"Nearest spiral galaxy, stunning naked-eye target","imaging_notes":"Wide FOV essential; nebulosity around core beautiful","min_aperture_mm":60,"source":"fallback"},
    {"id":"M33","name":"Triangulum Galaxy","aliases":["NGC 598"],"category":"galaxy","ra_deg":23.46,"dec_deg":30.66,"magnitude":5.7,"angular_size_arcmin":73,"constellation":"Triangulum","description":"Face-on spiral, needs dark skies","imaging_notes":"Very low surface brightness; bortle 4 or better","min_aperture_mm":80,"source":"fallback"},
    {"id":"M81","name":"Bode's Galaxy","aliases":["NGC 3031"],"category":"galaxy","ra_deg":149.0,"dec_deg":69.07,"magnitude":6.9,"angular_size_arcmin":26,"constellation":"Ursa Major","description":"Bright spiral, pairs with M82","imaging_notes":"Both M81 and M82 fit in same low-power FOV","min_aperture_mm":80,"source":"fallback"},
    {"id":"M82","name":"Cigar Galaxy","aliases":["NGC 3034"],"category":"galaxy","ra_deg":148.97,"dec_deg":69.68,"magnitude":8.4,"angular_size_arcmin":11,"constellation":"Ursa Major","description":"Starburst galaxy with dramatic dark lanes","imaging_notes":"H-alpha filter reveals gas filaments","min_aperture_mm":100,"source":"fallback"},
    {"id":"M51","name":"Whirlpool Galaxy","aliases":["NGC 5194"],"category":"galaxy","ra_deg":202.47,"dec_deg":47.2,"magnitude":8.4,"angular_size_arcmin":11,"constellation":"Canes Venatici","description":"Face-on spiral with NGC 5195 companion","imaging_notes":"8\"+ reveals spiral arms","min_aperture_mm":150,"source":"fallback"},
    {"id":"M104","name":"Sombrero Galaxy","aliases":["NGC 4594"],"category":"galaxy","ra_deg":189.99,"dec_deg":-11.62,"magnitude":8.0,"angular_size_arcmin":9,"constellation":"Virgo","description":"Edge-on spiral with prominent dust lane","imaging_notes":"Dark lane visible in 4\" scope","min_aperture_mm":100,"source":"fallback"},
    {"id":"NGC4565","name":"Needle Galaxy","aliases":[],"category":"galaxy","ra_deg":189.09,"dec_deg":25.99,"magnitude":9.6,"angular_size_arcmin":16,"constellation":"Coma Berenices","description":"Classic edge-on galaxy","imaging_notes":"Dust lane visible in 8\"+","min_aperture_mm":150,"source":"fallback"},
    # Nebulae
    {"id":"M42","name":"Orion Nebula","aliases":["NGC 1976"],"category":"nebula","ra_deg":83.82,"dec_deg":-5.39,"magnitude":4.0,"angular_size_arcmin":85,"constellation":"Orion","description":"Brightest diffuse nebula in the sky","imaging_notes":"Trapezium cluster at centre; OIII filter for contrast","min_aperture_mm":60,"source":"fallback"},
    {"id":"M57","name":"Ring Nebula","aliases":["NGC 6720"],"category":"nebula","ra_deg":283.4,"dec_deg":33.03,"magnitude":8.8,"angular_size_arcmin":1.4,"constellation":"Lyra","description":"Classic planetary nebula","imaging_notes":"100x+ magnification; OIII filter helps","min_aperture_mm":80,"source":"fallback"},
    {"id":"M27","name":"Dumbbell Nebula","aliases":["NGC 6853"],"category":"nebula","ra_deg":299.9,"dec_deg":22.72,"magnitude":7.4,"angular_size_arcmin":8,"constellation":"Vulpecula","description":"Largest and brightest planetary nebula","imaging_notes":"Apple-core shape in any scope; OIII enhances it","min_aperture_mm":60,"source":"fallback"},
    {"id":"M1","name":"Crab Nebula","aliases":["NGC 1952"],"category":"nebula","ra_deg":83.63,"dec_deg":22.01,"magnitude":8.4,"angular_size_arcmin":7,"constellation":"Taurus","description":"Supernova remnant with pulsar","imaging_notes":"OIII filter dramatically improves contrast","min_aperture_mm":100,"source":"fallback"},
    {"id":"M8","name":"Lagoon Nebula","aliases":["NGC 6523"],"category":"nebula","ra_deg":270.92,"dec_deg":-24.39,"magnitude":6.0,"angular_size_arcmin":45,"constellation":"Sagittarius","description":"Large emission nebula with open cluster","imaging_notes":"H-alpha filter excellent for imaging","min_aperture_mm":60,"source":"fallback"},
    {"id":"NGC7293","name":"Helix Nebula","aliases":[],"category":"nebula","ra_deg":337.41,"dec_deg":-20.84,"magnitude":7.3,"angular_size_arcmin":25,"constellation":"Aquarius","description":"Largest apparent planetary nebula","imaging_notes":"UHC or OIII filter essential","min_aperture_mm":100,"source":"fallback"},
    # Open clusters
    {"id":"M45","name":"Pleiades","aliases":["Seven Sisters"],"category":"cluster_open","ra_deg":56.75,"dec_deg":24.12,"magnitude":1.6,"angular_size_arcmin":110,"constellation":"Taurus","description":"Famous open cluster, naked-eye target","imaging_notes":"Wide-field scope or binoculars optimal","min_aperture_mm":60,"source":"fallback"},
    {"id":"NGC869","name":"Double Cluster","aliases":["h Persei"],"category":"cluster_open","ra_deg":34.75,"dec_deg":57.14,"magnitude":4.3,"angular_size_arcmin":30,"constellation":"Perseus","description":"Stunning pair of open clusters","imaging_notes":"Low power wide-field is best","min_aperture_mm":60,"source":"fallback"},
    {"id":"M35","name":"Open Cluster M35","aliases":["NGC 2168"],"category":"cluster_open","ra_deg":92.27,"dec_deg":24.34,"magnitude":5.3,"angular_size_arcmin":28,"constellation":"Gemini","description":"Rich open cluster in Gemini","imaging_notes":"NGC 2158 visible nearby as compressed haze","min_aperture_mm":60,"source":"fallback"},
    {"id":"M44","name":"Beehive Cluster","aliases":["Praesepe","NGC 2632"],"category":"cluster_open","ra_deg":130.08,"dec_deg":19.62,"magnitude":3.7,"angular_size_arcmin":95,"constellation":"Cancer","description":"Large open cluster in Cancer","imaging_notes":"Best in binoculars; too wide for most scopes","min_aperture_mm":60,"source":"fallback"},
    # Globular clusters
    {"id":"M13","name":"Hercules Cluster","aliases":["NGC 6205"],"category":"cluster_globular","ra_deg":250.42,"dec_deg":36.46,"magnitude":5.8,"angular_size_arcmin":20,"constellation":"Hercules","description":"Greatest globular in northern sky","imaging_notes":"Resolves to individual stars at 150x in 6\"+","min_aperture_mm":60,"source":"fallback"},
    {"id":"M22","name":"Sagittarius Cluster","aliases":["NGC 6656"],"category":"cluster_globular","ra_deg":279.1,"dec_deg":-23.9,"magnitude":5.1,"angular_size_arcmin":32,"constellation":"Sagittarius","description":"One of the finest globulars","imaging_notes":"Rivals M13; best in southern skies","min_aperture_mm":60,"source":"fallback"},
    {"id":"M3","name":"Globular M3","aliases":["NGC 5272"],"category":"cluster_globular","ra_deg":205.55,"dec_deg":28.38,"magnitude":6.2,"angular_size_arcmin":18,"constellation":"Canes Venatici","description":"Outstanding globular cluster","imaging_notes":"500,000+ stars; central condensation visible in small scopes","min_aperture_mm":60,"source":"fallback"},
    {"id":"M92","name":"Globular M92","aliases":["NGC 6341"],"category":"cluster_globular","ra_deg":259.28,"dec_deg":43.14,"magnitude":6.5,"angular_size_arcmin":14,"constellation":"Hercules","description":"Often overlooked sibling of M13","imaging_notes":"Beautiful resolved globular; rival to M13","min_aperture_mm":60,"source":"fallback"},
    # Double stars
    {"id":"ALB","name":"Albireo","aliases":[],"category":"double_star","ra_deg":292.68,"dec_deg":27.96,"magnitude":3.1,"angular_size_arcmin":0,"constellation":"Cygnus","description":"Gold and blue double — finest colour contrast","imaging_notes":"Easy split at 30x; stunning colour pair","min_aperture_mm":60,"source":"fallback"},
    {"id":"EPS_LYR","name":"Epsilon Lyrae","aliases":["Double Double"],"category":"double_star","ra_deg":281.08,"dec_deg":39.67,"magnitude":4.7,"angular_size_arcmin":0,"constellation":"Lyra","description":"The Double Double — two pairs of doubles","imaging_notes":"150x and good seeing to split both pairs","min_aperture_mm":60,"source":"fallback"},
    {"id":"MIZ","name":"Mizar & Alcor","aliases":[],"category":"double_star","ra_deg":200.98,"dec_deg":54.93,"magnitude":2.3,"angular_size_arcmin":0,"constellation":"Ursa Major","description":"Classic naked-eye and telescopic double","imaging_notes":"Good seeing test; Mizar itself is a close double","min_aperture_mm":60,"source":"fallback"},
    # Milky Way
    {"id":"MW_CORE","name":"Milky Way Core","aliases":["Galactic Centre"],"category":"milky_way","ra_deg":266.4,"dec_deg":-29.0,"magnitude":0.0,"angular_size_arcmin":600,"constellation":"Sagittarius","description":"Dense central bulge of our galaxy — spectacular wide-field target","imaging_notes":"Wide-angle lens or small scope; dark skies essential","min_aperture_mm":0,"source":"fallback"},
    {"id":"MW_CYGNUS","name":"Cygnus Star Cloud","aliases":[],"category":"milky_way","ra_deg":305.0,"dec_deg":40.0,"magnitude":0.0,"angular_size_arcmin":300,"constellation":"Cygnus","description":"Rich northern Milky Way star field","imaging_notes":"Best with fast wide-field optics; nebula filters useful","min_aperture_mm":0,"source":"fallback"},
]


def _load_fallback() -> list[CatalogueObject]:
    objects = []
    for d in FALLBACK_OBJECTS:
        try:
            objects.append(CatalogueObject(**d))
        except Exception:
            pass
    return objects


# ── Live catalogue fetch ───────────────────────────────────────────────────

async def _fetch_vizier_dsos() -> list[CatalogueObject]:
    """Fetch Messier + NGC objects from Vizier via astroquery."""
    try:
        from astroquery.vizier import Vizier
        import asyncio

        def _query():
            v = Vizier(columns=["*"], row_limit=500)
            # Messier catalogue
            result = v.get_catalogs("VII/118/mwsc")
            return result

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _query)

        objects = []
        if result and len(result) > 0:
            table = result[0]
            for row in table:
                try:
                    name = str(row.get("Name", "")).strip()
                    ra = float(row.get("RAJ2000", 0))
                    dec = float(row.get("DEJ2000", 0))
                    mag = float(row.get("Bmag", 10) or 10)
                    size = float(row.get("rh", 0) or 0) * 2  # radius → diameter arcmin
                    stype = str(row.get("Type", "")).strip()

                    cat = "galaxy"
                    if "OC" in stype or "open" in stype.lower():
                        cat = "cluster_open"
                    elif "GC" in stype or "glob" in stype.lower():
                        cat = "cluster_globular"
                    elif "PN" in stype or "nebula" in stype.lower():
                        cat = "nebula"

                    objects.append(CatalogueObject(
                        id=f"VIZ_{name.replace(' ', '_')}",
                        name=name,
                        category=cat,
                        ra_deg=ra,
                        dec_deg=dec,
                        magnitude=mag,
                        angular_size_arcmin=size,
                        source="vizier",
                    ))
                except Exception:
                    continue
        return objects
    except Exception as e:
        log.warning(f"Vizier fetch failed: {e}")
        return []


async def _fetch_planets_ephem(lat: float, lon: float) -> list[CatalogueObject]:
    """Compute current planet positions via ephem."""
    try:
        import ephem
        from datetime import datetime, timezone

        obs = ephem.Observer()
        obs.lat = str(lat)
        obs.lon = str(lon)
        obs.date = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S")

        planet_map = {
            "Mercury": (ephem.Mercury(), "MER"),
            "Venus":   (ephem.Venus(),   "VEN"),
            "Mars":    (ephem.Mars(),    "MAR"),
            "Jupiter": (ephem.Jupiter(), "JUP"),
            "Saturn":  (ephem.Saturn(),  "SAT"),
            "Uranus":  (ephem.Uranus(),  "URA"),
            "Neptune": (ephem.Neptune(), "NEP"),
        }

        objects = []
        for name, (body, pid) in planet_map.items():
            body.compute(obs)
            ra_deg = math.degrees(float(body.ra))
            dec_deg = math.degrees(float(body.dec))
            mag = float(body.mag) if hasattr(body, "mag") else 5.0
            objects.append(CatalogueObject(
                id=pid,
                name=name,
                category="planet",
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                magnitude=mag,
                angular_size_arcmin=0.5,
                description=f"Current {name} position (computed live)",
                source="ephem",
            ))
        return objects
    except Exception as e:
        log.warning(f"ephem planet fetch failed: {e}")
        return []


async def _fetch_jpl_comets() -> list[CatalogueObject]:
    """Fetch currently bright comets from JPL Horizons."""
    cfg = get_config()
    if not cfg.tools.jpl_horizons.enabled:
        return []
    try:
        import httpx
        timeout = cfg.tools.jpl_horizons.timeout_sec
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                "https://ssd-api.jpl.nasa.gov/cad.api",
                params={"dist-max": "0.2", "date-min": "now", "fullname": True},
            )
            resp.raise_for_status()
            data = resp.json()

        objects = []
        for row in data.get("data", [])[:8]:
            try:
                name = str(row[0]).strip()
                objects.append(CatalogueObject(
                    id=f"JPL_{name.replace(' ', '_')[:12]}",
                    name=name,
                    category="comet",
                    ra_deg=0.0,
                    dec_deg=0.0,
                    magnitude=10.0,
                    angular_size_arcmin=0,
                    description="Near-Earth object from JPL",
                    source="jpl",
                ))
            except Exception:
                continue
        return objects
    except Exception as e:
        log.warning(f"JPL Horizons fetch failed (non-critical): {e}")
        return []


async def build_live_catalogue(lat: float, lon: float) -> None:
    """Background task: fetch live catalogue and update shared state."""
    global _catalogue, _catalogue_meta

    _catalogue_meta["status"] = "building"
    _catalogue_meta["progress"] = 5
    _catalogue_meta["location"] = {"lat": lat, "lon": lon}

    # Start with fallback so there's always something to show
    fallback = _load_fallback()
    _catalogue = fallback
    _catalogue_meta["source"] = "fallback"
    _catalogue_meta["object_count"] = len(fallback)
    _catalogue_meta["progress"] = 20

    # Live planet positions
    planets = await _fetch_planets_ephem(lat, lon)
    _catalogue_meta["progress"] = 40

    # Vizier DSOs
    dsos = await _fetch_vizier_dsos()
    _catalogue_meta["progress"] = 75

    # JPL comets
    comets = await _fetch_jpl_comets()
    _catalogue_meta["progress"] = 90

    # Merge: live planets override fallback planets, add new DSOs
    existing_ids = {o.id for o in fallback}
    merged = list(fallback)

    # Replace fallback planets with live-computed ones
    if planets:
        merged = [o for o in merged if o.category != "planet"]
        merged.extend(planets)

    # Add new DSOs not in fallback
    for obj in dsos + comets:
        if obj.id not in existing_ids:
            merged.append(obj)

    _catalogue = merged

    # Write cache
    cfg = get_config()
    cache_path = Path(cfg.tools.catalogue.cache_file)
    try:
        cache_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "location": {"lat": lat, "lon": lon},
            "source": "live",
            "objects": [o.model_dump() for o in merged],
        }
        cache_path.write_text(json.dumps(cache_data, default=str))
    except Exception as e:
        log.warning(f"Cache write failed: {e}")

    _catalogue_meta.update({
        "status": "ready",
        "source": "live" if (planets or dsos) else "fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "object_count": len(_catalogue),
        "progress": 100,
    })
    log.info(f"Catalogue ready: {len(_catalogue)} objects")


def score_and_filter(
    objects: list[CatalogueObject],
    lat: float,
    lon: float,
    limiting_mag: float,
    min_alt: float = 10.0,
) -> list[dict]:
    """Score and filter objects for current visibility at location.
    Planets are computed live via ephem when available.
    """
    from datetime import datetime, timezone
    from backend.tools.horizons import score_altitude as _score_alt

    # Compute live planet positions
    live_planet_ra_dec: dict[str, tuple[float, float]] = {}
    try:
        import ephem, math as _m
        obs = ephem.Observer()
        obs.lat = str(lat)
        obs.lon = str(lon)
        obs.date = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
        obs.pressure = 0
        for pid, body in [
            ("MER", ephem.Mercury()), ("VEN", ephem.Venus()),
            ("MAR", ephem.Mars()),   ("JUP", ephem.Jupiter()),
            ("SAT", ephem.Saturn()), ("URA", ephem.Uranus()),
            ("NEP", ephem.Neptune()),
        ]:
            body.compute(obs)
            live_planet_ra_dec[pid] = (
                _m.degrees(float(body.ra)),
                _m.degrees(float(body.dec)),
            )
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    # If no real location given (lat=0, lon=0), skip altitude filtering
    no_location = (lat == 0.0 and lon == 0.0)
    scored = []
    for obj in objects:
        if obj.magnitude > limiting_mag + 4:
            continue
        if obj.category == "milky_way":
            scored.append({**obj.model_dump(), "altitude_deg": 0.0, "score": 70})
            continue
        if no_location:
            # Return unscored — frontend just needs the object list
            obj_dict = obj.model_dump()
            scored.append({**obj_dict, "altitude_deg": 0.0, "score": 0})
            continue
        # Use live position for planets if available
        if obj.category == "planet" and obj.id in live_planet_ra_dec:
            ra, dec = live_planet_ra_dec[obj.id]
        else:
            ra, dec = obj.ra_deg, obj.dec_deg
        alt = get_altitude(ra, dec, lat, lon, now)
        if min_alt > -80 and alt < min_alt:
            continue
        sc = int(_score_alt(alt) * 100)
        obj_dict = obj.model_dump()
        obj_dict["ra_deg"] = ra
        obj_dict["dec_deg"] = dec
        scored.append({**obj_dict, "altitude_deg": round(alt, 1), "score": sc})
    return sorted(scored, key=lambda x: x["score"], reverse=True)


# Initialise with fallback on import
_catalogue = _load_fallback()
_catalogue_meta["object_count"] = len(_catalogue)
_catalogue_meta["status"] = "ready"
_catalogue_meta["source"] = "fallback"
