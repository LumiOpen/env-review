'use strict';
/* env audit dashboard — vanilla SPA. All untrusted text (env sources, logs, hub metadata, rollouts)
   reaches the DOM either through textContent or through the escaping `html` template below. */

// ------------------------------------------------------------------ escaping & formatting
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
const part = (v) => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(part).join('') : (v == null || v === false) ? '' : esc(v);
function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => { out += part(v) + strings[i + 1]; });
  return new Raw(out);
}
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const main = () => document.getElementById('main');
const envHref = (k) => `/env/${encodeURIComponent(k)}`;
const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r(?!\n)/g;

const nf = new Intl.NumberFormat('en-US');
const fmtInt = (n) => n == null ? '—' : nf.format(n);
const fmtNum = (n, d = 3) => n == null || n === '' || Number.isNaN(+n) ? '—' : (+n).toFixed(d).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
const pct = (n, tot) => tot ? `${Math.round((100 * n) / tot)}%` : '';
function fmtBytes(b) {
  if (b == null) return '—';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}
function ago(sec) {
  if (sec == null) return 'unknown';
  const s = Math.max(0, Date.now() / 1000 - sec);
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
const fmtTime = (sec) => sec == null ? '—' : new Date(sec * 1000).toLocaleString();
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const truthy = (v) => v === true || String(v).toLowerCase() === 'true';

// ------------------------------------------------------------------ glossary: plain-language labels for every tag
// glossary.json (served by /api/glossary) maps each raw tag to {label, short, long, action, tone}. Every chip,
// chart label and summary sentence goes through entry(); values without an entry fall back to the raw tag and
// are logged once (console + window.glossaryMisses) so gaps are visible.
let GL = { fields: {}, categories: {}, concepts: [], how_it_works: [], caveats: [] };
let GL_USAGE = {};
let glAt = 0;
const glossaryMisses = new Set();
window.glossaryMisses = glossaryMisses;
async function loadGlossary(force = false) {
  if (!force && Date.now() - glAt < 30000) return;
  const d = await api('/api/glossary');
  GL = { fields: {}, categories: {}, concepts: [], how_it_works: [], caveats: [], ...d.glossary };
  GL_USAGE = d.usage || {};
  glAt = Date.now();
  if (Object.keys(d.missing || {}).length) console.warn('glossary.json has no entry for these values in the data:', d.missing);
}
const TONE_CLASS = { good: 'ok', warn: 'warn', bad: 'bad', neutral: 'info', unknown: 'muted' };
const MARK = { good: '✓', warn: '!', bad: '✗' };
const humanize = (v) => { const s = String(v).replace(/_/g, ' '); return s.charAt(0).toUpperCase() + s.slice(1); };
// category = "<phase>:<reason>"; phase-less values ("ok", "undeclared_dependency") are reasons
const catParts = (c) => { const s = String(c ?? ''); const i = s.lastIndexOf(':'); return i < 0 ? ['', s] : [s.slice(0, i), s.slice(i + 1)]; };
const PHASES = ['install', 'import', 'load', 'rollout', 'harness'];
const fieldTitle = (f) => f === 'category' ? 'Why it stopped' : ((GL.fields[f] || {}).title || humanize(f));
function entry(field, value) {
  const v = String(value);
  const e = field === 'category' ? GL.categories[v] : ((GL.fields[field] || {}).values || {})[v];
  if (e) return { long: null, action: null, tone: 'neutral', ...e, known: true };
  const id = `${field}:${v}`;
  if (!glossaryMisses.has(id)) { glossaryMisses.add(id); console.warn(`glossary: no entry for ${id}`); }
  return { label: humanize(v), short: 'No plain-language description for this tag yet.', long: null, action: null, tone: 'unknown', known: false };
}
// a category chip/label describes the reason; the phase is context shown in the popover
const catEntry = (c) => entry('category', catParts(c)[1]);
const toneOf = (field, v) => TONE_CLASS[(field === 'category' ? catEntry(v) : entry(field, v)).tone] || 'muted';
const labelOf = (field, v) => v == null || v === '' ? '' : (field === 'category' ? catEntry(v) : entry(field, v)).label;
// official is stored as a bool; the env table filter and overview crosstab use 'official' / 'community'
const officialKey = (v) => String(v === true || v === 'true' || v === 'official');

/* Chip: glossary label coloured by tone; hover/focus opens the explanation popover. Click opens the popover,
   or, when opts.href is set, navigates there (the hover popover still explains the tag).
   opts.raw appends the raw tag in muted code; opts.rawOnly shows just the tag (technical columns); opts.mark adds ✓/!/✗. */
function chip(field, value, opts = {}) {
  if (value == null || value === '') return dash;
  const v = String(value);
  const e = field === 'category' ? catEntry(v) : entry(field, v);
  const mark = opts.mark && MARK[e.tone] ? html`<span aria-hidden="true" class="mark">${MARK[e.tone]}</span>` : '';
  const nav = opts.href ? html` data-href="${opts.href}"` : '';
  return html`<button type="button" class="pill gchip t-${TONE_CLASS[e.tone] || 'muted'} ${opts.rawOnly ? 'rawonly' : ''} ${opts.href ? 'linked' : ''}" data-gf="${field}" data-gv="${v}" data-known="${e.known ? 1 : 0}"${nav} aria-label="${fieldTitle(field)}: ${e.label} (${v}). ${opts.href ? 'Show these environments' : 'Show explanation'}">${opts.rawOnly ? v : e.label}${mark}${opts.raw && !opts.rawOnly ? html`<code>${v}</code>` : ''}${opts.href ? html`<span aria-hidden="true" class="go"> →</span>` : ''}</button>`;
}
const chips = (field, vals, opts) => vals.length ? vals.map((v) => chip(field, v, opts)) : dash;
const VERDICT_ORDER = ['works', 'works_undeclared_deps', 'undeclared_deps', 'works_weak_reward', 'rotted', 'broken', 'hollow',
  'not_installable', 'unverifiable_here', 'listed_but_missing', 'harness', '(none)'];
const dot = (field, v) => html`<span class="dotc t-${toneOf(field, v)}"></span>`;
const dash = html`<span class="dim">—</span>`;

// ------------------------------------------------------------------ explanation popover (one shared element)
const pop = document.createElement('div');
pop.id = 'gpop';
pop.className = 'gpop';
pop.setAttribute('role', 'tooltip');
pop.hidden = true;
document.body.append(pop);
let popBtn = null;
let popPinned = false;
let popTimer;
const glossaryAnchor = (field, v) => `g-${field}-${v}`.replace(/[^A-Za-z0-9_-]/g, '_');
function popContent(field, v) {
  const e = field === 'category' ? catEntry(v) : entry(field, v);
  const [phase] = field === 'category' ? catParts(v) : [''];
  const pe = phase ? entry('category', phase) : null;
  return html`<div class="gp-head"><span class="gp-field">${fieldTitle(field)}</span><code>${v}</code></div>
    <div class="gp-label t-${TONE_CLASS[e.tone] || 'muted'}"><span class="dotc"></span>${e.label}</div>
    ${pe ? html`<p class="gp-phase">Stopped while <b>${pe.label.toLowerCase()}</b>: ${pe.short}</p>` : ''}
    <p class="gp-short">${e.short}</p>
    ${e.long ? html`<p class="gp-long">${e.long}</p>` : ''}
    ${e.action ? html`<p class="gp-action"><b>What to do</b> ${e.action}</p>` : ''}
    <a class="gp-more" href="/glossary#${glossaryAnchor(field, field === 'category' ? catParts(v)[1] : v)}">Open in glossary →</a>`;
}
function placePop(btn) {
  const r = btn.getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight, m = 8;
  let x = Math.min(Math.max(m, r.left), window.innerWidth - pw - m);
  let y = r.bottom + 6;
  if (y + ph > window.innerHeight - m && r.top - ph - 6 > m) y = r.top - ph - 6;
  pop.style.left = `${x + window.scrollX}px`;
  pop.style.top = `${y + window.scrollY}px`;
}
function showPop(btn, pin) {
  clearTimeout(popTimer);
  if (popBtn && popBtn !== btn) hidePop();
  popBtn = btn;
  popPinned = popPinned || pin;
  pop.innerHTML = popContent(btn.dataset.gf, btn.dataset.gv).s;
  pop.hidden = false;
  btn.setAttribute('aria-describedby', 'gpop');
  btn.setAttribute('aria-expanded', 'true');
  placePop(btn);
}
function hidePop() {
  clearTimeout(popTimer);
  pop.hidden = true;
  popPinned = false;
  if (popBtn) { popBtn.removeAttribute('aria-describedby'); popBtn.setAttribute('aria-expanded', 'false'); }
  popBtn = null;
}
const softHide = () => { if (!popPinned) { clearTimeout(popTimer); popTimer = setTimeout(hidePop, 160); } };
document.addEventListener('mouseover', (e) => {
  const b = e.target.closest('.gchip');
  if (b) { if (b !== popBtn) { clearTimeout(popTimer); popTimer = setTimeout(() => showPop(b, false), 220); } else clearTimeout(popTimer); return; }
  if (e.target.closest('#gpop')) { clearTimeout(popTimer); return; }
  if (popBtn) softHide(); else clearTimeout(popTimer);
});
document.addEventListener('focusin', (e) => { const b = e.target.closest('.gchip'); if (b) showPop(b, false); else if (!e.target.closest('#gpop')) softHide(); });
document.addEventListener('click', (e) => {
  const b = e.target.closest('.gchip');
  // chips sit inside clickable table rows: swallow the click so it only toggles the popover
  if (b && b.dataset.href) { e.preventDefault(); e.stopPropagation(); hidePop(); go(b.dataset.href); return; }
  if (b) { e.preventDefault(); e.stopPropagation(); if (popBtn === b && popPinned) hidePop(); else showPop(b, true); return; }
  if (!e.target.closest('#gpop') && popBtn) hidePop();
}, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && popBtn) { const b = popBtn; hidePop(); b.focus(); } });
window.addEventListener('resize', () => { if (popBtn) placePop(popBtn); });

// ------------------------------------------------------------------ data access
async function api(path) {
  const r = await fetch(path, { headers: { accept: 'application/json' } });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* non-JSON error body */ }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json();
}

// ------------------------------------------------------------------ router
let seq = 0;
function go(url) { history.pushState({}, '', url); route(); window.scrollTo(0, 0); }
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href]');
  if (!a || a.target || a.hasAttribute('download') || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const u = new URL(a.href, location.href);
  if (u.origin !== location.origin || u.pathname.startsWith('/api/') || u.pathname.startsWith('/static/')) return;
  if (u.pathname === location.pathname && u.search === location.search && u.hash) return; // in-page anchor
  e.preventDefault();
  go(u.pathname + u.search + u.hash);
});
window.addEventListener('popstate', route);

function setNav(which) {
  $$('.nav a').forEach((a) => { if (a.dataset.nav === which) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
}

const VIEWS = {
  '/': ['start', renderStart, 'Start here'],
  '/overview': ['overview', renderOverview, 'Charts'],
  '/envs': ['envs', renderEnvs, 'Environments'],
  '/glossary': ['glossary', renderGlossary, 'Glossary'],
};
async function route() {
  const p = location.pathname;
  const my = ++seq;
  hidePop();
  const view = VIEWS[p] || (p.startsWith('/env/') ? ['envs', (m) => renderEnv(decodeURIComponent(p.slice(5)), m), null] : null);
  if (!view) { main().innerHTML = html`<div class="state">No such page. <a href="/">Back to the start page</a></div>`.s; return; }
  setNav(view[0]);
  if (view[2]) document.title = `${view[2]} · Hub environment audit`;
  main().innerHTML = html`<div class="state">Loading…</div>`.s;
  try {
    await loadGlossary();
    await view[1](my);
  } catch (err) {
    if (my !== seq) return;
    main().innerHTML = html`<div class="state error">Could not load: ${err.message}<br><button type="button" id="retry">Retry</button></div>`.s;
    $('#retry').onclick = route;
  }
  refreshFreshness();
}

// ------------------------------------------------------------------ freshness badge
function collectedAt(f) {
  const raw = f.last_collect;
  if (raw) {
    const n = Number(raw);
    if (Number.isFinite(n) && n > 1e9) return n > 1e12 ? n / 1000 : n;
    const d = Date.parse(raw);
    if (!Number.isNaN(d)) return d / 1000;
  }
  return f.last_collect_mtime ?? f.newest_mtime;
}
async function refreshFreshness() {
  const el = $('#fresh');
  try {
    const f = await api('/api/freshness');
    const t = collectedAt(f);
    const age = t == null ? null : Date.now() / 1000 - t;
    el.className = `fresh ${age == null ? 'unknown' : age > 15 * 60 ? 'stale' : ''}`;
    const src = f.last_collect ? '.last_collect' : 'newest data file (.last_collect missing)';
    el.innerHTML = html`<span class="dot"></span><span>data ${ago(t)}</span>`.s;
    el.title = `${src}: ${fmtTime(t)}\n` + f.files.map((x) => `${x.name}: ${x.exists ? fmtTime(x.mtime) : 'missing'}`).join('\n');
  } catch {
    el.className = 'fresh unknown';
    el.textContent = 'server unreachable';
  }
}
setInterval(refreshFreshness, 60000);

// ------------------------------------------------------------------ charts
const NOT_RECORDED = new Set(['(none)', '?', '(unknown)']);
function chartLabel(field, v) {
  if (NOT_RECORDED.has(v)) return 'Not recorded';
  if (field === 'official') return entry('official', officialKey(v)).label;
  if (field === 'category') {
    const [ph, rs] = catParts(v);
    return ph ? `${entry('category', ph).label} → ${entry('category', rs).label}` : entry('category', rs).label;
  }
  return entry(field, v).label;
}
const chartTone = (field, v) => NOT_RECORDED.has(v) ? 'muted' : field === 'official' ? toneOf('official', officialKey(v)) : toneOf(field, v);

// horizontal bars; head = [what the label column is, what the count is]
function bars(items, field, hrefFn, head = ['', 'Envs']) {
  if (!items || !items.length) return html`<div class="empty">No data yet.</div>`;
  const max = Math.max(1, ...items.map((i) => i.n));
  const tot = items.reduce((s, i) => s + i.n, 0);
  return html`<div class="bars"><div class="br bh" aria-hidden="true"><span>${head[0]}</span><span></span><span>${head[1]}</span><span>share</span></div>${items.map((i) => {
    const lab = chartLabel(field, i.label);
    const inner = html`<span class="bl" title="${lab} — raw tag: ${i.label}"><span class="dotc t-${chartTone(field, i.label)}"></span>${lab}</span><svg class="bt" aria-hidden="true"><rect class="f-track" width="100%" height="100%" rx="2"/><rect class="f-${chartTone(field, i.label)}" width="${((100 * i.n) / max).toFixed(2)}%" height="100%" rx="2"/></svg><span class="bn">${fmtInt(i.n)}</span><span class="bp">${pct(i.n, tot)}</span>`;
    return hrefFn ? html`<a class="br" href="${hrefFn(i.label)}">${inner}</a>` : html`<div class="br">${inner}</div>`;
  })}</div>`;
}

// one 100%-wide bar per row, split by verdict; rowField labels the rows
function stacked(rows, rowField, hrefFn) {
  if (!rows || !rows.length) return html`<div class="empty">No data yet.</div>`;
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r.parts)))]
    .sort((a, b) => (VERDICT_ORDER.indexOf(a) + 1 || 99) - (VERDICT_ORDER.indexOf(b) + 1 || 99));
  return html`<div class="stack">${rows.map((r) => {
    let x = 0;
    const lab = chartLabel(rowField, r.label);
    const segs = keys.filter((k) => r.parts[k]).map((k) => {
      const w = (100 * r.parts[k]) / r.n;
      const seg = html`<rect class="f-${chartTone('verdict', k)}" x="${x.toFixed(2)}%" width="${w.toFixed(2)}%" height="100%"><title>${chartLabel('verdict', k)}: ${r.parts[k]} (${pct(r.parts[k], r.n)})</title></rect>`;
      x += w;
      return seg;
    });
    return html`<a class="bl" href="${hrefFn(r.label)}" title="raw tag: ${r.label}">${lab}</a><svg role="img" aria-label="${lab}: ${keys.filter((k) => r.parts[k]).map((k) => `${chartLabel('verdict', k)} ${r.parts[k]}`).join(', ')}">${segs}</svg><span class="bn">${fmtInt(r.n)}</span>`;
  })}</div><div class="legend">${keys.map((k) => html`<span title="raw tag: ${k}">${dot('verdict', k)}${chartLabel('verdict', k)}</span>`)}</div>`;
}

const panel = (title, caption, body, opts = {}) => html`<section class="panel ${opts.cls || ''}" ${opts.id ? html`id="${opts.id}"` : ''}><header><h2>${title}</h2>${opts.hint ? html`<span class="hint">${opts.hint}</span>` : ''}</header>${caption ? html`<p class="caption">${caption}</p>` : ''}${body}</section>`;
const envsQ = (k, v) => `/envs?${new URLSearchParams({ [k]: v })}`;

// ------------------------------------------------------------------ charts page
async function renderOverview(my) {
  const d = await api('/api/overview');
  if (my !== seq) return;
  const t = d.totals;
  const q = envsQ;
  const fr = d.freshness;
  main().innerHTML = html`
    <div class="pagehead"><h1>Charts</h1>
      <div class="statline">
        <span><b>${fmtInt(t.envs)}</b>environments on the hub</span><span><b>${fmtInt(t.stage1)}</b>run-tested</span>
        <span><b>${fmtInt(t.stage2)}</b>score-checked</span><span><b>${fmtInt(t.audited_keys)}</b>hand-reviewed</span>
        <span><b>${fmtInt(t.hollow_scan_keys)}</b>flagged by the fake-score scan</span><span><b>${fmtInt(t.gold_reviews)}</b>score reviews</span>
      </div>
      <p class="caption wide">Every bar is clickable and opens the matching environments. Hover a label for its raw tag; the <a href="/glossary">glossary</a> explains each one.</p></div>
    <div class="grid">
      ${panel('What happened to each environment', 'The overall result for every environment on the hub, combining all our tests.', bars(d.verdict, 'verdict', (v) => q('verdict', v), ['Result', 'Envs']), { hint: 'stage01.csv' })}
      ${panel('Did it install and run?', 'Installing it like a user would, then running 5 tasks twice with a fake model.', bars(d.status, 'status', (v) => q('status', v), ['Run result', 'Envs']), { hint: 'stage1.csv' })}
      ${panel('Where runs stopped', 'For environments that did not run cleanly: the step they got stuck on.', bars(d.phase, 'category', (v) => q('cat', v), ['Step', 'Envs']), { hint: 'phase of non-passing runs' })}
      ${panel('Most common reasons runs stopped', 'Step → reason, for the 20 most common. Includes things we could not provide (credentials, sandboxes), which are not defects.', bars(d.category, 'category', (v) => q('cat', v), ['Step → reason', 'Envs']), { hint: 'phase:reason' })}
      ${panel('Does a correct answer score higher than nonsense?', 'For environments that ran: we fed in the env’s own reference answers and compared the score against a nonsense answer. A healthy env scores the correct answer clearly higher.', d.scaling.length ? html`${bars(d.scaling, 'scaling', (v) => q('scaling', v), ['Score check', 'Envs'])}${d.gold_best_fmt.length ? html`<div class="label">Answer format that got through best</div>${bars(d.gold_best_fmt, 'gold_best_fmt', null, ['Format', 'Envs'])}` : ''}` : html`<div class="empty"><b>No score-check results yet.</b> They appear once the first runs are collected.</div>`, { hint: 'stage2_gold.csv' })}
      ${panel('Official vs community', 'How results differ between environments published by Prime Intellect and everyone else. Each bar is 100% of that group.', stacked(d.official, 'official', (v) => q('official', v)), { hint: 'result mix' })}
      ${panel('Older vs newer library API', 'Environments built on the older or the newer version of the verifiers library they depend on.', stacked(d.runtime, 'runtime', (v) => q('runtime', v)), { hint: 'hub runtime label' })}
      ${panel('Hand review of sampled findings', 'Reviewers re-checked a sample of failures and suspicious envs: is it a real problem with the environment, or caused by our test setup?', bars(d.audit, 'audit_verdict', (v) => q('audit', v), ['Review finding', 'Reviews']), { hint: `${fmtInt(t.audit_entries)} reviews` })}
      ${panel('Warning signs of fake scoring', 'Patterns a code scan flagged as possibly faking the reward or the data. Leads for review, not verdicts.', bars(d.hollow_flags, 'hollow_flags', (v) => q('q', v), ['Warning sign', 'Envs']), { hint: 'hollow.csv' })}
      ${panel('Why scores looked off', `When a correct answer did not clearly beat nonsense, a reviewer found out why. ${fmtInt(d.gold_review_genuine)} turned out to be real scoring problems.`, d.gold_review_cause.length ? bars(d.gold_review_cause, 'gold_review_cause', (v) => q('q', v), ['Reviewer finding', 'Reviews']) : html`<div class="empty"><b>No score reviews yet.</b></div>`, { hint: 'gold_review_*.jsonl' })}
      ${panel('Data freshness', 'When each underlying data file was last updated. The page reads them live.', html`
        <table class="ftable"><thead><tr><th>file</th><th>modified</th><th class="num">size</th></tr></thead><tbody>
        ${fr.files.map((f) => html`<tr><td class="mono">${f.name}</td><td title="${fmtTime(f.mtime)}">${f.exists ? ago(f.mtime) : html`<span class="dim">missing</span>`}</td><td class="num">${f.exists ? fmtBytes(f.size) : ''}</td></tr>`)}
        </tbody></table>`, { hint: fr.last_collect ? `.last_collect: ${fr.last_collect}` : '.last_collect missing' })}
    </div>`.s;
}

// ------------------------------------------------------------------ plain-language row helpers (table + detail)
const split = (v, sep) => (v ? String(v).split(sep).filter(Boolean) : []);
const GENUINE_CAUSES = new Set(['grader_bug', 'reward_not_correctness']);
const SUSPECT_SCALING = new Set(['flat', 'weak', 'inverted']);
// the single most useful "why" for a row: reviewer finding on suspicious scores > fake-score sign > where the run stopped
function whyOf(r) {
  const causes = split(r.gold_review_cause, ' | ');
  if (causes.length && SUSPECT_SCALING.has(r.scaling)) return ['gold_review_cause', causes.find((c) => GENUINE_CAUSES.has(c)) || causes[0]];
  if (r.group === 'hollow') { const f = split(r.hollow_flags, ';')[0]; return f ? ['hollow_flags', f] : ['audit_verdict', 'hollow']; }
  if (r.category && r.category !== 'ok') return ['category', r.category];
  return null;
}
// result groups: a partition of all envs computed server-side (row.group); the Start page counts the same thing
const GROUPS = [
  { id: 'works', label: 'Works', verdict: 'works' },
  { id: 'broken', label: 'Broken', verdict: 'broken' },
  { id: 'rotted', label: 'Broke after an update (rotted)', verdict: 'rotted' },
  { id: 'hollow', label: 'Fake scores (hollow)', verdict: 'hollow' },
  { id: 'unverifiable', label: 'Can’t verify', verdict: 'unverifiable_here' },
  { id: 'other', label: 'Not tested', verdict: 'harness' },
];

// ------------------------------------------------------------------ env table
const envCell = (r) => html`<a href="${envHref(r.key)}">${r.name || r.key}</a><span class="by">${r.owner}</span>`;
const PLAIN_COLS = [
  { k: 'key', label: 'Environment', cls: 'k', cell: envCell, title: (r) => r.description || r.key },
  { k: 'official', label: 'Who made it', cell: (r) => chip('official', officialKey(r.official)), sortv: (r) => (r.official ? 0 : 1) },
  { k: 'verdict', label: 'Result', cell: (r) => html`${chip('verdict', r.verdict)}${r.group === 'hollow' && r.verdict !== 'hollow' ? chip('audit_verdict', 'hollow') : ''}`, sortv: (r) => labelOf('verdict', r.verdict) },
  { k: 'why', label: 'Why', cell: (r) => { const w = whyOf(r); return w ? chip(w[0], w[1]) : dash; }, sortv: (r) => { const w = whyOf(r); return w ? labelOf(w[0], w[1]) : null; } },
  { k: 'scaling', label: 'Score check', cell: (r) => chip('scaling', r.scaling, { mark: true }), sortv: (r) => labelOf('scaling', r.scaling) },
];
const RAW_TAG = { rawOnly: true };
const TECH_COLS = [
  { k: 'key', label: 'env', cls: 'k mono', cell: (r) => html`<a href="${envHref(r.key)}">${r.key}</a>`, title: (r) => r.key },
  { k: 'owner', label: 'owner' },
  { k: 'runtime', label: 'rt', cell: (r) => chip('runtime', r.runtime, RAW_TAG) },
  { k: 'verdict', label: 'verdict', cell: (r) => chip('verdict', r.verdict, RAW_TAG) },
  { k: 'status', label: 's1 status', cell: (r) => chip('status', r.status, RAW_TAG) },
  { k: 'category', label: 's1 category', cls: 'cat', title: (r) => r.category || '' },
  { k: 'garbage_mean', label: 'garbage', num: true },
  { k: 'gold_best_mean', label: 'gold best', num: true, cell: (r) => html`${fmtNum(r.gold_best_mean)}${r.gold_best_fmt ? html`<span class="fmt">${r.gold_best_fmt}</span>` : ''}` },
  { k: 'scaling', label: 'scaling', cell: (r) => chip('scaling', r.scaling, RAW_TAG) },
  { k: 'audit_verdict', label: 'audit', cell: (r) => chips('audit_verdict', split(r.audit_verdict, '+'), RAW_TAG) },
  { k: 'gold_review_cause', label: 'gold review', cell: (r) => r.gold_review_cause ? html`${r.gold_review_genuine ? chip('gold_review_genuine', 'true', RAW_TAG) : ''}${chips('gold_review_cause', split(r.gold_review_cause, ' | '), RAW_TAG)}` : dash },
];
const EXPORT_EXTRA = ['name', 'group', 'official', 'api', 'verifiers', 'error', 'gold_best_fmt', 'gold_hit_rate', 'gold_review_genuine', 'hollow_flags', 'stars', 'asof_status'];
const phaseOf = (c) => c ? catParts(c)[0] || c : null;
const ANY = '*any*';
const NONE = '(none)';
const FILTERS = [
  { k: 'verdict', label: 'Result', field: 'verdict', val: (r) => r.verdict },
  { k: 'status', label: 'Run test', field: 'status', val: (r) => r.status },
  // phase from the dropdown; deep links may also carry a full "phase:reason" or a bare reason
  { k: 'cat', label: 'Stopped while', field: 'category', val: (r) => phaseOf(r.category), match: (r, v) => v === NONE ? !r.category : r.category === v || (r.category || '').startsWith(`${v}:`) || (r.category || '').endsWith(`:${v}`) },
  { k: 'scaling', label: 'Score check', field: 'scaling', val: (r) => r.scaling },
  { k: 'official', label: 'Who made it', field: 'official', val: (r) => r.official ? 'official' : 'community' },
  { k: 'runtime', label: 'Library version', field: 'runtime', val: (r) => r.runtime },
  { k: 'audit', label: 'Review finding', field: 'audit_verdict', multi: true, val: (r) => split(r.audit_verdict, '+') },
  { k: 'review', label: 'Score review', field: 'gold_review_cause', multi: true, val: (r) => split(r.gold_review_cause, ' | ') },
];

function matches(r, f, v) {
  if (!v) return true;
  if (f.multi) {
    const vals = f.val(r);
    return v === ANY ? vals.length > 0 : v === NONE ? vals.length === 0 : vals.includes(v);
  }
  if (f.match) return f.match(r, v);
  const x = f.val(r);
  return v === NONE ? x == null || x === '' : x === v;
}

async function renderEnvs(my) {
  const d = await api('/api/envs');
  if (my !== seq) return;
  const rows = d.rows.map((a) => Object.fromEntries(d.columns.map((c, i) => [c, a[i]])));
  rows.forEach((r) => {
    const w = whyOf(r);
    r._hay = [r.key, r.owner, r.name, r.description, r.error, r.category, r.verdict, r.gold_review_cause, r.hollow_flags, r.audit_verdict,
      r.gold_best_fmt, labelOf('verdict', r.verdict), labelOf('scaling', r.scaling), w && labelOf(w[0], w[1])]
      .filter(Boolean).join(' ').toLowerCase();
  });
  const params = new URLSearchParams(location.search);
  const st = {
    q: params.get('q') || '', sort: params.get('sort') || 'key', dir: params.get('dir') === 'desc' ? -1 : 1, f: {},
    show: GROUPS.some((g) => g.id === params.get('show')) ? params.get('show') : '', tech: params.get('cols') === 'tech',
  };
  FILTERS.forEach((f) => { st.f[f.k] = params.get(f.k) || ''; });
  const cols = () => (st.tech ? TECH_COLS : PLAIN_COLS);

  main().innerHTML = html`
    <div class="pagehead"><h1>Environments</h1><p class="caption wide">Every environment on the hub with our result. Click a coloured tag for what it means, or a row for the full story.</p></div>
    <div class="presets" role="group" aria-label="Quick filters">
      ${GROUPS.map((g) => html`<button type="button" class="preset t-${toneOf('verdict', g.verdict)}" data-show="${g.id}" aria-pressed="false"><span class="dotc"></span>${g.label}<span class="n" data-n="${g.id}"></span></button>`)}
      <span class="sep" aria-hidden="true"></span>
      <button type="button" class="preset t-info" id="p-official" aria-pressed="false">Official envs<span class="n" id="n-official"></span></button>
    </div>
    <div class="toolbar" role="search">
      <div class="field"><label for="q">Search</label><input id="q" type="search" placeholder="name, owner, error, reason…" value="${st.q}" autocomplete="off" spellcheck="false"></div>
      ${FILTERS.map((f) => html`<div class="field"><label for="f-${f.k}">${f.label}</label><select id="f-${f.k}" data-f="${f.k}"></select></div>`)}
      <button type="button" class="ghost" id="clear">Clear</button>
      <span class="count" id="count"></span>
      <button type="button" id="tech" aria-pressed="${st.tech}" title="Show the raw tags and scores used by the audit tooling">Technical columns</button>
      <button type="button" id="csv">Export CSV</button>
    </div>
    <div class="tablewrap"><table class="envs"><thead><tr id="thr"></tr></thead><tbody id="tb"></tbody></table></div>`.s;

  const head = () => {
    $('#thr').innerHTML = cols().map((c) => html`<th class="${c.num ? 'num' : ''}" data-k="${c.k}"><button type="button">${c.label}</button></th>`.s).join('');
  };
  let view = [];
  const apply = () => {
    const q = st.q.trim().toLowerCase();
    const terms = q ? q.split(/\s+/) : [];
    const pass = (r, skip) => (skip === 'show' || !st.show || r.group === st.show)
      && FILTERS.every((f) => f.k === skip || matches(r, f, st.f[f.k])) && terms.every((t) => r._hay.includes(t));
    // faceted option counts: each dropdown counts rows passing every *other* filter
    FILTERS.forEach((f) => {
      const sel = $(`#f-${f.k}`);
      const c = new Map();
      let anyN = 0;
      rows.forEach((r) => {
        if (!pass(r, f.k)) return;
        const v = f.val(r);
        const vs = f.multi ? (v.length ? v : [NONE]) : [v == null || v === '' ? NONE : v];
        if (f.multi && v.length) anyN++;
        vs.forEach((x) => c.set(x, (c.get(x) || 0) + 1));
      });
      const cur = st.f[f.k];
      if (cur && cur !== ANY && !c.has(cur)) c.set(cur, 0); // keep deep-linked values (e.g. a full category) selectable
      const opts = [...c.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
      sel.innerHTML = html`<option value="">All</option>${f.multi ? html`<option value="${ANY}">Any (${anyN})</option>` : ''}${opts.map(([v, n]) => html`<option value="${v}">${chartLabel(f.field, v)} (${n})</option>`)}`.s;
      sel.value = cur;
      sel.classList.toggle('on', !!cur);
    });
    // preset counts follow the other filters too
    const gn = new Map();
    rows.forEach((r) => { if (pass(r, 'show')) gn.set(r.group, (gn.get(r.group) || 0) + 1); });
    $$('[data-show]').forEach((b) => {
      b.setAttribute('aria-pressed', String(b.dataset.show === st.show));
      $(`[data-n="${b.dataset.show}"]`).textContent = fmtInt(gn.get(b.dataset.show) || 0);
    });
    $('#p-official').setAttribute('aria-pressed', String(st.f.official === 'official'));
    $('#n-official').textContent = fmtInt(rows.filter((r) => r.official && pass(r, 'official')).length);
    $('#q').classList.toggle('on', !!q);
    view = rows.filter((r) => pass(r, null));
    const col = cols().find((c) => c.k === st.sort) || cols()[0];
    const k = col.k;
    const sv = col.sortv || ((r) => r[k]);
    view.sort((a, b) => {
      const x = sv(a), y = sv(b);
      const xn = x == null || x === '', yn = y == null || y === '';
      if (xn || yn) return xn === yn ? a.key.localeCompare(b.key) : xn ? 1 : -1; // empties always last
      const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
      return (c || a.key.localeCompare(b.key)) * st.dir;
    });
    $$('th[data-k]').forEach((th) => {
      if (th.dataset.k === k) th.setAttribute('aria-sort', st.dir > 0 ? 'ascending' : 'descending'); else th.removeAttribute('aria-sort');
    });
    const cs = cols();
    $('#tb').innerHTML = view.length
      ? view.map((r) => html`<tr data-key="${r.key}">${cs.map((c) => html`<td class="${c.cls || ''} ${c.num ? 'num' : ''}" ${c.title ? html`title="${c.title(r)}"` : ''}>${c.cell ? c.cell(r) : c.num ? fmtNum(r[c.k]) : (r[c.k] ?? dash)}</td>`)}</tr>`.s).join('')
      : html`<tr><td colspan="${cs.length}" class="empty">No environment matches these filters. <a href="/envs">Clear all filters</a></td></tr>`.s;
    $('#count').innerHTML = html`<b>${fmtInt(view.length)}</b> of ${fmtInt(rows.length)}`.s;
    const p = new URLSearchParams();
    if (st.show) p.set('show', st.show);
    if (st.q) p.set('q', st.q);
    FILTERS.forEach((f) => { if (st.f[f.k]) p.set(f.k, st.f[f.k]); });
    if (st.sort !== 'key') p.set('sort', st.sort);
    if (st.dir < 0) p.set('dir', 'desc');
    if (st.tech) p.set('cols', 'tech');
    const qs = p.toString();
    history.replaceState({}, '', `/envs${qs ? `?${qs}` : ''}`);
  };

  let timer;
  $('#q').addEventListener('input', (e) => { st.q = e.target.value; clearTimeout(timer); timer = setTimeout(apply, 120); });
  $$('select[data-f]').forEach((s) => s.addEventListener('change', () => { st.f[s.dataset.f] = s.value; apply(); }));
  $$('[data-show]').forEach((b) => { b.onclick = () => { st.show = st.show === b.dataset.show ? '' : b.dataset.show; apply(); }; });
  $('#p-official').onclick = () => { st.f.official = st.f.official === 'official' ? '' : 'official'; apply(); };
  $('#clear').onclick = () => { st.q = ''; st.show = ''; $('#q').value = ''; FILTERS.forEach((f) => { st.f[f.k] = ''; }); apply(); };
  $('#tech').onclick = () => {
    st.tech = !st.tech;
    $('#tech').setAttribute('aria-pressed', String(st.tech));
    if (!cols().some((c) => c.k === st.sort)) { st.sort = 'key'; st.dir = 1; }
    head();
    apply();
  };
  $('#thr').addEventListener('click', (e) => {
    const th = e.target.closest('th[data-k]');
    if (!th) return;
    const k = th.dataset.k;
    if (st.sort === k) st.dir = -st.dir; else { st.sort = k; st.dir = cols().find((c) => c.k === k).num ? -1 : 1; }
    apply();
  });
  $('#tb').addEventListener('click', (e) => {
    if (e.target.closest('a, button')) return;
    const tr = e.target.closest('tr[data-key]');
    if (tr && !window.getSelection().toString()) go(envHref(tr.dataset.key));
  });
  $('#csv').onclick = () => exportCsv(view);
  head();
  apply();
}

function exportCsv(view) {
  const keys = [...new Set([...TECH_COLS.map((c) => c.k), ...EXPORT_EXTRA])];
  // plain-language columns first, so the file reads like the default table
  const plain = { result: (r) => labelOf('verdict', r.verdict), why: (r) => { const w = whyOf(r); return w ? labelOf(w[0], w[1]) : ''; }, score_check: (r) => labelOf('scaling', r.scaling) };
  const cell = (v) => {
    let s = v == null ? '' : String(v);
    if (/^[=@]|^[+-][^\d.]/.test(s)) s = `'${s}`; // spreadsheet formula-injection guard
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = ['key', ...Object.keys(plain), ...keys.filter((k) => k !== 'key')];
  const text = [header.join(','), ...view.map((r) => header.map((c) => cell(plain[c] ? plain[c](r) : r[c])).join(','))].join('\n') + '\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  a.download = `env_audit_${view.length}_envs.csv`;
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

// ------------------------------------------------------------------ env detail
const kv = (pairs) => {
  const rows = pairs.filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && !v.length));
  return rows.length ? html`<dl class="kv">${rows.map(([k, v, mono]) => html`<dt>${k}</dt><dd class="${mono ? 'mono' : ''}">${v instanceof Raw ? v : typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>`)}</dl>` : html`<div class="empty">Nothing recorded.</div>`;
};
const jsonBlock = (o) => html`<pre class="block">${JSON.stringify(o, null, 1)}</pre>`;
const section = (id, title, hint, body, cls = '') => html`<section class="panel ${cls}" id="${id}"><header><h2>${title}</h2><span class="hint">${hint || ''}</span></header>${body}</section>`;

function phasesTable(phases) {
  if (!phases || !Object.keys(phases).length) return html`<div class="empty">No phase data.</div>`;
  const SKIP = new Set(['ok', 'seconds', 'error', 'log_tail', 'result_files']);
  return html`<table class="phases"><thead><tr><th>phase</th><th>ok</th><th class="num">sec</th><th>detail</th></tr></thead><tbody>
    ${Object.entries(phases).map(([name, p]) => {
      const extra = Object.entries(p).filter(([k, v]) => !SKIP.has(k) && v != null && typeof v !== 'object').map(([k, v]) => `${k}=${isNum(v) ? fmtNum(v) : v}`).join('  ');
      return html`<tr><td class="ph">${name}</td><td>${p.ok ? html`<span class="pill t-ok">ok</span>` : html`<span class="pill t-bad">fail</span>`}</td><td class="num">${fmtNum(p.seconds, 1)}</td><td>
        ${p.error ? html`<pre class="errtext">${p.error}</pre>` : ''}
        ${extra ? html`<div class="extra">${extra}</div>` : ''}
        ${p.result_files && p.result_files.length ? html`<div class="extra dim">${p.result_files.join(', ')}</div>` : ''}
        ${p.log_tail ? html`<details><summary>log tail</summary><pre class="block">${p.log_tail.replace(ANSI, '')}</pre></details>` : ''}
      </td></tr>`;
    })}</tbody></table>`;
}

function goldSection(d) {
  const g = d.stage2_result && d.stage2_result.gold;
  const s2 = d.stage2 || {};
  if (!g) {
    const st = d.row && d.row.status;
    if (st === 'pass' || st === 'pass_with_fixes') return html`<div class="empty"><b>Not in stage 2 yet.</b> This env passed stage 1, so the gold run should reach it — stage2_gold/${d.key} doesn't exist yet.</div>`;
    return html`<div class="empty"><b>Not run in stage 2.</b> Stage 2 only runs envs that pass stage 1${st ? html`; this one is ${chip('status', st, { raw: true })}` : ''}.</div>`;
  }
  if (g.skipped) return kv([['skipped', g.skipped], ['garbage mean', fmtNum(g.garbage_mean)]]);
  const fmts = ['raw', 'boxed', 'xml', 'parser', 'custom'].filter((f) => g[f] && typeof g[f] === 'object');
  const vals = [g.garbage_mean, ...fmts.map((f) => g[f].reward_mean)].filter(isNum);
  const max = Math.max(1, ...vals.map(Math.abs));
  const w = (v) => isNum(v) ? ((100 * Math.max(0, v)) / max).toFixed(2) : 0;
  const best = s2.gold_best_fmt;
  const chart = html`<div class="goldchart" role="img" aria-label="reward by answer format: garbage ${fmtNum(g.garbage_mean)}, ${fmts.map((f) => `${f} ${fmtNum(g[f].reward_mean)}`).join(', ')}">
    <span class="lbl garbage">garbage</span><svg aria-hidden="true"><rect class="f-track" width="100%" height="100%" rx="2"/><rect class="f-muted" width="${w(g.garbage_mean)}%" height="100%" rx="2"/></svg><span class="num">${fmtNum(g.garbage_mean)}</span>
    ${fmts.map((f) => { const r = g[f]; const hit = r.gold_hits > 0; return html`<span class="lbl">${f}${f === best ? ' ★' : ''}${hit ? '' : html` <span class="dim">no hits</span>`}</span><svg aria-hidden="true"><rect class="f-track" width="100%" height="100%" rx="2"/><rect class="${hit ? (f === best ? 'f-ok' : 'f-accent') : 'f-muted'}" width="${w(r.reward_mean)}%" height="100%" rx="2"/></svg><span class="num">${fmtNum(r.reward_mean)}</span>`; })}
  </div>`;
  const table = html`<table class="phases"><thead><tr><th>format</th><th class="num">mean</th><th class="num">min</th><th class="num">max</th><th class="num">gold hits / req</th><th class="num">rc</th><th class="num">sec</th></tr></thead><tbody>
    <tr><td class="ph dim">garbage</td><td class="num">${fmtNum(g.garbage_mean)}</td><td colspan="5" class="dim">baseline answer "I think the answer is 0. \\boxed{0}"</td></tr>
    ${fmts.map((f) => { const r = g[f]; return html`<tr><td class="ph">${f}${f === 'parser' && g.parser_tag ? html` <span class="dim">&lt;${g.parser_tag}&gt;</span>` : ''}</td><td class="num">${fmtNum(r.reward_mean)}</td><td class="num">${fmtNum(r.reward_min)}</td><td class="num">${fmtNum(r.reward_max)}</td><td class="num ${r.gold_hits ? '' : 'dim'}">${fmtInt(r.gold_hits)} / ${fmtInt(r.mock_requests)}</td><td class="num">${r.rc ?? '—'}</td><td class="num">${fmtNum(r.seconds, 1)}</td></tr>${r.error ? html`<tr><td></td><td colspan="6"><pre class="errtext">${r.error}</pre></td></tr>` : ''}`; })}
  </tbody></table>`;
  return html`<div class="pills">${chip('scaling', s2.scaling, { raw: true })} <span class="sub">best <b>${best || '—'}</b> · hit rate ${fmtNum(s2.gold_hit_rate, 2)} · ${fmtInt(g.n_answers)} reference answers${g.shared_prompts != null ? ` · ${g.shared_prompts} shared prompts` : ''}${g.parser_tag ? ` · parser tag <${g.parser_tag}>` : ''}</span></div>
    <div class="label">reward by answer format</div>${chart}${table}
    ${d.stage2_result.phases ? html`<details><summary>stage-2 run phases</summary>${phasesTable(d.stage2_result.phases)}</details>` : ''}`;
}

function msgList(msgs, fold = false) {
  if (!msgs || !msgs.length) return html`<div class="empty">none</div>`;
  const one = (m) => html`<span class="role ${m.role}">${m.role}</span><div>${m.content ? html`<pre class="block">${m.content}</pre>` : html`<pre class="block dim">(empty)</pre>`}${m.tool_calls ? html`<details><summary>tool calls</summary><pre class="block">${m.tool_calls}</pre></details>` : ''}</div>`;
  if (fold && msgs.length > 6) { // long multi-turn transcripts: keep the opening and the ending visible
    const mid = msgs.slice(3, -2);
    return html`<div class="msgs">${msgs.slice(0, 3).map(one)}</div><details><summary>${mid.length} more messages</summary><div class="msgs">${mid.map(one)}</div></details><div class="msgs">${msgs.slice(-2).map(one)}</div>`;
  }
  return html`<div class="msgs">${msgs.map(one)}</div>`;
}

function rolloutCards(ro, hasLogs = true) {
  if (!ro || !ro.items.length) return html`<div class="empty"><b>No rollout output harvested.</b> No results.jsonl/traces.jsonl under eval_out${hasLogs ? html` — the rollout log under <a href="#sec-logs">Logs</a> says why` : ''}.</div>`;
  const show = (v) => v == null ? '(none)' : typeof v === 'string' ? v : JSON.stringify(v, null, 1);
  return html`<div class="dim extra">${ro.file}</div>${ro.items.map((r, i) => {
    if (r.kind === 'error') return html`<div class="rollout"><pre class="errtext">${r.error}</pre></div>`;
    const rewards = Object.entries(r.rewards || {});
    return html`<article class="rollout"><header><span class="rid">#${i + 1}</span>
      <span>reward <b class="mono">${isNum(r.reward) ? fmtNum(r.reward) : r.reward ?? '—'}</b>${r.reward_is_weighted_sum ? html`<span class="dim"> (Σ score×weight)</span>` : ''}</span>
      ${rewards.map(([k, v]) => html`<span class="chip" title="${k}">${k} ${isNum(v) ? fmtNum(v) : v}</span>`)}
      ${r.stop ? html`<span class="dim">stop: ${r.stop}</span>` : ''}${r.task ? html`<span class="dim">task: ${r.task}</span>` : ''}${r.n_traces > 1 ? html`<span class="dim">${r.n_traces} traces (first shown)</span>` : ''}
    </header>
    <div class="label">reference answer</div><pre class="block">${show(r.answer)}</pre>
    ${r.error ? html`<div class="label">error</div><pre class="errtext">${show(r.error)}</pre>` : ''}
    <details><summary>prompt · ${r.prompt.length} message${r.prompt.length === 1 ? '' : 's'}</summary>${msgList(r.prompt)}</details>
    <div class="label">completion · ${r.completion.length} message${r.completion.length === 1 ? '' : 's'}</div>${msgList(r.completion, true)}
    ${r.info ? html`<details><summary>info</summary>${jsonBlock(r.info)}</details>` : ''}
    </article>`;
  })}`;
}

function auditSection(d) {
  const out = [];
  d.audit.forEach((a) => out.push(html`<div class="card ${a.verdict === 'genuine' || a.verdict === 'hollow' ? 'genuine' : ''}"><header><span class="pill t-info">hand review</span>${chip('audit_verdict', a.verdict, { raw: true })}${a.category ? chip('category', a.category, { raw: true }) : ''}<span class="dim">${a.batch || ''}</span></header>
    ${kv([['root cause', a.root_cause], ['what', a.what], ['evidence', a.evidence], ['real-life fix', a.irl_fix], ['user impact', a.user_impact]])}</div>`));
  if (d.hollow) out.push(html`<div class="card"><header><span class="pill t-warn">fake-score scan</span>${chips('hollow_flags', split(d.hollow.flags, ';'), { raw: true })}</header><pre class="block">${d.hollow.details || ''}</pre></div>`);
  d.gold_review.forEach((r) => {
    const gen = truthy(r.genuine);
    out.push(html`<div class="card ${gen ? 'genuine' : ''}"><header><span class="pill t-info">score review</span>${chip('gold_review_cause', r.cause, { raw: true })}${chip('gold_review_genuine', String(gen), { raw: true })}<span class="dim">${r.review_file}${r.reviewed_at ? ` · ${r.reviewed_at}` : ''}</span></header>
      ${kv([['scaling', r.scaling], ['garbage → gold', `${fmtNum(r.garbage_mean)} → ${fmtNum(r.gold_best_mean)}`], ['explanation', r.explanation], ['evidence', r.evidence]])}
      ${r.suggested_gold_reply ? html`<div class="label">suggested gold reply</div><pre class="block">${r.suggested_gold_reply}</pre>` : ''}</div>`);
  });
  return out.length ? html`${out}` : html`<div class="empty">No manual audit, hollow-scan lead, or gold review for this env.</div>`;
}

function hubSection(d) {
  const det = d.details || {};
  const inv = d.inventory || {};
  const meta = det.metadata || {};
  const owner = det.owner || {};
  const flags = ['uses_sandbox', 'uses_judge', 'multi_turn', 'tool_env', 'hf_dataset', 'network'].filter((f) => f in inv);
  const envVars = Array.isArray(inv.env_vars) ? inv.env_vars : [];
  const tags = inv.tags || meta.tags || [];
  return html`${kv([
    ['version', inv.version || (meta.original_filename || '').replace(/\.tar\.gz$/, '')],
    ['runtime', inv.runtime], ['owner', `${inv.owner || owner.name || ''} (${owner.type || inv.owner_type || '?'})`],
    ['visibility', det.visibility], ['license', inv.license || det.license || meta.license],
    ['stars', inv.stars], ['created', inv.created_at || det.created_at], ['updated', inv.updated_at || det.updated_at],
    ['python', inv.python_requires || meta.python_requires], ['verifiers req', inv.verifiers_requirement],
    ['requires', (inv.requires_dist || meta.requires_dist || []).join(', '), true],
    ['wheel', inv.wheel_url || det.wheel_url, true],
    ['tags', tags.length ? html`<span class="chips">${tags.map((t) => html`<span class="chip">${t}</span>`)}</span>` : null],
    ['static scan', flags.length ? html`<span class="chips">${flags.map((f) => html`<span class="chip ${inv[f] ? 'on' : ''}">${inv[f] ? '' : 'no '}${f.replace(/_/g, ' ')}</span>`)}${inv.py_lines != null ? html`<span class="chip">${fmtInt(inv.py_lines)} py lines</span>` : ''}</span>` : null],
    ['env vars', envVars.length ? envVars.join(', ') : null, true],
    ['hub error', inv.error, true],
  ])}${Object.keys(det).length ? html`<details><summary>raw hub details JSON</summary>${jsonBlock(det)}</details>` : html`<div class="empty">No details/${d.key}.json.</div>`}`;
}

function stage1Section(d) {
  const r = d.stage1_result;
  const s1 = d.stage1 || {};
  const asof = d.stage1_asof;
  if (!r) return html`<div class="empty"><b>No stage-1 result.</b> ${d.row && d.row.status ? html`Status: ${chip('status', d.row.status, { raw: true })}` : 'This env was not run (listed but missing, or not yet harvested).'}</div>`;
  return html`<div class="pills">${chip('status', s1.status, { raw: true })} ${s1.category ? chip('category', s1.category, { raw: true }) : ''}</div>
    ${s1.error ? html`<pre class="errtext">${s1.error}</pre>` : ''}
    ${kv([['verifiers', `${r.verifiers_version || '—'}  (pin ${r.verifiers_pin || '—'}, api ${r.api || '—'}, cli ${r.cli || '—'})`, true],
      ['packages', r.n_packages], ['auto-installed', (r.auto_installed || []).join(', '), true],
      ['v1 roles', (r.v1_roles || []).join(', ')], ['runtime label mismatch', r.runtime_label_mismatch ? 'yes' : null],
      ['VM', d.host ? `${fmtNum(d.host.vm_seconds, 1)} s, slot ${d.host.slot ?? '—'}${d.host.host_killed ? ', host-killed' : ''}` : null],
      ['as-of rerun', asof ? html`${chip('asof_status', asof.status, { raw: true })} ${asof.category ? chip('category', asof.category, { raw: true }) : ''} <span class="dim">verifiers ${asof.verifiers || '—'}</span>` : null]])}
    <div class="label">phases</div>${phasesTable(r.phases)}`;
}

function probeSection(d) {
  const p = d.probe;
  if (!p) return html`<div class="empty">No probe.json — the env never reached import.</div>`;
  const SHOWN = ['env_class', 'env_mro', 'dataset_len', 'eval_dataset_len', 'dataset_columns', 'eval_dataset_columns', 'rubric_class', 'reward_funcs', 'reward_weights', 'max_turns', 'n_tools', 'modules', 'primary_module', 'env_id_used', 'uses_v1', 'import_s', 'load_s', 'import_ok', 'load_ok'];
  const parserTag = d.stage2_result && d.stage2_result.gold && d.stage2_result.gold.parser_tag;
  const errs = ['import_error', 'load_error', 'rubric_error', 'dataset_example_error', 'eval_dataset_example_error'].filter((k) => p[k]);
  const rest = Object.keys(p).filter((k) => !SHOWN.includes(k) && !errs.includes(k) && !/dataset_example$/.test(k));
  return html`${kv([
    ['env class', p.env_class, true], ['mro', (p.env_mro || []).join(' → '), true],
    ['train rows', p.dataset_len != null ? fmtInt(p.dataset_len) : null], ['eval rows', p.eval_dataset_len != null ? fmtInt(p.eval_dataset_len) : null],
    ['columns', (p.dataset_columns || p.eval_dataset_columns || []).join(', '), true],
    ['rubric', p.rubric_class, true], ['reward funcs', (p.reward_funcs || []).map((f, i) => `${f}${p.reward_weights ? ` ×${p.reward_weights[i]}` : ''}`).join(', '), true],
    ['parser tag', parserTag ? `<${parserTag}>` : null, true],
    ['max turns', p.max_turns], ['tools', p.n_tools],
    ['modules', [p.primary_module, ...(p.modules || []).filter((m) => m !== p.primary_module)].filter(Boolean).join(', '), true],
    ['env id used', p.env_id_used, true], ['v1 code', p.uses_v1 == null ? null : p.uses_v1 ? 'yes' : 'no'],
    ['import / load', `${p.import_ok ? 'ok' : 'fail'} ${fmtNum(p.import_s, 1)}s / ${p.load_ok == null ? '—' : p.load_ok ? 'ok' : 'fail'} ${fmtNum(p.load_s, 1)}s`],
    ...rest.map((k) => [k, p[k], true]),
  ])}
  ${errs.map((k) => html`<details ${k === 'rubric_error' ? '' : new Raw('open')}><summary>${k.replace(/_/g, ' ')}</summary><pre class="errtext">${p[k]}</pre></details>`)}
  ${['dataset_example', 'eval_dataset_example'].filter((k) => p[k]).map((k) => html`<details><summary>${k.replace(/_/g, ' ')}</summary>${jsonBlock(p[k])}</details>`)}`;
}

// ------------------------------------------------------------------ env detail: plain-language summary + timeline
const clip = (s, n = 320) => { const t = String(s || '').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
// tracebacks end with the informative line
const lastLine = (s) => String(s || '').split('\n').map((l) => l.replace(ANSI, '').trim()).filter(Boolean).pop() || '';

function plainSummary(d) {
  const row = d.row || {};
  const ve = row.verdict ? entry('verdict', row.verdict) : null;
  const [phase, reason] = catParts(row.category);
  const because = [];
  const actions = [];
  const hollowAudit = d.audit.find((a) => a.verdict === 'hollow');
  if (row.group === 'hollow') {
    const flags = split(row.hollow_flags, ';');
    const e = flags.length ? entry('hollow_flags', flags[0]) : entry('audit_verdict', 'hollow');
    because.push({ tags: flags.length ? chips('hollow_flags', flags) : chip('audit_verdict', 'hollow'), text: e.short, note: hollowAudit && (hollowAudit.what || hollowAudit.root_cause) });
    actions.push(e.action);
  }
  if (reason && reason !== 'ok') {
    const re = entry('category', reason);
    const failAudit = d.audit.find((a) => a.category && a.category === row.category);
    because.push({
      tags: chip('category', row.category),
      text: `${phase ? `It stopped while ${entry('category', phase).label.toLowerCase()}. ` : ''}${re.short}`,
      note: failAudit && failAudit.root_cause, error: lastLine(row.error),
    });
    actions.push(re.action);
    if (failAudit && failAudit.irl_fix) actions.push(`Reviewer’s suggested fix: ${failAudit.irl_fix}`);
  }
  const rev = d.gold_review.find((r) => truthy(r.genuine)) || d.gold_review[0];
  if (rev && SUSPECT_SCALING.has(row.scaling)) {
    const ce = entry('gold_review_cause', rev.cause);
    because.push({ tags: chip('gold_review_cause', rev.cause), text: ce.short, note: rev.explanation });
    actions.push(ce.action);
  }
  if (!because.length && row.category === 'ok') because.push({ tags: chip('category', 'ok'), text: entry('category', 'ok').short });
  actions.push(ve && ve.action);
  const todo = [...new Set(actions.filter(Boolean))];
  const se = row.scaling ? entry('scaling', row.scaling) : null;
  const nums = isNum(row.gold_best_mean) && isNum(row.garbage_mean)
    ? ` Correct answers averaged ${fmtNum(row.gold_best_mean, 2)}, nonsense ${fmtNum(row.garbage_mean, 2)} (scores run 0 to 1).` : '';
  const tone = row.group === 'hollow' ? 'bad' : ve ? TONE_CLASS[ve.tone] : 'muted';
  return html`<section class="summary t-${tone}" aria-labelledby="sum-h">
    <h2 id="sum-h" class="sr">Summary in plain words</h2>
    <p class="lead"><span class="lk">This environment</span>${row.verdict ? chip('verdict', row.verdict, { raw: true }) : html`<b>was not tested</b>`}${row.group === 'hollow' && row.verdict !== 'hollow' ? chip('audit_verdict', 'hollow') : ''}<span>${ve ? ve.short : ''}</span></p>
    <dl class="sumlist">
      ${because.length ? html`<dt>Because</dt><dd>${because.map((b) => html`<div class="why">${b.tags}<span>${b.text}</span>
        ${b.note ? html`<p class="note" title="${b.note}"><b>Reviewer:</b> ${clip(b.note)}</p>` : ''}
        ${b.error ? html`<p class="err" title="last line of the error we recorded"><code>${clip(b.error, 220)}</code></p>` : ''}</div>`)}</dd>` : ''}
      ${se ? html`<dt>Score check</dt><dd><div class="why">${chip('scaling', row.scaling, { mark: true })}<span>${se.short}${nums}</span></div></dd>` : ''}
      ${todo.length ? html`<dt>What to do</dt><dd><ul class="todo">${todo.map((a) => html`<li>${a}</li>`)}</ul></dd>` : ''}
    </dl>
  </section>`;
}

const STEP_STATE = {
  ok: ['✓', 'Passed'], fail: ['✗', 'Failed'], warn: ['!', 'Needs a look'], blocked: ['–', 'Can’t verify here'],
  harness: ['–', 'Our test failed'], skip: ['–', 'Not reached'], untested: ['–', 'Not tested'], inconclusive: ['–', 'Inconclusive'],
};
function okNote(p, ph, d) {
  const probe = d.probe || {};
  if (p === 'install') return `Installed in ${fmtNum(+ph.seconds, 0)} s${(d.stage1_result.auto_installed || []).length ? `, after we added the undeclared package${d.stage1_result.auto_installed.length > 1 ? 's' : ''} ${d.stage1_result.auto_installed.join(', ')}` : ''}.`;
  if (p === 'import') return 'The Python code loaded without errors.';
  if (p === 'load') return probe.dataset_len != null ? `Built the task set (${fmtInt(+probe.dataset_len)} tasks).` : 'Built the environment and its task set.';
  const n = +ph.n_rollouts;
  return `Ran ${Number.isFinite(n) ? fmtInt(n) : 'the'} attempts with the fake model${ph.reward_mean != null && ph.reward_mean !== '' ? `; it scored ${fmtNum(+ph.reward_mean, 2)} on average with its nonsense answer` : ''}.`;
}
function timeline(d) {
  const row = d.row || {};
  const res = d.stage1_result;
  const phases = (res && res.phases) || {};
  const [failPhase, reason] = catParts(row.category);
  const RUN_STEPS = [['install', 'Install'], ['import', 'Import'], ['load', 'Load'], ['rollout', 'Run']];
  // the step that stopped the run: first phase not ok, else (e.g. rollout ran but wrote no rewards) the category's phase
  let failAt = RUN_STEPS.map(([p]) => p).find((p) => phases[p] && !truthy(phases[p].ok));
  if (!failAt && !['pass', 'pass_with_fixes'].includes(row.status) && phases[failPhase]) failAt = failPhase;
  let stopped = false;
  const steps = RUN_STEPS.map(([p, name]) => {
    const ph = phases[p];
    const ex = entry('category', p).short;
    if (stopped) return { name, ex, state: 'skip', note: 'Not reached because an earlier step stopped.' };
    if (!res) return { name, ex, state: 'untested', note: p !== 'install' ? '' : row.verdict ? entry('verdict', row.verdict).short : 'We have no test record for this environment.' };
    if (p !== failAt) return ph ? { name, ex, state: 'ok', note: okNote(p, ph, d) } : { name, ex, state: 'skip', note: 'No record of this step.' };
    stopped = true;
    const e = entry('category', reason || 'exception');
    return { name, ex, state: row.status === 'blocked' ? 'blocked' : row.status === 'harness' ? 'harness' : 'fail', note: `${e.label}: ${e.short}` };
  });
  const sc = { name: 'Score check', ex: 'Does a correct reference answer score higher than a nonsense one?' };
  const se = row.scaling ? entry('scaling', row.scaling) : null;
  const rev = d.gold_review.find((r) => truthy(r.genuine)) || d.gold_review[0];
  if (row.group === 'hollow') Object.assign(sc, { state: 'fail', note: `${entry('verdict', 'hollow').label}: ${entry('verdict', 'hollow').short}` });
  else if (!se) Object.assign(sc, stopped || !res ? { state: 'skip', note: 'Only done for environments that run.' } : { state: 'untested', note: 'This environment has not been score-checked yet.' });
  else if (row.scaling === 'scales') Object.assign(sc, { state: 'ok', note: se.short });
  else if (SUSPECT_SCALING.has(row.scaling) && rev) {
    // a reviewer looked: either a real scoring problem, or our test's fault (inconclusive, not the env's)
    const ce = entry('gold_review_cause', rev.cause);
    Object.assign(sc, { state: truthy(rev.genuine) ? 'fail' : 'inconclusive', note: `${se.label}. A reviewer found: ${ce.label} — ${ce.short}` });
  } else if (SUSPECT_SCALING.has(row.scaling)) Object.assign(sc, { state: 'warn', note: `${se.label}: ${se.short} Not reviewed yet.` });
  else Object.assign(sc, { state: 'inconclusive', note: `${se.label}: ${se.short}` });
  steps.push(sc);
  return html`<ol class="timeline" aria-label="What happened at each step">${steps.map((s) => html`<li class="step s-${s.state}">
    <span class="mk" aria-hidden="true">${STEP_STATE[s.state][0]}</span>
    <div class="sb"><div class="sn"><b>${s.name}</b><span class="st">${STEP_STATE[s.state][1]}</span></div><p class="snote">${s.note}</p><p class="sex">${s.ex}</p></div></li>`)}</ol>`;
}

async function renderEnv(key, my) {
  const d = await api(`/api/env/${encodeURIComponent(key)}`);
  if (my !== seq) return;
  const row = d.row || {};
  const [owner, name] = key.split('__');
  const desc = (d.inventory && d.inventory.description) || (d.details && d.details.description) || row.description;
  document.title = `${name} · Hub environment audit`;
  const ro = d.rollouts;
  const roTabs = Object.entries(ro).filter(([, v]) => v.items.length);
  const techOpen = location.hash.startsWith('#sec-');
  main().innerHTML = html`
    <div class="crumbs"><a href="/envs">Environments</a> / <span class="mono">${key}</span></div>
    <div class="envhead">
      <h1><span class="owner">${owner} /</span> ${name}</h1>
      <div class="pills">${chip('official', officialKey(row.official))}${row.runtime ? chip('runtime', row.runtime) : ''}
        ${row.stars ? html`<span class="sub" title="hub stars">★ ${fmtInt(row.stars)}</span>` : ''}</div>
      ${desc ? html`<p class="desc">${desc}</p>` : ''}
    </div>
    ${plainSummary(d)}
    <section class="panel steps" aria-labelledby="tl-h"><header><h2 id="tl-h">What happened, step by step</h2><span class="hint">our automated test of this environment</span></header>${timeline(d)}</section>
    <div class="cols">
      ${section('sec-audit', 'What the reviewers found', 'hand / AI review of this environment', auditSection(d), 'full')}
      ${section('sec-gold', 'Correct answer vs nonsense', 'score with the reference answer (gold) vs a nonsense answer (garbage)', goldSection(d), 'full')}
      ${section('sec-rollouts', 'What the model was asked and answered', 'first 3 tasks per run: prompt, reference answer, reply, score', roTabs.length ? html`<div class="tabs">${roTabs.map(([k], i) => html`<button type="button" data-ro="${k}" aria-pressed="${i === 0}">${k === 'stage1' ? 'run test · nonsense answer' : 'score check · nonsense answer'}</button>`)}</div><div id="ro-body"></div>` : rolloutCards(null, d.logs.length > 0), 'full')}
    </div>
    <details class="tech" id="tech" ${techOpen ? new Raw('open') : ''}>
    <summary><span class="th">Raw data</span><span class="hint">hub metadata · run phases · probe · logs · source code</span></summary>
    <nav class="toc" aria-label="Sections">
      <a href="#sec-hub">Hub</a><a href="#sec-s1">Stage 1</a><a href="#sec-probe">Probe</a><a href="#sec-logs">Logs (${d.logs.length})</a><a href="#sec-src">Source</a>
    </nav>
    <div class="cols">
      ${section('sec-hub', 'Hub metadata', 'inventory · details', hubSection(d))}
      ${section('sec-s1', 'Stage 1', 'stage1_final/result.json', stage1Section(d))}
      ${section('sec-probe', 'Probe', 'probe.json', probeSection(d))}
      ${section('sec-logs', 'Logs', 'tail first · ANSI stripped', d.logs.length ? html`<div class="viewer"><div class="filelist" id="loglist">
          ${['stage1', 'stage2'].filter((s) => d.logs.some((l) => l.src === s)).map((s) => html`<div class="grp">${s === 'stage1' ? 'stage1_final' : 'stage2_gold'}</div>${d.logs.filter((l) => l.src === s).map((l) => html`<button type="button" data-src="${l.src}" data-name="${l.name}"><span>${l.name}</span><span>${fmtBytes(l.size)}</span></button>`)}`)}
        </div><div class="pane"><div class="bar"><span class="path" id="logpath"></span><span class="spacer"></span><span class="dim" id="loginfo"></span>
          <button type="button" id="logfull">Load full</button><button type="button" id="logwrap" aria-pressed="true">Wrap</button></div>
          <div class="scroll wrap" id="logscroll" tabindex="0"><pre id="logtext"></pre></div></div></div>` : html`<div class="empty">No logs harvested for this env.</div>`, 'full')}
      ${section('sec-src', 'Source', `data/src/${key}`, d.has_src ? html`<div class="viewer"><div class="filelist" id="srclist"><input type="search" id="srcfilter" placeholder="filter files" aria-label="filter files" spellcheck="false"><div id="srcfiles"><div class="empty">Loading…</div></div></div>
        <div class="pane"><div class="bar"><span class="path" id="srcpath"></span><span class="spacer"></span><span class="dim" id="srcinfo"></span><button type="button" id="srcwrap" aria-pressed="false">Wrap</button></div>
        <div class="scroll" id="srcscroll" tabindex="0"><div class="code"><pre class="gutter" id="srcgutter"></pre><pre class="src" id="srctext"></pre></div></div></div></div>` : html`<div class="empty">No extracted source for this env (data/src/${key} missing).</div>`, 'full')}
    </div></details>`.s;

  if (roTabs.length) {
    const show = (k) => {
      $$('[data-ro]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.ro === k)));
      $('#ro-body').innerHTML = rolloutCards(ro[k]).s;
    };
    $$('[data-ro]').forEach((b) => { b.onclick = () => show(b.dataset.ro); });
    show(roTabs[0][0]);
  }
  if (d.logs.length) wireLogs(key, d.logs, my);
  if (d.has_src) wireSource(key, my);
  if (location.hash) { const el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView(); }
}

function toggleWrap(btn, target) {
  btn.onclick = () => {
    const on = btn.getAttribute('aria-pressed') !== 'true';
    btn.setAttribute('aria-pressed', String(on));
    target.classList.toggle('wrap', on);
  };
}

function wireLogs(key, logs, my) {
  let cur = null;
  const load = async (src, name, full) => {
    cur = { src, name };
    $$('#loglist button').forEach((b) => b.setAttribute('aria-current', String(b.dataset.src === src && b.dataset.name === name)));
    $('#logpath').textContent = `${src} / ${name}`;
    $('#loginfo').textContent = 'loading…';
    try {
      const r = await api(`/api/env/${encodeURIComponent(key)}/log?${new URLSearchParams({ src, name, full: full ? 'true' : 'false' })}`);
      if (my !== seq || cur.src !== src || cur.name !== name) return;
      $('#logtext').textContent = r.text.replace(ANSI, '') || '(empty file)';
      $('#loginfo').textContent = r.truncated ? `last ${fmtBytes(r.size - r.start)} of ${fmtBytes(r.size)}` : fmtBytes(r.size);
      $('#logfull').disabled = !r.truncated || full;
      $('#logfull').textContent = r.truncated && full ? 'Capped at 8 MB' : 'Load full';
      const sc = $('#logscroll');
      sc.scrollTop = full ? 0 : sc.scrollHeight; // tail-first: land on the end of the log
    } catch (e) {
      $('#loginfo').textContent = '';
      $('#logtext').textContent = `Could not load log: ${e.message}`;
    }
  };
  $$('#loglist button').forEach((b) => { b.onclick = () => load(b.dataset.src, b.dataset.name, false); });
  $('#logfull').onclick = () => cur && load(cur.src, cur.name, true);
  toggleWrap($('#logwrap'), $('#logscroll'));
  const pref = ['logs/rollout.log', 'logs/load.log', 'console.log'];
  const s1 = logs.filter((l) => l.src === 'stage1' && l.size > 0);
  const first = pref.map((n) => s1.find((l) => l.name === n)).find(Boolean) || s1[0] || logs[0];
  load(first.src, first.name, false);
}

async function wireSource(key, my) {
  let r;
  try {
    r = await api(`/api/env/${encodeURIComponent(key)}/src`);
  } catch (e) {
    $('#srcfiles').innerHTML = html`<div class="empty">Could not list files: ${e.message}</div>`.s;
    return;
  }
  if (my !== seq) return;
  const files = r.files;
  let cur = null;
  const list = (filter) => {
    const f = filter.toLowerCase();
    const shown = files.filter((x) => !f || x.path.toLowerCase().includes(f));
    $('#srcfiles').innerHTML = (shown.length ? html`${shown.map((x) => html`<button type="button" data-path="${x.path}" aria-current="${x.path === cur}" title="${x.path}"><span>\u200e${x.path}\u200e</span><span>${fmtBytes(x.size)}</span></button>`)}` : html`<div class="empty">No file matches.</div>`).s
      + (r.truncated ? html`<div class="empty notice">Listing capped at ${fmtInt(r.max)} files.</div>`.s : '');
  };
  const open = async (path) => {
    cur = path;
    $$('#srcfiles button').forEach((b) => b.setAttribute('aria-current', String(b.dataset.path === path)));
    $('#srcpath').textContent = path;
    $('#srcinfo').textContent = 'loading…';
    try {
      const f = await api(`/api/env/${encodeURIComponent(key)}/src/file?${new URLSearchParams({ path })}`);
      if (my !== seq || cur !== path) return;
      const text = f.binary ? '(binary file — not shown)' : f.text;
      const n = text.split('\n').length;
      $('#srcgutter').textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n');
      $('#srctext').textContent = text;
      $('#srcinfo').textContent = `${fmtBytes(f.size)}${f.truncated ? ' · first 1 MB shown' : ''}`;
      $('#srcscroll').scrollTop = 0;
    } catch (e) {
      $('#srcinfo').textContent = '';
      $('#srcgutter').textContent = '';
      $('#srctext').textContent = `Could not load file: ${e.message}`;
    }
  };
  $('#srcfiles').addEventListener('click', (e) => { const b = e.target.closest('button[data-path]'); if (b) open(b.dataset.path); });
  $('#srcfilter').addEventListener('input', (e) => list(e.target.value));
  toggleWrap($('#srcwrap'), $('#srcscroll'));
  list('');
  const depth = (x) => x.path.split('/').length;
  const pick = files.find((x) => /^readme(\.md)?$/i.test(x.path)) || files.find((x) => x.path === 'pyproject.toml')
    || files.filter((x) => x.path.endsWith('.py')).sort((a, b) => depth(a) - depth(b))[0] || files[0];
  if (pick) open(pick.path);
  else $('#srctext').textContent = '(empty directory)';
}

// ------------------------------------------------------------------ start page
const exampleLinks = (keys) => keys && keys.length
  ? html`<span class="ex">e.g. ${keys.map((k, i) => html`${i ? ', ' : ''}<a href="${envHref(k)}">${k.split('__')[1] || k}</a>`)}</span>` : '';
const share = (n, tot) => (tot ? Math.round((100 * n) / tot) : 0);

function outcomeStrip(f, T) {
  const gs = GROUPS.map((g) => ({ ...g, ...(f.groups[g.id] || { n: 0, verdicts: {}, examples: [] }) })).filter((g) => g.n);
  const extra = (g) => Object.entries(g.verdicts).filter(([v]) => v !== g.verdict && g.id !== 'other')
    .map(([v, n]) => `${fmtInt(n)} ${entry('verdict', v).label.toLowerCase()}`).join(', ');
  const desc = (g) => g.id === 'other'
    ? `Gone from the hub, or our test setup failed. ${Object.entries(g.verdicts).map(([v, n]) => `${fmtInt(n)} ${entry('verdict', v).label.toLowerCase()}`).join(', ')}. No verdict on the environment.`
    : entry('verdict', g.verdict).short;
  return html`<div class="strip" role="img" aria-label="${gs.map((g) => `${g.label}: ${g.n}`).join(', ')}">${gs.map((g) => html`<a class="seg t-${toneOf('verdict', g.verdict)}" style="flex-grow:${g.n}" href="/envs?show=${g.id}" tabindex="-1" aria-hidden="true" title="${g.label}: ${fmtInt(g.n)}"></a>`)}</div>
    <div class="outcomes">${gs.map((g) => html`<a class="outcome t-${toneOf('verdict', g.verdict)}" href="/envs?show=${g.id}">
      <span class="on"><b>${fmtInt(g.n)}</b><span>${share(g.n, T)}%</span></span>
      <span class="ol"><span class="dotc"></span>${g.label}</span>
      <span class="od">${desc(g)}${extra(g) ? html` <span class="dim">Includes ${extra(g)}.</span>` : ''}</span></a>`)}</div>`;
}

function reasonList(items, total) {
  if (!items.length) return html`<div class="empty">Nothing recorded yet.</div>`;
  const max = Math.max(1, ...items.map((i) => i.n));
  return html`<ol class="reasons">${items.map((it) => {
    const e = entry('category', it.reason);
    const top = Object.entries(it.phases)[0];
    const where = top && top[0] ? `mostly while ${entry('category', top[0]).label.toLowerCase()}` : '';
    return html`<li><div class="rh"><a href="${envsQ('cat', it.reason)}" class="rl"><span class="dotc t-${TONE_CLASS[e.tone] || 'muted'}"></span>${e.label}</a>
      <svg class="bt" aria-hidden="true"><rect class="f-track" width="100%" height="100%" rx="2"/><rect class="f-${TONE_CLASS[e.tone] || 'muted'}" width="${((100 * it.n) / max).toFixed(2)}%" height="100%" rx="2"/></svg>
      <span class="bn">${fmtInt(it.n)}</span><span class="bp">${total ? `${share(it.n, total)}%` : ''}</span></div>
      <p>${e.short} <code class="tag">${it.reason}</code></p><p class="meta">${where}${where && it.examples.length ? ' · ' : ''}${exampleLinks(it.examples)}</p></li>`;
  })}</ol>`;
}

function publisherBlock(f) {
  const rows = f.publisher.map((p) => {
    const g = p.groups;
    const testable = p.n - (g.unverifiable || 0) - (g.other || 0);
    return { ...p, works: g.works || 0, testable, label: entry('official', String(p.official)).label };
  });
  const [o, c] = rows;
  return html`<p class="finding">${o && c ? html`<b>${share(o.works, o.n)}%</b> of official environments work, versus <b>${share(c.works, c.n)}%</b> of community ones. Counting only the ones we could actually test, it is <b>${share(o.works, o.testable)}%</b> vs <b>${share(c.works, c.testable)}%</b>: official envs more often need credentials or sandboxes we didn’t provide.` : ''}</p>
    <div class="stack">${rows.map((p) => {
      let x = 0;
      const segs = GROUPS.filter((gr) => p.groups[gr.id]).map((gr) => {
        const w = (100 * p.groups[gr.id]) / p.n;
        const s = html`<rect class="f-${toneOf('verdict', gr.verdict)}" x="${x.toFixed(2)}%" width="${w.toFixed(2)}%" height="100%"><title>${gr.label}: ${p.groups[gr.id]} (${pct(p.groups[gr.id], p.n)})</title></rect>`;
        x += w;
        return s;
      });
      return html`<a class="bl" href="${envsQ('official', p.official ? 'official' : 'community')}">${p.label}</a><svg role="img" aria-label="${p.label}: ${GROUPS.filter((gr) => p.groups[gr.id]).map((gr) => `${gr.label} ${p.groups[gr.id]}`).join(', ')}">${segs}</svg><span class="bn">${fmtInt(p.n)}</span>`;
    })}</div><div class="legend">${GROUPS.map((gr) => html`<span>${dot('verdict', gr.verdict)}${gr.label}</span>`)}</div>`;
}

function problemList(f) {
  if (!f.problems.length) return html`<div class="empty">No confirmed problems recorded yet.</div>`;
  return html`<ul class="problems">${f.problems.map((p) => {
    const e = entry(p.field, p.value);
    return html`<li class="t-${TONE_CLASS[e.tone] || 'muted'}"><div class="ph"><b class="pn">${fmtInt(p.n)}</b>${chip(p.field, p.value, { href: problemHref(p) })}</div>
      <p>${e.short}</p>${e.action ? html`<p class="act"><b>What to do</b> ${e.action}</p>` : ''}<p class="meta">${exampleLinks(p.examples)}</p></li>`;
  })}</ul>`;
}

// where a landing-page problem tag leads: the env table filtered to exactly those envs
const FIELD_FILTER = { verdict: 'verdict', status: 'status', category: 'cat', scaling: 'scaling', audit_verdict: 'audit',
  gold_review_cause: 'review', runtime: 'runtime' };
const problemHref = (p) => FIELD_FILTER[p.field] ? envsQ(FIELD_FILTER[p.field], p.value) : null;

function selfCheck(f) {
  const a = f.failure_audit, g = f.gold_reviews;
  const parts = (vs) => Object.entries(vs).map(([v, n]) => html`<b>${fmtInt(n)}</b> ${entry('audit_verdict', v).label.toLowerCase()}`);
  const join = (xs) => xs.map((x, i) => html`${i ? (i === xs.length - 1 ? ' and ' : ', ') : ''}${x}`);
  return html`<p class="finding">${a.n ? html`To check our own test, reviewers re-examined <b>${fmtInt(a.n)}</b> sampled failures: ${join(parts(a.verdicts))}.` : ''}
    ${g.n ? html` Where a correct answer did not clearly beat nonsense, reviewers looked at <b>${fmtInt(g.n)}</b> environments and found <b>${fmtInt(g.genuine)}</b> real scoring problems; the rest were our test’s fault or the test didn’t apply.` : ''}</p>`;
}

async function renderStart(my) {
  const f = await api('/api/findings');
  if (my !== seq) return;
  const T = f.totals.envs;
  const n = (id) => (f.groups[id] || {}).n || 0;
  const tested = T - n('unverifiable') - n('other');
  const breaking = n('broken') + n('rotted');
  const s2 = Object.values(f.scaling).reduce((s, x) => s + x, 0);
  main().innerHTML = html`
    <section class="intro">
      <h1>Do the environments on Prime Intellect’s hub actually work?</h1>
      <p class="lede">The Prime Intellect Environments Hub lists <b>${fmtInt(T)}</b> RL environments: small Python packages that give an AI model tasks and score its answers, used to evaluate models and to train them with reinforcement learning.
        We installed and ran every one automatically in throwaway virtual machines, with a fake model whose answers we control, to check two things: does it run at all, and does a correct answer actually score higher than nonsense?
        A broken environment, or one whose scores are fake, gives anyone evaluating or training on it wrong numbers, often without any error to warn them.</p>
      <p class="meta">New here? Every coloured tag explains itself on hover or click, and the <a href="/glossary">glossary</a> lists them all. <a href="#how">How this audit works ↓</a></p>
    </section>

    <h2 class="sect">Key findings</h2>
    <section class="panel">
      <p class="finding big"><b>${share(n('works'), T)}%</b> of all environments work (${fmtInt(n('works'))} of ${fmtInt(T)}). Of the ${fmtInt(tested)} we could fully test, <b>${share(n('works'), tested)}%</b> work and <b>${share(breaking, tested)}%</b> are broken.</p>
      ${outcomeStrip(f, T)}
    </section>
    <div class="grid start">
      ${panel('Why environments break', `The five most common reasons among the ${fmtInt(breaking)} broken environments (including those that broke after an update). Click a reason to see them.`, reasonList(f.break_reasons, breaking))}
      ${panel('Problems confirmed as real', 'Environments that run without errors but whose scores are fake or wrong, plus definite packaging and update breakages. These are the dangerous ones: nothing tells a user something is off.', html`${problemList(f)}${selfCheck(f)}`)}
      ${panel('Official vs community', 'Environments published by Prime Intellect compared with everyone else’s. Each bar is 100% of that group.', publisherBlock(f))}
      ${panel('Do the scores mean anything?', `For the ${fmtInt(s2)} environments that ran, we fed in each environment’s own reference answers and compared the score with a nonsense answer.`, bars(Object.entries(f.scaling).map(([label, c]) => ({ label, n: c })), 'scaling', (v) => envsQ('scaling', v), ['Score check', 'Envs']))}
      ${panel('What we couldn’t test', `${fmtInt(n('unverifiable'))} environments need something we deliberately didn’t provide. That means unknown, not broken. The most common needs:`, reasonList(f.blocked_reasons, n('unverifiable')))}
    </div>

    <h2 class="sect" id="how">How this audit works</h2>
    <div class="howgrid">
      <ol class="howto">${GL.how_it_works.map((s) => html`<li><b>${s.step}</b><p>${s.plain}</p></li>`)}</ol>
      <aside class="panel caveats" aria-labelledby="cav-h"><h3 id="cav-h">Keep in mind</h3><ul>${GL.caveats.map((c) => html`<li>${c}</li>`)}</ul>
        <p class="meta"><a href="/glossary#concepts">Key terms explained →</a></p></aside>
    </div>`.s;
  if (location.hash) { const el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView(); }
}

// ------------------------------------------------------------------ glossary page
// env-table filter that shows the envs carrying a value (search for fields without a dropdown)
const GLOSSARY_FILTER = { verdict: 'verdict', status: 'status', scaling: 'scaling', runtime: 'runtime', audit_verdict: 'audit', official: 'official', category: 'cat' };
function usageLink(field, v) {
  const n = field === 'category' ? (GL_USAGE.categories || {})[v] : (GL_USAGE[field] || {})[v];
  if (!n) return html`<span class="dim">0</span>`;
  if (field === 'asof_status' || field === 'gold_review_genuine') return fmtInt(n);
  const k = GLOSSARY_FILTER[field] || 'q';
  const val = field === 'official' ? (v === 'true' ? 'official' : 'community') : v;
  return html`<a href="${envsQ(k, val)}" title="show these environments">${fmtInt(n)}</a>`;
}
function termTable(field, values) {
  return html`<table class="gtable"><thead><tr><th>Label</th><th>Tag</th><th>Meaning</th><th>What to do</th><th class="num">Envs</th></tr></thead><tbody>
    ${values.map(([v, e]) => html`<tr class="gterm" id="${glossaryAnchor(field, v)}" data-hay="${[v, e.label, e.short, e.long, e.action].filter(Boolean).join(' ').toLowerCase()}">
      <td><span class="pill gl t-${TONE_CLASS[e.tone] || 'info'}">${e.label}</span></td><td><code class="tag">${v}</code></td>
      <td><p class="gs">${e.short}</p>${e.long ? html`<p class="gl2">${e.long}</p>` : ''}</td><td class="ga">${e.action || html`<span class="dim">—</span>`}</td>
      <td class="num">${usageLink(field, v)}</td></tr>`)}</tbody></table>`;
}

async function renderGlossary(my) {
  await loadGlossary(true);
  if (my !== seq) return;
  const fields = Object.entries(GL.fields);
  const cats = Object.entries(GL.categories);
  const phaseCats = cats.filter(([k]) => PHASES.includes(k));
  const reasonCats = cats.filter(([k]) => !PHASES.includes(k));
  const toc = [['concepts', 'Key ideas'], ['how', 'How it works'], ...fields.map(([f, d]) => [`f-${f}`, d.title || humanize(f)]), ['c-phases', 'Steps of a run'], ['c-reasons', 'Why a run stopped']];
  main().innerHTML = html`
    <div class="pagehead"><h1>Glossary</h1><p class="caption wide">Every term and tag used in this dashboard, in plain words. “Tag” is the raw value in the data files; “Envs” counts how many environments carry it (click to list them).</p></div>
    <div class="gsearch" role="search"><input id="gq" type="search" placeholder="Search terms, tags and explanations…" aria-label="Search the glossary" autocomplete="off" spellcheck="false"><span class="count" id="gcount" aria-live="polite"></span></div>
    <nav class="toc" aria-label="Glossary sections">${toc.map(([id, t]) => html`<a href="#${id}">${t}</a>`)}</nav>
    <section class="gsec panel" id="concepts"><header><h2>Key ideas</h2></header>
      <dl class="concepts">${GL.concepts.map((c) => html`<div class="gterm" id="${glossaryAnchor('concept', c.term)}" data-hay="${`${c.term} ${c.plain}`.toLowerCase()}"><dt>${c.term}</dt><dd>${c.plain}</dd></div>`)}</dl></section>
    <section class="gsec panel" id="how"><header><h2>How it works</h2></header>
      <ol class="howto compact">${GL.how_it_works.map((s) => html`<li class="gterm" data-hay="${`${s.step} ${s.plain}`.toLowerCase()}"><b>${s.step}</b><p>${s.plain}</p></li>`)}</ol>
      <h3 class="label">Keep in mind</h3><ul class="cav">${GL.caveats.map((c) => html`<li class="gterm" data-hay="${c.toLowerCase()}">${c}</li>`)}</ul></section>
    ${fields.map(([f, d]) => html`<section class="gsec panel" id="f-${f}"><header><h2>${d.title || humanize(f)}</h2><code class="tag">${f}</code></header>${d.help ? html`<p class="caption">${d.help}</p>` : ''}${termTable(f, Object.entries(d.values || {}))}</section>`)}
    <section class="gsec panel" id="c-phases"><header><h2>Steps of a run</h2><code class="tag">category: phase</code></header><p class="caption">The first half of a “phase:reason” category: which step of our test the environment stopped at.</p>${termTable('category', phaseCats)}</section>
    <section class="gsec panel" id="c-reasons"><header><h2>Why a run stopped</h2><code class="tag">category: reason</code></header><p class="caption">The second half of a “phase:reason” category. Some are defects in the environment, some are things we could not provide, some are failures of our own test setup.</p>${termTable('category', reasonCats)}</section>
    <div class="empty" id="gnone" hidden>No term matches. Try a shorter word.</div>`.s;
  const terms = $$('.gterm');
  const filter = () => {
    const qs = $('#gq').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    terms.forEach((t) => { const ok = qs.every((q) => t.dataset.hay.includes(q)); t.hidden = !ok; if (ok) shown++; });
    $$('.gsec').forEach((s) => { s.hidden = qs.length > 0 && !s.querySelector('.gterm:not([hidden])'); });
    $('#gnone').hidden = shown > 0;
    $('#gcount').textContent = qs.length ? `${shown} of ${terms.length} terms` : `${terms.length} terms`;
  };
  $('#gq').addEventListener('input', filter);
  filter();
  if (location.hash) {
    const el = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('hl'); }
  }
}

route();
