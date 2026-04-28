/**
 * planner.js — Tab 2: Plan Ahead (LangGraph SSE stream)
 */
const Planner = (() => {
  let _nightScores = [];

  async function generate() {
    const loc = Geocoder.getSelected();
    if (!loc) { App.showError('Please select a location first.'); return; }
    const target = Catalogue.getSelected();
    if (!target) { App.showError('Please select a target object first.'); return; }

    const btn = document.getElementById('ahead-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Running AstroAgent…';
    App.showError('');

    // Reset UI
    const progress = document.getElementById('agent-progress');
    const track = document.getElementById('progress-track');
    const nightGrid = document.getElementById('night-grid');
    const planOutput = document.getElementById('plan-output');
    progress.classList.remove('hidden');
    track.innerHTML = '';
    nightGrid.classList.add('hidden');
    planOutput.classList.add('hidden');
    _nightScores = [];

    const model = document.getElementById('model-select').value;

    API.planStream(
      {
        lat: loc.lat,
        lon: loc.lon,
        target_id: target.id,
        equipment_preset: Equipment.getPreset(),
        equipment_raw: Equipment.getRaw(),
        model,
        ollama_timeout: 90,
      },
      onEvent,
      () => {
        btn.disabled = false;
        btn.innerHTML = '📅 Generate 7-Night Plan';
      },
      (err) => {
        App.showError('Stream error: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = '📅 Generate 7-Night Plan';
      }
    );
  }

  function onEvent(data) {
    switch (data.event) {
      case 'start':
        addProgressItem({ agent: 'System', status: 'running', message: data.message });
        break;
      case 'progress':
        addProgressItem(data);
        break;
      case 'plan':
        renderPlan(data);
        break;
      case 'error':
        App.showError('Agent error: ' + data.message);
        addProgressItem({ agent: 'System', status: 'error', message: data.message });
        break;
      case 'done':
        addProgressItem({ agent: 'System', status: 'done', message: '✓ Pipeline complete' });
        collapseProgressWhenDone();
        break;
    }
  }

  function addProgressItem(evt) {
    const track = document.getElementById('progress-track');
    const icons = { running: '<span class="spinner"></span>', done: '✓', error: '✕', warning: '⚠' };
    const div = document.createElement('div');
    div.className = `prog-item ${evt.status || 'running'} fade-in`;
    div.innerHTML = `
      <span class="prog-icon">${icons[evt.status] || '…'}</span>
      <span class="prog-agent">${evt.agent || ''}</span>
      <span class="prog-msg">${evt.message || ''}</span>`;
    track.appendChild(div);
    // Auto-scroll only if not collapsed
    const wrapper = document.getElementById('agent-progress');
    if (!wrapper.classList.contains('collapsed')) {
      track.scrollTop = track.scrollHeight;
    }
  }

  function collapseProgressWhenDone() {
    const wrapper   = document.getElementById('agent-progress');
    const track     = document.getElementById('progress-track');
    const items     = track.querySelectorAll('.prog-item');
    const total     = items.length;
    const warnings  = track.querySelectorAll('.prog-item.warning').length;
    const loops     = track.querySelectorAll('.prog-item.warning').length; // critic loops = warning count
    const summary   = warnings > 0
      ? `${total} steps · ${warnings} critic issue(s) flagged`
      : `${total} steps · all checks passed`;

    // Build the collapsed header bar
    const header = document.createElement('div');
    header.className = 'progress-header';
    header.innerHTML = `
      <div class="progress-summary">
        <span class="ph-icon">🤖</span>
        <span class="ph-label">AstroAgent pipeline</span>
        <span class="ph-summary">${summary}</span>
      </div>
      <button class="ph-toggle" id="progress-toggle" onclick="Planner.toggleProgress()">
        Show log ▼
      </button>`;

    wrapper.insertBefore(header, track);
    wrapper.classList.add('collapsed');
  }

  function toggleProgress() {
    const wrapper = document.getElementById('agent-progress');
    const track   = document.getElementById('progress-track');
    const btn     = document.getElementById('progress-toggle');
    const collapsed = wrapper.classList.toggle('collapsed');
    btn.textContent = collapsed ? 'Show log ▼' : 'Hide log ▲';
    if (!collapsed) track.scrollTop = track.scrollHeight;
  }

  function renderPlan(data) {
    const plan = data.plan;
    const nights = data.night_scores || [];
    const equipment = data.equipment || {};
    _nightScores = nights;

    // Night grid
    renderNightGrid(nights, plan);

    // Plan output
    const el = document.getElementById('plan-output');
    el.classList.remove('hidden');
    el.innerHTML = `<div class="plan-output">
      ${renderNarrative(plan, equipment)}
      ${renderImagingParams(plan)}
      ${renderWarnings(plan.critic_warnings || [])}
      ${renderBestNight(plan.best_night, plan.backup_night)}
    </div>`;
  }

  function renderNightGrid(nights, plan) {
    const el = document.getElementById('night-grid');
    el.classList.remove('hidden');
    el.innerHTML = nights.map(n => {
      const isBest = plan.best_night && n.date === plan.best_night.date;
      const isBackup = plan.backup_night && n.date === plan.backup_night.date;
      const cls = isBest ? 'best' : isBackup ? 'backup' : '';
      const label = isBest ? '★ Best' : isBackup ? '↑ Backup' : '';
      const scoreColor = n.overall_score >= 70 ? 'var(--green)'
        : n.overall_score >= 45 ? 'var(--gold)' : 'var(--red)';
      return `
        <div class="night-tile ${cls}">
          <div class="night-date">${n.date.slice(5)}</div>
          <div class="night-score" style="color:${scoreColor}">${n.overall_score.toFixed(0)}</div>
          <div class="night-moon">🌙 ${n.moon_illumination_pct.toFixed(0)}%</div>
          ${label ? `<div class="night-label" style="color:${isBest?'var(--green)':'var(--gold)'}">${label}</div>` : ''}
        </div>`;
    }).join('');
  }

  function renderNarrative(plan, equipment) {
    return `
    <div class="plan-section">
      <div class="plan-section-title">AI Observation Plan</div>
      <div class="narrative-box">
        ${plan.narrative || 'Plan generated.'}
        <div class="narrative-meta" style="margin-top:12px;">
          <span class="n-pill">🤖 ${equipment.scope_name || 'scope'}</span>
          <span class="n-pill">📅 Best: ${plan.best_night?.date || '?'}</span>
          <span class="n-pill">🔄 Critic loops: ${plan.critique_loops || 0}</span>
        </div>
      </div>
    </div>`;
  }

  function renderImagingParams(plan) {
    const items = [
      { label: 'ISO',       value: plan.recommended_iso,     color: 'var(--gold)' },
      { label: 'Sub length',value: plan.recommended_sub_sec + 's', color: 'var(--teal)' },
      { label: 'Filter',    value: plan.recommended_filter || 'None', color: 'var(--accent)' },
      { label: 'Dew risk',  value: plan.dew_risk ? '⚠ Yes' : '✓ No',
        color: plan.dew_risk ? 'var(--red)' : 'var(--green)' },
    ];
    return `
    <div class="plan-section">
      <div class="plan-section-title">📷 Imaging Parameters</div>
      <div class="imaging-grid">
        ${items.map(i => `
          <div class="imaging-item">
            <div class="imaging-label">${i.label}</div>
            <div class="imaging-value" style="color:${i.color}">${i.value}</div>
          </div>`).join('')}
      </div>
    </div>`;
  }

  function renderWarnings(warnings) {
    if (!warnings.length) return '';
    return `
    <div class="plan-section">
      <div class="plan-section-title">⚠ Critic Warnings</div>
      <div class="warning-list">
        ${warnings.map(w => `<div class="warning-item"><span>⚠</span><span>${w}</span></div>`).join('')}
      </div>
    </div>`;
  }

  function renderBestNight(best, backup) {
    if (!best) return '';
    const row = (label, val) => `<div class="eq-row"><span>${label}</span><span class="eq-val">${val}</span></div>`;
    return `
    <div class="plan-section">
      <div class="plan-section-title">🌙 Night Details</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="equipment-card">
          <div class="eq-title" style="color:var(--green)">★ Best Night — ${best.date}</div>
          ${row('Score', best.overall_score.toFixed(1) + '/100')}
          ${row('Cloud', best.cloud_score.toFixed(0) + '/100')}
          ${row('Seeing', best.seeing_score.toFixed(0) + '/100')}
          ${row('Moon', best.moon_illumination_pct.toFixed(0) + '% lit')}
          ${best.moon_rises ? row('Moon rises', best.moon_rises) : ''}
          ${best.best_window_start ? row('Window starts', best.best_window_start + ' UTC') : ''}
        </div>
        ${backup ? `
        <div class="equipment-card">
          <div class="eq-title" style="color:var(--gold)">↑ Backup Night — ${backup.date}</div>
          ${row('Score', backup.overall_score.toFixed(1) + '/100')}
          ${row('Cloud', backup.cloud_score.toFixed(0) + '/100')}
          ${row('Moon', backup.moon_illumination_pct.toFixed(0) + '% lit')}
        </div>` : ''}
      </div>
    </div>`;
  }

  return { generate, toggleProgress };
})();
