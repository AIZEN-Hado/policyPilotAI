'use strict';
/* All remote text is inserted as text nodes. Forms retain their evidence revision. */
(() => {
 const labels = {POLICY_ID:'Policy ID', MEMBER_ID:'Member ID', ADMISSION_DATE:'Admission date', DISCHARGE_DATE:'Discharge date', ROOM_LIMIT:'Room limit', SUM_INSURED:'Sum insured'};
 function candidates(row, field) {
  return ['rules', 'neural'].flatMap(source => (source === 'rules'
   ? row.result?.review_fields?.fields?.[field]?.candidates || []
   : row.result?.specialists?.suggestions?.[field] || []).map(item => ({...item, source})));
 }
 function rate(value, denominator) { return denominator && Number.isFinite(value) ? `${(value * 100).toFixed(1)}% (${denominator} reviewed fields)` : 'No reviewed fields'; }
 if (typeof module !== 'undefined') module.exports = {candidates, rate};
 if (typeof document === 'undefined') return;
 const root = document.getElementById('review-tools');
 if (!root) return;
 const get = id => document.getElementById(id);
 const node = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
 };
 const list = (target, items, render, empty) => {
  target.replaceChildren();
  if (!items.length) target.append(node('p', empty, 'small'));
  else for (const item of items) target.append(render(item));
 };
 function citation(item) {
  const button = node('button', `${item.filename || 'Source'} · page ${item.page}`, 'textbutton');
  button.type = 'button';
  button.addEventListener('click', () => document.dispatchEvent(new CustomEvent('policy:evidence', {detail:{documentId:item.document_id, page:item.page}})));
  return button;
 }
 let row = null, sequence = 0, generation = 0, fetchKey = '', neuralKey = '', formRevision = null, dirty = false, saving = false;
 const form = get('correction-form');
 for (const [key, label] of Object.entries(labels)) get('correction-field').append(new Option(label, key));
 const status = get('correction-status');
 function setStatus(text, error = false) { status.textContent = text; status.className = error ? 'error' : 'small'; }
 function setRevision() {
  formRevision = row?.review_revision || null;
  dirty = false;
  setStatus('');
  updateLock();
 }
 function updateLock() {
  const stale = Boolean(formRevision && row?.review_revision !== formRevision);
  get('correction-save').disabled = saving || !formRevision || stale || row?.state !== 'ready';
  get('correction-reset').hidden = !stale;
  if (stale) setStatus('The review changed. Reload the current revision and recheck your citation before saving.', true);
 }
 function fillPages() {
  const doc = row?.documents.find(item => item.id === get('correction-document').value);
  get('correction-page').replaceChildren(...(doc?.pages || []).map(page => new Option(`Page ${page.page}`, page.page)));
  get('correction-start').value = '';
  get('correction-end').value = '';
 }
 function fillCandidates() {
  const options = candidates(row, get('correction-field').value);
  const select = get('correction-candidate');
  select.replaceChildren(new Option('Enter a value and source citation', ''));
  options.forEach((item, index) => select.append(new Option(`${item.source}: ${item.value ?? item.source_text} · page ${item.page}`, index)));
 }
 function initializeForm() {
  form.reset();
  get('correction-document').replaceChildren(...row.documents.map(doc => new Option(doc.filename, doc.id)));
  fillPages(); fillCandidates(); setRevision();
 }
 form.addEventListener('input', () => { dirty = true; });
 form.addEventListener('change', () => { dirty = true; });
 get('correction-field').addEventListener('change', fillCandidates);
 get('correction-document').addEventListener('change', fillPages);
 get('correction-candidate').addEventListener('change', () => {
  const index = get('correction-candidate').value;
  if (index === '') return;
  const item = candidates(row, get('correction-field').value)[Number(index)];
  if (!item) return;
  get('correction-value').value = item.value ?? item.source_text;
  get('correction-source').value = item.source;
  get('correction-document').value = item.document_id;
  fillPages();
  get('correction-page').value = item.page;
  get('correction-start').value = item.start_offset;
  get('correction-end').value = item.end_offset;
 });
 get('correction-reset').addEventListener('click', () => initializeForm());
 function neural() {
  const key = JSON.stringify([row.id, row.result?.specialists]);
  if (key === neuralKey) return;
  neuralKey = key;
  const target = get('neural-results');
  target.replaceChildren();
  const result = row.result?.specialists;
  target.append(node('p', `Neural assistance: ${result?.state || 'not run'}`, 'small'));
  if (result?.detail) target.append(node('p', result.detail, 'small'));
  if (result?.checkpoint) target.append(node('p', `Checkpoint: ${result.checkpoint}`, 'small'));
  if (result?.state !== 'ready') return;
  target.append(node('p', 'Scores order evidence; they are not probabilities. Compare suggestions with the extracted rule fields and original pages.', 'small'));
  for (const [key, label] of Object.entries(labels)) {
   const section = node('details');
   section.append(node('summary', label));
   const suggestions = result.suggestions?.[key] || [];
   if (!suggestions.length) section.append(node('p', 'No neural suggestion.', 'small'));
   for (const item of suggestions) {
    const p = node('p', `${item.value ?? item.source_text} `);
    p.append(citation(item)); section.append(p);
   }
   const evidence = result.evidence?.[key] || [];
   if (evidence.length) section.append(node('h4', 'Ranked supporting passages'));
   const ranked = node('ol');
   for (const item of evidence) {
    const li = node('li');
    li.append(node('q', item.source_text), node('p', `Ordering score: ${item.score}`, 'small'), citation(item));
    ranked.append(li);
   }
   section.append(ranked); target.append(section);
  }
 }
 function renderTools(data) {
  list(get('document-checklist'), data.checklist || [], item => node('li', `${item.present ? 'Present' : 'Missing'} · ${item.label}${item.required ? '' : ' (optional)'}`), 'No checklist available.');
  const timeline = get('claim-timeline');
  timeline.replaceChildren();
  for (const warning of data.timeline_warnings || []) timeline.append(node('p', String(warning).replaceAll('_', ' '), 'ocr-tag'));
  for (const [title, unresolved] of [['Dated evidence', false], ['Unresolved dates', true]]) {
   const items = (data.timeline || []).filter(item => Boolean(!item.normalized_date) === unresolved);
   if (!items.length) continue;
   timeline.append(node('h4', title));
   for (const item of items) {
    const p = node('p', `${labels[item.field] || item.field}: ${item.normalized_date || item.value || item.source_text} · ${item.confirmed ? 'Reviewer confirmed' : item.source} `);
    p.append(citation(item));
    if (item.unresolved_reason) p.append(node('span', ` · ${item.unresolved_reason.replaceAll('_', ' ')}`, 'small'));
    timeline.append(p);
   }
  }
  if (!timeline.childNodes.length) timeline.append(node('p', 'No admission or discharge date evidence yet.', 'small'));
  const currentIds = new Set((data.current_corrections || []).map(item => item.id));
  list(get('correction-history'), data.corrections || [], item => {
   const li = node('li');
   li.append(node('strong', `${labels[item.field] || item.field}: ${item.value}`), node('p', `${currentIds.has(item.id) ? 'Current' : 'Historical'} · ${item.outcome} · ${item.source} · ${item.actor} · ${item.created_at}`, 'small'), node('p', item.reason), citation(item));
   return li;
  }, 'No reviewer corrections recorded.');
 }
 async function loadTools() {
  const id = row.id, request = ++sequence;
  get('review-tools-status').textContent = 'Loading review tools…';
  try {
   const data = await api(`/cases/${encodeURIComponent(id)}/tools`);
   if (request !== sequence || row?.id !== id) return;
   renderTools(data);
   get('review-tools-status').textContent = '';
  } catch (error) {
   if (request !== sequence || row?.id !== id) return;
   fetchKey = '';
   get('review-tools-status').textContent = `Review tools unavailable. ${error.message}`;
  }
 }
 document.addEventListener('policy:case', event => {
  const next = event.detail?.case;
  if (!next) { row = null; sequence++; generation++; fetchKey = ''; root.hidden = true; return; }
  const changed = row?.id !== next.id;
  if (changed) generation++;
  row = next; root.hidden = false;
  if (changed || (!dirty && formRevision !== row.review_revision)) initializeForm();
  updateLock(); neural();
  get('review-report').href = `/api/cases/${encodeURIComponent(row.id)}/report`;
  if (changed) for (const id of ['document-checklist', 'claim-timeline', 'correction-history']) get(id).replaceChildren();
  const key = JSON.stringify([row.id, row.updated_at, row.review_revision]);
  if (key !== fetchKey) { fetchKey = key; loadTools(); }
 });
 form.addEventListener('submit', async event => {
  event.preventDefault();
  if (saving || !row || formRevision !== row.review_revision || !formRevision) return;
  const id = row.id, session = generation;
  const body = {review_revision:formRevision};
  for (const [key, control] of Object.entries({field:'field', value:'value', reason:'reason', document_id:'document', page:'page', start_offset:'start', end_offset:'end', source:'source'})) {
   body[key] = ['page','start_offset','end_offset'].includes(key) ? Number(get(`correction-${control}`).value) : get(`correction-${control}`).value;
  }
  if (body.end_offset <= body.start_offset) { setStatus('End offset must be greater than start offset.', true); return; }
  saving = true; updateLock(); setStatus('Saving reviewer correction…');
  try {
   await api(`/cases/${encodeURIComponent(id)}/corrections`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
   if (row?.id !== id || session !== generation) return;
   dirty = false; formRevision = null; fetchKey = '';
   document.dispatchEvent(new CustomEvent('policy:refresh-case', {detail:{id}}));
   setStatus('Correction saved. Reloading the current review…');
  } catch (error) {
   if (row?.id !== id || session !== generation) return;
   setStatus(error.status === 409 ? 'The review changed. Your correction was not saved. Reload the current revision and recheck your citation.' : error.message, true);
   if (error.status === 409) document.dispatchEvent(new CustomEvent('policy:refresh-case', {detail:{id}}));
  } finally { saving = false; updateLock(); }
 });
 let metricsSequence = 0;
 async function metrics() {
  const request = ++metricsSequence;
  const target = get('review-metrics');
  get('review-metrics-status').textContent = 'Loading review statistics…';
  try {
   const data = await api('/review-metrics');
   if (request !== metricsSequence) return;
   target.replaceChildren();
   const summary = node('dl', null, 'review-statistics');
   for (const [label, value] of [['Reviewed suggestion fields',data.reviewed_fields],['Manual fields without a prediction',data.manual_fields ?? 0],['Accepted suggestions',data.accepted],['Corrected suggestions',data.corrected],['Correction rate',rate(data.correction_rate,data.reviewed_fields)],['Rule / model disagreements',data.disagreements],['Unavailable inference runs',`${data.unavailable_runs} of ${data.inference_runs} runs`]]) {
    const group = node('div'); group.append(node('dt', label), node('dd', value)); summary.append(group);
   }
   target.append(summary, node('p', data.denominator || 'Counts use the latest reviewed field per evidence revision, not every edit.', 'small'), node('p', data.notice, 'small'));
   if (data.neural) target.append(node('p', `Neural suggestions: ${data.neural.accepted} accepted, ${data.neural.corrected} corrected. Correction rate: ${rate(data.neural.correction_rate, data.neural.reviewed_fields)}.`, 'small'));
   if (data.by_checkpoint?.length) {
    const table = node('table');
    const caption = node('caption', 'Neural review outcomes by checkpoint and field');
    const head = node('tr');
    for (const label of ['Checkpoint','Field','Reviewed','Accepted','Corrected','Correction rate']) { const th = node('th', label); th.scope = 'col'; head.append(th); }
    const thead = node('thead'); thead.append(head);
    const tbody = node('tbody');
    for (const item of data.by_checkpoint) {
     const tr = node('tr');
     for (const value of [item.checkpoint, labels[item.field] || item.field, item.reviewed_fields, item.accepted, item.corrected, rate(item.correction_rate,item.reviewed_fields)]) tr.append(node('td', value));
     tbody.append(tr);
    }
    table.append(caption, thead, tbody); target.append(table);
   }
   get('review-metrics-status').textContent = data.reviewed_fields ? '' : 'No reviewed field outcomes yet.';
  } catch (error) { if (request === metricsSequence) get('review-metrics-status').textContent = `Review statistics unavailable. ${error.message}`; }
 }
 get('review-dashboard').addEventListener('toggle', event => { if (event.target.open) metrics(); });
 get('refresh-review-metrics').addEventListener('click', metrics);
})();
