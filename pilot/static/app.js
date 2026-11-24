'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
let cases = [], active = null, selected = null, poll = null, loading = false, processingAvailable = false, pdfAvailable = true;
const labels = {draft:'Draft',queued:'Queued',processing:'Processing',ready:'Review ready',failed:'Needs attention'};
const badge = (state, acknowledged=false) => {
 const label = state === 'ready' && acknowledged ? 'Reviewed' : labels[state] || state;
 return `<span class="badge ${esc(state)}">${esc(label)}</span>`;
};
const kinds = {policy:'Policy wording',schedule:'Policy schedule',endorsement:'Endorsement',claim_form:'Claim form',
 bill:'Hospital bill',discharge:'Discharge summary',receipt:'Payment receipt',other:'Supporting document'};
const fieldLabels = {
 POLICY_ID:'Policy ID', MEMBER_ID:'Member ID', ADMISSION_DATE:'Admission date',
 DISCHARGE_DATE:'Discharge date', ROOM_LIMIT:'Room limit', SUM_INSURED:'Sum insured',
};
const fieldStatuses = {
 found:'Found', missing:'Missing', conflicting:'Conflicting values', needs_verification:'Needs verification',
};
const fieldReasons = {
 check_against_original:'Check the original PDF.',
 endorsement_applicability_unverified:'Confirm whether this endorsement applies.',
 ambiguous_numeric_date:'The month and day are ambiguous.',
 invalid_calendar_date:'The source date is invalid.',
 unrecognized_date:'The date format could not be read.',
};
let fieldSnapshot = null;
let navigationVersion = 0;
let requestedCase = null;
const markupCache = new Map();
function setMarkup(id, html) {
 if(markupCache.get(id) === html) return;
 $(id).innerHTML = html;
 markupCache.set(id, html);
}

function renderReviewFields(report, caseId) {
 const panel = $('review-fields');
 const rows = Object.entries(fieldLabels).filter(([key]) => report?.fields?.[key]);
 const snapshot = rows.length ? JSON.stringify([caseId, report]) : null;
 if(snapshot === fieldSnapshot) return;
 fieldSnapshot = snapshot;
 panel.hidden = !rows.length;
 if(!rows.length) {
  panel.replaceChildren();
  return;
 }
 const chronology = report.issues?.includes('discharge_before_admission')
  ? '<p class="ocr-tag">The discharge date is earlier than the admission date. Check both sources.</p>' : '';
 const missing = rows.filter(([key]) => report.fields[key].status === 'missing').length;
 const flagged = rows.filter(([key]) => ['conflicting', 'needs_verification'].includes(report.fields[key].status)).length;
 const summary = [flagged && `${flagged} to verify`, missing && `${missing} missing`].filter(Boolean).join(' · ');
 panel.innerHTML = `<h3 id="review-fields-title">Extracted fields</h3>${summary ? `<p class="field-summary">${summary}</p>` : ''}${chronology}` + rows.map(([key, label]) => {
  const field = report.fields[key];
  const status = Object.hasOwn(fieldStatuses, field.status) ? field.status : 'needs_verification';
  const amount = key === 'ROOM_LIMIT' || key === 'SUM_INSURED';
  const value = status === 'found' && field.value != null
   ? `<span class="field-value">${amount ? 'INR ' : ''}${esc(field.value)}</span>` : '';
  const header = `<strong>${label}</strong>${value}<span class="field-status ${status}">${fieldStatuses[status]}</span>`;
  if(!field.candidates?.length) return `<div class="field-row"><div class="field-heading">${header}</div></div>`;
  const citations = field.candidates.map(candidate => {
   const reasons = [...new Set((candidate.review_reasons || []).map(reason =>
    Object.hasOwn(fieldReasons, reason) ? fieldReasons[reason] : 'Check the original PDF.'))];
   return `<li><q>${esc(candidate.source_text)}</q>
    <button type="button" class="textbutton" data-evidence="${esc(candidate.document_id)}" data-page="${esc(candidate.page)}">
     ${esc(candidate.filename)} · page ${esc(candidate.page)} ↗
    </button>${reasons.map(reason => `<p class="small">${esc(reason)}</p>`).join('')}</li>`;
  }).join('');
  return `<details class="field-row"${status !== 'found' ? ' open' : ''}>
   <summary class="field-heading">${header}</summary>
   <ul class="field-citations">${citations}</ul>
  </details>`;
 }).join('');
}

function message(text, error=false) { $('message').textContent=text; $('message').className=text?(error?'error':'success'):''; }
async function api(path,options={}) {
 const response=await fetch('/api'+path,{credentials:'same-origin',...options});
 if(response.status===401){location.replace('/login');throw Error('Please sign in to continue.');}
 if(!response.ok){let data;try{data=await response.json();}catch{throw Error('The service did not respond. Check your connection.');}const error = Error(typeof data.detail==='string'?data.detail:'Please check the supplied fields.');
 error.status=response.status;throw error;}
 return response.status===204?null:response.json();
}
function renderList(){
 const query=$('search').value.trim().toLowerCase();
 const state=$('state-filter').value;
 const filtered=cases.filter(c=>(c.title.toLowerCase().includes(query)||c.id.toLowerCase().includes(query))&&(state==='all'||c.state===state));
 $('list-summary').textContent=filtered.length+' of '+cases.length+' cases'+(state==='all'?'':' · '+labels[state]);
 $('total').textContent=cases.length;$('ready').textContent=cases.filter(c=>c.state==='ready').length;$('processing').textContent=cases.filter(c=>['queued','processing'].includes(c.state)).length;$('failed').textContent=cases.filter(c=>c.state==='failed').length;
 $('queue-columns').hidden = filtered.length === 0;
 if(!filtered.length) {
  const searching = query || state !== 'all';
  setMarkup('case-list', searching
   ? '<div class="empty"><strong>No matching cases.</strong><p>Try a different search or choose All statuses.</p></div>'
   : '<div class="empty"><strong>No cases yet.</strong><p>Create a case to start reviewing its documents.</p></div>');
  return;
 }
 setMarkup('case-list', filtered.map(c => {
  const date = new Date(c.created_at).toLocaleDateString('en-IN', {day:'numeric', month:'short', year:'numeric'});
  return `<button type="button" class="case-row" data-case="${esc(c.id)}">
   <span><strong>${esc(c.title)}</strong><small>${esc(c.id.slice(0,8).toUpperCase())}</small></span>
   ${badge(c.state)}<time class="date small" datetime="${esc(c.created_at)}"><span class="sr-only">Created </span>${esc(date)}</time>
   <span class="case-arrow" aria-hidden="true">→</span></button>`;
 }).join(''));
}
async function refreshList(){cases=await api('/cases');renderList();}
async function openCase(id){
 const version=++navigationVersion;
 requestedCase=id;
 clearTimeout(poll);
 const row=await api('/cases/'+encodeURIComponent(id));
 if(version!==navigationVersion) return;
 const changingCase=active?.id!==id;
 if(changingCase){
  selected=null;
  $('upload-form').reset();
 }
 active=row;
 $('overview').hidden=true;
 $('detail').hidden=false;
 renderCase();
 if(changingCase) $('case-title').focus();
 schedulePoll();
}
function schedulePoll(){
 clearTimeout(poll);
 if(active && requestedCase===active.id) poll=setTimeout(tick,['queued','processing'].includes(active.state)?3000:10000);
}
async function tick(){
 if(!active || requestedCase!==active.id) return;
 if(loading || reviewingCase===active.id){schedulePoll();return;}
 const id=active.id;
 try{await openCase(id);}
 catch(e){if(requestedCase===id){message(e.message,true);schedulePoll();}}
}
let reviewingCase = null;
function assessmentMarkup(result, {busy, reading, hasDocuments}) {
 if(!result) {
  if(reading) return '<div class="empty"><strong>Reading PDF fields…</strong><p>Checking the attached pages for labeled values and source citations.</p></div>';
  if(busy) return '<div class="empty"><strong>Processing documents…</strong><p>You can return to the queue while this case runs.</p></div>';
  if(!hasDocuments) return '<div class="empty"><strong>No documents to review.</strong><p>Attach a synthetic PDF to begin.</p></div>';
  if(!pdfAvailable) return '<div class="empty"><strong>PDF review is unavailable.</strong><p>Download the original documents to review them.</p></div>';
  return '<div class="empty"><strong>No field review yet.</strong><p>Select Review PDF fields to see labeled values and their source pages.</p></div>';
 }
 const warnings = (result.extraction_warnings || []).map(w =>
  `<li><button type="button" class="textbutton" data-evidence="${esc(w.document_id)}" data-page="${esc(w.page)}">${esc(w.filename)} · page ${esc(w.page)} ↗</button></li>`).join('');
 const coverage = result.evidence_coverage?.omitted_document_ids?.length || 0;
 const findings = (result.findings || []).map(f => `<article class="finding"><p>${esc(f.statement)}</p>
  <blockquote>${esc(f.quote)}</blockquote>${f.needs_verification ? '<p class="ocr-tag">Verify this source text against the original PDF.</p>' : ''}
  <button type="button" class="textbutton" data-evidence="${esc(f.document_id)}" data-page="${esc(f.page)}">${esc(f.filename)} · page ${esc(f.page)} ↗</button></article>`).join('');
 const questions = (result.questions || []).map(q => `<li>${esc(q)}</li>`).join('');
 return `<div class="review-caption small"><strong>${esc(result.model)}</strong><span>${esc(result.total_pages)} pages · ${esc(result.ocr_pages)} OCR</span></div>
  <p>${esc(result.summary)}</p>
  ${result.context_truncated ? '<div class="ocr-tag">Only selected excerpts were reviewed.</div>' : ''}
  ${coverage ? `<div class="ocr-tag">${esc(coverage)} uploaded documents had no selected excerpts. Review their originals.</div>` : ''}
  ${warnings ? `<h3 class="warning-title">Check against original PDF</h3><ul class="warning-pages">${warnings}</ul>` : ''}
  ${findings}${questions ? `<h2>Verify before deciding</h2><ul class="question-list">${questions}</ul>` : ''}
  <p class="small">${esc(result.notice)}</p>`;
}
function renderCase(){
 const busy=['queued','processing'].includes(active.state);
 $('case-id').textContent='CASE / '+active.id.slice(0,8).toUpperCase();$('case-title').textContent=active.title;$('case-description').textContent=active.description;$('case-state').innerHTML=badge(active.state, active.review_acknowledged);
 const reading=reviewingCase===active.id;
 const locked=busy || reading || loading===active.id;
 $('run').disabled=locked || !processingAvailable;
 $('run').textContent=busy?'Processing in background…':active.state==='failed'?'Retry processing':'Process & assess';
 $('run').hidden=!processingAvailable;
 $('upload-button').disabled=locked || Boolean(loading) || active.documents.length>=12;
 $('upload-button').textContent=loading===active.id?'Uploading…':'Attach document';
 $('delete-case').disabled=locked;
 $('acknowledge').disabled=locked || active.state!=='ready' || !active.review_revision || active.review_acknowledged;
 $('acknowledge').textContent=active.review_acknowledged?'Acknowledgement recorded':'Record acknowledgement';
 const pdfReview=$('pdf-review');
 pdfReview.hidden=!['draft','failed'].includes(active.state) || !active.documents.length;
 pdfReview.disabled=locked || reviewingCase!==null || !pdfAvailable;
 pdfReview.textContent=reading?'Reading PDF fields…':pdfAvailable?'Review PDF fields':'PDF review unavailable';
 $('case-error').hidden=!active.error;$('case-error').textContent=active.error||'';
 $('doc-count').textContent=active.documents.length+' of 12';
 if(!active.documents.some(doc=>doc.id===selected))selected=active.documents[0]?.id || null;
 setMarkup('documents',active.documents.length?active.documents.map(d=>`<button class="doc-button ${d.id===selected?'selected':''}" aria-pressed="${d.id===selected}" data-doc="${esc(d.id)}"><span>${esc(kinds[d.kind] || d.kind)} · ${d.pages?d.pages.length+(d.pages.length===1?' page':' pages'):'Awaiting extraction'}</span>${esc(d.filename)}</button>`).join(''):'<p class="empty">Attach this claim’s documents below.</p>');
 renderSource();
 const result=active.result;
 renderReviewFields(result?.review_fields, active.id);
 setMarkup('result', assessmentMarkup(result, {busy, reading, hasDocuments: active.documents.length > 0}));
 setMarkup('events',active.events.map(e=>`<div class="event"><span>${esc(e.action.replaceAll('_',' '))}</span><span>${esc(e.actor)} · ${esc(new Date(e.created_at).toLocaleString('en-IN'))}</span></div>`).join(''));
 document.dispatchEvent(new CustomEvent('policy:case',{detail:{id:active.id,updatedAt:active.updated_at,case:active}}));
}
function renderSource(){
 const doc=active.documents.find(d=>d.id===selected);
 $('download').hidden=!doc;
 if(!doc){
  $('source-title').textContent='Select a document';
  setMarkup('source-content','<div class="empty"><strong>No source pages yet.</strong><p>Attach a PDF and review its fields to see the source text.</p></div>');
  return;
 }
 $('source-title').textContent=doc.filename;
 $('download').href=`/api/cases/${encodeURIComponent(active.id)}/documents/${encodeURIComponent(doc.id)}`;
 const pages=doc.pages?.map(p=>{
  const method=p.method==='ocr'?'OCR text':p.method==='fixture'?'Sample page':'PDF text';
  return `<section class="page-text" id="page-${esc(p.page)}" tabindex="-1"><h3>Page ${esc(p.page)} · ${method}</h3>${p.needs_verification?'<div class="ocr-tag">Check this page against the original PDF.</div>':''}<pre>${esc(p.text || 'No readable text found on this page.')}</pre></section>`;
 }).join('');
 setMarkup('source-content',pages || '<div class="empty"><strong>Original attached.</strong><p>Select Review PDF fields to see readable text, or download the original.</p></div>');
}
document.addEventListener('policy:refresh-case',async e=>{
 const id=e.detail?.id;
 if(!id || active?.id!==id || requestedCase!==id) return;
 try{await openCase(id);}catch(error){if(requestedCase===id)message(error.message,true);}
});
document.addEventListener('policy:connection',e=>{processingAvailable=Boolean(e.detail?.processing_enabled);if(active)renderCase();});
document.addEventListener('policy:evidence',e=>focusSource(e.detail.documentId,Number(e.detail.page)));
async function back(){
 ++navigationVersion;
 requestedCase=null;
 clearTimeout(poll);
 active=null;
 selected=null;
 document.dispatchEvent(new CustomEvent('policy:case',{detail:null}));
 $('detail').hidden=true;
 $('overview').hidden=false;
 await refreshList();
 if(!requestedCase) $('new-case').focus({preventScroll:true});
}
const safely = fn => async event => {try{await fn(event);}catch(e){message(e.message,true);}};
$('sign-out').onclick=safely(async()=>{await api('/auth/logout',{method:'POST'});location.replace('/login');});
api('/auth/me').then(user=>{$('sign-out').hidden=user.auth_mode!=='session';}).catch(()=>{});
$('new-case').onclick=()=>{$('create-error').hidden=true;$('new-dialog').showModal();};$('close-dialog').onclick=()=>$('new-dialog').close();$('about').onclick=()=>$('about-dialog').showModal();$('close-about').onclick=()=>$('about-dialog').close();
$('home').onclick=safely(back);$('back').onclick=safely(back);$('search').oninput=renderList;$('state-filter').onchange=renderList;
$('case-list').onclick=safely(async e=>{const b=e.target.closest('[data-case]');if(b){message('');await openCase(b.dataset.case);}});
$('documents').onclick=e=>{const b=e.target.closest('[data-doc]');if(b){
 selected=b.dataset.doc;
 renderCase();
 $('source-title').focus();
}};
function openEvidenceCitation(event) {
 const citation = event.target.closest('[data-evidence]');
 if(citation) focusSource(citation.dataset.evidence,Number(citation.dataset.page));
}
function focusSource(documentId,page){
 if(!active?.documents.some(doc=>doc.id===documentId)) return;
 selected=documentId;
 renderCase();
 if(Number.isInteger(page) && page > 0) {
  const sourcePage = document.getElementById('page-' + page);
  if(sourcePage) {
   sourcePage.tabIndex = -1;
   sourcePage.focus({preventScroll:true});
   sourcePage.scrollIntoView({block:'nearest'});
   return;
  }
 }
 $('source-title').focus();
}
$('result').onclick = openEvidenceCitation;
$('review-fields').onclick = openEvidenceCitation;
$('create-form').onsubmit=async e=>{
 e.preventDefault();
 const button=$('create-button'),error=$('create-error');
 button.disabled=true;button.textContent='Creating case…';error.hidden=true;
 try{
  const row=await api('/cases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:$('title').value,description:$('description').value})});
  $('new-dialog').close();e.target.reset();message('Case created. Attach the matching policy and claim documents.');
  try{await openCase(row.id);}catch(e){message('Case created, but could not be opened. Return to the claims list. '+e.message,true);}
 }catch(e){error.textContent=e.message;error.hidden=false;error.tabIndex=-1;error.focus();}
 finally{button.disabled=false;button.textContent='Create case';}
};
$('upload-form').onsubmit=safely(async e=>{
 e.preventDefault();
 const file=$('file').files[0];
 if(!file || loading) return;
 if(file.size>10*1024*1024) throw Error('Choose a PDF of 10 MB or less.');
 const id=active.id, kind=$('document-kind').value;
 loading=id;
 renderCase();
 try{
  await api(`/cases/${id}/documents?kind=${encodeURIComponent(kind)}&filename=${encodeURIComponent(file.name)}`,
   {method:'PUT',headers:{'Content-Type':'application/pdf'},body:file});
  if(requestedCase===id){
   $('file').value='';
   message('Document attached. Review the current packet to see its fields.');
   await openCase(id);
  }
 } finally {
  loading=false;
  if(active) renderCase();
 }
});
$('pdf-review').onclick=safely(async()=>{
 const id=active.id;
 reviewingCase=id;
 renderCase();
 message('Reading PDFs and checking labeled fields…');
 try {
  await api('/cases/'+id+'/pdf-review',{method:'POST'});
  if(requestedCase===id){
   await openCase(id);
   message('PDF field review is ready. Follow a citation to check the original page.');
  }
 } finally {
  reviewingCase=null;
  if(active) renderCase();
 }
});
$('run').onclick=safely(async()=>{
 const id=active.id;
 $('run').disabled=true;
 try{
  await api('/cases/'+id+'/assess',{method:'POST'});
  if(requestedCase===id){message('Queued for extraction and assessment.');await openCase(id);}
 } finally {if(active) renderCase();}
});
$('acknowledge').onclick=safely(async()=>{
 const id=active.id, revision=active.review_revision;
 $('acknowledge').disabled=true;
 try {
  await api('/cases/'+id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({review_revision:revision})});
  if(requestedCase===id){await openCase(id);message('Review acknowledgement recorded.');}
 } catch(error) {
  if(error.status===409 && requestedCase===id){
   await openCase(id);
   message('The case changed. Check the latest evidence before recording your acknowledgement.',true);
  } else throw error;
 } finally {if(active) renderCase();}
});
$('delete-case').onclick=safely(async()=>{
 const id=active.id;
 if(!confirm('Delete this case? Access ends immediately. Uploaded files are queued for removal.')) return;
 await api('/cases/'+id,{method:'DELETE'});
 if(requestedCase===id){await back();message('Case deleted. Uploaded files are queued for removal.');}
});
(async()=>{try{await refreshList();}catch(e){message(e.message,true);$('list-summary').textContent='Review queue unavailable';$('case-list').innerHTML='<p class="empty">Unable to load the workspace. Check server access and refresh.</p>';}try{const r=await api('/readiness');processingAvailable=Boolean(r.processing_enabled);pdfAvailable=r.pdf_review_enabled!==false;if(active)renderCase();$('readiness').textContent=r.inference==='registered'?'Model connection configured':r.inference==='disconnected'?'Documents available · model disconnected':'Model unavailable';}catch{$('readiness').textContent='Inference unavailable';}})();
