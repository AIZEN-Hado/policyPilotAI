'use strict';
(()=>{
 const byId=id=>document.getElementById(id);
 let messageSignature=null,caseVersion=null;
 let connection={configured:false,state:'disconnected',processing_enabled:false},caseId=null,operator=false,timer=null;
 async function request(path,options={}){
  const r=await fetch('/api'+path,{credentials:'same-origin',...options});
  if(r.status===401){location.replace('/login');throw Error('Please sign in.');}
  const body=await r.json();if(!r.ok)throw Error(typeof body.detail==='string'?body.detail:'Service unavailable.');return body;
 }
 function update(){
  const states={disconnected:'Not connected',unavailable:'Connection unavailable',registered:'Model registered · generation unverified',model_missing:'Configured model not found'};
  byId('model-status').textContent=states[connection.state]||'Connection unavailable';
  byId('model-name').textContent=connection.model||'Model connection';
  byId('model-note').textContent=connection.detail||'Your documents remain available.';
  window.PolicyOrb?.set(connection.state==='registered'?'idle':'off');
  document.dispatchEvent(new CustomEvent('policy:connection',{detail:connection}));
 }
 async function refreshConnection(){
  try{connection=await request('/inference');}
  catch(e){connection={configured:false,state:'unavailable',processing_enabled:false,detail:e.message};}
  update();clearTimeout(timer);timer=setTimeout(refreshConnection,20000);
 }
 async function refreshCleanup(){if(!operator)return;try{const counts=await request('/storage/cleanup');byId('cleanup-status').textContent=counts.pending+' cleanup tasks pending · '+counts.eligible+' eligible now';}catch(e){byId('cleanup-status').textContent=e.message;}}
 byId('about').addEventListener('click',refreshCleanup);
 byId('cleanup-retry').onclick=async()=>{const button=byId('cleanup-retry');button.disabled=true;try{await request('/storage/cleanup',{method:'POST'});await refreshCleanup();}catch(e){byId('cleanup-status').textContent=e.message;}finally{button.disabled=false;}};
 function node(tag,text,cls){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
 async function conversation(){
  if(!caseId)return;const requested=caseId;
  try{
   const rows=await request('/cases/'+requested+'/messages');if(caseId!==requested)return;
   byId('chat-hint').textContent='';
   const signature=JSON.stringify(rows);
   if(messageSignature===signature)return;
   messageSignature=signature;
   const thread=byId('chat-thread');thread.replaceChildren();
   for(const row of rows){
    const q=node('article','','chat-message user');q.append(node('div','YOU','message-author'),node('p',row.question));thread.append(q);
    const answer=node('article','','chat-message assistant');answer.append(node('div','POLICYPILOT','message-author'));
    if(row.response){
     if(row.stale)answer.append(node('p','Documents changed. Recheck these earlier sources.','ocr-tag'));
     answer.append(node('p',row.response.summary));
     for(const finding of row.response.findings || []){answer.append(node('p',finding.statement));const citation=node('button',finding.filename+' · page '+finding.page+' — “'+finding.quote+'”','textbutton chat-citation');citation.type='button';citation.onclick=()=>document.dispatchEvent(new CustomEvent('policy:evidence',{detail:{documentId:finding.document_id,page:finding.page}}));answer.append(citation);}
     for(const question of row.response.questions || [])answer.append(node('p',question,'small'));
    }else if(row.state==='pending'){answer.append(node('p','This earlier request did not complete.','small'));}
    else answer.append(node('p',row.state==='stale'?'The documents changed before this answer completed.':'This question did not complete. Check model status before retrying.','small'));
    thread.append(answer);
   }
   window.PolicyOrb?.refresh();
  }catch(e){if(caseId===requested)byId('chat-hint').textContent=e.message;}
 }
 document.addEventListener('policy:case',e=>{
  const next=e.detail?.id || null,version=e.detail?.updatedAt || null;
  if(caseId===next && caseVersion===version) return;
  if(caseId!==next){
   byId('chat-thread').replaceChildren();byId('chat-hint').textContent='';messageSignature=null;
  }
  caseId=next;caseVersion=version;conversation();
 });
 document.addEventListener('visibilitychange',()=>{if(!document.hidden){refreshConnection();conversation();}});
 request('/auth/me').then(user=>{operator=Boolean(user.model_operator);byId('cleanup-tools').hidden=!operator;}).catch(()=>{});
 refreshConnection();
})();
