"""Generate local credentials without printing them; preserve existing secrets."""
import argparse
import json
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]

def read_env():
    path = ROOT / ".env"
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker-ip", required=True)
    args = parser.parse_args()
    env = ROOT / ".env"
    if not env.exists():
        values = {"MQTT_BIND_IP": args.broker_ip, "MQTT_USERNAME": "parking",
                  "MQTT_PASSWORD": secrets.token_urlsafe(32), "INFLUX_USERNAME": "parking-admin",
                  "INFLUX_PASSWORD": secrets.token_urlsafe(32), "INFLUX_TOKEN": secrets.token_urlsafe(48),
                  "GRAFANA_USERNAME": "parking-admin", "GRAFANA_PASSWORD": secrets.token_urlsafe(32)}
        env.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        secret_dir = ROOT / ".secrets"
        secret_dir.mkdir(exist_ok=True)
        # Convert in place with mosquitto_passwd -U before starting the broker.
        (secret_dir / "mosquitto.passwd").write_text(f"parking:{values['MQTT_PASSWORD']}\n")
        print("Generated .env and local MQTT password file; no credentials printed.")
    else:
        values = read_env()
        print("Preserved existing .env and credentials.")
    # Header is completed by the local secure Wi-Fi prompt; never overwrite it here.
    (ROOT / ".secrets" / "setup-state.json").write_text(json.dumps({"broker_ip": values["MQTT_BIND_IP"]}))

if __name__ == "__main__":
    main()
