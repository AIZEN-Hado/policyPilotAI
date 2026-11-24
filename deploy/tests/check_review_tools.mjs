// Dependency-free DOM contract checks: races, revision preservation, citations, escaping.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
class Element extends EventTarget {
 constructor(text = '', value = '') { super(); this.textContent = text; this.value = value; this.children = []; }
 append(...items) { this.children.push(...items); }
 replaceChildren(...items) { this.children = items; }
 get childNodes() { return this.children; }
 reset() { this.resets = (this.resets || 0) + 1; }
}
const nodes = new Map();
const document = new EventTarget();
document.getElementById = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
document.createElement = () => new Element();
class CustomEvent extends Event { constructor(type, {detail}) { super(type); this.detail = detail; } }
const pending = [];
const context = {document, CustomEvent, Option:Element, api:(url, options) => new Promise((resolve, reject) => pending.push({url, options, resolve, reject}))};
vm.runInNewContext(readFileSync(new URL('../../pilot/static/review-tools.js', import.meta.url),'utf8'), context);
const get = id => document.getElementById(id);
const change = row => document.dispatchEvent(new CustomEvent('policy:case',{detail:row ? {case:row} : null}));
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const row = {id:'a',state:'ready',updated_at:'1',review_revision:'r1',documents:[],result:{specialists:{state:'unavailable',detail:'<script>bad</script>'}}};
change(row);
assert.equal(get('neural-results').children[1].textContent, '<script>bad</script>');
get('correction-value').value = 'unsaved';
get('correction-form').dispatchEvent(new Event('input'));
const resets = get('correction-form').resets;
change({...row, updated_at:'2',review_revision:'r2'});
assert.equal(get('correction-form').resets, resets);
assert.equal(get('correction-value').value,'unsaved');
assert.equal(get('correction-save').disabled,true);
assert.match(get('correction-status').textContent,/review changed/);
get('correction-reset').dispatchEvent(new Event('click'));
assert.equal(get('correction-save').disabled,false);
change({...row,id:'b'});
pending[0].resolve({checklist:[{label:'OLD CASE'}]});
await flush();
assert.equal(get('document-checklist').children.length,0,'stale response cannot render another case');
pending.at(-1).resolve({checklist:[{label:'<b>Policy</b>',present:true,required:true}],timeline:[{field:'ADMISSION_DATE',value:'ambiguous',source:'rules',document_id:'doc',page:1}],corrections:[]});
await flush();
assert.equal(get('document-checklist').children[0].textContent,'Present · <b>Policy</b>');
assert.equal(get('claim-timeline').children[0].textContent,'Unresolved dates');
let evidence;
document.addEventListener('policy:evidence', event => { evidence = event.detail; });
get('claim-timeline').children[1].children[0].dispatchEvent(new Event('click'));
assert.equal(evidence.documentId,'doc');
assert.equal(evidence.page,1);
// Saving carries the frozen revision and exact citation, and asks the app to reload.
let refresh;
document.addEventListener('policy:refresh-case', event => { refresh = event.detail; });
for (const [id,value] of Object.entries({field:'POLICY_ID',value:'SYN-1',reason:'Checked source',document:'doc',page:'1',start:'0',end:'5',source:'rules'})) get(`correction-${id}`).value=value;
get('correction-form').dispatchEvent(new Event('submit',{cancelable:true}));
assert.equal(pending.at(-1).options.method,'POST');
const body=JSON.parse(pending.at(-1).options.body);
assert.equal(body.review_revision,'r1');
assert.equal(body.start_offset,0);
assert.equal(body.end_offset,5);
assert.equal(body.document_id,'doc');
pending.at(-1).resolve({});
await flush();
assert.equal(refresh.id,'b');
assert.equal(get('correction-save').disabled,true,'saved revision remains locked until case reload');
change(null);
assert.equal(get('review-tools').hidden,true);
get('review-dashboard').open=true;
get('review-dashboard').dispatchEvent(new Event('toggle'));
pending.at(-1).resolve({reviewed_fields:0,accepted:0,corrected:0,correction_rate:null,disagreements:0,unavailable_runs:0,inference_runs:0,notice:'Not accuracy',by_checkpoint:[]});
await flush();
assert.equal(get('review-metrics-status').textContent,'No reviewed field outcomes yet.');
assert.equal(get('review-metrics').children[0].children[4].children[1].textContent,'No reviewed fields');
console.log('PASS: stale navigation, revision-bound drafts, safe text, citations and empty metrics.');
