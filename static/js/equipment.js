/**
 * equipment.js — equipment preset chips + LLM resolver
 */
const Equipment = (() => {
  let _profile = null; // resolved EquipmentProfile
  let _preset = 'casual';

  function init() {
    // Preset chips
    document.querySelectorAll('.chip[data-preset]').forEach(chip => {
      chip.addEventListener('click', () => selectPreset(chip.dataset.preset));
    });

    // Resolve button
    document.getElementById('resolve-btn').addEventListener('click', resolveFromText);
  }

  function selectPreset(preset) {
    _preset = preset;
    document.querySelectorAll('.chip[data-preset]').forEach(c =>
      c.classList.toggle('active', c.dataset.preset === preset)
    );

    const freeWrap = document.getElementById('equipment-free-wrap');
    if (preset === 'custom') {
      freeWrap.classList.remove('hidden');
      document.getElementById('equipment-card').classList.add('hidden');
      _profile = null;
    } else {
      freeWrap.classList.add('hidden');
      // Use preset — show a simple card
      const presetCards = {
        pro:    { scope: '8" SCT / RC', camera: 'Dedicated astro cam', mount: 'Goto EQ (EQ6-R)', sub: 300, aperture: 203 },
        casual: { scope: '6" Reflector / 80mm Refractor', camera: 'DSLR (APS-C)', mount: 'EQ5 / HEQ5', sub: 90, aperture: 150 },
        mobile: { scope: 'Smartphone / Binoculars', camera: 'Smartphone', mount: 'None / Alt-Az', sub: 4, aperture: 50 },
      };
      const p = presetCards[preset];
      if (p) showPresetCard(preset, p);
      _profile = null; // will be resolved by backend on generate
    }
  }

  function showPresetCard(preset, p) {
    const card = document.getElementById('equipment-card');
    card.classList.remove('hidden');
    card.innerHTML = `
      <div class="eq-title">${p.scope}</div>
      <div class="eq-row"><span>Camera</span><span class="eq-val">${p.camera}</span></div>
      <div class="eq-row"><span>Mount</span><span class="eq-val">${p.mount}</span></div>
      <div class="eq-row"><span>Aperture</span><span class="eq-val">${p.aperture}mm</span></div>
      <div class="eq-row"><span>Max unguided sub</span><span class="eq-val">${p.sub}s</span></div>
      <span class="eq-badge eq-badge-preset">preset: ${preset}</span>`;
  }

  async function resolveFromText() {
    const raw = document.getElementById('equipment-free').value.trim();
    if (!raw) return;

    const btn = document.getElementById('resolve-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Identifying…';

    try {
      const model = document.getElementById('model-select').value;
      _profile = await API.resolveEquipment({ raw_input: raw, preset: _preset, model });
      showResolvedCard(_profile);
    } catch (e) {
      App.showError('Equipment resolution failed: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '🔍 Identify equipment';
    }
  }

  function showResolvedCard(p) {
    const card = document.getElementById('equipment-card');
    card.classList.remove('hidden');
    const badge = p.resolved_by === 'llm'
      ? `<span class="eq-badge eq-badge-llm">✓ identified by AI</span>`
      : `<span class="eq-badge eq-badge-preset">preset fallback: ${p.preset}</span>`;
    card.innerHTML = `
      <div class="eq-title">${p.scope_name}</div>
      <div class="eq-row"><span>Camera</span><span class="eq-val">${p.camera_name}</span></div>
      <div class="eq-row"><span>Mount</span><span class="eq-val">${p.mount_name}</span></div>
      <div class="eq-row"><span>Aperture</span><span class="eq-val">${p.aperture_mm}mm</span></div>
      <div class="eq-row"><span>Focal length</span><span class="eq-val">${p.focal_length_mm}mm</span></div>
      <div class="eq-row"><span>FOV</span><span class="eq-val">${p.fov_w_deg.toFixed(2)}° × ${p.fov_h_deg.toFixed(2)}°</span></div>
      <div class="eq-row"><span>Plate scale</span><span class="eq-val">${p.plate_scale_arcsec_px.toFixed(2)}"/px</span></div>
      <div class="eq-row"><span>Max unguided sub</span><span class="eq-val">${p.max_unguided_sub_sec}s</span></div>
      <div class="eq-row"><span>Limiting mag</span><span class="eq-val">${p.limiting_magnitude}</span></div>
      ${badge}`;
  }

  function getPreset()  { return _preset; }
  function getProfile() { return _profile; }
  function getRaw()     { return document.getElementById('equipment-free').value.trim(); }

  return { init, getPreset, getProfile, getRaw };
})();
