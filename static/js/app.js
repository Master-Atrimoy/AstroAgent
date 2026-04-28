/**
 * app.js — application init, tab switching, shared state
 * Must load last (depends on all other modules).
 */
const App = (() => {
  let _catPollInterval = null;

  async function init() {
    // Date in header
    document.getElementById('hdr-date').textContent =
      new Date().toLocaleDateString('en-GB', { weekday:'short', day:'numeric', month:'short', year:'numeric' });

    // Init modules
    Geocoder.init();
    Equipment.init();
    Catalogue.init();

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Check health + load models
    await checkHealth();
    await loadModels();
  }

  async function checkHealth() {
    try {
      const data = await API.health();
      const pill = document.getElementById('hdr-status');
      if (data.ollama === 'connected' || data.ollama.startsWith('connected')) {
        pill.textContent = '🟢 Ollama connected';
        pill.style.color = 'var(--green)';
      } else {
        pill.textContent = '🔴 Ollama offline';
        pill.style.color = 'var(--red)';
      }
    } catch {
      document.getElementById('hdr-status').textContent = '🔴 API offline';
    }
  }

  async function loadModels() {
    try {
      const data = await API.ollamaModels();
      const select = document.getElementById('model-select');
      const hint = document.getElementById('model-hint');
      const models = data.models || [];

      if (models.length) {
        select.innerHTML = models.map((m, i) =>
          `<option value="${m.name}">${m.name}${i === 0 ? ' ★ recommended' : ''}</option>`
        ).join('');
        hint.textContent = `${models.length} model(s) available`;
        hint.style.color = 'var(--green)';
      } else {
        hint.textContent = 'No models found — run: ollama pull llama3.2';
        hint.style.color = 'var(--red)';
      }
    } catch {
      document.getElementById('model-hint').textContent = 'Could not load models';
    }
  }

  function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.tab-pane').forEach(p =>
      p.classList.toggle('active', p.id === `pane-${tab}`));
  }

  async function onLocationChanged(location) {
    // Trigger background catalogue refresh for new location
    try {
      await API.catalogueRefresh(location.lat, location.lon);
      startCataloguePolling(location);
    } catch {}

    // Load scored catalogue for current conditions
    const aperture = 150; // default until equipment resolved
    const objects = await Catalogue.load(location.lat, location.lon, aperture, 19);
    document.getElementById('hdr-status').textContent =
      `📍 ${location.name} · ${objects.length} objects loaded`;
  }

  function startCataloguePolling(location) {
    if (_catPollInterval) clearInterval(_catPollInterval);
    _catPollInterval = setInterval(async () => {
      try {
        const status = await API.catalogueStatus();
        if (status.status === 'ready' && status.source === 'live') {
          clearInterval(_catPollInterval);
          _catPollInterval = null;
          showCatalogueBanner(status);
        }
      } catch {}
    }, 5000);
  }

  function showCatalogueBanner(status) {
    const banner = document.getElementById('cat-banner');
    const text = document.getElementById('cat-banner-text');
    banner.classList.remove('hidden');
    text.textContent = `✨ Live catalogue ready — ${status.object_count} objects loaded`;
  }

  async function applyLiveCatalogue() {
    const loc = Geocoder.getSelected();
    if (!loc) return;
    const objects = await Catalogue.load(loc.lat, loc.lon, 150, 19);
    document.getElementById('cat-banner').classList.add('hidden');
    document.getElementById('hdr-status').textContent =
      `✨ ${objects.length} live objects loaded`;
  }

  function showError(msg) {
    const el = document.getElementById('error-box');
    el.classList.toggle('hidden', !msg);
    el.textContent = msg;
  }

  // Boot
  document.addEventListener('DOMContentLoaded', init);

  return { switchTab, onLocationChanged, applyLiveCatalogue, showError };
})();
