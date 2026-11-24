"""Local course demo: floor plans, device simulation and scenes."""
from __future__ import annotations

import argparse
import hmac
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
SEED = json.loads((ROOT / "data/seed.json").read_text())
HOUSE_FILE = ROOT / "assets/apple-roomplan/projected.js"
SEED["house"] = json.loads(HOUSE_FILE.read_text().removeprefix("window.ROOMPLAN_PROJECTED = ").strip().removesuffix(";"))["house"]
PLAN_KEYS = ("apple","house","custom","apartment")
TYPES = SEED["types"]
TYPES["switch"] = dict(name="开关灯", mark="◉", w=36, h=36, color="#f0dfbb", caps={"power": [True, False]})
TYPES["curtain"] = dict(name="电动窗帘", mark="▥", w=95, h=22, color="#a9bcb9", caps={"position": [0, 100]})
ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SEASONS = ("春", "夏", "秋", "冬")
MODES = ("normal", "home", "away", "sleep")

class Problem(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)

def number(v, low, high):
    return type(v) in (int, float) and math.isfinite(v) and low <= v <= high

def point(p):
    return isinstance(p, list) and len(p) == 2 and all(number(x, -10000, 10000) for x in p)

def polygon(p):
    return isinstance(p, list) and 3 <= len(p) <= 100 and all(point(x) for x in p)

def inside(x,y,poly):
    odd=False
    for (a,b),(c,d) in zip(poly,poly[1:]+poly[:1]):
        if ((b>y)!=(d>y)) and x < (c-a)*(y-b)/(d-b)+a:
            odd=not odd
    return odd

def distance_to_edges(x,y,poly):
    distances=[]
    for (a,b),(c,d) in zip(poly,poly[1:]+poly[:1]):
        dx,dy=c-a,d-b
        t=max(0,min(1,((x-a)*dx+(y-b)*dy)/(dx*dx+dy*dy or 1)))
        distances.append(math.hypot(x-a-t*dx,y-b-t*dy))
    return min(distances)

def packed(data):
    return json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":"))

def default_device(obj):
    kind=obj.get("type")
    if kind in ("lamp","switch","ac"):
        obj.setdefault("power",False)
    if kind=="lamp":
        obj.setdefault("level",60)
    if kind=="ac":
        obj.setdefault("target",25)
        obj.setdefault("mode","制冷")
    if kind=="curtain":
        obj.setdefault("position",0)

def valid_value(domain,value):
    if type(domain[0]) is bool:
        return type(value) is bool
    if type(domain[0]) is int:
        return number(value,*domain)
    return type(value) is str and value in domain

class Store:
    def __init__(self, path):
        self.db=sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.lock=threading.RLock()
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY, plan TEXT NOT NULL, device TEXT, ts REAL NOT NULL,
              status TEXT NOT NULL, message TEXT NOT NULL, state TEXT);
            CREATE INDEX IF NOT EXISTS event_lookup ON events(plan,device,id);
        """)
        with self.db:
            for key in PLAN_KEYS:
                plan=SEED[key]
                model=dict(plan=plan,rev=1,seq=1,mode="normal",occupied={},overrides={},due={},
                           climate={"season":"夏","indoor":30,"outdoor":33},delay=5)
                self.db.execute("INSERT OR IGNORE INTO plans VALUES (?,?)",(key,packed(model)))

    def read(self,key):
        row=self.db.execute("SELECT payload FROM plans WHERE id=?",(key,)).fetchone()
        if not row: raise Problem("找不到这个户型。",404)
        return json.loads(row[0])

    def write(self,key,m):
        m["seq"]+=1
        self.db.execute("UPDATE plans SET payload=? WHERE id=?",(packed(m),key))

    def feed(self,key,device=None,limit=35):
        args=(key,device,limit) if device else (key,limit)
        where=" AND device=?" if device else ""
        res=self.db.execute("SELECT id,ts,device,status,message,state FROM events WHERE plan=?"+where+" ORDER BY id DESC LIMIT ?",args)
        return [dict(id=r["id"],time=datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S"),device=r["device"],status=r["status"],
                     message=r["message"],state=json.loads(r["state"]) if r["state"] else None) for r in res]

    def event(self,key,obj,status,message):
        state=None
        if obj and status=="ok":
            fields=TYPES.get(obj["type"],{}).get("caps",{})
            state=packed({k:obj[k] for k in fields if k in obj})
        self.db.execute("INSERT INTO events(plan,device,ts,status,message,state) VALUES (?,?,?,?,?,?)",
                        (key,obj["id"] if obj else None,time.time(),status,message,state))

    def snapshot(self,key):
        m=self.read(key)
        return {**m,"events":self.feed(key,limit=12),"mountOrigin":SEED["mountOrigin"]}

    def replace(self,key,m,body):
        p=body.get("plan")
        if body.get("rev")!=m["rev"]:
            raise Problem("户型已在另一页面修改。请重新加载，再保存你的修改。",409)
        if not isinstance(p,dict) or p.get("key")!=key or not polygon(p.get("outline")):
            raise Problem("户型边界无效。")
        p={k:p.get(k) for k in ("key","title","outline","rooms","walls","doors","windows","items")}
        if not isinstance(p["title"],str) or not p["title"].strip() or len(p["title"])>70:
            raise Problem("请输入有效户型名称。")
        for field in ("walls","doors","windows"):
            if not isinstance(p[field],list) or len(p[field])>250 or any(not isinstance(w,dict) or not point(w.get("a")) or not point(w.get("b")) or w["a"]==w["b"] for w in p[field]):
                raise Problem("线段数据无效。")
        if not isinstance(p["rooms"],list) or len(p["rooms"])>30:
            raise Problem("房间列表无效。")
        ids=set()
        for r in p["rooms"]:
            if (not isinstance(r,dict) or not good_id(r.get("id")) or r["id"] in ids or not good_name(r.get("name"))
                or not polygon(r.get("p")) or not point(r.get("tag"))):
                raise Problem("房间边界或名称无效。")
            ids.add(r["id"])
        if not isinstance(p["items"],list) or len(p["items"])>250:
            raise Problem("物品列表无效。")
        old={v["id"]:v for v in m["plan"]["items"]}
        ids=set()
        result=[]
        for v in p["items"]:
            if (not isinstance(v,dict) or not good_id(v.get("id")) or v["id"] in ids or not good_name(v.get("name"))
                or not isinstance(v.get("type"),str) or v["type"] not in (*TYPES,"scanned")
                or not all(number(v.get(k),lo,hi) for k,lo,hi in (("x",-10000,10000),("y",-10000,10000),("w",1,2000),("h",1,2000),("angle",-3600,3600)))):
                raise Problem("物品位置、尺寸或名称无效。")
            ids.add(v["id"])
            previous=old.get(v["id"])
            if previous and previous.get("mount")=="ceiling":
                if v["type"]!="lamp" or any(v[k]!=previous[k] for k in ("x","y","w","h","angle")):
                    raise Problem("请在三维页管理吸顶灯的位置。")
                result.append({**previous,"name":v["name"]})
                continue
            if v.get("mount") is not None:
                raise Problem("请从安装入口创建吸顶灯。")
            obj={k:v[k] for k in ("id","type","name","x","y","w","h","angle")}
            for k,domain in TYPES.get(v["type"],{}).get("caps",{}).items():
                if previous and previous["type"]==v["type"] and k in previous:
                    obj[k]=previous[k]
                elif k in v and valid_value(domain,v[k]):
                    obj[k]=v[k]
            default_device(obj)
            result.append(obj)
        p["items"]=result
        m["plan"]=p
        if body.get("replace"):
            m.update(mode="normal",occupied={},overrides={},due={})
        m["rev"]+=1
        self.event(key,None,"ok","已保存户型")
        self.write(key,m)

    def mount(self,key,m,data):
        u,v=data.get("u"),data.get("v")
        if key!="apple" or not number(u,-20,20) or not number(v,-20,20):
            raise Problem("请在扫描客厅内安装灯泡。")
        x,y=[100*a+b for a,b in zip((u,v),SEED["mountOrigin"])]
        poly=m["plan"]["outline"]
        if not inside(x,y,poly) or distance_to_edges(x,y,poly)<16:
            raise Problem("安装位置在房间外或离墙太近。")
        mounted=[o for o in m["plan"]["items"] if o.get("mount")=="ceiling"]
        if len(mounted)>=4:raise Problem("样例客厅最多安装四盏吸顶灯。")
        if any(math.hypot(o["x"]-x,o["y"]-y)<28 for o in mounted):
            raise Problem("安装位置离另一盏灯太近。")
        n=1+max((o.get("n",0) for o in mounted),default=0)
        obj=dict(id=secrets.token_hex(8),type="lamp",mount="ceiling",n=n,name=f"灯泡 {n}",x=round(x,4),y=round(y,4),w=16,h=16,angle=0,power=False,level=60)
        m["plan"]["items"].append(obj)
        m["rev"]+=1
        self.event(key,obj,"ok","安装 "+obj["name"])
        schedule(self,key,m)
        self.write(key,m)
        return obj

    def remove(self,key,m,device):
        obj=get_obj(m,device)
        m["plan"]["items"].remove(obj)
        m["rev"]+=1
        self.event(key,obj,"ok","移除 "+obj["name"])
        schedule(self,key,m)
        self.write(key,m)

    def apply(self,key,obj,cap,val,reason):
        obj[cap]=val
        info={"power":("开灯" if val else "关灯") if obj["type"] in ("lamp","switch") else ("开机" if val else "关机"),
              "level":f"亮度 {val}%","position":f"开合 {val}%","target":f"目标温度 {val} °C","mode":str(val)}
        self.event(key,obj,"ok",f"{obj['name']} · {info.get(cap,str(val))}（{reason}）")

    def command(self,key,m,device,body):
        obj=get_obj(m,device)
        cap=body.get("capability")
        val=body.get("value")
        fields=TYPES.get(obj["type"],{}).get("caps",{})
        if not isinstance(cap,str) or cap not in fields or not valid_value(fields[cap],val):
            raise Problem("设备不支持该操作，或参数超出范围。")
        outcome=body.get("outcome","ok")
        if outcome not in ("ok","offline","fail","timeout"):raise Problem("未知的模拟结果。")
        if outcome=="ok":
            self.apply(key,obj,cap,val,"手动")
            r=room_for(m,obj)
            if m["mode"]=="sleep" and r and not r.get("sleep") and obj["type"] in ("lamp","switch"):
                m["overrides"][r["id"]]=time.time()+15
                schedule(self,key,m)
        else:
            self.event(key,obj,outcome,{"offline":"设备离线","fail":"执行失败，状态未改变","timeout":"响应超时，保留最后确认状态"}[outcome])
        self.write(key,m)
        return {"result":outcome,"item":obj}

    def scene(self,key,m,mode):
        if mode not in MODES: raise Problem("未知的场景。")
        m.update(mode=mode,overrides={},due={})
        self.event(key,None,"ok","切换场景："+{"normal":"手动","home":"回家","away":"离家","sleep":"睡眠"}[mode])
        if mode=="away":
            for o in m["plan"]["items"]:
                if o.get("power"): self.apply(key,o,"power",False,"离家")
        elif mode=="home":
            lights=[o for o in m["plan"]["items"] if o["type"] in ("lamp","switch")]
            first=next((o for o in lights if (room_for(m,o) or {}).get("id")=="entry"),lights[0] if lights else None)
            if first and not first["power"]:self.apply(key,first,"power",True,"回家")
            self.climate(key,m,True)
        elif mode=="sleep":
            for o in m["plan"]["items"]:
                if o["type"] in ("lamp","switch") and o.get("power") and (room_for(m,o) or {}).get("sleep"):
                    self.apply(key,o,"power",False,"睡眠")
            self.climate(key,m,True)
            schedule(self,key,m)
        self.write(key,m)

    def climate(self,key,m,record=False):
        env=m["climate"]
        season,t,out=env["season"],env["indoor"],env["outdoor"]
        acs=[x for x in m["plan"]["items"] if x["type"]=="ac"]
        if season not in ("夏","冬"):
            if record:self.event(key,None,"ok","春秋温控建议：优先自然通风。")
            return
        cooling=season=="夏"
        target=round(max(24 if cooling else 18,min(28 if cooling else 22,
                     (25 if cooling else 20) + .12*(t-(25 if cooling else 20)) + .09*(out-(30 if cooling else 8)))),1)
        if m["mode"]=="sleep" and cooling: target=min(28,round(target+.5,1))
        if record:self.event(key,None,"ok",f"{season}季温控：室内 {t}°C／室外 {out}°C，目标 {target}°C")
        for o in acs:
            desired="制冷" if cooling else "制热"
            if o["mode"]!=desired:self.apply(key,o,"mode",desired,"温控")
            if o["target"]!=target:self.apply(key,o,"target",target,"温控")
            power=(t>target if o.get("power") else t>=target+1) if cooling else (t<target if o.get("power") else t<=target-1)
            if o.get("power")!=power:self.apply(key,o,"power",power,"温控")

    def tick(self):
        with self.lock,self.db:
            for key in PLAN_KEYS:
                m=self.read(key)
                now=time.time()
                if m["mode"]!="sleep" or not any(x<=now for x in (*m["due"].values(),*m["overrides"].values())):
                    continue
                schedule(self,key,m,now)
                self.write(key,m)

def good_id(v):return isinstance(v,str) and ID.fullmatch(v)
def good_name(v):return isinstance(v,str) and 1<=len(v.strip())<=70

def get_obj(m,device):
    o=next((o for o in m["plan"]["items"] if o["id"]==device),None)
    if o is None: raise Problem("设备不存在。",404)
    return o

def room_for(m,obj):
    return next((r for r in m["plan"]["rooms"] if inside(obj["x"],obj["y"],r["p"])),None)

def schedule(store,key,m,now=None):
    if m["mode"]!="sleep":return
    now=now if now is not None else time.time()
    rooms=m["plan"]["rooms"]
    for r in rooms:
        rid=r["id"]
        if r.get("sleep"):continue
        if m["overrides"].get(rid,0)>now:
            m["due"].pop(rid,None)
            continue
        m["overrides"].pop(rid,None)
        lamps=[o for o in m["plan"]["items"] if o["type"] in ("lamp","switch") and room_for(m,o)==r]
        if m["occupied"].get(rid):
            m["due"].pop(rid,None)
            for o in lamps:
                if not o["power"]: store.apply(key,o,"power",True,"有人")
        elif any(o["power"] for o in lamps):
            due=m["due"].setdefault(rid,now+m["delay"])
            if due<=now:
                for o in lamps:
                    if o["power"]:store.apply(key,o,"power",False,"无人延时")
                m["due"].pop(rid,None)
        else:
            m["due"].pop(rid,None)
    live={r["id"] for r in rooms}
    for field in ("due","overrides"):
        m[field]={k:v for k,v in m[field].items() if k in live}

class Handler(BaseHTTPRequestHandler):
    server_version="CourseDemo"
    def log_message(self,*args):
        if self.server.verbose: super().log_message(*args)

    def send_json(self,data,status=200,headers=()):
        pay=packed(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(pay)))
        for key,v in headers:self.send_header(key,v)
        self.end_headers()
        self.wfile.write(pay)

    def session(self):
        try:
            c=SimpleCookie(self.headers.get("Cookie",""))
            tok=c["home_demo"].value
        except (KeyError,ValueError):return False
        with self.server.session_lock:
            return self.server.sessions.get(tok,0)>time.time()

    def body(self):
        try:
            n=int(self.headers.get("Content-Length","0"))
            if not 0<n<=3*1024*1024:raise Problem("请求大小无效。")
            data=json.loads(self.rfile.read(n))
            if isinstance(data,dict):return data
        except (ValueError,OverflowError):pass
        raise Problem("请求格式不正确。")

    def route(self,method):
        path=unquote(urlsplit(self.path).path)
        try:
            if not path.startswith("/api/"):
                if method!="GET":raise Problem("页面不存在。",404)
                return self.static(path)
            if method!="GET":
                origin=self.headers.get("Origin")
                if origin and urlsplit(origin).netloc!=self.headers.get("Host"):raise Problem("无效的请求来源。",403)
            if path=="/api/status" and method=="GET":return self.send_json({"service":"smart-home-demo","signedIn":self.session()})
            if path=="/api/login" and method=="POST":
                provided=self.body().get("pin")
                if not isinstance(provided,str) or not hmac.compare_digest(provided,self.server.pin):
                    raise Problem("演示口令不正确。",401)
                token=secrets.token_urlsafe(27)
                with self.server.session_lock:
                    now=time.time()
                    self.server.sessions={k:v for k,v in self.server.sessions.items() if v>now}
                    self.server.sessions[token]=now+3600*12
                return self.send_json({"signedIn":True},headers=[("Set-Cookie",f"home_demo={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")])
            if not self.session():raise Problem("请先登录。",401)
            if path=="/api/types" and method=="GET":return self.send_json(TYPES)
            match=re.fullmatch(r"/api/plans/(apartment|apple|custom|house)(?:/(.*))?",path)
            if not match:raise Problem("接口不存在。",404)
            key, action=match.groups()
            store=self.server.store
            # Apply deterministic simulator latency before taking the database lock.
            body=self.body() if method in ("POST","PUT") else {}
            if method=="POST" and action and re.fullmatch(r"devices/[A-Za-z0-9_-]{1,80}/command",action):
                time.sleep(.9 if body.get("outcome")=="timeout" else .13)
            with store.lock,store.db:
                m=store.read(key)
                return self.send_json(self.plan_api(store,key,m,action,method,body))
        except Problem as e:self.send_json({"error":str(e)},e.status)
        except (BrokenPipeError,ConnectionResetError):pass

    def plan_api(self,store,key,m,action,method,body):
        if action is None:
            if method=="GET":return store.snapshot(key)
            if method=="PUT":store.replace(key,m,body);return store.snapshot(key)
        if action=="mount" and method=="POST":
            return {"item":store.mount(key,m,body),"snapshot":store.snapshot(key)}
        if action=="scene" and method=="POST":
            store.scene(key,m,body.get("mode"));return store.snapshot(key)
        if action=="environment" and method=="POST":
            r=body.get("room")
            if r is not None:
                if not isinstance(r,str) or r not in {o["id"] for o in m["plan"]["rooms"]} or type(body.get("occupied")) is not bool:
                    raise Problem("房间或感应状态无效。")
                m["occupied"][r]=body["occupied"]
                room=next(o["name"] for o in m["plan"]["rooms"] if o["id"]==r)
                store.event(key,None,"ok",room+(" 有人" if body["occupied"] else " 无人"))
                schedule(store,key,m)
            if "climate" in body:
                q=body["climate"]
                if not isinstance(q,dict) or q.get("season") not in SEASONS or not number(q.get("indoor"),0,45) or not number(q.get("outdoor"),-25,52):
                    raise Problem("温度或季节无效。")
                m["climate"]={k:q[k] for k in ("season","indoor","outdoor")}
                if m["mode"] in ("home","sleep"):store.climate(key,m,True)
            if "delay" in body:
                if not number(body["delay"],1,60):raise Problem("关灯延时为 1–60 秒。")
                m["delay"]=body["delay"]
                m["due"]={}
                schedule(store,key,m)
            store.write(key,m);return store.snapshot(key)
        match=re.fullmatch(r"devices/([A-Za-z0-9_-]{1,80})(?:/(history|command))?",action or "")
        if match:
            device,leaf=match.groups()
            if leaf=="command" and method=="POST":
                detail=store.command(key,m,device,body)
                return {**detail,"snapshot":store.snapshot(key)}
            if leaf=="history" and method=="GET":
                get_obj(m,device)
                return {"events":store.feed(key,device)}
            if leaf is None and method=="DELETE":
                store.remove(key,m,device);return store.snapshot(key)
        raise Problem("接口不存在。",404)

    def static(self,path):
        rel=path.lstrip("/") or "index.html"
        p=(ROOT/rel).resolve()
        valid=(p.parent==ROOT and p.suffix in (".html",".css",".js")) or any(p.is_relative_to(ROOT/d) for d in ("assets","vendor"))
        if not valid or not p.is_file(): raise Problem("文件不存在。",404)
        content=p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",mimetypes.guess_type(p.name)[0] or "application/octet-stream")
        self.send_header("Content-Length",str(len(content)))
        self.send_header("Cache-Control","no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):self.route("GET")
    def do_POST(self):self.route("POST")
    def do_PUT(self):self.route("PUT")
    def do_DELETE(self):self.route("DELETE")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8768)
    parser.add_argument("--db",type=Path,default=ROOT/".local/demo.sqlite3")
    parser.add_argument("--verbose",action="store_true")
    opts=parser.parse_args()
    opts.db.parent.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(("127.0.0.1",opts.port),Handler)
    server.store=Store(opts.db)
    server.pin=os.environ.get("HOME_DEMO_PIN","2468")
    server.sessions={}
    server.session_lock=threading.Lock()
    server.verbose=opts.verbose
    stop=threading.Event()
    def timers():
        while not stop.wait(.25):server.store.tick()
    threading.Thread(target=timers,daemon=True).start()
    print(f"智能家居演示  http://127.0.0.1:{opts.port}/",flush=True)
    print(f"演示口令：{server.pin}",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:stop.set();server.server_close()

if __name__=="__main__":main()
