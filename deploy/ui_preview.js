/* The standalone preview keeps case edits in memory and exposes only bundled synthetic PDFs. */
'use strict';
(() => {
 const packets = JSON.parse(document.getElementById('sample-packets').textContent);
 const stamp = '2026-11-18T09:00:00Z';
 let nextId = 1;
 function sampleCase(id, title, description, packet) {
  return {id, title, description, packet, state:packet ? 'ready' : 'draft',
   documents:packet ? packets[packet].documents : [], result:packet ? packets[packet].result : null,
   review_revision:packet ? id+'-1' : null, review_acknowledged:false,
   events:[{action:'case_created', actor:'Preview reviewer', created_at:stamp}], created_at:stamp};
 }
 const cases = [
  sampleCase('syn-c003', 'SYN-C003 · Conflicting admission dates', 'Compare the date on the claim form with the date recorded at discharge.', 'SYN-C003'),
  sampleCase('syn-c001', 'SYN-C001 · Hospitalization review', 'Check the schedule, identifiers and admission dates in this synthetic claim.', 'SYN-C001'),
  sampleCase('syn-c004', 'SYN-C004 · Documents to collect', 'Attach the synthetic sample packet to try reviewing PDF fields.', null),
 ];
 const reply = (data,status=200) => Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
 function record(row, action) {
  row.events.unshift({action, actor:'Preview reviewer', created_at:new Date().toISOString()});
 }
 window.fetch = (input,options={}) => {
  const url = String(input), method = options.method || 'GET';
  if(url==='/api/auth/me') return reply({auth_mode:'proxy',model_operator:false});
  if(url==='/api/readiness') return reply({processing_enabled:false,inference:'disconnected',pdf_review_enabled:true});
  if(url==='/api/inference') return reply({processing_enabled:false,state:'disconnected',detail:'Offline preview. The sample packet is available locally.'});
  if(url==='/api/cases' && method==='GET') return reply(cases.map(({id,title,state,created_at})=>({id,title,state,created_at})));
  if(url==='/api/cases' && method==='POST'){
   const {title,description}=JSON.parse(options.body);
   const row=sampleCase('preview-'+nextId++,title,description,null);
   cases.unshift(row);
   return reply({id:row.id},201);
  }
  const match=url.match(/^\/api\/cases\/([^/?]+)(.*)$/);
  const row=match && cases.find(c=>c.id===match[1]);
  if(!row) return reply({detail:'Preview case not found.'},404);
  const path=match[2];
  if(path==='/messages' && method==='GET') return reply([]);
  if(path==='/pdf-review' && method==='POST' && row.packet){
   row.documents=packets[row.packet].documents;
   row.result=packets[row.packet].result;
   row.state='ready'; row.review_revision=row.id+'-1';
   record(row,'pdf_fields_reviewed');
   return reply({state:'ready'});
  }
  if(path==='/review' && method==='POST'){
   if(!row.review_revision || JSON.parse(options.body || '{}').review_revision!==row.review_revision)
    return reply({detail:'The case changed. Review the latest evidence.'},409);
   if(!row.review_acknowledged) record(row,'review_acknowledged');
   row.review_acknowledged=true;
   return reply({status:'recorded'});
  }
  if(!path && method==='DELETE'){
   cases.splice(cases.indexOf(row),1);return Promise.resolve(new Response(null,{status:204}));
  }
  if(!path && method==='GET') return reply(row);
  return reply({detail:'This action requires the live workspace.'},409);
 };
 document.addEventListener('policy:case',event=>{
  const row=cases.find(c=>c.id===event.detail?.id);
  document.getElementById('preview-attach').hidden=!row || row.documents.length>0;
  const doc=row?.documents.find(d=>d.id===selected);
  if(doc){
   const link=document.getElementById('download');
   link.href='data:application/pdf;base64,'+packets[row.packet].originals[doc.id];
   link.download=doc.filename;
  }
 });
 document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('attach-sample').onclick=async()=>{
   const row=cases.find(c=>c.id===active?.id);
   if(!row || row.documents.length) return;
   row.packet='SYN-C003';
   row.documents=packets[row.packet].documents.map(doc=>({...doc,pages:null}));
   record(row,'sample_documents_attached');
   await openCase(row.id);
   message('Sample packet attached. Select Review PDF fields.');
  };
  document.querySelector('.brand').onclick=event=>{event.preventDefault();document.getElementById('home').click();};
  document.getElementById('preview-reset').onclick=()=>location.reload();
  if(location.hash==='#review') openCase('syn-c003');
 });
})();
