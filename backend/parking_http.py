"""Test-only MQTT/HTTP bridge. Parking allocation and matching stay in HTTP service."""
import hashlib
import json
import sqlite3
import uuid
from datetime import timedelta
from urllib.request import Request, build_opener, ProxyHandler
from parking_v1 import ARRIVAL,COMMAND,ACK,FEEDBACK,FEEDBACK_ACK,decode,ident,stamp

class ParkingHTTP:
    def __init__(self,url,path,publish,clock,lcd_map=None):
        self.url=url.rstrip('/');self.publish=publish;self.clock=clock;self.lcd_map=lcd_map or {}
        self.http=build_opener(ProxyHandler({}))
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS joint_arrivals(id TEXT PRIMARY KEY,direction TEXT,hash TEXT,observation TEXT,recognition TEXT,decision TEXT,command TEXT,state TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS joint_feedback(id TEXT PRIMARY KEY,arrival TEXT,hash TEXT,ack TEXT)')
        # Never recapture or invent a new OPEN after an uncertain process restart.
        self.db.execute("UPDATE joint_arrivals SET state='review_restart' WHERE state IN ('capturing','committing','command_pending')")
        self.db.commit();self.last_send={};self.retry_at={}

    def request(self,path,data=None,content_type=None):
        headers={'Cache-Control':'no-store'}
        if content_type:headers['Content-Type']=content_type
        with self.http.open(Request(self.url+path,data=data,headers=headers),timeout=30) as r:
            body=r.read(16*1024*1024+1)
            if len(body)>16*1024*1024:raise ValueError('HTTP response limit')
            return body,r.headers

    def status(self):return json.loads(self.request('/parking/status')[0])

    def preflight(self):
        spec=json.loads(self.request('/openapi.json')[0])
        commit=spec['components']['schemas']['CommitRequest']
        if set(commit['properties'])!={'observation_id','request_id'}:raise ValueError('Commit schema changed: review required')
        if not all(p in spec['paths'] for p in ('/camera/snapshot','/parking/analyze','/parking/commit','/parking/status')):raise ValueError('HTTP routes unavailable')
        status=self.status()
        if status.get('gate_mode')!='simulation' or status.get('storage')!='local':raise ValueError('Requires explicitly isolated local test storage')
        return {'api_reachable':True,'openapi_checked':True,'storage':'local','gate_mode':'simulation'}

    def update(self,aid,**fields):
        allowed={'observation','recognition','decision','command','state'}
        if not fields.keys()<=allowed:raise ValueError('Ledger field')
        self.db.execute('UPDATE joint_arrivals SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),aid));self.db.commit()

    def row(self,aid):
        self.db.row_factory=sqlite3.Row
        r=self.db.execute('SELECT * FROM joint_arrivals WHERE id=?',(aid,)).fetchone()
        return dict(r) if r else None

    def emit(self,topic,m):self.publish(topic,json.dumps(m,ensure_ascii=False,separators=(',',':')))

    def commit(self,row):
        # Exactly the two OpenAPI fields. Stable request ID binds HTTP work to MQTT arrival.
        body={'observation_id':row['observation'],'request_id':'joint:'+row['id']}
        d=json.loads(self.request('/parking/commit',json.dumps(body).encode(),'application/json')[0])['decision']
        if (d['observation_id']!=row['observation'] or d['request_id']!=body['request_id']
            or d['camera']!=row['direction'] or type(d['approved']) is not bool or d['gate']['mode']!='simulation'):raise ValueError('Uncorrelated HTTP decision')
        self.update(row['id'],decision=json.dumps(d))
        return d

    def arrival(self,m):
        common={'schema_version','event_id','producer_id','occurred_at','arrival_id','direction','trigger'}
        if not common<=m.keys() or m['schema_version']!=1 or m['direction'] not in ('entrance','exit') or m['trigger']!='ultrasonic':raise ValueError('Arrival schema')
        if not all(ident(m[k]) for k in ('event_id','producer_id','arrival_id')):raise ValueError('Arrival identity')
        aid=m['arrival_id'];digest=hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest()
        old=self.row(aid)
        if old:
            if old['hash']!=digest:raise ValueError('Conflicting arrival')
            return
        age=(self.clock()-stamp(m['occurred_at'])).total_seconds()
        if not -1<=age<18:raise ValueError('Stale arrival')
        self.db.execute('INSERT INTO joint_arrivals VALUES(?,?,?,NULL,NULL,NULL,NULL,?)',(aid,m['direction'],digest,'capturing'));self.db.commit()
        photo,headers=self.request('/camera/snapshot?camera='+m['direction'])
        if headers.get_content_type()!='image/jpeg' or not photo.startswith(b'\xff\xd8'):raise ValueError('Fresh JPEG required')
        boundary='parking_'+uuid.uuid4().hex
        form=(f'--{boundary}\r\nContent-Disposition: form-data; name="camera"\r\n\r\n{m["direction"]}\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="test-camera.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()+photo+f'\r\n--{boundary}--\r\n'.encode()
        recognition=json.loads(self.request('/parking/analyze',form,'multipart/form-data; boundary='+boundary)[0])
        observation=str(uuid.UUID(recognition['observation_id']))
        # Store only the necessary recognition, never images or response debug data.
        recognition={k:recognition.get(k) for k in ('eligible','license_plate','vehicle_type')}
        recognition['capture_sha256']=hashlib.sha256(photo).hexdigest()
        self.update(aid,observation=observation,recognition=json.dumps(recognition),state='analyzed')
        if recognition['eligible'] is not True:self.update(aid,state='review_recognition');return
        if m['direction']=='exit':self.update(aid,state='exit_wait_passage');self.finish_exit(aid);return
        plate=recognition['license_plate'];lcd=self.lcd_map.get(plate,plate)
        if not isinstance(lcd,str) or not 1<=len(lcd)<=16 or any(not 32<=ord(c)<=126 for c in lcd):raise ValueError('Explicit ASCII LCD mapping required before reserving')
        if not self.clock.verified() or (self.clock()-stamp(m['occurred_at'])).total_seconds()>=18:raise ValueError('Entrance authorization window elapsed before reservation')
        self.update(aid,state='committing');d=self.commit(self.row(aid))
        if not d['approved']:self.update(aid,state='denied');return
        if (self.clock()-stamp(m['occurred_at'])).total_seconds()>=19:self.update(aid,state='review_reserved_late');return
        now=self.clock();command={'schema_version':1,'event_id':uuid.uuid5(uuid.NAMESPACE_URL,'message:'+aid).hex,
          'producer_id':'parking-http-test','occurred_at':now.isoformat(),'arrival_id':aid,
          'command_id':uuid.uuid5(uuid.NAMESPACE_URL,'command:'+aid).hex,'session_id':d['session_id'],'decision_id':d['id'],
          'direction':'entrance','action':'OPEN','issued_at':now.isoformat(),'expires_at':(now+timedelta(seconds=5)).isoformat(),
          'license_plate':plate,'lcd_plate':lcd,'vehicle_type':d['vehicle_type']}
        self.update(aid,command=json.dumps(command),state='command_pending')

    def finish_exit(self,aid):
        row=self.row(aid)
        if not row or row['direction']!='exit' or row['state'] not in ('exit_wait_passage','exit_commit_pending'):return
        rows=self.db.execute('SELECT ack FROM joint_feedback WHERE arrival=?',(aid,)).fetchall()
        # Durable receipt stores proof internally alongside its cached wire ACK.
        if not any(json.loads(r[0]).get('_completed') is True and json.loads(r[0]).get('_direction')=='exit' for r in rows):return
        self.update(aid,state='exit_commit_pending')
        d=self.commit(self.row(aid)) # Server atomically matches and releases AFTER passage.
        self.update(aid,state='exit_completed' if d['approved'] else 'review_unmatched_exit')

    def receive(self,topic,payload,retained=False):
        if retained:raise ValueError('Retained integration message')
        m=decode(payload)
        if topic==ARRIVAL:return self.arrival(m)
        if topic==ACK:
            row=self.row(m['arrival_id'])
            if row and row['command'] and m['command_id']==json.loads(row['command'])['command_id']:
                if m['state'] in ('accepted','rejected','failed','unknown'):self.update(row['id'],state='entry_accepted' if m['state']=='accepted' else 'review_gate_'+m['state'])
            return
        if topic!=FEEDBACK:raise ValueError('Topic')
        required={'schema_version','event_id','producer_id','occurred_at','arrival_id','command_id','direction','state','passage_confirmed','simulation','reason'}
        if (not required<=m.keys() or m['schema_version']!=1 or m['simulation'] is not True
            or m['direction'] not in ('entrance','exit') or m['state'] not in ('opening','completed','hold','failed')
            or type(m['passage_confirmed']) is not bool or (m['passage_confirmed'] and m['state']!='completed')
            or not all(ident(m[k]) for k in ('event_id','producer_id','arrival_id'))):raise ValueError('Feedback schema')
        stamp(m['occurred_at']);row=self.row(m['arrival_id'])
        if row and row['direction']!=m['direction']:raise ValueError('Direction conflict')
        if m['direction']=='exit' and m['command_id'] is not None:raise ValueError('Local exit command must be null')
        if row and row['direction']=='entrance' and row['command'] and m['command_id']!=json.loads(row['command'])['command_id']:raise ValueError('Entrance command correlation')
        digest=hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest()
        existing=self.db.execute('SELECT hash,ack FROM joint_feedback WHERE id=?',(m['event_id'],)).fetchone()
        if existing:
            if existing[0]!=digest:raise ValueError('Conflicting feedback')
            ack=json.loads(existing[1])
        else:
            ack={'schema_version':1,'event_id':uuid.uuid4().hex,'producer_id':'parking-http-test',
                 'occurred_at':self.clock().isoformat(),'arrival_id':m['arrival_id'],'feedback_id':m['event_id'],'state':'recorded',
                 '_completed':m['state']=='completed' and m['passage_confirmed'] is True,'_direction':m['direction']}
            self.db.execute('INSERT INTO joint_feedback VALUES(?,?,?,?)',(m['event_id'],m['arrival_id'],digest,json.dumps(ack)));self.db.commit()
        self.emit(FEEDBACK_ACK,{k:v for k,v in ack.items() if not k.startswith('_')})
        if m['direction']=='exit':self.finish_exit(m['arrival_id'])

    def tick(self):
        now=self.clock()
        for aid,raw in self.db.execute("SELECT id,command FROM joint_arrivals WHERE state='command_pending'").fetchall():
            command=json.loads(raw)
            if now>=stamp(command['expires_at']):self.update(aid,state='review_ack_timeout');continue
            if now.timestamp()-self.last_send.get(aid,0)>=1:self.emit(COMMAND,command);self.last_send[aid]=now.timestamp()
        for (aid,) in self.db.execute("SELECT id FROM joint_arrivals WHERE state='exit_commit_pending'").fetchall():
            if now.timestamp()-self.retry_at.get(aid,0)>=2:
                self.retry_at[aid]=now.timestamp();self.finish_exit(aid)

    def close(self):self.db.close()
