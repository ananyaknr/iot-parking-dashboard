"""Isolated, disabled-by-default contract adapter. No recognition or session archive."""
from datetime import datetime,timezone
import re
import threading
import unicodedata


class RecognitionAdapter:
    def __init__(self,active_gate,*,enabled=False):
        self.active_gate=active_gate;self.enabled=enabled;self.result=None;self.lock=threading.Lock()

    def receive(self,message,*,now=None):
        if not self.enabled:raise PermissionError('Teammate contract/production delivery not configured')
        expected={'schema_version','result_id','arrival_id','occurred_at','license_plate','lcd_plate',
                  'vehicle_type','status','authorized','origin','session_id','photo_ref'}
        if not isinstance(message,dict) or set(message)!=expected:raise ValueError('Invalid recognition keys')
        if type(message['schema_version']) is not int or message['schema_version']!=2 or message['origin']!='synthetic':
            raise ValueError('Only isolated synthetic adapter verification is enabled')
        if not isinstance(message['result_id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',message['result_id']):
            raise ValueError('Invalid result ID')
        if message['vehicle_type'] not in ('car','supercar','unknown') or message['status'] not in ('recognized','review','failed'):
            raise ValueError('Unsupported recognition status/type')
        if type(message['authorized']) is not bool:raise ValueError('Authorization must be explicit')
        if message['authorized'] and (message['status']!='recognized' or message['vehicle_type']=='unknown'):
            raise ValueError('Unknown/failed recognition cannot authorize')
        if message['session_id'] is not None or message['photo_ref'] is not None:
            raise ValueError('Session/photo projection requires teammate agreement')
        plate=message['license_plate'];lcd=message['lcd_plate']
        if plate is not None and (not isinstance(plate,str) or not 1<=len(plate)<=64
            or any(unicodedata.category(char) in ('Cc','Cs') for char in plate)):
            raise ValueError('Invalid original plate')
        if lcd is not None and (not isinstance(lcd,str) or not re.fullmatch('[A-Za-z0-9 -]{1,16}',lcd)):
            raise ValueError('LCD requires separately supplied ASCII text')
        now=now or datetime.now(timezone.utc)
        stamp=datetime.fromisoformat(message['occurred_at'])
        if stamp.tzinfo is None or not -1<=(now-stamp).total_seconds()<=5:raise ValueError('Expired recognition')
        gate=self.active_gate()
        if not gate.get('fresh') or not gate.get('payload_valid') or not gate.get('arrival_id') or gate['arrival_id']!=message['arrival_id']:
            raise ValueError('Recognition does not match current fresh arrival')
        with self.lock:
            if self.result and self.result['result_id']==message['result_id']:
                if self.result!=message:raise ValueError('Result ID conflict')
                return 'duplicate'
            self.result=dict(message)
        return 'accepted'

    def snapshot(self):
        gate=self.active_gate()
        with self.lock:result=dict(self.result) if self.result else None
        available=bool(result and gate.get('fresh') and gate.get('payload_valid')
                       and gate.get('arrival_id')==result['arrival_id']
                       and (datetime.now(timezone.utc)-datetime.fromisoformat(result['occurred_at'])).total_seconds()<30)
        if not available:return {'status':'not_configured' if not self.enabled else 'waiting','license_plate':None,'vehicle_type':'unknown'}
        return dict(result,lcd_delivery='not_sent_contract_pending',gate_authorization='disabled',
                    lcd_status='ascii_fallback_required' if result['lcd_plate'] is None else 'prepared')
