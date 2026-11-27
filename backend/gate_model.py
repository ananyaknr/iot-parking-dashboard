"""Gate v2 simulation telemetry. Legacy occupancy never populates this state."""
import math
import re
from dataclasses import dataclass, field

GATE_RANGES = {'u1_distance_cm':(2,400),'u2_distance_cm':(2,400),
               'arrival_count':(0,4294967295),'completed_count':(0,4294967295),
               'vibration_raw':(0,1),'vibration_transition_count':(0,4294967295)}
GATE_KEYS = {'node','schema_version','mode','control_mode','boot_id','uptime_ms',
             'u1_distance_cm','u2_distance_cm','u1_state','u2_state','gate_sim_state',
             'servo_enabled','arrival_count','completed_count','vibration_raw',
             'vibration_transition_count','vibration_semantics','event_seq','last_event',
             'arrival_id','passage_id','event_id'}
STATES = {'boot_wait','closed','authorization_wait','open_wait','passing','closing','hold'}
EVENTS = {'boot','ready','arrival','authorized','authorization_denied','passage_detected',
          'clearance_confirmed','passage_completed','cycle_timeout','sensor_unknown',
          'unexpected_passage','closing_obstruction','second_vehicle','supervised_reset','counter_exhausted'}


def identity(boot, kind, number):
    return f'v2:{boot}:{kind}:{number}'


def validate_gate(message):
    if set(message) != GATE_KEYS or message.get('node') != 'uno':
        raise ValueError('Gate schema keys/source differ')
    if type(message['schema_version']) is not int or message['schema_version'] != 2:
        raise ValueError('Unsupported gate version')
    if message['mode'] != 'gate_sim' or message['control_mode'] not in ('standalone','integrated'):
        raise ValueError('Unsupported gate control mode')
    if message['servo_enabled'] is not False:
        raise ValueError('Physical servo actuation is not supported')
    boot = message['boot_id']
    if not isinstance(boot,str) or not re.fullmatch('[0-9a-f]{32}',boot):
        raise ValueError('Invalid boot identity')
    for name in ('uptime_ms','event_seq','arrival_count','completed_count','vibration_transition_count','vibration_raw'):
        if type(message[name]) is not int or not 0 <= message[name] <= (1 if name=='vibration_raw' else 4294967295):
            raise ValueError('Invalid unsigned counter')
    if message['completed_count'] > message['arrival_count'] or message['vibration_semantics'] != 'sampled_transitions':
        raise ValueError('Inconsistent counters/semantics')
    for zone in ('u1','u2'):
        value,state = message[zone+'_distance_cm'],message[zone+'_state']
        if state not in ('unknown','clear','detected'):
            raise ValueError('Invalid zone state')
        if value is None:
            if state != 'unknown':raise ValueError('No echo is not clearance')
        elif type(value) not in (int,float) or not math.isfinite(value) or not 2 <= value <= 400:
            raise ValueError('Invalid distance')
        elif (state=='clear' and value<14.95) or (state=='detected' and value>18.05):
            raise ValueError('Zone contradicts hysteresis')
    state = message['gate_sim_state']
    if state not in STATES or message['last_event'] not in EVENTS:
        raise ValueError('Invalid gate state/event')
    if state=='authorization_wait' and message['control_mode']!='integrated':
        raise ValueError('Unexpected authorization state')
    if state in ('authorization_wait','open_wait','passing','closing') and message['arrival_count'] <= message['completed_count']:
        raise ValueError('Active cycle without arrival')
    if state=='closing' and not all(message[z+'_state']=='clear' and message[z+'_distance_cm'] is not None
                                     and message[z+'_distance_cm']>=18 for z in ('u1','u2')):
        raise ValueError('Closing without valid clearance')
    for field,kind,counter in [('arrival_id','a','arrival_count'),('passage_id','p','completed_count'),('event_id','e','event_seq')]:
        expected = identity(boot,kind,message[counter]) if field=='event_id' or message[counter] else None
        if message[field] != expected:raise ValueError('Uncorrelated event identity')
    return message


@dataclass
class GateSource:
    name: str = 'gate'
    message: dict = field(default_factory=dict)
    last_valid: float | None = None
    last_received: float | None = None
    payload_valid: bool = False
    retired_boots: list = field(default_factory=list)
    last_accepted: dict = field(default_factory=dict)

    def accept(self,message,now):
        if self.last_received is not None and now<=self.last_received:return False
        old=self.last_accepted
        if old:
            if message['boot_id'] in self.retired_boots:return False
            if message['boot_id']==old['boot_id']:
                delta=(message['uptime_ms']-old['uptime_ms']) & 0xffffffff
                if not 0 < delta < 0x80000000:return False
                if any(message[key]<old[key] for key in ('event_seq','arrival_count','completed_count','vibration_transition_count')):
                    return False
                if message['event_seq']==old['event_seq'] and any(message[key]!=old[key]
                    for key in ('arrival_count','completed_count','gate_sim_state','last_event')):return False
            else:
                self.retired_boots=(self.retired_boots+[old['boot_id']])[-128:]
        self.last_accepted=dict(message);self.message=dict(message)
        self.last_valid=self.last_received=now;self.payload_valid=True
        return True

    def reject(self,now):
        if self.last_received is None or now>self.last_received:
            self.message={};self.last_received=now;self.payload_valid=False

    def snapshot(self,now,stale_after=10):
        age=None if self.last_valid is None else max(0,now-self.last_valid)
        fresh=age is not None and age<stale_after
        usable=fresh and self.payload_valid
        result={'schema_version':2,'simulation':True,'fresh':fresh,'payload_valid':self.payload_valid,
                'gate_sim_state':self.message.get('gate_sim_state','unknown') if usable else 'unknown',
                'servo_enabled':False if usable else None,'vibration_semantics':'sampled_transitions',
                'vibration_polarity':'unverified','received_recently':self.last_received is not None and now-self.last_received<stale_after}
        if age is not None:result['age_seconds']=float(age)
        for field in GATE_RANGES:
            valid=usable and self.message.get(field) is not None
            result[field+'_valid']=valid
            if valid:result[field]=self.message[field]
        for zone in ('u1','u2'):result[zone+'_state']=self.message.get(zone+'_state','unknown') if usable else 'unknown'
        for key in ('boot_id','event_seq','event_id','arrival_id','passage_id','last_event','control_mode','mode'):
            if usable:result[key]=self.message[key]
        return result
