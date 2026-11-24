// Dependency-free UI logic checks using DOM doubles, not a browser/layout test.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const root=new URL('../../',import.meta.url);
const read=p=>readFileSync(new URL(p,root),'utf8');
const html=read('pilot/static/index.html');
const nodes=new Map();
let focused=null;
function node(id) {
 return {id,hidden:false,disabled:false,value:id==='state-filter'?'all':'',dataset:{},textContent:'',innerHTML:'',className:'',
  replaceChildren(){this.innerHTML='';},focus(){focused=this.id;},scrollIntoView(){this.scrolled=true;},
  showModal(){this.open=true;},close(){this.open=false;},reset(){this.didReset=true;},addEventListener(){}};
}
for(const match of html.matchAll(/\bid="([^"]+)"/g)) {
 assert(!nodes.has(match[1]),'Duplicate ID '+match[1]);nodes.set(match[1],node(match[1]));
}
const preview=read('artifacts/policypilot-ui-preview.html');
for(const id of ['sample-packets','preview-attach','attach-sample','preview-reset','page-1'])nodes.set(id,node(id));
nodes.get('sample-packets').textContent=preview.match(/<script type="application\/json" id="sample-packets">([^<]*)<\/script>/)[1];
const brand=node('brand');
const listeners=new Map();
const context=vm.createContext({console,Response,URL,Date,JSON,Map,Set,Boolean,Number,String,Object,Error,
 location:{hash:'',replace(){throw Error('Unexpected navigation');}},
 setTimeout(){return 1;},clearTimeout(){},confirm(){return true;},
 CustomEvent:class {constructor(type,{detail}){this.type=type;this.detail=detail;}},
 document:{getElementById(id){assert(nodes.has(id),'Missing DOM hook '+id);return nodes.get(id);},
  addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(fn);},
  dispatchEvent(e){for(const fn of listeners.get(e.type)||[])fn(e);},querySelector(){return brand;},querySelectorAll(){return [];}}
});
context.window=context;
vm.runInContext(read('deploy/ui_preview.js'),context);
vm.runInContext(read('pilot/static/app.js'),context);
const run=s=>vm.runInContext(s,context);
for(const fn of listeners.get('DOMContentLoaded') || [])fn();
await run('refreshList()');
assert.equal(nodes.get('total').textContent,3);
assert.equal(nodes.get('list-summary').textContent,'3 of 3 cases');
assert.equal(nodes.get('queue-columns').hidden,false);
assert.match(nodes.get('case-list').innerHTML,/<time\b[^>]+datetime=/);
nodes.get('search').value='syn-c003';run('renderList()');
assert.equal(nodes.get('list-summary').textContent,'1 of 3 cases');
assert(!nodes.get('case-list').innerHTML.includes('syn-c001'));
nodes.get('search').value='';nodes.get('state-filter').value='draft';run('renderList()');
assert.equal(nodes.get('list-summary').textContent,'1 of 3 cases · Draft');
nodes.get('search').value='no such claim';run('renderList()');
assert.match(nodes.get('case-list').innerHTML,/No matching cases/);
assert.match(nodes.get('case-list').innerHTML,/All statuses/);
assert.equal(nodes.get('queue-columns').hidden,true);
nodes.get('search').value='';nodes.get('state-filter').value='all';
await run("openCase('syn-c003')");
assert.equal(focused,'case-title');
assert.equal(nodes.get('run').disabled,true);
assert.match(nodes.get('review-fields').innerHTML,/class="field-row" open/);
assert.match(nodes.get('review-fields').innerHTML,/Conflicting values/);
assert.match(nodes.get('review-fields').innerHTML,/\d+ to verify/);
assert.match(nodes.get('result').innerHTML,/Check against original PDF/);
assert.match(nodes.get('download').href,/^data:application\/pdf;base64,JVBER/);
const discharge=run("active.documents.find(doc=>doc.kind==='discharge').id");
context.citation={target:{closest(){return {dataset:{evidence:discharge,page:'1'}};}}};
run('openEvidenceCitation(citation)');
assert.equal(focused,'page-1');
assert.match(nodes.get('source-content').innerHTML,/2026-10-03/);
assert(nodes.get('page-1').scrolled);
// Unchanged polls must not replace the user's expanded/collapsed field markup.
nodes.get('review-fields').innerHTML='user-expanded-state';run('renderCase()');
assert.equal(nodes.get('review-fields').innerHTML,'user-expanded-state');
await run("openCase('syn-c004')");
assert(nodes.get('review-fields').hidden);
assert.match(nodes.get('source-content').innerHTML,/No source pages yet/);
assert.match(nodes.get('result').innerHTML,/No documents to review/);
assert(!nodes.get('source-content').innerHTML.includes('2026-10-03'));
assert.equal(nodes.get('preview-attach').hidden,false);
await nodes.get('attach-sample').onclick();
assert.equal(nodes.get('pdf-review').hidden,false);
await nodes.get('pdf-review').onclick();
assert.equal(nodes.get('pdf-review').hidden,true);
assert.match(nodes.get('review-fields').innerHTML,/Conflicting values/);
assert.equal(nodes.get('acknowledge').disabled,false);
run("active.review_revision='old-revision'");
await nodes.get('acknowledge').onclick();
assert.match(nodes.get('message').textContent,/case changed/);
assert.equal(nodes.get('acknowledge').disabled,false);
await nodes.get('acknowledge').onclick();
assert.equal(nodes.get('acknowledge').textContent,'Acknowledgement recorded');
assert.equal(nodes.get('acknowledge').disabled,true);
assert.match(nodes.get('case-state').innerHTML,/Reviewed/);
// A slow detail response must not reopen a case after the reviewer returns to the queue.
const fixtureFetch=context.fetch;
let release;
context.fetch=(url,options)=>url==='/api/cases/syn-c004'
 ? new Promise(resolve=>{release=()=>resolve(fixtureFetch(url,options));}) : fixtureFetch(url,options);
const pending=run("openCase('syn-c004')");
await run('back()');release();await pending;
assert.equal(nodes.get('detail').hidden,true);assert.equal(run('active'),null);
context.fetch=fixtureFetch;
// Failed create stays in the dialog, preserves input, restores button and focuses error.
const originalFetch=context.fetch;
context.fetch=()=>Promise.resolve(new Response(JSON.stringify({detail:'Please choose another case title.'}),{status:400}));
nodes.get('title').value='Keep this title';nodes.get('description').value='Keep this synthetic case description.';
run("$('new-case').onclick()");
context.submitEvent={preventDefault(){},target:nodes.get('create-form')};
await run("$('create-form').onsubmit(submitEvent)");
assert.equal(nodes.get('new-dialog').open,true);
assert.equal(nodes.get('title').value,'Keep this title');
assert.equal(nodes.get('create-error').hidden,false);
assert.equal(focused,'create-error');assert.equal(nodes.get('create-button').disabled,false);
context.fetch=originalFetch;
await run("$('create-form').onsubmit(submitEvent)");
assert.equal(nodes.get('new-dialog').open,false);
assert.equal(nodes.get('case-title').textContent,'Keep this title');
assert.equal(focused,'case-title');
await run('back()');assert.equal(focused,'new-case');
// Escaping stays in place for untrusted titles and quoted evidence.
run("cases[0].title='<img src=x onerror=alert(1)>';renderList()");
assert.match(nodes.get('case-list').innerHTML,/&lt;img/);
assert(!nodes.get('case-list').innerHTML.includes('<img'));
run("renderReviewFields({fields:{POLICY_ID:{status:'found',value:'<bad>',candidates:[{source_text:'<script>',filename:'\"onclick=bad',document_id:'doc',page:1}]}}},'escaping-test')");
assert(!nodes.get('review-fields').innerHTML.includes('<script>'));
assert.match(nodes.get('review-fields').innerHTML,/&lt;bad&gt;/);
console.log('PASS: search/filter, conflicts, page citation focus, polling, empty case, form recovery, create/back, sample PDF download and review, stale acknowledgement, late response and HTML escaping (DOM doubles).');
