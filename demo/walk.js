'use strict';
window.createRoomWalker=(T,source,home)=>{
  const cell=.085;
  const clearance=.205;
  const outlines=source.rooms.map(r=>r.outline);
  const xs=outlines.flat().map(p=>p[0]), zs=outlines.flat().map(p=>p[1]);
  const minX=Math.min(...xs)-.6, minZ=Math.min(...zs)-.6;
  const w=Math.ceil((Math.max(...xs)-minX+.6)/cell);
  const h=Math.ceil((Math.max(...zs)-minZ+.6)/cell);
  const pos=i=>[minX+(i%w+.5)*cell,minZ+(Math.floor(i/w)+.5)*cell];
  const index=(x,z)=>{
    const a=Math.floor((x-minX)/cell),b=Math.floor((z-minZ)/cell);
    return (a>=0&&a<w&&b>=0&&b<h)?b*w+a:-1;
  };
  const roomAt=new Uint8Array(w*h);
  const solid=new Uint8Array(w*h);
  const inside=(x,z,p)=>{
    let hit=false;
    for(let i=0,j=p.length-1;i<p.length;j=i++){
      const [a,b]=p[i],[c,d]=p[j];
      if((b>z)!==(d>z)&&x<(c-a)*(z-b)/(d-b)+a)hit=!hit;
    }
    return hit;
  };
  const distanceToEdge=(x,z,a,b)=>{
    const u=b[0]-a[0],v=b[1]-a[1],m=u*u+v*v;
    const t=m?Math.max(0,Math.min(1,((x-a[0])*u+(z-a[1])*v)/m)):0;
    return (x-a[0]-u*t)**2+(z-a[1]-v*t)**2;
  };
  function raster(poly,margin,paint){
    if(poly.length<3)return;
    const u=poly.map(p=>p[0]), v=poly.map(p=>p[1]);
    const x0=Math.max(0,Math.floor((Math.min(...u)-minX-margin)/cell));
    const z0=Math.max(0,Math.floor((Math.min(...v)-minZ-margin)/cell));
    const x1=Math.min(w-1,Math.floor((Math.max(...u)-minX+margin)/cell));
    const z1=Math.min(h-1,Math.floor((Math.max(...v)-minZ+margin)/cell));
    for(let z=z0;z<=z1;z++)for(let x=x0;x<=x1;x++){
      const i=z*w+x,[a,b]=pos(i);
      if(inside(a,b,poly)||margin&&poly.some((p,k)=>distanceToEdge(a,b,p,poly[(k+1)%poly.length])<=margin**2))paint(i);
    }
  }
  for(let i=0;i<outlines.length;i++)raster(outlines[i],0,k=>{roomAt[k]=i+1;});
  const surface=roomAt.slice();
  for(const door of source.portals){
    const {approach:a,exit:b,t,w:width}=door,r=width*.49;
    raster([a,b,b,a].map(([x,z],i)=>[x+t[0]*r*(i<2?-1:1),z+t[1]*r*(i<2?-1:1)]),0,k=>{surface[k]=1;});
  }
  // Project real obstacle triangles within the person's height, including thin doors and walls.
  const clip=(poly,bound,sign)=>{
    const out=[];
    for(let i=0;i<poly.length;i++){
      const a=poly[i],b=poly[(i+1)%poly.length],x=(a[1]-bound)*sign,y=(b[1]-bound)*sign;
      if(x>=0)out.push(a);
      if((x>=0)!==(y>=0)){
        const t=x/(x-y);out.push(a.map((v,j)=>v+(b[j]-v)*t));
      }
    }
    return out;
  };
  for(const room of source.rooms)for(const part of room.meshes){
    if(part.kind==='floor')continue;
    for(let i=0;i<part.i.length;i+=3){
      const tri=part.i.slice(i,i+3).map(v=>part.p.slice(v*3,v*3+3));
      const p=clip(clip(tri,.018,1),1.69,-1).map(v=>[v[0],v[2]]);
      raster(p,clearance,k=>{solid[k]=1;});
    }
  }
  const pass=i=>i>=0&&i<surface.length&&surface[i]&&!solid[i];
  const steps=[[-1,0],[1,0],[0,-1],[0,1],[-1,-1],[-1,1],[1,-1],[1,1]];
  function neighbors(i,visit){
    const x=i%w,z=Math.floor(i/w);
    for(const [a,b] of steps){
      if(x+a<0||x+a>=w||z+b<0||z+b>=h)continue;
      const next=i+a+b*w;
      if(pass(next)&&(!(a&&b)||pass(i+a)&&pass(i+b*w)))visit(next,a&&b?Math.SQRT2:1);
    }
  }
  function nearest(x,z,allowed){
    let best=-1,cost=Infinity;
    for(let i=0;i<surface.length;i++){
      if(!pass(i))continue;
      const [a,b]=pos(i),d=(x-a)**2+(z-b)**2;
      if(d<cost&&allowed(i)){best=i;cost=d;}
    }
    return best;
  }
  const spawn=nearest(-3.62,3.58,i=>source.rooms[roomAt[i]-1]?.id==='entry');
  if(spawn<0)throw new Error('The entry has no walkable floor');
  const reachable=new Uint8Array(w*h), queue=[spawn];
  reachable[spawn]=1;
  for(let k=0;k<queue.length;k++)neighbors(queue[k],next=>{
    if(!reachable[next]){reachable[next]=1;queue.push(next);}
  });
  const straight=(a,b)=>{
    const distance=Math.hypot(a[0]-b[0],a[1]-b[1]),n=Math.max(1,Math.ceil(distance/(cell*.24)));
    let prev=index(...a);
    for(let s=0;s<=n;s++){
      const f=s/n,i=index(a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f);
      if(!pass(i))return false;
      const dx=i%w-prev%w;
      if(dx&&Math.floor(i/w)!==Math.floor(prev/w)&&(!pass(prev+dx)||!pass(i-dx)))return false;
      prev=i;
    }
    return true;
  };
  function path(start,goal){
    const startIndex=index(...start);
    const from=reachable[startIndex]?startIndex:nearest(start[0],start[1],i=>reachable[i]&&straight(start,pos(i)));
    if(from<0||goal<0)return null;
    const stack=[from], prev=new Int32Array(w*h).fill(-1);prev[from]=from;
    for(let k=0;k<stack.length&&prev[goal]<0;k++)neighbors(stack[k],next=>{
      if(prev[next]===-1){prev[next]=stack[k];stack.push(next);}
    });
    if(prev[goal]<0)return null;
    const raw=[];
    for(let i=goal;i!==from;i=prev[i])raw.push(pos(i));
    raw.push(pos(from),start);raw.reverse();
    const points=[start];
    for(let a=0;a<raw.length-1;){
      let b=raw.length-1;
      while(b>a+1&&!straight(raw[a],raw[b]))b--;
      points.push(raw[b]);a=b;
    }
    // Round only corners whose curve samples remain clear of walls and furniture.
    const soft=[points[0]];
    for(let i=1;i<points.length-1;i++){
      const [a,p,b]=points.slice(i-1,i+2);
      const trim=q=>{const f=Math.min(.25,.22/(Math.hypot(q[0]-p[0],q[1]-p[1])||1));return p.map((x,j)=>x+(q[j]-x)*f);};
      const u=trim(a),v=trim(b);
      const curve=[u,...[.2,.4,.6,.8].map(t=>p.map((x,j)=>(1-t)**2*u[j]+2*t*(1-t)*x+t*t*v[j])),v];
      soft.push(...(curve.slice(1).every((q,j)=>straight(curve[j],q))?curve:[p]));
    }
    soft.push(points.at(-1));
    return soft.map(([x,z])=>new T.Vector3(x,0,z));
  }
  const avatar=new T.Group();avatar.name='resident';avatar.visible=false;home.add(avatar);
  const color=c=>new T.MeshStandardMaterial({color:c,roughness:.86});
  const coat=color('#244f63'), skin=color('#c48b64'), trousers=color('#39424b'), shoes=color('#20252b'),hair=color('#443228');
  const sphere=new T.SphereGeometry(1,12,8);
  const mesh=(parent,x,y,z,a,b,c,material)=>{
    const node=new T.Mesh(sphere,material);node.position.set(x,y,z);node.scale.set(a,b,c);parent.add(node);return node;
  };
  const body=new T.Group();avatar.add(body);
  mesh(body,0,1.12,0,.143,.255,.105,coat);
  mesh(body,0,1.369,0,.048,.073,.052,skin);
  mesh(body,0,1.485,.01,.092,.122,.091,skin);
  mesh(body,0,1.553,-.013,.095,.076,.091,hair);
  const limb=(x,y,length,r,material,foot,arm)=>{
    const g=new T.Group();g.position.set(x,y,0);body.add(g);
    mesh(g,0,-length*.48,0,r,length*.53,r,material);
    mesh(g,0,-length,arm?0:.038,arm?.032:.05,arm?.056:.045,arm?.035:.09,foot);
    return g;
  };
  const legs=[limb(-.067,.83,.76,.056,trousers,shoes,false),limb(.067,.83,.76,.056,trousers,shoes,false)];
  const arms=[limb(-.163,1.26,.48,.037,coat,skin,true),limb(.163,1.26,.48,.037,coat,skin,true)];
  const shadow=new T.Mesh(new T.CircleGeometry(.23,24),new T.MeshBasicMaterial({color:'#344943',transparent:true,opacity:.22,depthWrite:false}));
  shadow.rotation.x=-Math.PI/2;shadow.position.y=.021;avatar.add(shadow);
  const ring=new T.Mesh(new T.RingGeometry(.20,.23,24),new T.MeshBasicMaterial({color:'#f1f4e8',transparent:true,opacity:.74,depthWrite:false}));
  ring.rotation.x=-Math.PI/2;ring.position.y=.023;avatar.add(ring);
  const room=(p,old)=>{
    const match=source.rooms.find(r=>r.id===old);
    if(match&&inside(p.x,p.z,match.outline))return old;
    return source.rooms[roomAt[index(p.x,p.z)]-1]?.id||old;
  };
  return {avatar,spawn:new T.Vector3(pos(spawn)[0],0,pos(spawn)[1]),room,
    roomPath(start,id){
      const r=source.rooms.find(r=>r.id===id);
      if(!r)return null;
      return path([start.x,start.z],nearest(...r.center,i=>reachable[i]&&source.rooms[roomAt[i]-1]?.id===id));
    },
    pointPath(start,hit){
      if(!surface[index(hit.x,hit.z)])return null;
      const goal=nearest(hit.x,hit.z,i=>reachable[i]);
      if(goal<0||Math.hypot(hit.x-pos(goal)[0],hit.z-pos(goal)[1])>.58)return null;
      return path([start.x,start.z],goal);
    },
    stride(distance,amount){
      const stride=Math.sin(distance*10.4)*amount;
      body.position.y=Math.abs(stride)*.021;
      legs.forEach((g,i)=>{g.rotation.x=stride*(i?-.49:.49);});
      arms.forEach((g,i)=>{g.rotation.x=stride*(i?.41:-.41);});
    }
  };
};
