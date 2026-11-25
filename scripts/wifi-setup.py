"""Temporary loopback-only Wi-Fi setup. Password never enters chat, logs or responses."""
import hmac
import json
from pathlib import Path
import secrets
import threading
from flask import Flask, request, make_response
from waitress import create_server

ROOT=Path(__file__).resolve().parents[1]
app=Flask(__name__)
app.config["MAX_CONTENT_LENGTH"]=4096
token=secrets.token_urlsafe(32)
saved=threading.Event()
HOST="127.0.0.1:8765"

@app.before_request
def local_only():
    if request.host!=HOST or request.remote_addr!="127.0.0.1":return "Local access only",403

@app.after_request
def secure(response):
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Content-Security-Policy"]="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    return response

@app.route("/",methods=["GET","POST"])
def setup():
    if saved.is_set():return '<h1>Wi-Fi settings saved locally.</h1><p>You can close this tab. Tell the assistant “saved”.</p>'
    if request.method=="POST":
        if request.headers.get("Origin")!="http://"+HOST or not hmac.compare_digest(request.form.get("token",""),token) or not hmac.compare_digest(request.cookies.get("setup_token",""),token):
            return "Invalid local setup request",403
        ssid=request.form.get("ssid","")
        password=request.form.get("password","")
        if not 1<=len(ssid.encode())<=32 or not 8<=len(password)<=63:return "Enter a valid SSID and an 8–63 character WPA2 hotspot password.",400
        values=dict(line.split("=",1) for line in (ROOT/".env").read_text().splitlines() if line and not line.startswith("#") and "=" in line)
        q=lambda value:json.dumps(value,ensure_ascii=False)
        header='\n'.join(['#pragma once','#define WIFI_ENTERPRISE 0',
            'const char WIFI_SSID[] = '+q(ssid)+';',
            'const char WIFI_PASSWORD[] = '+q(password)+';',
            'const char MQTT_HOST[] = '+q(values["MQTT_BIND_IP"])+';',
            'const uint16_t MQTT_PORT = 1883;',
            'const char MQTT_USERNAME[] = '+q(values["MQTT_USERNAME"])+';',
            'const char MQTT_PASSWORD[] = '+q(values["MQTT_PASSWORD"])+';',''])
        (ROOT/'firmware/esp32_gateway/secrets.h').write_text(header,encoding="utf-8")
        saved.set()
        return '<h1>Wi-Fi settings saved locally.</h1><p>You can close this tab. Tell the assistant “saved”.</p>'
    html='''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Local ESP32 Wi-Fi setup</title><style>body{font:17px Segoe UI,sans-serif;background:#f2f5f9;color:#17304e;max-width:520px;margin:60px auto;padding:25px}form{background:white;padding:28px;border-radius:14px}label{display:block;margin:20px 0 8px}input{width:100%;box-sizing:border-box;padding:12px;font:inherit;border:1px solid #b7c6d7;border-radius:7px}button{padding:13px 20px;background:#1467a8;color:white;border:0;border-radius:7px;font:inherit;margin-top:24px}p{line-height:1.6}</style><h1>ESP32 Wi-Fi setup</h1><p>This page runs only on your computer. Your hotspot password is saved locally for the ESP32 firmware and is never sent to chat.</p><form method="post"><input type="hidden" name="token" value="TOKEN"><label for="ssid">Hotspot network name</label><input id="ssid" name="ssid" value="jm" required maxlength="32"><label for="password">Hotspot password</label><input id="password" name="password" type="password" required minlength="8" maxlength="63" autocomplete="off"><button>Save locally</button></form>'''.replace('TOKEN',token)
    response=make_response(html)
    response.set_cookie("setup_token",token,httponly=True,samesite="Strict")
    return response

if __name__=="__main__":
    server=create_server(app,host="127.0.0.1",port=8765,threads=2)
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    print("Local credential setup: http://127.0.0.1:8765 (no password logging)",flush=True)
    saved.wait(timeout=1800)
    if saved.is_set():
        print("Local Wi-Fi configuration saved; no credentials printed.",flush=True)
        threading.Event().wait(15)
    server.close()
