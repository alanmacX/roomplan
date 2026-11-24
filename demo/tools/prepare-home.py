"""Build one WebGL scene from Apple’s room USDZ files, preserving their shared scan coordinates."""
import json, math, subprocess, sys, tempfile, zipfile
from pathlib import Path
root=Path(__file__).resolve().parent.parent
z=zipfile.ZipFile(sys.argv[1])
prefix='RoomPlanMultiscanMerging/MyHome/'
ids={'Livingroom':'living','Hallway1':'hall','Hallway2':'entry','Bedroom1':'bed','Bedroom2':'bed2','Bedroom3':'bed3',
     'Bedroom4':'bed4','Bathroom1':'bath','Bathroom2':'bath2','Diningroom':'dining','Kitchen':'kitchen'}
raw={k:json.loads(z.read(prefix+k+'/capturedRoom.json')) for k in ids}
floor=raw['Livingroom']['floors'][0]
ax=math.atan2(floor['transform'][2],floor['transform'][0]);c,s=math.cos(ax),math.sin(ax)
def flat(x,z):return x*c+z*s,-x*s+z*c
def uncenter(obj,p=(0,0,0)):
    x,y,z=p;m=obj['transform'];return flat(m[12]+m[0]*x+m[4]*y+m[8]*z,m[14]+m[2]*x+m[6]*y+m[10]*z)
def geometry(path):
    return json.loads(path.read_text().removeprefix('window.ROOMPLAN_MESHES = ').strip().removesuffix(';'))
source=geometry(root/'assets/apple-roomplan/geometry.js')
ground_points=[flat(x,z) for m in source if not m['furniture'] for x,_,z in zip(*[iter(m['positions'])]*3)]
origin=[(min(p[i] for p in ground_points)+max(p[i] for p in ground_points))/2 for i in range(2)]
def local(p):return [p[i]-origin[i] for i in range(2)]
def distance(a,b):return math.dist(a,b)
def poly(a):
    f=a['floors'][0];return [local(uncenter(f,v)) for v in f['polygonCorners']]
def nearest(p,q):
    def close(a,b):
        v=[b[i]-a[i] for i in range(2)]; ll=sum(x*x for x in v) or 1
        t=max(0,min(1,sum((p[i]-a[i])*v[i] for i in range(2))/ll))
        return [a[i]+t*v[i] for i in range(2)]
    return min((close(a,b) for a,b in zip(q,q[1:]+q[:1])),key=lambda q:distance(p,q))
polys={k:poly(a) for k,a in raw.items()}
def unit(v):
    l=math.hypot(*v)
    if l<1e-6:raise ValueError('Portal has no wall direction')
    return [a/l for a in v]
def room_center(a,k):
    if a.get('sections'):
        p=a['sections'][0]['center'];return local(flat(p[0],p[2]))
    return [sum(x[i] for x in polys[k])/len(polys[k]) for i in range(2)]
# Chosen from neighboring captured openings in Apple's sample; the hallway and kitchen joins
# use shared wall-free boundary sections rather than inventing doors.
matches=[
 ('Livingroom','Diningroom','openings',2),('Livingroom','Hallway1','openings',0),
 ('Hallway1','Bedroom1','doors',2),('Hallway1','Bedroom2','doors',0),
 ('Hallway1','Hallway2',None,None),('Hallway2','Bathroom1','doors',3),
 ('Hallway2','Bedroom3','doors',5),('Hallway2','Bedroom4','doors',4),
 ('Bedroom4','Bathroom2','openings',0),('Diningroom','Kitchen',None,None)
]
def inside(point,outline):
    x,z=point
    return sum((az>z)!=(bz>z) and x<(bx-ax)*(z-az)/(bz-az)+ax
               for (ax,az),(bx,bz) in zip(outline,outline[1:]+outline[:1]))%2==1

portals=[]
for a,b,kind,index in matches:
    if kind:
        d=raw[a][kind][index]
        p=local(uncenter(d))
        p=nearest(p,polys[a]); unit_axis=unit([u-v for u,v in zip(uncenter(d,(1,0,0)),uncenter(d))])
        width=min(1.75,max(.60,d['dimensions'][0]*.94))
    elif a=='Hallway1':
        p=nearest([-3.70,-3.12],polys[a]);unit_axis=[1,0];width=.91
    else:
        p=nearest([8.61,-2.28],polys[a]);unit_axis=[1,0];width=1.60
    q=p[:] if a=='Hallway1' and b=='Hallway2' and inside(p,polys[b]) else nearest(p,polys[b])
    gap=distance(p,q)
    if gap>(.30 if kind is None else .22):raise ValueError(f'Unverified gap: {a} -> {b}: {gap:.2f}')
    normal=[-unit_axis[1],unit_axis[0]]
    for sign in (1,-1):
        approach=[p[i]-.31*sign*normal[i] for i in range(2)]
        exit=[q[i]+.31*sign*normal[i] for i in range(2)]
        if inside(approach,polys[a]) and inside(exit,polys[b]):break
    else:raise ValueError(f'Passage does not connect interiors: {a} -> {b}')
    portals.append(dict(a=ids[a],b=ids[b],p=p,q=q,t=unit_axis,w=width,gap=gap,approach=approach,exit=exit))
def element_group(name):
    n=name.rstrip('0123456789').lower()
    return 'floor' if n=='floor' else 'door' if n=='door' else 'wall' if n=='wall' else n

# Split solid triangles against the measured doorway volumes, attaching a short floor
# threshold separately in the browser. The rest of every original mesh is unchanged.
def partition(poly,dist):
    values=[dist(p) for p in poly]
    if min(values)>=-1e-7:return poly,[]
    if max(values)<=1e-7:return [],poly
    inside=[];outside=[]
    for a,b,da,db in zip(poly,poly[1:]+poly[:1],values,values[1:]+values[:1]):
        if da>=-1e-7:inside.append(a)
        if da<=1e-7:outside.append(a)
        if da*db < -1e-14:
            t=da/(da-db);p=[a[i]+(b[i]-a[i])*t for i in range(3)]
            inside.append(p);outside.append(p)
    return inside,outside

def carve(tri,portal):
    p,q,t,w=[portal[k] for k in ('p','q','t','w')]
    center=[(p[i]+q[i])/2 for i in range(2)]
    depth=portal['gap']/2+.19
    normal=[-t[1],t[0]]
    def inward(a,offset,sign):
        return lambda v:offset-sign*((v[0]-center[0])*a[0]+(v[2]-center[1])*a[1])
    planes=[inward(t,w/2,1),inward(t,w/2,-1),inward(normal,depth,1),inward(normal,depth,-1)]
    rest=tri; result=[]
    for plane in planes:
        take, leave=partition(rest,plane)
        if len(leave)>=3:result.append(leave)
        if len(take)<3:return result
        rest=take
    return result

rooms=[]
with tempfile.TemporaryDirectory() as d:
    tmp=Path(d);program=tmp/'mesh-export'
    subprocess.run(['swiftc',str(root/'tools/export-room.swift'),'-o',str(program)],check=True)
    for key, rid in ids.items():
        scan=raw[key];base_y=scan['floors'][0]['transform'][13]
        file=tmp/'room.usdz';out=tmp/'geometry.js'
        file.write_bytes(z.read(prefix+key+'/floorplan.usdz'))
        subprocess.run([str(program),str(file),str(out)],check=True,stdout=subprocess.DEVNULL)
        converted=[]
        # The second hall overlaps the first hall at the bedroom threshold and
        # contains an extra capture of the same door, so trim that mesh too.
        cutters=[p for p in portals if rid in (p['a'],p['b']) or
                 (rid=='entry' and (p['a'],p['b'])==('hall','bed2'))]
        for m in geometry(out):
            points=[]
            for x,y,zv in zip(*[iter(m['positions'])]*3):
                a,b=local(flat(x,zv));points.append([a,y-base_y,b])
            group=element_group(m['name'])
            if group in ('wall','door') and cutters:
                chunks=[]
                for a,b,c_ in zip(*[iter(m['indices'])]*3):
                    tris=[[points[a],points[b],points[c_]]]
                    for portal in cutters:tris=[fragment for t in tris for fragment in carve(t,portal)]
                    for fragment in tris:
                        for i in range(1,len(fragment)-1):chunks+=fragment[:1]+fragment[i:i+2]
                points=chunks;indices=list(range(len(points)))
                if not indices:continue
            else:indices=m['indices']
            converted.append(dict(name=m['name'],kind=group,furniture=m['furniture'],color=m['color'],
                                  p=[round(v,5) for point in points for v in point],i=indices))
        rooms.append(dict(id=rid,outline=polys[key],center=room_center(scan,key),meshes=converted))
out={'rooms':rooms,'portals':portals}
(root/'assets/apple-roomplan/home-mesh.js').write_text('window.SCAN_HOME = '+json.dumps(out,ensure_ascii=False,separators=(',',':'))+';\n')
print('Rooms:',len(rooms),'Portals:',len(portals),'Meshes:',sum(len(r['meshes']) for r in rooms))
print('Opening joins (m):',[(p['a'],p['b'],round(p['gap'],3)) for p in portals])
