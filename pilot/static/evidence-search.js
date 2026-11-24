'use strict';

/* Exact text matches scoped to the currently open case's stored page text. */
(() => {
 const root = document.getElementById('evidence-search');
 if (!root) return;
 root.innerHTML = `<form role="search">
   <label for="case-evidence-query">Find text in case documents</label>
   <div class="evidence-search-controls">
    <input id="case-evidence-query" type="search" maxlength="160" required placeholder="e.g. room rent">
    <button type="submit" class="secondary">Find</button>
   </div>
 </form>
 <p class="small" role="status"></p>
 <ul class="evidence-matches"></ul>`;
 const input = root.querySelector('input');
 const list = root.querySelector('ul');
 const status = root.querySelector('[role=status]');
 let caseId = null;
 let searched = '';
 let previousResults = '';

 function search() {
  const matches = [];
  // Match whitespace across PDF line wraps. Escape all user-supplied punctuation.
  const phrase = searched.split(/\s+/u).map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
  const pattern = new RegExp(phrase, 'iu');
  let pageCount = 0;
  for (const doc of active.documents) {
   for (const page of doc.pages || []) {
    const source = page.text || '';
    if (!source.trim()) continue;
    pageCount++;
    const match = pattern.exec(source);
    if (!match) continue;
    matches.push({
     doc: doc.id, filename: doc.filename, page: page.page,
     before: source.slice(Math.max(0, match.index - 65), match.index),
     hit: match[0], after: source.slice(match.index + match[0].length, match.index + match[0].length + 90),
    });
   }
  }
  const signature = JSON.stringify([pageCount, matches]);
  if (signature === previousResults) return;
  previousResults = signature;
  list.replaceChildren();
  status.textContent = matches.length
   ? `${matches.length} matching ${matches.length === 1 ? 'page' : 'pages'} of ${pageCount} with readable text.`
   : `No match in ${pageCount} readable ${pageCount === 1 ? 'page' : 'pages'}. Try a shorter phrase.`;
  for (const match of matches) {
   const item = document.createElement('li');
   const citation = document.createElement('button');
   citation.type = 'button';
   citation.className = 'textbutton';
   citation.textContent = `${match.filename} · page ${match.page}`;
   citation.dataset.evidence = match.doc;
   citation.dataset.page = match.page;
   const snippet = document.createElement('p');
   const mark = document.createElement('mark');
   mark.textContent = match.hit;
   snippet.append(match.before, mark, match.after);
   item.append(citation, snippet);
   list.append(item);
  }
 }

 function clearResults() {
  list.replaceChildren(); status.textContent = '';
  searched = ''; previousResults = '';
 }
 root.querySelector('form').addEventListener('submit', event => {
  event.preventDefault();
  if (!active || active.id !== caseId) return;
  searched = input.value.trim();
  if (searched) search();
  else clearResults();
 });
 input.addEventListener('input', clearResults);
 list.addEventListener('click', event => {
  if (active?.id === caseId) openEvidenceCitation(event);
 });
 document.addEventListener('policy:case', event => {
  const id = event.detail?.id || null;
  if (caseId !== id) {
   input.value = '';
   clearResults();
   caseId = id;
  }
  root.hidden = !id || active?.id !== id || !active.documents.some(doc => doc.pages?.some(p => p.text?.trim()));
  if (root.hidden) clearResults();
  else if (searched) search();
 });
})();
