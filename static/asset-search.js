"use strict";

// Peso pairs against these currencies have a chart even when the upstream search index is down.
const PESO_BASES = 'USD|CHF|GBP|EUR|JPY|AUD|CAD|SGD|HKD|CNY|NZD|KRW|INR|AED|SAR|THB|MYR|IDR|TWD|VND';
function pesoPair(text) {
  const match = new RegExp(`^(${PESO_BASES})\\s*/?\\s*PHP(?:=X)?$`, 'i').exec(text.trim());
  if (!match) return null;
  const base = match[1].toUpperCase();
  return {symbol: `${base}PHP=X`, name: `${base}/PHP`, exchange: 'CCY'};
}

function bindAssetSearch(input, list, form, select) {
  let timer, request, rows = [], active = -1;
  function close() {
    clearTimeout(timer);
    if (request) request.abort();
    request = null;
    rows = []; active = -1;
    list.replaceChildren(); list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }
  function choose(symbol) {
    close(); input.value = symbol; select(symbol);
  }
  function show(results) {
    rows = results;
    for (const [i, row] of rows.entries()) {
      const option = document.createElement('li');
      option.id = `${list.id}-${i}`;
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      for (const [key, css] of [['symbol', 'sym'], ['name', 'name'], ['exchange', 'exch']]) {
        const span = document.createElement('span');
        span.className = `sug-${css}`; span.textContent = row[key] || ''; option.append(span);
      }
      option.addEventListener('pointerdown', ev => ev.preventDefault());
      option.addEventListener('click', () => choose(row.symbol));
      list.append(option);
    }
    list.hidden = !rows.length;
    input.setAttribute('aria-expanded', String(!list.hidden));
  }
  input.addEventListener('input', () => {
    close();
    const q = input.value.trim(), pair = pesoPair(q);
    if (pair) return show([pair]);
    if (q.length < 2) return;
    timer = setTimeout(async () => {
      const req = request = new AbortController();
      try {
        const data = await requestJSON(`/api/search?q=${encodeURIComponent(q)}`, req.signal);
        if (req === request && input.value.trim() === q) show(data.results || []);
      } catch { if (req === request) close(); }
    }, 260);
  });
  input.addEventListener('blur', close);
  input.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') return close();
    if (!rows.length || !['ArrowUp', 'ArrowDown'].includes(ev.key)) return;
    ev.preventDefault();
    const n = rows.length;
    active = ev.key === 'ArrowDown' ? (active + 1) % n : (active <= 0 ? n - 1 : active - 1);
    [...list.children].forEach((item, i) => item.setAttribute('aria-selected', String(i === active)));
    const option = list.children[active];
    input.setAttribute('aria-activedescendant', option.id);
    option.scrollIntoView({block: 'nearest'});
  });
  form.addEventListener('submit', ev => {
    ev.preventDefault();
    const q = input.value.trim();
    if (q) choose(rows[active]?.symbol || pesoPair(q)?.symbol || q);
  });
  return close;
}
