'use strict';
const el = id => document.getElementById(id);
const token = location.hash.slice(1);
history.replaceState(null, '', '/');
let report;
const text = (id, value) => { el(id).textContent = value; };
async function request(path) {
  const response = await fetch(path, {headers: {'X-Civic-Token': token}, cache: 'no-store', credentials: 'omit'});
  if (!response.ok) throw new Error('Snapshot access failed. Reopen the full URL printed by civic serve.');
  return response;
}
function horizon() {
  const h = report.horizons.find(h => h.horizon_days === Number(el('horizon').value));
  text('fraction', h.closure_fraction === null ? 'No eligible cases' : `${(h.closure_fraction * 100).toFixed(1)}%`);
  text('denominator', `${h.closed_within_horizon} closed within ${h.horizon_days} days / ${h.eligible_known} eligible known outcomes`);
  text('exclusions', `${h.too_recent_known} known cases lack full follow-up; ${h.unknown_outcome_excluded} unknown outcomes with full follow-up excluded.`);
}
function agencies() {
  const rows = report.by_agency.filter(row => row.agency.toLowerCase().includes(el('agency').value.toLowerCase()));
  el('agencies').replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const key of ['agency','cohort_rows','closed_count','open_count','unknown_outcome_count']) {
      const td = document.createElement('td'); td.textContent = row[key]; tr.append(td);
    }
    el('agencies').append(tr);
  }
  text('agency-count', `${rows.length} of ${report.by_agency.length} agencies displayed`);
}
async function download(format) {
  try {
    const response = await request(`/download/report.${format}`);
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a'); a.href = url; a.download = `report.${format}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { text('message', error.message); }
}
(async () => {
  try {
    if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error('Reopen the full URL printed by civic serve. The access token is held only in this tab.');
    report = await (await request('/api/report')).json();
    const c = report.snapshot.manifest;
    text('context', `${c.source} · created ${c.cohort_start} to ${c.cohort_end} (exclusive) · observed ${c.observed_at}`);
    text('coverage', `Coverage: ${c.completeness}; basis: ${c.completeness_basis}.`);
    for (const [label, key] of [['In cohort','cohort_rows'],['Validated closed','closed_count'],['Known open','open_count'],['Unknown outcomes','unknown_outcome_count']]) {
      const card = document.createElement('article'); const title = document.createElement('p'); title.textContent = label;
      const value = document.createElement('strong'); value.textContent = report.summary[key]; card.append(title, value); el('counts').append(card);
    }
    for (const [key, count] of Object.entries(report.open_age_bands)) {
      const p = document.createElement('p'); p.textContent = `${key.replaceAll('_', ' ')}: ${count}`; el('ages').append(p);
    }
    for (const warning of report.warnings) { const li = document.createElement('li'); li.textContent = warning.replaceAll('_', ' '); el('warnings').append(li); }
    text('quality', JSON.stringify(report.snapshot.quality, null, 2));
    text('provenance', JSON.stringify(report.snapshot, null, 2));
    horizon(); agencies(); el('report').hidden = false; text('message', 'Snapshot loaded. Read-only; no live refresh.');
    el('horizon').addEventListener('change', horizon); el('agency').addEventListener('input', agencies);
    el('json').addEventListener('click', () => download('json')); el('csv').addEventListener('click', () => download('csv'));
  } catch (error) { text('message', error.message); }
})();
