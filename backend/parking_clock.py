"""Small SNTP check for five-second commands; never adjusts the Windows clock."""
from datetime import datetime, timezone
import socket
import struct
import threading
import time

class VerifiedClock:
    def __init__(self,stop,host='time.windows.com'):
        self.offset=0.;self.checked=None;self.wall=None;self.monotonic=None
        threading.Thread(target=self.run,args=(stop,host),daemon=True).start()

    def verified(self):
        return (self.checked is not None and time.monotonic()-self.checked<300
                and abs((time.time()-self.wall)-(time.monotonic()-self.monotonic))<.5)

    def __call__(self):return datetime.fromtimestamp(time.time()+self.offset,timezone.utc)

    def run(self,stop,host):
        while not stop.is_set():
            try:
                start=time.time();packet=bytearray(48);packet[0]=0x23
                ntp=start+2208988800;seconds=int(ntp)
                packet[40:48]=struct.pack('!II',seconds,int((ntp-seconds)*2**32))
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
                    s.settimeout(2);s.connect((host,123));s.send(packet);data=s.recv(512)
                end=time.time()
                if len(data)<48 or data[0]&7!=4 or data[0]>>6==3 or not 1<=data[1]<=15 or data[24:32]!=packet[40:48] or end-start>1:raise ValueError('Unverifiable NTP')
                def ts(at):
                    sec,frac=struct.unpack('!II',data[at:at+8]);return sec-2208988800+frac/2**32
                self.offset=((ts(32)-start)+(ts(40)-end))/2
                self.wall=end;self.monotonic=time.monotonic();self.checked=self.monotonic
            except (OSError,ValueError,struct.error):pass
            stop.wait(60)
