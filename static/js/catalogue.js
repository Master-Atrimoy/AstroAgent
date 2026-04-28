/**
 * catalogue.js — target browser + search
 *
 * Behaviour:
 * - On init: fetches fallback catalogue from /api/catalogue immediately
 * - Category chips: clicking shows all objects in that category in dropdown
 * - Input focus: opens dropdown with current category browse
 * - Typing: filters in real time
 * - After location set: reloads with altitude scores
 */
const Catalogue = (() => {
  let _objects = [];
  let _selected = null;
  let _debounce = null;
  let _activeCategory = 'all';

  const CATEGORIES = [
    { id: 'all',              label: 'All',           icon: '🔭' },
    { id: 'planet',           label: 'Planets',       icon: '🪐' },
    { id: 'galaxy',           label: 'Galaxies',      icon: '🌌' },
    { id: 'nebula',           label: 'Nebulae',       icon: '🌫' },
    { id: 'cluster_open',     label: 'Open Clusters', icon: '✨' },
    { id: 'cluster_globular', label: 'Globulars',     icon: '⭕' },
    { id: 'double_star',      label: 'Double Stars',  icon: '⭐' },
    { id: 'milky_way',        label: 'Milky Way',     icon: '🌠' },
    { id: 'comet',            label: 'Comets',        icon: '☄️' },
  ];

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    renderCategoryFilter();
    bindInputEvents();
    await loadFallback();
  }

  function bindInputEvents() {
    const input = document.getElementById('target-input');

    // Open browse on focus
    input.addEventListener('focus', () => showCategoryBrowse());

    // Filter as user types
    input.addEventListener('input', () => {
      clearTimeout(_debounce);
      const q = input.value.trim().toLowerCase();
      if (!q) { showCategoryBrowse(); return; }
      _debounce = setTimeout(() => searchLocal(q), 180);
    });

    // Close on blur — delay so mousedown on item fires first
    input.addEventListener('blur', () => setTimeout(closeDropdown, 220));
  }

  // ── Load ──────────────────────────────────────────────────────────────────

  async function loadFallback() {
    try {
      // min_alt=-90 returns everything regardless of altitude
      const data = await API.catalogue({ lat: 0, lon: 0, aperture_mm: 150, sqm: 19, min_alt: -90 });
      _objects = data.objects || [];
    } catch (e) {
      console.warn('Fallback catalogue load failed:', e);
    }
  }

  async function load(lat, lon, apertureMm, sqm) {
    try {
      const data = await API.catalogue({ lat, lon, aperture_mm: apertureMm, sqm, min_alt: 8 });
      _objects = data.objects || [];
      return _objects;
    } catch (e) {
      console.warn('Catalogue load failed:', e);
      return [];
    }
  }

  // ── Category filter ───────────────────────────────────────────────────────

  function renderCategoryFilter() {
    const el = document.getElementById('cat-filter');
    el.innerHTML = CATEGORIES.map(c =>
      `<button class="cat-chip ${c.id === 'all' ? 'active' : ''}" data-cat="${c.id}">
         ${c.icon} ${c.label}
       </button>`
    ).join('');

    el.querySelectorAll('.cat-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        setCategory(btn.dataset.cat);
        document.getElementById('target-input').focus();
        showCategoryBrowse();
      });
    });
  }

  function setCategory(cat) {
    _activeCategory = cat;
    document.querySelectorAll('.cat-chip').forEach(c =>
      c.classList.toggle('active', c.dataset.cat === cat)
    );
  }

  // ── Browse (no query) ─────────────────────────────────────────────────────

  function showCategoryBrowse() {
    const filtered = _activeCategory === 'all'
      ? _objects
      : _objects.filter(o => o.category === _activeCategory);

    const sorted = [...filtered].sort((a, b) =>
      (b.score || 0) - (a.score || 0) || a.magnitude - b.magnitude
    );

    renderDropdown(sorted.slice(0, 12), false);
  }

  // ── Search ────────────────────────────────────────────────────────────────

  function searchLocal(q) {
    const matches = _objects.filter(o => {
      const catOk = _activeCategory === 'all' || o.category === _activeCategory;
      const nameOk = o.name.toLowerCase().includes(q)
        || o.id.toLowerCase().includes(q)
        || (o.aliases || []).some(a => a.toLowerCase().includes(q))
        || (o.constellation || '').toLowerCase().includes(q);
      return catOk && nameOk;
    });

    matches.sort((a, b) => {
      const aExact = a.id.toLowerCase() === q || a.name.toLowerCase() === q;
      const bExact = b.id.toLowerCase() === q || b.name.toLowerCase() === q;
      if (aExact && !bExact) return -1;
      if (!aExact && bExact) return 1;
      return (b.score || 0) - (a.score || 0);
    });

    renderDropdown(matches.slice(0, 10), true);
  }

  // ── Render dropdown ───────────────────────────────────────────────────────

  function renderDropdown(results, isSearch) {
    const dd = document.getElementById('target-dropdown');

    if (!results.length) {
      dd.innerHTML = `<div class="dropdown-item" style="color:var(--text3);cursor:default;">
        No objects found${_activeCategory !== 'all' ? ' in this category' : ''}
      </div>`;
      dd.classList.add('open');
      return;
    }

    const catInfo = CATEGORIES.find(c => c.id === _activeCategory);
    const header = (!isSearch && _activeCategory !== 'all')
      ? `<div style="padding:6px 12px 4px;font-size:10px;color:var(--text3);
           font-family:var(--mono);text-transform:uppercase;letter-spacing:.1em;
           border-bottom:1px solid var(--border);">
           ${catInfo.icon} ${catInfo.label} · ${results.length} shown
         </div>`
      : '';

    dd.innerHTML = header + results.map((r, i) => {
      const sc = r.score > 0
        ? `<span style="margin-left:auto;font-family:var(--mono);font-size:10px;
             color:${_scoreColor(r.score)};padding-left:8px;">${r.score}</span>` : '';
      const altStr = r.altitude_deg > 0 ? `${r.altitude_deg.toFixed(0)}° · ` : '';
      return `
        <div class="dropdown-item" data-idx="${i}">
          <div class="di-main" style="display:flex;align-items:center;gap:4px;">
            <span>${r.name}</span>
            <span style="color:var(--text3);font-size:10px;">${r.id}</span>
            ${sc}
          </div>
          <div class="di-sub">
            ${r.category.replace(/_/g,' ')} · ${altStr}mag ${r.magnitude}
            ${r.constellation ? '· ' + r.constellation : ''}
          </div>
        </div>`;
    }).join('');

    dd.classList.add('open');

    dd.querySelectorAll('.dropdown-item[data-idx]').forEach((el, i) => {
      el.addEventListener('mousedown', () => select(results[i]));
    });
  }

  function _scoreColor(s) {
    if (s >= 75) return 'var(--green)';
    if (s >= 55) return 'var(--gold)';
    if (s >= 35) return 'var(--accent)';
    return 'var(--red)';
  }

  // ── Select / clear ────────────────────────────────────────────────────────

  function select(obj) {
    _selected = obj;
    document.getElementById('target-input').value = '';
    closeDropdown();

    const tag = document.getElementById('target-tag');
    tag.classList.remove('hidden');
    tag.innerHTML = `
      <div>
        <div class="tag-name">🎯 ${obj.name}</div>
        <div class="tag-coords">
          ${obj.category.replace(/_/g,' ')} · mag ${obj.magnitude}
          ${obj.altitude_deg > 0 ? ' · ' + obj.altitude_deg.toFixed(0) + '° alt' : ''}
        </div>
      </div>
      <button class="tag-clear" onclick="Catalogue.clearSelected()">×</button>`;
  }

  function clearSelected() {
    _selected = null;
    document.getElementById('target-tag').classList.add('hidden');
    document.getElementById('target-input').value = '';
  }

  function closeDropdown() {
    document.getElementById('target-dropdown').classList.remove('open');
  }

  function setObjects(o) { _objects = o; }
  function getSelected() { return _selected; }
  function getObjects()  { return _objects; }

  return { init, load, setObjects, select, clearSelected, getSelected, getObjects };
})();
