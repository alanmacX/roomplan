"""Derive 2D plans from the Apple RoomPlan sample’s actual USDZ meshes and CapturedRoom exports."""
import json, math, subprocess, sys, tempfile, zipfile
from pathlib import Path

root=Path(__file__).resolve().parent.parent
archive=zipfile.ZipFile(sys.argv[1])
keys={'Livingroom':('living','客厅'),'Hallway1':('hall','走廊'), 'Hallway2':('entry','过厅'),
      'Bedroom1':('bed','主卧'),'Bedroom2':('bed2','次卧'),'Bedroom3':('bed3','卧室三'),
      'Bedroom4':('bed4','卧室四'),'Bathroom1':('bath','卫生间一'),'Bathroom2':('bath2','卫生间二'),
      'Diningroom':('dining','餐厅'),'Kitchen':('kitchen','厨房')}
prefix='RoomPlanMultiscanMerging/MyHome/'
scans={name:json.loads(archive.read(prefix+name+'/capturedRoom.json')) for name in keys}
floor=scans['Livingroom']['floors'][0]
heading=math.atan2(floor['transform'][2],floor['transform'][0])
c,s=math.cos(heading),math.sin(heading)

def flat(x,z):return ((x*c+z*s)*100,(-x*s+z*c)*100)
def world(o,v=(0,0,0)):
    x,y,z=v; m=o['transform']
    return flat(m[12]+x*m[0]+y*m[4]+z*m[8],m[14]+x*m[2]+y*m[6]+z*m[10])
def cut(a,b):return {'a':a,'b':b}
def lerp(a,b,t):return [a[i]+(b[i]-a[i])*t for i in range(2)]
def hull(points):
    p=sorted(set(tuple(round(k,4) for k in q) for q in points))
    def turn(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def half(v):
        out=[]
        for x in v:
            while len(out)>1 and turn(out[-2],out[-1],x)<=0:out.pop()
            out.append(x)
        return out
    return half(p)[:-1]+half(reversed(p))[:-1]
def floor_poly(a):
    f=a['floors'][0]
    return [world(f,v) for v in f['polygonCorners']]
def min_p(poly):return [min(v[i] for v in poly) for i in range(2)]
def local(p,base):return [round(v-b,4) for v,b in zip(p,base)]
def spans(src,origin):
    ans=[]
    for v in src:
        w=v['dimensions'][0]/2
        ans.append({**cut(local(world(v,(-w,0,0)),origin),local(world(v,(w,0,0)),origin)),
                    'parent':v.get('parentIdentifier'),'id':v.get('identifier')})
    return ans
def walls_for(scan,origin,doors):
    result=[]
    for wall in spans(scan['walls'],origin):
        a,b=wall['a'],wall['b']; dx,dy=b[0]-a[0],b[1]-a[1];ll=dx*dx+dy*dy
        if ll<1:continue
        def frac(p):return ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/ll
        parts=[]
        for d in doors:
            if d['parent']!=wall['id']:continue
            q=sorted([max(0,min(1,frac(d['a']))),max(0,min(1,frac(d['b'])))])
            parts.append(q)
        last=0
        for lo,hi in sorted(parts):
            if lo-last>.001:result.append(cut(lerp(a,b,last),lerp(a,b,lo)))
            last=max(last,hi)
        if 1-last>.001:result.append(cut(lerp(a,b,last),b))
    return result
def mesh_json(path):
    return json.loads(path.read_text().removeprefix('window.ROOMPLAN_MESHES = ').rstrip().removesuffix(';'))
def source_objects(meshes,origin):
    return [(m['name'],hull(local(flat(x,z),origin) for x,_,z in zip(*[iter(m['positions'])]*3)))
            for m in meshes if m['furniture']]
labels={'fireplace':'壁炉','oven':'烤箱','sofa':'沙发','storage':'储物柜','table':'桌几','television':'电视','chair':'椅子','bed':'床','sink':'水槽','toilet':'马桶','bathtub':'浴缸','refrigerator':'冰箱','stove':'灶台','dishwasher':'洗碗机','washerDryer':'洗衣机'}
mesh_alias={'washerDryer':'washerdryer','television':'television'}
def category(n):return n.rstrip('0123456789').lower()
def attach_shape(o,kind,mesh_candidates):
    match=[(key,ps) for key,ps in mesh_candidates if category(key)==mesh_alias.get(kind,kind.lower()) and len(ps)>=3]
    if not match:return None
    k,points=min(match,key=lambda m:math.hypot(sum(x for x,_ in m[1])/len(m[1])-o['x'],sum(y for _,y in m[1])/len(m[1])-o['y']))
    if math.hypot(sum(x for x,_ in points)/len(points)-o['x'],sum(y for _,y in points)/len(points)-o['y'])>max(30,o['w']*.65):
        return None
    mesh_candidates.remove((k,points))
    a=math.radians(o['angle']);co,si=math.cos(a),math.sin(a)
    return {'kind':kind,'p':[[round((x-o['x'])*co+(y-o['y'])*si,3),round(-(x-o['x'])*si+(y-o['y'])*co,3)] for x,y in points]}
seed=json.loads((root/'data/seed.json').read_text())
apple=seed['apple']; base_ap=min_p(floor_poly(scans['Livingroom']))
apple_candidates=source_objects(mesh_json(root/'assets/apple-roomplan/geometry.js'),base_ap)
apple_shapes={}
scan_items=scans['Livingroom']['objects']
for o in apple['items']:
    if not o['id'].startswith('scan-'):continue
    captured=scan_items[int(o['id'].split('-')[-1])]
    kind=next(iter(captured.get('category',{})),'')
    shape=attach_shape(o,kind,apple_candidates)
    if shape:apple_shapes[o['id']]=shape

all_points=[v for a in scans.values() for v in floor_poly(a)]
origin=min_p(all_points)
home={'key':'house','title':'整套扫描户型','outline':[local(x,origin) for x in hull(all_points)],
      'rooms':[],'items':[],'walls':[],'doors':[],'windows':[]}
home_shapes={}
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp); program=tmp/'extract'
    subprocess.run(['swiftc',str(root/'tools/export-room.swift'),'-o',str(program)],check=True)
    for name,(rid,display) in keys.items():
        a=scans[name]; geo=tmp/'geo.js'; model=tmp/'room.usdz'
        model.write_bytes(archive.read(prefix+name+'/floorplan.usdz'))
        subprocess.run([str(program),str(model),str(geo)],check=True,stdout=subprocess.DEVNULL)
        candidates=source_objects(mesh_json(geo),origin)
        poly=[local(x,origin) for x in floor_poly(a)]
        center=[sum(x[i] for x in poly)/len(poly) for i in range(2)]
        if a.get('sections'):
            center=local(flat(a['sections'][0]['center'][0],a['sections'][0]['center'][2]),origin)
        home['rooms'].append(dict(id=rid,name=display,p=poly,tag=center,sleep=rid=='bed'))
        ds=spans([*a.get('doors',[]),*a.get('openings',[])],origin)
        home['doors']+=ds
        home['windows']+=spans(a.get('windows',[]),origin)
        home['walls']+=walls_for(a,origin,ds)
        for i,o in enumerate(a.get('objects',[])):
            w,_,h=o['dimensions']
            if min(w,h)<=.01:continue
            x,y=local(world(o),origin); dx,dy=local(world(o,(1,0,0)),origin)
            kind=next(iter(o.get('category',{})),'')
            item=dict(id=f'{rid}-scan-{i}',type={'bed':'bed','sofa':'sofa','table':'table'}.get(kind,'scanned'),
                      name=labels.get(kind,kind or '扫描家具'),x=x,y=y,w=round(w*100,4),h=round(h*100,4),
                      angle=round(math.degrees(math.atan2(dy-y,dx-x)),4))
            home['items'].append(item)
            shape=attach_shape(item,kind,candidates)
            if shape:home_shapes[item['id']]=shape
        home['items'].append(dict(id=rid+'-lamp',type='lamp',name=display+'灯',x=center[0],y=center[1],w=20,h=20,angle=0,level=60,power=rid in ('bed','living')))
        if rid=='living':
            home['items'].append(dict(id='room-ac',type='ac',name='客厅空调',x=center[0]+95,y=center[1],w=60,h=22,angle=0,power=False,target=25,mode='制冷'))
projection={'apple':apple_shapes,'house':home_shapes}
data=dict(house=home,footprints=projection)
(root/'assets/apple-roomplan/projected.js').write_text('window.ROOMPLAN_PROJECTED = '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n')
print('扫描投影轮廓', {k:len(v) for k,v in projection.items()}, '房间',len(home['rooms']))
