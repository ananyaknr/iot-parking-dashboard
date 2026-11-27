"""Small bounded sensor-event identity ledger; never contains recognition/session data."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import threading


def gate_routing(origin,prefix,bucket,routing='off',approved=False):
    if routing=='off':return False
    if routing=='isolated' and origin in ('hardware_gate_sim','synthetic') and prefix in ('parking/test','issue1/parking/test') and bucket=='sensor_test':return True
    if routing=='production' and approved and (origin,prefix,bucket)==('hardware_gate_sim','parking','sensor_data'):return True
    raise ValueError('Gate schema/routing transition is not approved or isolated')


class GateEvents:
    def __init__(self,path,capacity=5000):
        self.lock=threading.Lock();self.capacity=capacity
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=1,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
        page=self.db.execute('PRAGMA page_size').fetchone()[0]
        self.db.execute(f'PRAGMA max_page_count={2*1024*1024//page}')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, stamp TEXT NOT NULL, fields TEXT NOT NULL)')
        self.db.commit()

    def remember(self,message,stamp):
        event={'event_id':message['event_id'],'boot_id':message['boot_id'],
               'event_seq':message['event_seq'],'last_event':message['last_event'],
               'arrival_id':message['arrival_id'],'passage_id':message['passage_id'],
               'arrival_count':message['arrival_count'],'completed_count':message['completed_count'],
               'servo_enabled':False,'simulation':True,'schema_version':2}
        with self.lock,self.db:
            row=self.db.execute('SELECT stamp,fields FROM events WHERE id=?',(event['event_id'],)).fetchone()
            if row:
                if json.loads(row[1])!=event:raise ValueError('Event identity reused with different content')
                original=datetime.fromisoformat(row[0])
                return (original,event) if original>=datetime.now(timezone.utc)-timedelta(days=7) else None
            if self.db.execute('SELECT count(*) FROM events').fetchone()[0]>=self.capacity:
                raise ValueError('Bounded gate event ledger full; supervised maintenance required')
            self.db.execute('INSERT INTO events VALUES (?,?,?)',(event['event_id'],stamp.isoformat(),json.dumps(event)))
            return stamp,event

    def recent(self):
        with self.lock:
            rows=self.db.execute('SELECT stamp,fields FROM events ORDER BY stamp DESC LIMIT 20').fetchall()
        return [dict(json.loads(fields),received_at_utc=stamp) for stamp,fields in rows]

    def close(self):
        with self.lock:self.db.close()
