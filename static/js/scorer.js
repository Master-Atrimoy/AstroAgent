/**
 * scorer.js — Tab 1: Right Now instant scorer
 */
const Scorer = (() => {

  async function generate() {
    const loc = Geocoder.getSelected();
    if (!loc) { App.showError('Please select a location first.'); return; }

    const btn = document.getElementById('now-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Scoring…';
    App.showError('');

    const model = document.getElementById('model-select').value;
    const preset = Equipment.getPreset();
    const raw = Equipment.getRaw();
    const target = Catalogue.getSelected();

    try {
      const data = await API.rightNow({
        lat: loc.lat,
        lon: loc.lon,
        equipment_preset: preset,
        equipment_raw: raw,
        target_id: target ? target.id : null,
        model,
      });
      renderResults(data);
    } catch (e) {
      App.showError('Error: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '⚡ Score Right Now';
    }
  }

  function renderResults(data) {
    renderDaytimeWarning(data.twilight);
    renderNarrative(data);
    renderConditions(data.conditions);
    renderCards(data.top_targets || []);
  }

  function renderDaytimeWarning(twilight) {
    // Remove old banner if present
    const old = document.getElementById('daytime-banner');
    if (old) old.remove();
    if (!twilight) return;

    const pane = document.getElementById('pane-now');
    const banner = document.createElement('div');
    banner.id = 'daytime-banner';

    if (twilight.is_daytime) {
      banner.className = 'twilight-banner twilight-day';
      const darkTime = twilight.next_dark_start ? ' · Dark from ~' + twilight.next_dark_start.slice(11,16) + ' UTC' : '';
      banner.innerHTML = `☀️ <strong>Currently daytime</strong> (Sun ${twilight.sun_alt}° above horizon) — targets scored for tonight's dark window${darkTime}.`;
    } else if (twilight.label === 'Civil twilight') {
      banner.className = 'twilight-banner twilight-twilight';
      banner.innerHTML = `🌆 <strong>Civil twilight</strong> (Sun ${Math.abs(twilight.sun_alt)}° below horizon) — only very bright planets and Moon visible yet.`;
    } else if (twilight.label === 'Nautical twilight') {
      banner.className = 'twilight-banner twilight-twilight';
      banner.innerHTML = `🌇 <strong>Nautical twilight</strong> (Sun ${Math.abs(twilight.sun_alt)}° below horizon) — good for planets and bright clusters. DSOs improving.`;
    } else if (twilight.label === 'Astronomical twilight') {
      banner.className = 'twilight-banner twilight-twilight';
      banner.innerHTML = `🌃 <strong>Astronomical twilight</strong> (Sun ${Math.abs(twilight.sun_alt)}° below horizon) — near-dark, most deep sky objects now accessible.`;
    } else {
      return; // Dark sky — no banner needed
    }

    pane.insertBefore(banner, pane.firstChild);
  }

  function renderNarrative(data) {
    const el = document.getElementById('now-narrative');
    el.classList.remove('hidden');
    el.innerHTML = `
      <div style="margin-bottom:12px;">${data.narrative || 'Plan generated.'}</div>
      <div class="narrative-meta">
        <span class="n-pill">🤖 ${data.equipment?.scope_name || 'Unknown scope'}</span>
        <span class="n-pill">🌙 ${data.conditions?.moon_pct?.toFixed(0) || '?'}% moon</span>
        <span class="n-pill">⭐ lim. mag ${data.conditions?.limiting_mag || '?'}</span>
        <span class="n-pill">${data.conditions?.bortle || ''}</span>
        <span class="n-pill" style="margin-left:auto;color:var(--text3);">
          ${new Date(data.generated_at).toLocaleTimeString()}
        </span>
      </div>`;
  }

  function renderConditions(c) {
    if (!c) return;
    const el = document.getElementById('now-conditions');
    el.classList.remove('hidden');
    el.innerHTML = [
      { label: 'Cloud score',  value: (c.cloud_score || 0).toFixed(0) + '/100', color: 'var(--teal)' },
      { label: 'Seeing',       value: (c.seeing || 0).toFixed(1) + '/5',        color: 'var(--gold)' },
      { label: 'Transparency', value: (c.transparency || 0).toFixed(1) + '/5',  color: 'var(--accent)' },
      { label: 'Moon',         value: (c.moon_pct || 0).toFixed(0) + '% lit',   color: 'var(--text2)' },
      { label: 'Lim. mag',     value: 'mag ' + (c.limiting_mag || '?'),          color: 'var(--green)' },
    ].map(i => `
      <div class="cond-item">
        <div class="cond-label">${i.label}</div>
        <div class="cond-value" style="color:${i.color}">${i.value}</div>
      </div>`).join('');
  }

  function renderCards(targets) {
    const el = document.getElementById('now-results');
    if (!targets.length) {
      el.innerHTML = '<div style="color:var(--text3);text-align:center;padding:32px;">No visible targets found above the horizon.</div>';
      return;
    }
    const hdr = `<div style="display:flex;justify-content:space-between;margin-bottom:10px;">
      <span style="font-size:13px;font-weight:600;">Top targets right now</span>
      <span style="font-family:var(--mono);font-size:11px;color:var(--text3);">${targets.length} objects</span>
    </div>`;
    el.innerHTML = hdr + targets.map(makeCard).join('');
    el.querySelectorAll('.obj-card').forEach(card => {
      card.addEventListener('click', () => toggleCard(card));
    });
  }

  function makeCard(t) {
    const sc = scoreClass(t.score);
    const typeTag = `<span class="obj-tag t-${t.category}">${t.category.replace(/_/g,' ')}</span>`;
    const bestTag = t.score >= 75 && !t.daytime_planet ? `<span class="obj-tag t-best">🌟 best tonight</span>` : '';
    const dayTag  = t.daytime_planet ? `<span class="obj-tag t-daytime">☀️ daytime — filter needed</span>` : '';
    const moonWarn = t.moon_warning ? `<div class="moon-warning-inline">${t.moon_warning}</div>` : '';
    const scoredFor = t.scored_for && t.scored_for !== 'now'
      ? `<span class="scored-for-label">scored for ${t.scored_for}</span>` : '';
    const bars = renderBars(t.components || {});
    return `
    <div class="obj-card ${t.daytime_planet ? 'obj-card--day' : ''}" data-id="${t.id}">
      <div class="card-top">
        <div class="score-badge ${sc}">${t.score}</div>
        <div class="card-info">
          <div class="card-name">${t.name}<span class="card-id">${t.id}</span>${scoredFor}</div>
          <div class="card-meta">mag ${t.magnitude} · ${t.altitude_deg}° alt · ${t.angular_size_arcmin > 0 ? t.angular_size_arcmin+"'" : '—'}</div>
          <div class="card-tags">${typeTag}${bestTag}${dayTag}</div>
          ${moonWarn}
        </div>
        <div class="card-chevron">▼</div>
      </div>
      <div class="card-detail hidden">
        <div class="card-desc">${t.description || ''}</div>
        ${t.imaging_notes ? `<div class="card-tip">💡 ${t.imaging_notes}</div>` : ''}
        ${bars}
        <div class="card-footer">
          <span>Alt: ${t.altitude_deg}°</span><span>·</span>
          <span>Min aperture: ${t.min_aperture_mm}mm</span><span>·</span>
          <span>Source: ${t.source}</span>
        </div>
      </div>
    </div>`;
  }

  function toggleCard(card) {
    const detail = card.querySelector('.card-detail');
    const chevron = card.querySelector('.card-chevron');
    const open = card.classList.toggle('open');
    detail.classList.toggle('hidden', !open);
    chevron.textContent = open ? '▲' : '▼';
  }

  function renderBars(components) {
    const labels = { altitude:'Altitude', seeing:'Seeing', darkness:'Darkness', equipment:'Equipment', affinity:'Affinity' };
    return Object.entries(components).map(([k, v]) => `
      <div class="bar-row">
        <div class="bar-labels"><span>${labels[k]||k}</span><span>${Math.round(v*100)}</span></div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.round(v*100)}%;background:${barColor(v)};"></div></div>
      </div>`).join('');
  }

  function scoreClass(s) {
    if (s >= 75) return 'sc-ex';
    if (s >= 55) return 'sc-gd';
    if (s >= 35) return 'sc-fa';
    return 'sc-po';
  }

  function barColor(v) {
    if (v >= .75) return 'var(--green)';
    if (v >= .50) return 'var(--gold)';
    if (v >= .25) return 'var(--accent)';
    return 'var(--red)';
  }

  return { generate };
})();
