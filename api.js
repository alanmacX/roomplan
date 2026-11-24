'use strict';
window.homeAPI=(()=>{
  let dialog=null;
  const request=async(path,method='GET',data)=>{
    const r=await fetch('/api'+path,{method,cache:'no-store',...(data?{headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})});
    const payload=await r.json();
    if(!r.ok){const e=new Error(payload.error||'请求没有完成。');e.status=r.status;throw e;}
    return payload;
  };
  function signIn(){
    if(dialog)return dialog;
    dialog=new Promise(resolve=>{
      const d=document.createElement('dialog');
      d.className='demo-login';
      d.innerHTML='<form><h2>打开智能家居</h2><p>本机演示默认口令：<code>2468</code></p><label>演示口令 <input name="pin" type="password" inputmode="numeric" required autocomplete="current-password"></label><p class="login-error" role="status"></p><button type="submit">进入</button></form>';
      document.body.append(d);
      d.addEventListener('cancel',e=>e.preventDefault());
      const form=d.querySelector('form');
      form.onsubmit=async e=>{
        e.preventDefault();const btn=form.querySelector('button');btn.disabled=true;
        try{await request('/login','POST',{pin:form.elements.pin.value});d.close();d.remove();dialog=null;resolve(true);}
        catch(err){d.querySelector('.login-error').textContent=err.message;btn.disabled=false;form.elements.pin.select();}
      };
      d.showModal();
    });
    return dialog;
  }
  const ready=location.protocol==='file:' ? Promise.resolve(false):(async()=>{
    let status;
    try{status=await request('/status')}catch{return false;}
    if(status.service!=='smart-home-demo')return false;
    return status.signedIn ? true : signIn();
  })();
  async function api(path,method,data){
    try{return await request(path,method,data)}
    catch(err){if(err.status!==401)throw err;await signIn();return request(path,method,data);}
  }
  const resource=(key,suffix='')=>'/plans/'+key+suffix;
  return {
    ready, types:()=>api('/types'), get:key=>api(resource(key)),
    save:(key,plan,rev,replace=false)=>api(resource(key),'PUT',{plan,rev,replace}),
    scene:(key,mode)=>api(resource(key,'/scene'),'POST',{mode}),
    environment:(key,data)=>api(resource(key,'/environment'),'POST',data),
    command:(key,id,capability,value,outcome='ok')=>api(resource(key,'/devices/'+encodeURIComponent(id)+'/command'),'POST',{capability,value,outcome}),
    history:(key,id)=>api(resource(key,'/devices/'+encodeURIComponent(id)+'/history')),
    mount:(u,v)=>api(resource('apple','/mount'),'POST',{u,v}),
    remove:(key,id)=>api(resource(key,'/devices/'+encodeURIComponent(id)),'DELETE')
  };
})();
