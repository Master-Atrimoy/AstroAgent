/**
 * geocoder.js — location search + GPS locate-me with reverse geocoding
 */
const Geocoder = (() => {
  let _map      = null;
  let _marker   = null;
  let _debounce = null;
  let _selected = null;

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    const input = document.getElementById('location-input');

    input.addEventListener('input', () => {
      clearTimeout(_debounce);
      const q = input.value.trim();
      if (q.length < 2) { closeDropdown(); return; }
      _debounce = setTimeout(() => search(q), 320);
    });

    input.addEventListener('blur', () => setTimeout(closeDropdown, 200));
  }

  // ── City search ───────────────────────────────────────────────────────────

  async function search(q) {
    try {
      const data = await API.searchLocations(q);
      renderDropdown(data.results || []);
    } catch { closeDropdown(); }
  }

  function renderDropdown(results) {
    const dd = document.getElementById('location-dropdown');
    if (!results.length) { closeDropdown(); return; }
    dd.innerHTML = results.map((r, i) => `
      <div class="dropdown-item" data-idx="${i}">
        <div class="di-main">${r.display}</div>
        <div class="di-sub">${r.lat.toFixed(4)}°, ${r.lon.toFixed(4)}°</div>
      </div>`).join('');
    dd.classList.add('open');
    dd.querySelectorAll('.dropdown-item').forEach((el, i) => {
      el.addEventListener('mousedown', () => select(results[i]));
    });
  }

  // ── GPS locate-me ─────────────────────────────────────────────────────────

  function locateMe() {
    if (!navigator.geolocation) {
      setLocateStatus('error', '⚠ Geolocation not supported by your browser');
      return;
    }

    // Visual: spinner on button
    const btn  = document.getElementById('locate-me-btn');
    const icon = document.getElementById('locate-me-icon');
    btn.disabled = true;
    icon.innerHTML = '<span class="spinner" style="width:12px;height:12px;border-color:rgba(255,255,255,.3);border-top-color:#fff;"></span>';
    setLocateStatus('info', '📡 Getting your GPS position…');

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = parseFloat(pos.coords.latitude.toFixed(5));
        const lon = parseFloat(pos.coords.longitude.toFixed(5));
        const acc = Math.round(pos.coords.accuracy);

        setLocateStatus('info', `📡 Found you (±${acc}m) — resolving location name…`);

        // Reverse geocode: search Open-Meteo with lat/lon as query string
        // Use a fallback display name if reverse geocoding fails
        const display = await reverseGeocode(lat, lon);

        btn.disabled = false;
        icon.textContent = '📡';

        select({
          name:    display.name,
          country: display.country,
          lat,
          lon,
          display: display.full,
          fromGps: true,
          accuracy: acc,
        });

        setLocateStatus('success', `✓ Location set from GPS (±${acc}m accuracy)`);
        // Auto-hide status after 4s
        setTimeout(() => {
          const el = document.getElementById('locate-me-status');
          if (el) el.classList.add('hidden');
        }, 4000);
      },
      (err) => {
        btn.disabled = false;
        icon.textContent = '📡';
        const messages = {
          1: 'Location permission denied — please allow access in browser settings',
          2: 'Position unavailable — try searching by city name instead',
          3: 'Location request timed out — try again',
        };
        setLocateStatus('error', '⚠ ' + (messages[err.code] || err.message));
      },
      {
        enableHighAccuracy: true,
        timeout: 12000,
        maximumAge: 60000,  // use cached position if < 1 min old
      }
    );
  }

  async function reverseGeocode(lat, lon) {
    // Open-Meteo geocoding doesn't support reverse geocoding directly.
    // We use a lat/lon search via nominatim (OSM) as a free fallback.
    // If that fails, we construct a coordinate-based display name.
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
        { headers: { 'Accept-Language': 'en' } }
      );
      if (!res.ok) throw new Error('nominatim failed');
      const data = await res.json();
      const addr = data.address || {};
      const city = addr.city || addr.town || addr.village || addr.county || 'Unknown location';
      const state = addr.state || '';
      const country = addr.country || '';
      return {
        name:    city,
        country: country,
        full:    [city, state, country].filter(Boolean).join(', '),
      };
    } catch {
      // Fallback: coordinate-based display
      const ns = lat >= 0 ? 'N' : 'S';
      const ew = lon >= 0 ? 'E' : 'W';
      return {
        name:    `${Math.abs(lat).toFixed(2)}°${ns} ${Math.abs(lon).toFixed(2)}°${ew}`,
        country: '',
        full:    `${Math.abs(lat).toFixed(4)}°${ns}, ${Math.abs(lon).toFixed(4)}°${ew}`,
      };
    }
  }

  function setLocateStatus(type, msg) {
    const el = document.getElementById('locate-me-status');
    el.classList.remove('hidden', 'locate-info', 'locate-success', 'locate-error');
    el.classList.add(`locate-${type}`);
    el.textContent = msg;
  }

  // ── Select (shared by search + locate-me) ────────────────────────────────

  function select(location) {
    _selected = location;
    document.getElementById('location-input').value = '';
    closeDropdown();

    const ns = location.lat >= 0 ? 'N' : 'S';
    const ew = location.lon >= 0 ? 'E' : 'W';
    const coordStr = `${Math.abs(location.lat).toFixed(4)}°${ns}, ${Math.abs(location.lon).toFixed(4)}°${ew}`;
    const gpsBadge = location.fromGps
      ? `<span class="gps-badge">📡 GPS${location.accuracy ? ' ±'+location.accuracy+'m' : ''}</span>`
      : '';

    const tag = document.getElementById('location-tag');
    tag.classList.remove('hidden');
    tag.innerHTML = `
      <div class="tag-content">
        <div class="tag-name">📍 ${location.display} ${gpsBadge}</div>
        <div class="tag-coords">${coordStr}</div>
      </div>
      <button class="tag-clear" onclick="Geocoder.clear()">×</button>`;

    showMap(location.lat, location.lon);
    App.onLocationChanged(location);
  }

  // ── Map ───────────────────────────────────────────────────────────────────

  function showMap(lat, lon) {
    const mapEl = document.getElementById('map');
    mapEl.classList.remove('hidden');

    if (!_map) {
      _map = L.map('map', { zoomControl: true, attributionControl: true });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 18,
      }).addTo(_map);
    }

    // Zoom closer for GPS (exact location) vs city search
    _map.setView([lat, lon], 11);

    if (_marker) _marker.remove();
    const icon = L.divIcon({ className: 'star-marker', iconSize: [22, 22], iconAnchor: [11, 22] });
    _marker = L.marker([lat, lon], { icon }).addTo(_map);

    setTimeout(() => _map && _map.invalidateSize(), 150);
  }

  // ── Clear ─────────────────────────────────────────────────────────────────

  function clear() {
    _selected = null;
    document.getElementById('location-tag').classList.add('hidden');
    document.getElementById('map').classList.add('hidden');
    document.getElementById('location-input').value = '';
    document.getElementById('locate-me-status').classList.add('hidden');
    if (_marker) { _marker.remove(); _marker = null; }
  }

  function closeDropdown() {
    document.getElementById('location-dropdown').classList.remove('open');
  }

  function getSelected() { return _selected; }

  return { init, select, clear, locateMe, getSelected };
})();
