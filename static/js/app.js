(function () {
  'use strict';

  const THEME_KEY = 'bcv-theme';
  const root = document.documentElement;

  function getStoredTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  function storeTheme(theme) {
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}
  }
  function applyTheme(theme) {
    if (theme === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      const icon = btn.querySelector('.theme-icon');
      if (icon) icon.textContent = theme === 'dark' ? '☀' : '☾';
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }
  }
  function toggleTheme() {
    const current = root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    storeTheme(next);
  }

  function initTheme() {
    const stored = getStoredTheme();
    if (stored === 'dark' || stored === 'light') {
      applyTheme(stored);
      return;
    }
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(prefersDark ? 'dark' : 'light');
  }

  function bindThemeToggle() {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.addEventListener('click', toggleTheme);
  }

  /* ----- Sparkline rendering ------------------------------------------- */

  function fmtVenezuelan(v) {
    if (typeof v !== 'number' || !isFinite(v)) return '—';
    let s = v.toFixed(8);
    s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  function renderSparkline(svg, values) {
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!values || values.length < 2) {
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', '50%');
      t.setAttribute('y', '50%');
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('dominant-baseline', 'middle');
      t.setAttribute('font-size', '10');
      t.setAttribute('fill', 'currentColor');
      t.setAttribute('opacity', '0.4');
      t.textContent = '—';
      svg.appendChild(t);
      return;
    }
    const W = 100, H = 32, P = 2;
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const range = (max - min) || 1;
    const stepX = (W - 2 * P) / (values.length - 1);
    const points = values.map((v, i) => {
      const x = P + i * stepX;
      const y = H - P - ((v - min) / range) * (H - 2 * P);
      return [x, y];
    });
    const d = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' ');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', 'currentColor');
    path.setAttribute('stroke-width', '1.5');
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-linecap', 'round');
    svg.appendChild(path);

    const last = points[points.length - 1];
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', last[0]);
    c.setAttribute('cy', last[1]);
    c.setAttribute('r', '1.6');
    c.setAttribute('fill', 'currentColor');
    svg.appendChild(c);
  }

  function applySparklines() {
    document.querySelectorAll('[data-spark]').forEach(function (el) {
      try {
        const raw = el.getAttribute('data-spark');
        const values = JSON.parse(raw);
        renderSparkline(el, values);
      } catch (e) { /* ignore */ }
    });
  }

  function applyValues() {
    document.querySelectorAll('[data-bcv-value]').forEach(function (el) {
      const raw = el.getAttribute('data-bcv-value');
      const n = parseFloat(raw);
      el.textContent = isFinite(n) ? fmtVenezuelan(n) : raw;
    });
  }

  /* ----- Manual scrape trigger ---------------------------------------- */

  function bindScrapeButton() {
    const btn = document.getElementById('scrape-btn');
    if (!btn) return;
    const keyInput = document.getElementById('scrape-key');
    btn.addEventListener('click', async function () {
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Scrapeando…';
      try {
        const headers = { 'Content-Type': 'application/json' };
        if (keyInput && keyInput.value.trim()) headers['X-API-Key'] = keyInput.value.trim();
        const resp = await fetch('/api/scrape', { method: 'POST', headers: headers });
        const data = await resp.json();
        if (!resp.ok) {
          alert('Scrape falló: ' + (data.detail || resp.status));
        } else {
          window.location.reload();
        }
      } catch (e) {
        alert('Error: ' + e);
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  }

  /* ----- Calculator --------------------------------------------------- */

  const amtEl = document.getElementById('calc-amount');
  const fromEl = document.getElementById('calc-from');
  const toEl = document.getElementById('calc-to');
  const swapEl = document.getElementById('calc-swap');
  const resultValue = document.getElementById('calc-result-value');
  const resultMeta = document.getElementById('calc-result-meta');

  function fmtCalc(n) {
    if (typeof n !== 'number' || !isFinite(n)) return '—';
    let s = n.toFixed(4);
    s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  let calcTimer = null;
  async function runCalculation() {
    const amount = parseFloat(amtEl.value);
    if (!amount || amount <= 0) {
      resultValue.textContent = '—';
      resultMeta.textContent = '';
      return;
    }
    const from = fromEl.value;
    const to = toEl.value;
    try {
      const resp = await fetch('/api/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: amount, from_currency: from, to_currency: to }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        resultValue.textContent = 'Error';
        resultMeta.textContent = data.detail || '';
        return;
      }
      resultValue.textContent = fmtCalc(data.result) + ' ' + data.to_currency;
      resultMeta.textContent = 'Tasa: ' + fmtCalc(data.rate) + ' · Fecha BCV: ' + data.source_date;
    } catch (e) {
      resultValue.textContent = 'Error';
      resultMeta.textContent = e.message;
    }
  }

  function scheduleCalc() {
    if (calcTimer) clearTimeout(calcTimer);
    calcTimer = setTimeout(runCalculation, 300);
  }

  if (amtEl && fromEl && toEl) {
    amtEl.addEventListener('input', scheduleCalc);
    fromEl.addEventListener('change', runCalculation);
    toEl.addEventListener('change', runCalculation);
    if (swapEl) {
      swapEl.addEventListener('click', function () {
        const tmp = fromEl.value;
        fromEl.value = toEl.value;
        toEl.value = tmp;
        runCalculation();
      });
    }
    runCalculation();
  }

  /* ----- Boot --------------------------------------------------------- */

  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    bindThemeToggle();
    applySparklines();
    applyValues();
    bindScrapeButton();
  });
})();
