"""Isolated confirmed v1 simulation adapter. No allocation or session writes."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from model import unique_object

PREFIX='parking/test/'
TELEMETRY=PREFIX+'gate/v3/telemetry'
CONTROL=PREFIX+'gate/v3/control'
WIRE_ACK=PREFIX+'gate/v3/ack'
ARRIVAL=PREFIX+'v1/arrival'
COMMAND=PREFIX+'v1/gate/command'
ACK=PREFIX+'v1/gate/ack'
FEEDBACK=PREFIX+'v1/gate/feedback'
FEEDBACK_ACK=FEEDBACK+'/ack'
PHASES=('boot','closed','authorization_wait','open','closing','hold')
DIRECTIONS=('none','entrance','exit','manual')

def stamp(value):
    if not isinstance(value,str):raise ValueError('UTC timestamp required')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None or result.utcoffset().total_seconds()!=0:raise ValueError('UTC required')
    return result

def ident(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9:_-]{1,96}',value) is not None

def decode(payload):
    if len(payload)>2048:raise ValueError('Payload limit')
    result=json.loads(payload,object_pairs_hook=unique_object,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(result,dict):raise ValueError('Object required')
    return result

class ParkingV1:
    def __init__(self,path,publish,*,clock=lambda:datetime.now(timezone.utc),mono=time.monotonic,clock_verified=lambda:True):
        self.publish=publish;self.clock=clock;self.mono=mono;self.clock_verified=clock_verified;self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS arrivals (id TEXT PRIMARY KEY,payload TEXT NOT NULL,expires REAL NOT NULL,last_sent REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, event TEXT UNIQUE NOT NULL, arrival TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, token TEXT UNIQUE NOT NULL, ack TEXT NOT NULL, state TEXT NOT NULL)')
        self.db.execute('CREATE INDEX IF NOT EXISTS command_state ON commands(state)')
        self.db.execute('CREATE TABLE IF NOT EXISTS rejections (id TEXT PRIMARY KEY, hash TEXT NOT NULL, ack TEXT NOT NULL)')
        # An interrupted execution is never resent after restart.
        for cid,raw in self.db.execute("SELECT id,ack FROM commands WHERE state='pending'").fetchall():
            ack=json.loads(raw);ack['status']=ack['state']='unknown';ack['reason']='executor_restart'
            ack['event_id']=uuid.uuid4().hex;ack['ack_id']=uuid.uuid4().hex;ack['occurred_at']=self.clock().isoformat()
            self.db.execute('UPDATE commands SET state=?,ack=? WHERE id=?',('unknown',json.dumps(ack),cid))
        self.db.execute('CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, arrival TEXT NOT NULL, transition TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_send REAL NOT NULL DEFAULT 0, recorded INTEGER NOT NULL DEFAULT 0)')
        self.db.commit();self.current=None;self.received=None;self.recognition=None;self.rejected=0
        self.retired=[];self.feedback_enabled=True

    def transition(self,m,old):
        aid=f"r_{m['boot_id']}_{m['cycle']}"
        arrival=self.db.execute('SELECT payload FROM arrivals WHERE id=?',(aid,)).fetchone()
        if not arrival:return
        state={3:'opening',5:'hold'}.get(m['phase'])
        if m['phase']==1 and m['reason']==16:state='hold'
        # R_COMPLETE is emitted only after explicit CONFIRM, safe CLOSE and closing.
        if (m['mode']=='entrance_exit_sim' and m['phase']==1 and m['reason']==13 and old and old['phase']==4 and old['cycle']==m['cycle']
            and old['boot_id']==m['boot_id'] and old['gateway_boot_id']==m['gateway_boot_id']):state='completed'
        if not state:return
        transition=f"{aid}:{m['phase']}:{m['reason']}"
        if self.db.execute('SELECT 1 FROM feedback WHERE transition=?',(transition,)).fetchone():return
        command=self.db.execute('SELECT id FROM commands WHERE arrival=?',(aid,)).fetchone()
        payload={'schema_version':1,'event_id':uuid.uuid4().hex,'producer_id':'sensor-gateway',
          'occurred_at':self.clock().isoformat(),'arrival_id':aid,'command_id':command[0] if command else None,
          'direction':json.loads(arrival[0])['direction'],'state':state,'passage_confirmed':state=='completed',
          'simulation':True,'reason':None if state=='completed' else 'passage_unverified_safe_close' if m['reason']==16 else 'controller_reason_'+str(m['reason'])}
        self.db.execute('INSERT INTO feedback(id,arrival,transition,payload) VALUES(?,?,?,?)',
                        (payload['event_id'],aid,transition,json.dumps(payload)))
        self.db.commit()

    def feedback_ack(self,m):
        required={'schema_version','event_id','producer_id','occurred_at','arrival_id','feedback_id','state'}
        if not required<=set(m) or type(m['schema_version']) is not int or m['schema_version']!=1 or m['state']!='recorded':raise ValueError('Feedback acknowledgement')
        if not all(ident(m[k]) for k in ('event_id','producer_id','arrival_id','feedback_id')):raise ValueError('Identity')
        stamp(m['occurred_at'])
        row=self.db.execute('SELECT arrival FROM feedback WHERE id=?',(m['feedback_id'],)).fetchone()
        if not row or row[0]!=m['arrival_id']:raise ValueError('Feedback correlation')
        self.db.execute('UPDATE feedback SET recorded=1 WHERE id=?',(m['feedback_id'],));self.db.commit()

    def emit(self,topic,message):self.publish(topic,json.dumps(message,ensure_ascii=False,separators=(',',':')))

    def telemetry(self,m):
        required={'schema_version','mode','boot_id','gateway_boot_id','uptime_ms','gateway_uptime_ms','u1_distance_cm','u2_distance_cm','u1_state','u2_state','phase','lane','cycle','vibration_raw','vibration_transition_count','reason','minimum_open_ms','started_at_ms','servo_enabled'}
        if set(m)!=required or m['schema_version']!=3 or type(m['schema_version']) is not int or m['mode'] not in ('entrance_exit_sim','entrance_exit_auto_sim') or m['servo_enabled'] is not False:raise ValueError('G3 schema')
        for key in ('boot_id','gateway_boot_id'):
            if not isinstance(m[key],str) or not re.fullmatch('[0-9a-f]{32}',m[key]):raise ValueError('Boot')
        for key in ('uptime_ms','gateway_uptime_ms','cycle','vibration_raw','vibration_transition_count','reason','minimum_open_ms','started_at_ms','phase','lane'):
            if type(m[key]) is not int or not 0<=m[key]<=4294967295:raise ValueError('Unsigned field')
        if m['phase']>5 or m['lane']>3 or m['reason']>16 or m['vibration_raw']>1 or not 5000<=m['minimum_open_ms']<=60000:raise ValueError('State bounds')
        for z in ('u1','u2'):
            v=m[z+'_distance_cm'];s=m[z+'_state']
            if s not in ('unknown','clear','detected'):raise ValueError('Zone')
            if v is None:
                if s!='unknown':raise ValueError('No echo is not clear')
            elif type(v) not in (int,float) or not math.isfinite(v) or not 2<=v<=400 or (s=='clear' and v<14.95) or (s=='detected' and v>18.05):raise ValueError('Distance')
        if m['phase']==4 and not all(m[z+'_state']=='clear' and m[z+'_distance_cm']>=18 for z in ('u1','u2')):raise ValueError('Unsafe closing')
        old=self.current
        if old:
            epoch=(m['boot_id'],m['gateway_boot_id'])
            old_epoch=(old['boot_id'],old['gateway_boot_id'])
            if epoch in self.retired:raise ValueError('Retired epoch')
            if epoch==old_epoch:
                if not 0<((m['uptime_ms']-old['uptime_ms'])&0xffffffff)<0x80000000 or m['cycle']<old['cycle']:raise ValueError('Replay')
            else:self.retired=(self.retired+[old_epoch])[-128:]
        self.current=dict(m);self.received=self.mono()
        if m['lane'] in (1,2) and m['cycle'] and m['phase']==(2 if m['lane']==1 else 3):
            age=((m['uptime_ms']-m['started_at_ms'])&0xffffffff)/1000
            if age<20:
                aid=f"r_{m['boot_id']}_{m['cycle']}"
                if not self.db.execute('SELECT 1 FROM arrivals WHERE id=?',(aid,)).fetchone():
                    if self.db.execute('SELECT count(*) FROM arrivals').fetchone()[0]>=5000:raise ValueError('Arrival ledger full')
                    now=self.clock();payload={'schema_version':1,'event_id':uuid.uuid4().hex,'arrival_id':aid,
                        'occurred_at':now.isoformat(),'producer_id':'sensor-gateway','trigger':'ultrasonic',
                        'direction':DIRECTIONS[m['lane']]}
                    self.db.execute('INSERT INTO arrivals VALUES(?,?,?,?)',(aid,json.dumps(payload),(now.timestamp()+20-age),-1e9));self.db.commit()
        self.transition(m,old)
        return m

    def command(self,m):
        digest=hashlib.sha256(json.dumps(m,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        row=self.db.execute('SELECT hash,ack FROM rejections WHERE id=?',(m.get('command_id'),)).fetchone()
        if row:
            if row[0]==digest:self.emit(ACK,json.loads(row[1]));return 'duplicate'
            raise ValueError('Conflicting rejected command')
        try:return self._command(m)
        except ValueError:
            # Reject recognizable commands explicitly, but never overwrite an existing identity.
            if (m.get('schema_version')==1 and all(ident(m.get(k)) for k in ('event_id','arrival_id','command_id','producer_id'))
                and not self.db.execute('SELECT 1 FROM commands WHERE id=?',(m['command_id'],)).fetchone()
                and self.db.execute('SELECT count(*) FROM rejections').fetchone()[0]<5000):
                ack={'schema_version':1,'event_id':uuid.uuid4().hex,'ack_id':uuid.uuid4().hex,
                     'producer_id':'sensor-gateway','occurred_at':self.clock().isoformat(),'arrival_id':m['arrival_id'],
                     'command_id':m['command_id'],'state':'rejected','reason':'validation_or_controller_state'}
                self.db.execute('INSERT INTO rejections VALUES(?,?,?)',(m['command_id'],digest,json.dumps(ack)));self.db.commit();self.emit(ACK,ack)
            raise

    def _command(self,m):
        keys={'schema_version','event_id','arrival_id','producer_id','occurred_at','command_id','session_id','decision_id','action','direction','issued_at','expires_at','license_plate','lcd_plate','vehicle_type'}
        if not keys<=set(m) or type(m['schema_version']) is not int or m['schema_version']!=1:raise ValueError('Command schema')
        if not all(ident(m[k]) for k in ('event_id','arrival_id','command_id','session_id','decision_id','producer_id')):raise ValueError('Identity')
        if m['action']!='OPEN' or m['direction']!='entrance' or m.get('authorized',True) is not True:raise ValueError('Only entrance OPEN')
        now=self.clock();issued=stamp(m['issued_at']);expiry=stamp(m['expires_at']);occurred=stamp(m['occurred_at'])
        plate=m['license_plate'];lcd=m['lcd_plate']
        if not isinstance(plate,str) or not 1<=len(plate)<=64 or any(unicodedata.category(c) in ('Cc','Cs') for c in plate):raise ValueError('Original plate')
        if not isinstance(lcd,str) or not 1<=len(lcd)<=16 or any(not 32<=ord(c)<=126 for c in lcd):raise ValueError('LCD ASCII')
        if m['vehicle_type'] not in ('car','sportcar','supercar'):raise ValueError('Vehicle type')
        digest=hashlib.sha256(json.dumps(m,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        row=self.db.execute('SELECT hash,ack FROM commands WHERE id=?',(m['command_id'],)).fetchone()
        if row:
            if row[0]!=digest:raise ValueError('Conflicting command ID')
            state=self.db.execute('SELECT state FROM commands WHERE id=?',(m['command_id'],)).fetchone()[0]
            if state!='pending':self.emit(ACK,json.loads(row[1]))
            return 'duplicate'
        if not self.clock_verified() or now.year<2025 or not -1<=(now-issued).total_seconds()<5 or not 0<(expiry-now).total_seconds()<=6 or abs((expiry-issued).total_seconds()-5)>.001 or abs((occurred-issued).total_seconds())>1:raise ValueError('Expired command or unverifiable clock')
        g=self.current
        if not g or self.mono()-self.received>2 or g['phase']!=2 or g['lane']!=1 or m['arrival_id']!=f"r_{g['boot_id']}_{g['cycle']}":raise ValueError('Not current entrance')
        if not self.db.execute('SELECT 1 FROM arrivals WHERE id=?',(m['arrival_id'],)).fetchone():raise ValueError('Unannounced arrival')
        if self.db.execute('SELECT count(*) FROM commands').fetchone()[0]>=5000:raise ValueError('Command ledger full')
        token=uuid.uuid4().hex[:8]
        ack={'schema_version':1,'event_id':uuid.uuid4().hex,'ack_id':uuid.uuid4().hex,'arrival_id':m['arrival_id'],'command_id':m['command_id'],
             'occurred_at':now.isoformat(),'producer_id':'sensor-gateway','status':'unknown','state':'unknown','reason':'awaiting_controller',
             'physical_movement':False}
        # No plate/session archive: persist fingerprint and delivery receipt only.
        self.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?)',(m['command_id'],m['event_id'],m['arrival_id'],digest,token,json.dumps(ack),'pending'));self.db.commit()
        remaining=int((expiry-now).total_seconds()*1000)
        control={'boot_id':g['boot_id'],'gateway_boot_id':g['gateway_boot_id'],'cycle':g['cycle'],'wire_token':token,
                 'deadline_ms':(g['gateway_uptime_ms']+remaining)&0xffffffff,'lcd_hex':lcd.encode('ascii').hex(),'vehicle_type':m['vehicle_type']}
        self.recognition={k:m[k] for k in ('license_plate','lcd_plate','vehicle_type','occurred_at','arrival_id')}
        self.emit(CONTROL,control)
        return 'accepted'

    def receive(self,topic,payload,retained=False):
        with self.lock:
            if retained:raise ValueError('Retained control/telemetry')
            m=decode(payload)
            try:
                if topic==TELEMETRY:return self.telemetry(m)
                if topic==COMMAND:self.command(m);return None
                if topic==FEEDBACK_ACK:self.feedback_ack(m);return None
                if topic==WIRE_ACK:
                    if set(m)!={'wire_token','status'} or m['status'] not in ('ok','duplicate','rejected','timeout'):raise ValueError('Wire ack')
                    row=self.db.execute('SELECT id,ack,state FROM commands WHERE token=?',(m['wire_token'],)).fetchone()
                    if row and row[2]=='pending':
                        ack=json.loads(row[1]);ack['status']=ack['state']='accepted' if m['status'] in ('ok','duplicate') else 'rejected' if m['status']=='rejected' else 'unknown'
                        ack['reason']='simulated_open_lcd' if ack['status']=='accepted' else 'uno_'+m['status']
                        # New acknowledgement state is its own event; retries reuse it.
                        ack['event_id']=uuid.uuid4().hex;ack['ack_id']=uuid.uuid4().hex;ack['occurred_at']=self.clock().isoformat()
                        self.db.execute('UPDATE commands SET state=?,ack=? WHERE id=?',(ack['status'],json.dumps(ack),row[0]));self.db.commit();self.emit(ACK,ack)
                    return None
                raise ValueError('Topic')
            except sqlite3.IntegrityError as exc:raise ValueError('Reused event or arrival') from exc

    def tick(self):
        with self.lock:
            now=self.clock().timestamp();mono=self.mono()
            for aid,raw,last in self.db.execute('SELECT id,payload,last_sent FROM arrivals WHERE expires>?',(now,)).fetchall():
                if mono-last>=1 and not self.db.execute('SELECT 1 FROM commands WHERE arrival=?',(aid,)).fetchone():
                    self.publish(ARRIVAL,raw);self.db.execute('UPDATE arrivals SET last_sent=? WHERE id=?',(mono,aid))
            for cid,raw in self.db.execute("SELECT id,ack FROM commands WHERE state='pending'").fetchall():
                ack=json.loads(raw)
                if now-stamp(ack['occurred_at']).timestamp()>=5:
                    ack['status']=ack['state']='unknown';ack['reason']='uno_ack_timeout'
                    ack['event_id']=uuid.uuid4().hex;ack['ack_id']=uuid.uuid4().hex;ack['occurred_at']=self.clock().isoformat()
                    self.db.execute('UPDATE commands SET state=?,ack=? WHERE id=?',('unknown',json.dumps(ack),cid));self.emit(ACK,ack)
            for fid,raw,attempts in self.db.execute('SELECT id,payload,attempts FROM feedback WHERE recorded=0 AND next_send<=?',(now,)).fetchall():
                self.publish(FEEDBACK,raw)
                delay=(2,4,8,16,30)[min(attempts,4)]
                self.db.execute('UPDATE feedback SET attempts=?,next_send=? WHERE id=?',(attempts+1,now+delay,fid))
            self.db.commit()

    def snapshot(self):
        with self.lock:
            fresh=self.received is not None and self.mono()-self.received<10
            correlated=bool(self.current and self.recognition and self.recognition['arrival_id']==f"r_{self.current['boot_id']}_{self.current['cycle']}")
            outcome=None
            if self.current:
                row=self.db.execute('SELECT state FROM commands WHERE arrival=?',(f"r_{self.current['boot_id']}_{self.current['cycle']}",)).fetchone()
                if row:outcome=row[0]
            return {'enabled':True,'fresh':fresh,'telemetry':dict(self.current) if fresh and self.current else None,
                    'recognition':dict(self.recognition) if fresh and correlated else None,
                    'command_outcome':outcome,'feedback_enabled':True,'clock_verified':self.clock_verified(),
                    'pending_feedback':self.db.execute('SELECT count(*) FROM feedback WHERE recorded=0').fetchone()[0],
                    'session_release':'teammate_owned','rejected':self.rejected}

    def close(self):self.db.close()
