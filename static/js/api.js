/**
 * api.js — centralised fetch layer for DeepSkyAgent
 * All backend communication goes through here.
 */
const API = (() => {
  const BASE = '';

  async function get(path, params = {}) {
    const qs = new URLSearchParams(params).toString();
    const url = `${BASE}${path}${qs ? '?' + qs : ''}`;
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function post(path, body = {}) {
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  // SSE streaming — returns an EventSource-compatible wrapper
  function stream(path, body = {}, onEvent, onDone, onError) {
    // Use fetch + ReadableStream for POST-based SSE
    fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(async res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete line
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              onEvent(data);
            } catch {}
          }
        }
      }
      onDone && onDone();
    }).catch(onError || console.error);
  }

  return {
    health:           ()           => get('/api/health'),
    searchLocations:  (q)          => get('/api/locations/search', { q }),
    ollamaModels:     ()           => get('/api/ollama/models'),
    catalogueStatus:  ()           => get('/api/catalogue/status'),
    catalogueRefresh: (lat, lon)   => get('/api/catalogue/refresh', { lat, lon }),
    catalogue:        (params)     => get('/api/catalogue', params),
    resolveEquipment: (body)       => post('/api/equipment/resolve', body),
    rightNow:         (body)       => post('/api/rightnow', body),
    planStream:       (body, onEvent, onDone, onError) =>
                        stream('/api/plan/stream', body, onEvent, onDone, onError),
  };
})();
