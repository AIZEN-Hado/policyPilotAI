'use strict';
document.getElementById('login-form').onsubmit=async event=>{
 event.preventDefault();
 const button=document.getElementById('sign-in'),error=document.getElementById('login-error');
 button.disabled=true;error.hidden=true;
 try{
  const response=await fetch('/api/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value})});
  document.getElementById('password').value='';
  if(!response.ok){let data;try{data=await response.json();}catch{throw Error('Sign in unavailable. Try again later.');}throw Error(data.detail||'Sign in unavailable.');}
  location.replace('/');
 }catch(e){error.textContent=e.message;error.hidden=false;}
 finally{button.disabled=false;}
};
