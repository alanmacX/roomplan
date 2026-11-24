'use strict';
window.createBulbInstaller = (T,{scene,renderer,camera,footprint,ground,ceiling,render,focus,onPlacement}) => {
  const $=id=>document.getElementById(id);
  const source=window.LED_BULB_ASSET;
  if(!source||!footprint?.length)throw new Error('Missing lamp model or floor outline');
  const storage='roomplan-lamps-v1', limit=4, api=window.homeAPI;
  let online=false, syncSeq=0, busy=false;
  const decode=(s,K)=>new K(Uint8Array.from(atob(s),ch=>ch.charCodeAt(0)).buffer);
  const position=new T.BufferAttribute(decode(source.position,Float32Array),3);
  const normal=new T.BufferAttribute(decode(source.normal,Float32Array),3);
  const uv=new T.BufferAttribute(decode(source.uv,Float32Array),2);
  const tris=decode(source.index,Uint16Array), groups=[[],[]];
  for(let i=0;i<tris.length;i+=3){
    const y=(position.getY(tris[i])+position.getY(tris[i+1])+position.getY(tris[i+2]))/3;
    groups[y>.047?1:0].push(tris[i],tris[i+1],tris[i+2]);
  }
  const parts=groups.map(indices=>new T.BufferGeometry()
    .setAttribute('position',position).setAttribute('normal',normal).setAttribute('uv',uv).setIndex(indices));
  const textures=source.textures.map((uri,i)=>{
    const texture=new T.TextureLoader().load(uri,()=>render());
    texture.flipY=false;texture.anisotropy=Math.min(4,renderer.capabilities.getMaxAnisotropy());
    if(i===1)texture.colorSpace=T.SRGBColorSpace;
    return texture;
  });
  // A small studio environment gives the original normal and metal maps something to reflect.
  const studio=new T.Scene();studio.background=new T.Color('#353c46');
  const panel=(w,h,x,y,z,intensity,tint)=>{
    const geometry=new T.PlaneGeometry(w,h);
    const value=new T.Color(tint).multiplyScalar(intensity);
    const material=new T.MeshBasicMaterial({color:value,side:T.DoubleSide,toneMapped:false});
    const mesh=new T.Mesh(geometry,material);mesh.position.set(x,y,z);mesh.lookAt(0,0,0);studio.add(mesh);
  };
  panel(4,2,-3,2,2,3.1,'#f2f3ff');panel(1,4,3,1,-2,4,'#fff1de');panel(2,2,0,-3,-2,1.4,'#eff5ff');
  const pmrem=new T.PMREMGenerator(renderer), reflections=pmrem.fromScene(studio,.06,.1,30);
  pmrem.dispose();studio.traverse(o=>{o.geometry?.dispose();o.material?.dispose()});
  function material(){
    return new T.MeshStandardMaterial({map:textures[1],normalMap:textures[0],roughnessMap:textures[2],metalnessMap:textures[2],
      roughness:1,metalness:1,envMap:reflections.texture,envMapIntensity:.92,side:T.DoubleSide});
  }
  const metal=material();
  const mounted=new T.Group();scene.add(mounted);
  const stage=new T.Plane(new T.Vector3(0,1,0),-ground);
  const ray=new T.Raycaster();
  const pickSpace=new T.Vector2();
  const cursorGroup=new T.Group();scene.add(cursorGroup);
  const ringMaterial=new T.MeshBasicMaterial({color:'#287869',side:T.DoubleSide,transparent:true,opacity:.88,depthTest:false});
  const ring=(inside,outside,mat)=>{
    const obj=new T.Mesh(new T.RingGeometry(inside,outside,38),mat);obj.rotation.x=-Math.PI/2;obj.renderOrder=4;return obj;
  };
  const floorRing=ring(.13,.15,ringMaterial);cursorGroup.add(floorRing);
  const topRing=ring(.09,.105,ringMaterial);topRing.position.y=ceiling-ground;cursorGroup.add(topRing);
  const projection=new T.BufferGeometry().setFromPoints([new T.Vector3(),new T.Vector3(0,ceiling-ground,0)]);
  const riser=new T.Line(projection,new T.LineDashedMaterial({color:'#436c61',dashSize:.065,gapSize:.045,depthTest:false,transparent:true,opacity:.75}));
  riser.renderOrder=4;riser.computeLineDistances();cursorGroup.add(riser);
  cursorGroup.visible=false;
  const finishMarker=ring(.083,.095,new T.MeshBasicMaterial({color:'#417467',side:T.DoubleSide,transparent:true,opacity:.75,depthTest:false}));
  finishMarker.position.y=-.048;
  let items=[], current=null, installing=false, closeup=false, candidate=null;
  let markerScale=.26, markerOpacity=0;
  const keycap=document.createElement('canvas');keycap.width=keycap.height=96;
  const ctx=keycap.getContext('2d');
  ctx.beginPath();ctx.arc(48,48,40,0,Math.PI*2);
  ctx.fillStyle='#fffdf4';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=3;ctx.stroke();
  ctx.beginPath();ctx.arc(48,48,32,0,Math.PI*2);ctx.strokeStyle='#244c43';ctx.lineWidth=6;ctx.stroke();
  const badge=new T.CanvasTexture(keycap);badge.colorSpace=T.SRGBColorSpace;
  const instruction='点客厅内的位置，灯泡会装在正上方。';
  function updateMarkers(metersPerPixel,polar,detail){
    markerOpacity=(1-T.MathUtils.smoothstep(polar,.10,.38))*(1-T.MathUtils.smoothstep(detail,.04,.35));
    markerScale=metersPerPixel*21;
    for(const b of items)styleMarker(b);
    const adjust=T.MathUtils.clamp(metersPerPixel*70,.85,2);
    floorRing.scale.setScalar(adjust);topRing.scale.setScalar(adjust);
  }
  function styleMarker(b){
    b.marker.visible=markerOpacity>.015;
    b.marker.material.opacity=markerOpacity;
    b.marker.material.color.set(b.on?'#ffc660':b.id===current?'#a8d7c5':'#fffdf4');
    b.marker.scale.setScalar(markerScale);
  }
  function inside(u,v){
    let hit=false, clearance=Infinity;
    for(let i=0;i<footprint.length;i++){
      const [x,y]=footprint[i], [a,b]=footprint[(i+1)%footprint.length];
      if((y>v)!==(b>v)&&u<(a-x)*(v-y)/(b-y)+x)hit=!hit;
      const d=(a-x)**2+(b-y)**2;
      const t=d?Math.max(0,Math.min(1,((u-x)*(a-x)+(v-y)*(b-y))/d)):0;
      clearance=Math.min(clearance,Math.hypot(u-x-t*(a-x),v-y-t*(b-y)));
    }
    return hit&&clearance>=.16;
  }
  function placementError(p){
    if(!p||!inside(p.x,p.z))return '请点客厅内、离墙至少 16 厘米的位置。';
    const nearby=items.find(b=>Math.hypot(b.u-p.x,b.v-p.z)<.28);
    if(nearby)return '离'+(nearby.name||'灯泡 '+nearby.n)+'太近，换个位置试试。';
    return '';
  }
  function make(state){
    const node=new T.Group();node.position.set(state.u,ceiling,state.v);mounted.add(node);
    const shape=new T.Group();shape.rotation.z=Math.PI;
    shape.position.y=-.020;node.add(shape);
    const diffuser=material();
    diffuser.onBeforeCompile=shader=>{
      shader.vertexShader=shader.vertexShader
        .replace('#include <common>','#include <common>\nvarying float bulbLocalY;')
        .replace('#include <begin_vertex>','#include <begin_vertex>\nbulbLocalY = position.y;');
      shader.fragmentShader=shader.fragmentShader
        .replace('#include <common>','#include <common>\nvarying float bulbLocalY;')
        .replace('#include <emissivemap_fragment>','#include <emissivemap_fragment>\ntotalEmissiveRadiance *= smoothstep(0.047, 0.061, bulbLocalY);');
    };
    const housing=new T.Mesh(parts[0],metal);
    const globe=new T.Mesh(parts[1],diffuser);
    housing.castShadow=true;globe.castShadow=true;
    shape.add(housing,globe);
    const socket=new T.Mesh(new T.CylinderGeometry(.029,.024,.030,24),new T.MeshStandardMaterial({color:'#b5b2a9',roughness:.56,envMap:reflections.texture,envMapIntensity:.5}));
    socket.position.y=-.014;node.add(socket);
    const light=new T.SpotLight('#ffd19b',0,9,1.17,.52,2);
    light.position.y=-.125;light.target.position.y=-3;
    light.castShadow=true;
    light.shadow.mapSize.set(512,512);light.shadow.camera.near=.16;light.shadow.camera.far=9;
    light.shadow.normalBias=.018;light.shadow.bias=-.0002;
    node.add(light,light.target);
    const hit=new T.Mesh(new T.SphereGeometry(.12,10,8),new T.MeshBasicMaterial({visible:false}));
    hit.position.y=-.064;hit.userData.id=state.id;node.add(hit);
    const marker=new T.Sprite(new T.SpriteMaterial({map:badge,transparent:true,depthTest:false,depthWrite:false,toneMapped:false}));
    marker.position.y=.012;marker.renderOrder=5;marker.userData.id=state.id;node.add(marker);
    const b={...state,node,light,diffuser,hit,socket,marker};
    setLight(b);return b;
  }
  function setLight(b){
    // Keep power and last brightness separate. Turning off does not erase the level.
    const level=b.on?b.level/100:0;
    b.light.intensity=level*210;
    b.diffuser.emissive.set('#ffc684');
    b.diffuser.emissiveIntensity=level*1.3;
    styleMarker(b);
  }
  function save(){
    try{localStorage.setItem(storage,JSON.stringify(items.map(({id,n,u,v,on,level})=>({id,n,u,v,on,level}))));return true}
    catch{return false}
  }
  function restore(){
    try{
      const data=JSON.parse(localStorage.getItem(storage)??'null');
      if(Array.isArray(data))return data.slice(0,limit).filter(b=>b&&typeof b.id==='string'&&Number.isInteger(b.n)&&b.n>0&&Number.isFinite(b.u)&&Number.isFinite(b.v)&&inside(b.u,b.v)&&typeof b.on==='boolean'&&Number.isInteger(b.level)&&b.level>=1&&b.level<=100);
    }catch{}
    return inside(.25,-.06)?[{id:'lamp-1',n:1,u:.25,v:-.06,on:false,level:60}]:[];
  }
  items=restore().map(make);
  current=items[0]?.id??null;
  function selected(){return items.find(b=>b.id===current)}
  function note(text=''){$('bulbNotice').textContent=text}
  function finish(){note(save()?'':'浏览器无法保存这次修改。');refresh();render()}
  function free(b){
    b.node.removeFromParent();b.light.dispose();b.diffuser.dispose();b.hit.geometry.dispose();b.hit.material.dispose();b.socket.geometry.dispose();b.socket.material.dispose();b.marker.material.dispose();
  }
  function sync(next,prefer=null){
    if(next.seq<syncSeq)return;
    syncSeq=next.seq;
    const [ox,oz]=next.mountOrigin;
    const remote=next.plan.items.filter(o=>o.mount==='ceiling').map(o=>({id:o.id,n:o.n,name:o.name,u:(o.x-ox)/100,v:(o.y-oz)/100,on:o.power,level:o.level}));
    const old=new Map(items.map(b=>[b.id,b]));
    items=remote.map(o=>{
      const b=old.get(o.id);
      if(!b)return make(o);
      old.delete(o.id);Object.assign(b,o);b.node.position.set(b.u,ceiling,b.v);setLight(b);return b;
    });
    for(const b of old.values())free(b);
    if(prefer)current=prefer;
    if(!selected()){current=items[0]?.id??null;unfocus();}
    refresh();render();
  }
  async function remoteCall(action){
    if(busy)return;
    busy=true;refresh();
    try{await action();}
    catch(err){note(err.message||'灯泡命令没有完成。')}
    finally{busy=false;refresh();render();}
  }
  function refresh(){
    const b=selected();
    for(const item of items)styleMarker(item);
    if(b&&!closeup)b.node.add(finishMarker);else finishMarker.removeFromParent();
    const list=$('bulbList');list.replaceChildren(...items.map(v=>{
      const btn=document.createElement('button');btn.type='button';btn.dataset.bulb=v.id;
      btn.setAttribute('aria-pressed',String(v.id===current));btn.textContent=v.name||'灯泡 '+v.n;
      return btn;
    }));
    $('bulbControls').hidden=!b;
    $('installBulb').setAttribute('aria-pressed',String(installing));
    const full=items.length>=limit&&!installing;
    $('installBulb').textContent=installing?'取消安装':full?'已装满（4 盏）':'安装灯泡';
    $('installBulb').disabled=busy||items.length>=limit&&!installing;
    $('lamp').disabled=busy;
    $('brightness').disabled=busy;
    $('removeBulb').disabled=busy;
    renderer.domElement.classList.toggle('is-installing',installing);
    if(!b)return;
    $('lamp').textContent=b.on?'关灯':'开灯';
    $('lamp').setAttribute('aria-pressed',String(b.on));
    $('brightness').value=b.level;
    $('brightnessValue').textContent=b.level+'%';
    $('inspectBulb').textContent=closeup?'回到房间':'看细节';
    $('inspectBulb').setAttribute('aria-pressed',String(closeup));
  }
  function clearPreview(){
    if(!cursorGroup.visible)return;
    cursorGroup.visible=false;render();
  }
  function cancel(){
    if(!installing)return;
    installing=false;candidate=null;cursorGroup.visible=false;onPlacement(false);note();refresh();render();
  }
  function enter(){
    if(installing){cancel();return}
    if(busy||items.length>=limit)return;
    unfocus();installing=true;onPlacement(true);
    note(instruction);refresh();
  }
  function updateRay(event){
    const rect=renderer.domElement.getBoundingClientRect();
    pickSpace.set((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2);
    ray.setFromCamera(pickSpace,camera);
  }
  function previewAt(p){
    candidate=p;
    if(!p){clearPreview();return}
    cursorGroup.visible=true;cursorGroup.position.set(p.x,ground+.008,p.z);
    const error=placementError(p);
    ringMaterial.color.set(error?'#b44738':'#287869');
    if(!error&&$('bulbNotice').textContent!==instruction&&!busy)note(instruction);
    render();
  }
  function install(p){
    if(busy)return;
    const error=placementError(p);
    if(error){previewAt(p);note(error);return}
    if(online){
      remoteCall(async()=>{const result=await api.mount(p.x,p.z);cancel();sync(result.snapshot,result.item.id);note('已安装'+result.item.name+'。');});
      return;
    }
    const n=1+items.reduce((v,x)=>Math.max(v,x.n),0);
    const id=globalThis.crypto?.randomUUID?.()??'bulb-'+Date.now();
    const b=make({id,n,u:+p.x.toFixed(3),v:+p.z.toFixed(3),on:false,level:60});
    items.push(b);current=id;cancel();finish();if(!$('bulbNotice').textContent)note('已安装灯泡 '+n+'。');
  }
  function unfocus(){
    if(!closeup)return;
    closeup=false;focus(null);refresh();render();
  }
  $('installBulb').onclick=enter;
  $('bulbList').onclick=e=>{
    const btn=e.target.closest('[data-bulb]');
    if(btn){current=btn.dataset.bulb;if(closeup){const b=selected();focus(new T.Vector3(b.u,ceiling-.053,b.v))}note();refresh();render();$('bulbList').querySelector('[aria-pressed=true]')?.focus();}
  };
  $('lamp').onclick=()=>{
    const b=selected();if(!b)return;
    if(online){remoteCall(async()=>sync((await api.command('apple',b.id,'power',!b.on)).snapshot));return;}
    b.on=!b.on;setLight(b);finish();
  };
  $('brightness').oninput=e=>{
    const b=selected();if(!b)return;
    const value=Number(e.target.value);$('brightnessValue').textContent=value+'%';
    if(!online){b.level=value;setLight(b);render();}
  };
  $('brightness').onchange=e=>{
    const b=selected(), level=Number(e.target.value);
    if(online&&b){remoteCall(async()=>sync((await api.command('apple',b.id,'level',level)).snapshot));return;}
    if(!save())note('浏览器无法保存这次修改。');
  };
  $('inspectBulb').onclick=()=>{
    if(closeup){unfocus();return}
    cancel();const b=selected();if(!b)return;
    closeup=true;focus(new T.Vector3(b.u,ceiling-.053,b.v));refresh();render();
  };
  $('removeBulb').onclick=()=>{
    const b=selected();if(!b)return;
    if(online){remoteCall(async()=>{unfocus();sync(await api.remove('apple',b.id));});return;}
    unfocus();free(b);
    items=items.filter(v=>v!==b);current=items[0]?.id??null;finish();
  };
  refresh();
  api?.ready.then(async enabled=>{
    if(!enabled)return;
    online=true;
    sync(await api.get('apple'));
    setInterval(async()=>{
      if(busy||installing||document.hidden||document.activeElement===$('brightness'))return;
      try{const v=await api.get('apple');if(!busy&&!installing&&v.seq>syncSeq)sync(v);}
      catch(err){note(err.message);}
    },850);
  }).catch(err=>note(err.message));
  return {cancel,unfocus,clearPreview,updateMarkers,
    preview(e){if(!installing)return false;updateRay(e);previewAt(ray.ray.intersectPlane(stage,new T.Vector3()));return true;},
    place(e){if(!installing)return false;updateRay(e);install(ray.ray.intersectPlane(stage,new T.Vector3()));return true;},
    pick(e){
      if(closeup||installing)return;
      updateRay(e);const hit=ray.intersectObjects(items.flatMap(b=>b.marker.visible?[b.marker,b.hit]:[b.hit]),false)[0];if(!hit)return;
      current=hit.object.userData.id;note();refresh();render();
    },
    key(e){
      if(!installing)return false;
      const moves={ArrowLeft:[-.15,0],ArrowRight:[.15,0],ArrowUp:[0,-.15],ArrowDown:[0,.15]};
      if(e.key==='Enter'){e.preventDefault();install(candidate??new T.Vector3(0,ground,0));return true;}
      const step=moves[e.key];if(!step)return false;
      e.preventDefault();const point=(candidate??new T.Vector3(0,ground,0)).clone();point.x+=step[0];point.z+=step[1];previewAt(point);return true;
    }
  };
};
