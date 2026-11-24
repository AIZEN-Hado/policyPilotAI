/* Mint ribbons projected and shaded on Canvas2D. No WebGL or network activity. */
'use strict';
(()=>{
 const canvases=new Map(),motion=matchMedia('(prefers-reduced-motion: reduce)');
 const activeStates=new Set(['starting','loading','processing','queued','stopping']);
 let frame=null,last=0,elapsed=0,paused=false;
 const control=document.getElementById('orb-motion');
 function paint(canvas,time,view){
  const ctx=canvas.getContext('2d');if(!ctx)return;
  const {width:w,height:h}=canvas.getBoundingClientRect();if(!w||!h)return;
  const dpr=Math.min(devicePixelRatio||1,1.5);
  if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){
   canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
  }
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const busy=activeStates.has(canvas.dataset.state),ambient=canvas.dataset.ambient==='true';
  const t=time*(busy?.00029:.00010);
  const r=Math.min(w*.34,h*.43);
  const cx=w*.5+view.x*r*.045,cy=h*.49+view.y*r*.035;
  const tilt=-.43+.08*Math.sin(t*.53),ct=Math.cos(tilt),st=Math.sin(tilt);
  // Thin, overlapping cross sections create a folded surface without a 3D renderer.
  // The same geometry is drawn once when the visitor requests reduced motion.
  if(ambient){
   ctx.fillStyle='rgba(192,224,203,.12)';
   for(let y=14;y<h;y+=18){
    for(let x=14;x<w;x+=18)ctx.fillRect(x,y,.85,.85);
   }
  }
  const layers=ambient?64:22,steps=ambient?96:40;
  for(let layer=0;layer<layers;layer++){
   const v=layer/(layers-1)*2-1;
   const section=Math.sqrt(Math.max(0,1-v*v));
   const shine=(1+Math.cos(v*3.7+t*.4))*.5;
   ctx.strokeStyle='rgba('+Math.round(104+shine*100)+','+
    Math.round(189+shine*57)+','+Math.round(149+shine*68)+','+(.48+.45*shine)+')';
   ctx.fillStyle='#152a20';
   ctx.lineWidth=Math.max(.65,r*.007);
   ctx.beginPath();
   for(let i=0;i<=steps;i++){
    const a=i/steps*Math.PI*2, sa=Math.sin(a), ca=Math.cos(a);
    const fold=.82+.13*Math.sin(3*a+v*2+t)+.055*Math.cos(2*a-v*4-t*.6);
    const x=section*ca*fold+.10*Math.sin(v*3+t);
    const z=section*sa*fold;
    const y=v*.81-z*.45+.12*section*Math.sin(2*a+v*2+t*.65);
    const px=cx+(x*ct-y*st)*r*1.12,py=cy+(x*st+y*ct)*r*1.06;
    if(i===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);
   }
   ctx.closePath();ctx.fill();ctx.stroke();
  }
  ctx.globalAlpha=1;
 }
 function visible(c){const b=c.getBoundingClientRect();return b.width&&b.height&&b.bottom>0&&b.top<innerHeight&&b.right>0&&b.left<innerWidth;}
 function loop(time){
  frame=null;if(document.hidden){last=0;return;}
  const delta=last?Math.min(time-last,70):0;
  if(last&&delta<40){frame=requestAnimationFrame(loop);return;}
  last=time;if(!paused&&!motion.matches)elapsed+=delta;
  let animate=false;
  for(const [c,s] of canvases){
   if(!c.isConnected){canvases.delete(c);continue;}
   if(!visible(c))continue;
   const moving=!paused&&!motion.matches&&(c.dataset.ambient==='true'||activeStates.has(c.dataset.state));
   if(s.dirty||moving){paint(c,elapsed,s);s.dirty=false;}
   animate=animate||moving;
  }
  if(animate)frame=requestAnimationFrame(loop);else last=0;
 }
 function wake(){for(const s of canvases.values())s.dirty=true;if(frame===null)frame=requestAnimationFrame(loop);}
 function track(c){
  if(canvases.has(c))return;
  const view={dirty:true,x:0,y:0};canvases.set(c,view);
  if(c.dataset.ambient!=='true')return;
  c.addEventListener('pointermove',e=>{
   if(motion.matches||paused||e.pointerType==='touch')return;
   const b=c.getBoundingClientRect();view.x=(e.clientX-b.left)/b.width*2-1;view.y=(e.clientY-b.top)/b.height*2-1;
  },{passive:true});
  c.addEventListener('pointerleave',()=>{view.x=0;view.y=0;wake();});
 }
 function updateControl(){
  if(!control)return;
  control.hidden=motion.matches;
  control.textContent=paused?'Resume motion':'Pause motion';
  control.setAttribute('aria-pressed',String(paused));
  control.setAttribute('aria-label',paused?'Resume decorative animation':'Pause decorative animation');
 }
 if(control)control.onclick=()=>{paused=!paused;updateControl();wake();};
 window.PolicyOrb={refresh(){document.querySelectorAll('canvas[data-orb]').forEach(track);wake();},set(state){document.querySelectorAll('canvas[data-orb="model"]').forEach(c=>c.dataset.state=state);wake();}};
 new MutationObserver(()=>PolicyOrb.refresh()).observe(document.body,{childList:true,subtree:true});
 document.addEventListener('visibilitychange',()=>{last=0;wake();});
 addEventListener('resize',wake);addEventListener('scroll',wake,{passive:true});
 motion.addEventListener('change',()=>{updateControl();wake();});
 updateControl();PolicyOrb.refresh();
})();
