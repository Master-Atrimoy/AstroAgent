/* AstroAgent v2 — Frontend */
'use strict';
const API = '';

// ── State ─────────────────────────────────────────────────────────────────────
let sessionId      = null;
let allTargets     = [];
let allPresets     = {};
let selectedEquip  = null;   // {key, name, ...} or null for custom
let resolvedLoc    = null;   // {name, display, lat, lon, tz_offset}
let locSearchTimer = null;
let tgtSugTimer    = null;

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  await createSession();
  await discoverModels();
  await loadTargets();
  await loadPresets();
  setupUI();
}

// ── Session ───────────────────────────────────────────────────────────────────
async function createSession() {
  try {
    const r = await fetch(`${API}/api/session`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ollama_model: getModel(), ollama_base_url: getBaseUrl()}),
    });
    const d = await r.json();
    sessionId = d.session_id;
  } catch(e) { setStatus('error','Backend unreachable'); }
}

function getModel()   { return document.getElementById('model-select').value || 'llama3.1'; }
function getBaseUrl() { return document.getElementById('ollama-url').value.trim() || 'http://localhost:11434'; }
function getTimeout() { return parseInt(document.getElementById('timeout-select').value) || 90; }

// ── Ollama model discovery ────────────────────────────────────────────────────
async function discoverModels() {
  const sel  = document.getElementById('model-select');
  const stat = document.getElementById('model-status');
  stat.textContent = '…'; stat.className = 'model-status';
  try {
    const r = await fetch(`${API}/api/ollama/models?base_url=${encodeURIComponent(getBaseUrl())}`);
    const d = await r.json();
    if (!d.models.length) {
      sel.innerHTML = '<option value="">No models — run: ollama pull llama3.1</option>';
      stat.textContent = '✗'; stat.className = 'model-status err';
    } else {
      const prev = sel.value;
      sel.innerHTML = d.models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
      if (prev && d.models.includes(prev)) sel.value = prev;
      stat.textContent = '✓'; stat.className = 'model-status ok';
    }
  } catch(e) {
    sel.innerHTML = '<option value="llama3.1">llama3.1 (default)</option>';
    stat.textContent = '?'; stat.className = 'model-status';
  }
}

document.getElementById('btn-refresh-models').addEventListener('click', discoverModels);
document.getElementById('ollama-url').addEventListener('change', discoverModels);

// ── Targets ───────────────────────────────────────────────────────────────────
async function loadTargets() {
  try {
    const r = await fetch(`${API}/api/targets`);
    const d = await r.json();
    allTargets = d.targets || [];
    // Render quick-access chips for popular targets
    const chips = ['M31','M42','M45','M51','M57','M13','M27','NGC7000','Saturn','Jupiter'];
    document.getElementById('target-chips').innerHTML = chips.map(c =>
      `<span class="chip" onclick="setTarget('${c}')">${c}</span>`
    ).join('');
  } catch(e) {}
}

function setTarget(name) {
  document.getElementById('target-in').value = name;
  document.getElementById('target-sug').classList.add('hidden');
}

// ── Equipment presets ─────────────────────────────────────────────────────────
async function loadPresets() {
  try {
    const r = await fetch(`${API}/api/equipment/presets`);
    const d = await r.json();
    allPresets = d.categories || {};
    renderPresets('professional');
  } catch(e) {}
}

function renderPresets(cat) {
  const container = document.getElementById('eq-presets');
  const customDiv = document.getElementById('eq-custom');
  if (cat === 'custom') {
    container.innerHTML = '';
    customDiv.classList.remove('hidden');
    selectedEquip = null;
    document.getElementById('eq-selected').classList.add('hidden');
    return;
  }
  customDiv.classList.add('hidden');
  const presets = allPresets[cat] || [];
  container.innerHTML = presets.map(p => `
    <button class="eq-preset-btn ${selectedEquip?.key === p.key ? 'selected':''}"
            onclick="selectPreset('${p.key}','${esc(p.name)}','${p.aperture_mm}','${p.focal_ratio}','${p.mount_type}','${p.max_sub_sec}')">
      <span class="eq-preset-name">${esc(p.name)}</span>
      <span class="eq-preset-meta">${p.aperture_mm}mm f/${p.focal_ratio} · ${p.mount_type} · max ${p.max_sub_sec}s</span>
    </button>`).join('');
}

function selectPreset(key, name, ap, fr, mount, maxSub) {
  selectedEquip = {key, name, aperture_mm: ap, focal_ratio: fr, mount_type: mount, max_sub_sec: maxSub};
  document.querySelectorAll('.eq-preset-btn').forEach(b => b.classList.remove('selected'));
  event.currentTarget.classList.add('selected');
  const sel = document.getElementById('eq-selected');
  sel.textContent = `✓ ${name}`;
  sel.classList.remove('hidden');
}

// Equipment tab switching
document.querySelectorAll('.eq-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.eq-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    renderPresets(tab.dataset.cat);
  });
});

// ── Location autocomplete ─────────────────────────────────────────────────────
const locIn  = document.getElementById('location-in');
const locSug = document.getElementById('location-sug');

locIn.addEventListener('input', () => {
  const q = locIn.value.trim();
  clearTimeout(locSearchTimer);
  if (!q || q.length < 2) { locSug.classList.add('hidden'); return; }
  // Immediate: check if it looks like lat,lon
  if (/^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$/.test(q)) {
    const [lat, lon] = q.split(',').map(Number);
    setLocation({name: q, display: `${lat.toFixed(3)}, ${lon.toFixed(3)}`, lat, lon, tz_offset: 0});
    locSug.classList.add('hidden');
    return;
  }
  locSearchTimer = setTimeout(() => searchLocations(q), 300);
});

async function searchLocations(q) {
  try {
    const r = await fetch(`${API}/api/locations/search?q=${encodeURIComponent(q)}&limit=8`);
    const d = await r.json();
    const results = d.results || [];
    if (!results.length) { locSug.classList.add('hidden'); return; }
    locSug.innerHTML = results.map((loc, i) => `
      <div class="sug-item" onclick="setLocationFromSug(${i})" data-idx="${i}">
        <span class="sug-name">${esc(loc.display || loc.name)}</span>
        <span class="sug-sub">${loc.lat.toFixed(2)}°, ${loc.lon.toFixed(2)}°</span>
      </div>`).join('');
    locSug._results = results;
    locSug.classList.remove('hidden');
  } catch(e) { locSug.classList.add('hidden'); }
}

function setLocationFromSug(idx) {
  const results = locSug._results || [];
  if (results[idx]) setLocation(results[idx]);
  locSug.classList.add('hidden');
}

function setLocation(loc) {
  resolvedLoc = loc;
  locIn.value = loc.display || loc.name;
  const tag = document.getElementById('loc-resolved');
  tag.innerHTML = `<span>📍 ${esc(loc.display||loc.name)} (${loc.lat.toFixed(2)}°, ${loc.lon.toFixed(2)}°)</span>
    <span class="loc-clear" onclick="clearLocation()" title="Clear">✕</span>`;
  tag.classList.remove('hidden');
}

function clearLocation() {
  resolvedLoc = null;
  locIn.value = '';
  document.getElementById('loc-resolved').classList.add('hidden');
}

document.addEventListener('click', e => {
  if (!locIn.contains(e.target) && !locSug.contains(e.target)) locSug.classList.add('hidden');
});

// ── Target autocomplete ───────────────────────────────────────────────────────
const tgtIn  = document.getElementById('target-in');
const tgtSug = document.getElementById('target-sug');

tgtIn.addEventListener('input', () => {
  const q = tgtIn.value.trim().toLowerCase();
  clearTimeout(tgtSugTimer);
  if (!q) { tgtSug.classList.add('hidden'); return; }
  tgtSugTimer = setTimeout(() => {
    const matches = allTargets.filter(t =>
      t.name.toLowerCase().includes(q) || t.key.toLowerCase().includes(q)
    ).slice(0, 8);
    if (!matches.length) { tgtSug.classList.add('hidden'); return; }
    tgtSug.innerHTML = matches.map(t => `
      <div class="sug-item" onclick="setTarget('${esc(t.key)}')">
        <span class="sug-name">${esc(t.name)}</span>
        <span class="sug-sub">${t.type} · mag ${t.magnitude ?? '?'}</span>
      </div>`).join('');
    tgtSug.classList.remove('hidden');
  }, 150);
});

document.addEventListener('click', e => {
  if (!tgtIn.contains(e.target) && !tgtSug.contains(e.target)) tgtSug.classList.add('hidden');
});

// ── Run plan ──────────────────────────────────────────────────────────────────
document.getElementById('run-btn').addEventListener('click', runPlan);

async function runPlan() {
  const target = tgtIn.value.trim();
  const date   = document.getElementById('date-in').value;
  const model  = getModel();
  const timeout = getTimeout();
  const baseUrl = getBaseUrl();

  // Determine equipment string
  let equipment = '';
  const customActive = document.querySelector('.eq-tab.active')?.dataset.cat === 'custom';
  if (customActive) {
    equipment = document.getElementById('equipment-custom').value.trim();
  } else if (selectedEquip) {
    equipment = selectedEquip.key;  // use preset key
  }

  // Validate
  const errs = [];
  if (!target) errs.push('Target is required');
  if (!resolvedLoc) errs.push('Location is required — type a city name and select from the dropdown');
  if (!equipment) errs.push('Equipment is required — select a preset or enter custom equipment');
  if (!model) errs.push('Select an Ollama model (click ⟳ to discover)');
  if (errs.length) { alert(errs.join('\n')); return; }

  if (!sessionId) await createSession();

  // Reset UI
  document.getElementById('welcome').classList.add('hidden');
  document.getElementById('plan-card').classList.add('hidden');
  document.getElementById('right-panel').classList.remove('hidden');
  const stream = document.getElementById('stream');
  stream.innerHTML = ''; stream.classList.remove('hidden');
  document.getElementById('night-grid').innerHTML = '';
  document.getElementById('critique-box').classList.add('hidden');

  setStatus('running', 'Planning…');
  document.getElementById('run-btn').disabled = true;

  const params = new URLSearchParams({
    session_id: sessionId,
    target,
    location: resolvedLoc.display || resolvedLoc.name,
    lat: resolvedLoc.lat,
    lon: resolvedLoc.lon,
    timezone_offset: resolvedLoc.tz_offset || 0,
    equipment,
    date_preference: date,
    ollama_model: model,
    ollama_base_url: baseUrl,
    ollama_timeout: timeout,
  });

  const es = new EventSource(`${API}/api/plan?${params}`);

  es.addEventListener('step',   e => appendStep(JSON.parse(e.data)));
  es.addEventListener('result', e => { renderResult(JSON.parse(e.data)); setStatus('done','Plan ready'); es.close(); done(); });
  es.addEventListener('error',  e => { try { const d=JSON.parse(e.data); appendStep({agent:'System',type:'issue',content:d.message||'Unknown error'}); setStatus('error','Error'); } catch(x){} done(); });
  es.addEventListener('done',   () => { done(); if(es.readyState!==EventSource.CLOSED) es.close(); });
  es.onerror = () => { setStatus('error','Connection lost'); done(); es.close(); };

  function done() { document.getElementById('run-btn').disabled = false; }
}

// ── Stream rendering ──────────────────────────────────────────────────────────
function appendStep(d) {
  const stream = document.getElementById('stream');
  const agent  = d.agent || 'System';
  const type   = d.type  || 'info';
  const badgeClass = agent.includes('Target') ? 'b-ta'
    : agent.includes('Plan') ? 'b-pb'
    : agent.includes('Critic') ? 'b-cr' : 'b-sys';
  const label = agent.includes('Target') ? 'Target'
    : agent.includes('Plan') ? 'Planner'
    : agent.includes('Critic') ? 'Critic' : 'Sys';
  const row = document.createElement('div');
  row.className = 'step-row';
  row.innerHTML = `<span class="s-badge ${badgeClass}">${label}</span>
    <span class="s-text ${type}">${esc(d.content || '')}</span>`;
  stream.appendChild(row);
  stream.scrollTop = stream.scrollHeight;
}

// ── Plan result rendering ─────────────────────────────────────────────────────
function renderResult(state) {
  const plan     = state.imaging_plan;
  const critique = state.critique_result;
  const windows  = state.night_windows || [];

  if (!plan) {
    appendStep({agent:'System', type:'issue', content: state.error || 'No plan generated.'});
    return;
  }

  renderNights(windows);
  if (critique) renderCritique(critique);

  const approved = critique?.approved ?? true;
  const tgt  = plan.target      || {};
  const w    = plan.best_window || {};
  const eq   = plan.equipment   || {};
  const bkp  = plan.backup_window;
  const sc   = w.overall_score || 0;
  const sClass = sc >= 7 ? 'good' : sc >= 4 ? 'warn' : 'bad';

  const card = document.getElementById('plan-card');
  card.innerHTML = `
    <div class="pc-hdr">
      <div>
        <div class="pc-name">${esc(tgt.name || '—')}</div>
        <div class="pc-sub">${esc(tgt.object_type||'')} · mag ${tgt.magnitude??'?'} · ${tgt.angular_size_arcmin??'?'} arcmin</div>
      </div>
      <span class="pc-verdict ${approved?'ok':'warn'}">${approved?'✓ Approved':'⚠ Caveats'}</span>
    </div>

    <div class="pc-grid">
      ${tile('Best night', esc(w.date||'—'), `${esc(w.start_utc||'')}–${esc(w.end_utc||'')} UTC`,
             `<div class="score-bar"><div class="score-fill" style="width:${Math.round(sc/10*100)}%"></div></div>`)}
      ${tile('Score', `<span class="${sClass}">${sc}/10</span>`,`Limit: ${esc(w.limiting_factor||'none')}`)}
      ${tile('Window', `${w.duration_hours??'—'}h`, `Peak alt: ${w.target_max_altitude_deg??'?'}°`)}
      ${tile('Moon', `<span class="${(w.moon_illumination_pct??0)>60?'warn':'good'}">${w.moon_illumination_pct??'?'}%</span>`,
             `Sets ${esc(w.moon_set_utc||'—')} UTC`)}
      ${tile('Cloud / Seeing', `<span class="${(w.cloud_cover_pct??0)<30?'good':(w.cloud_cover_pct??0)<60?'warn':'bad'}">${w.cloud_cover_pct??'?'}%</span>`,
             `Seeing ${w.seeing_score??'?'}/5 · Transp ${w.transparency_score??'?'}/5`)}
      ${tile('Integration', `${plan.total_integration_minutes??'?'} min`,
             `${plan.recommended_sub_count??'?'} × ${plan.recommended_sub_seconds??'?'}s`)}
    </div>

    <div class="pc-sec">Imaging settings</div>
    <div>
      ${row2('Sub-exposure', `${plan.recommended_sub_seconds??'—'}s per frame`)}
      ${row2('ISO / Gain', plan.recommended_iso ? `ISO ${plan.recommended_iso}` : plan.recommended_gain ? `Gain ${plan.recommended_gain}` : '—')}
      ${row2('Filter', plan.filter_recommendation||'—')}
      ${row2('Dew risk', plan.dew_risk||'—')}
      ${row2('Dew heater', plan.dew_heater_recommended ? '✓ Recommended' : 'Not required')}
    </div>

    <div class="pc-sec">Session logistics</div>
    <div>
      ${row2('Setup time', plan.setup_time_utc ? plan.setup_time_utc+' UTC' : '—')}
      ${row2('Transit (peak)', plan.transit_time_utc ? plan.transit_time_utc+' UTC' : '—')}
      ${row2('Face direction', plan.cardinal_direction||'—')}
      ${row2('Telescope', eq.preset_name || `${eq.aperture_mm??'?'}mm f/${eq.focal_ratio??'?'} ${eq.mount_type||''}`)}
      ${row2('Mount limit', eq.max_recommended_sub_sec ? `${eq.max_recommended_sub_sec}s max sub` : '—')}
      ${bkp ? row2('Backup night', `${bkp.date} (score ${bkp.overall_score}/10)`) : ''}
    </div>

    ${plan.framing_notes ? `<div class="pc-sec">Framing</div><div>${row2('Notes', plan.framing_notes)}</div>` : ''}
    ${plan.reasoning_summary ? `<div class="pc-reason">${esc(plan.reasoning_summary)}</div>` : ''}
  `;
  card.classList.remove('hidden');
}

function tile(label, val, sub, extra='') {
  return `<div class="pc-tile">
    <div class="pc-tile-lbl">${label}</div>
    <div class="pc-tile-val">${val}</div>
    ${sub ? `<div class="pc-tile-sub">${sub}</div>` : ''}
    ${extra}
  </div>`;
}

function row2(label, val) {
  return `<div class="pc-row">
    <span class="pc-row-lbl">${esc(label)}</span>
    <span class="pc-row-val">${esc(String(val??'—'))}</span>
  </div>`;
}

function renderNights(windows) {
  const grid = document.getElementById('night-grid');
  if (!windows.length) { grid.innerHTML = '<p style="font-size:11px;color:var(--dim)">No data</p>'; return; }
  const maxS = Math.max(...windows.map(w => w.overall_score||0));
  grid.innerHTML = windows.map(w => {
    const sc = w.overall_score||0;
    const cls = sc>=7?'hi':sc>=4?'mid':'lo';
    return `<div class="n-row ${sc===maxS?'best':''}">
      <div class="n-date">${esc(w.date||'?')}${sc===maxS?' ★':''}</div>
      <span class="n-score ${cls}">${sc}/10</span>
      <div class="n-metas">
        <span class="n-meta nm-c">☁ ${w.cloud_cover_pct??'?'}%</span>
        <span class="n-meta nm-m">☽ ${w.moon_illumination_pct??'?'}%</span>
        <span class="n-meta nm-s">👁 ${w.seeing_score??'?'}/5</span>
      </div>
    </div>`;
  }).join('');
}

function renderCritique(cr) {
  const box = document.getElementById('critique-box');
  const content = document.getElementById('critique-content');
  let html = `<div class="c-item ${cr.approved?'c-ok':'c-bad'}">${esc(cr.critique_summary||'')}</div>`;
  (cr.issues||[]).forEach(i => { html += `<div class="c-item c-bad">${esc(i)}</div>`; });
  content.innerHTML = html;
  box.classList.remove('hidden');
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function setStatus(state, label) {
  const p = document.getElementById('status-pill');
  p.className = `pill ${state}`;
  p.textContent = label;
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function setupUI() {
  // Pre-fill location if user types lat,lon and hits enter
  document.getElementById('location-in').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const q = e.target.value.trim();
      if (/^-?\d+\.?\d*\s*,\s*-?\d+\.?\d*$/.test(q)) {
        const [lat, lon] = q.split(',').map(Number);
        setLocation({name:q,display:`${lat.toFixed(3)},${lon.toFixed(3)}`,lat,lon,tz_offset:0});
      }
    }
  });
}

boot();
