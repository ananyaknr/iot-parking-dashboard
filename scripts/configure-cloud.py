"""Local credential setup. No token is printed, committed or passed on CLI."""
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cloud_storage import load_config, PRODUCTION, TEST

def main():
    testing = "--test" in sys.argv
    path = ROOT / ".secrets" / ("cloud-test.json" if testing else "cloud.json")
    if input("Confirmed InfluxDB Cloud Serverless Free Plan, no paid upgrade? [yes/no] ").strip().lower() != "yes":
        raise SystemExit("No configuration changed.")
    bucket = TEST if testing else PRODUCTION
    print("Create/verify bucket:", bucket, "(30-day retention) and default DBRP mapping before continuing.")
    config = {"url": input("Regional HTTPS URL from InfluxDB: ").strip(), "bucket": bucket,
              "free_plan_confirmed": True,
              "read_token": getpass.getpass("Bucket-scoped read token: "),
              "write_token": getpass.getpass("Bucket-scoped write token: ")}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        with open(temporary, "x", encoding="utf-8") as file:
            json.dump(config, file)
        if os.name != "nt":
            temporary.chmod(0o600)
        load_config(temporary, testing=testing)
        os.replace(temporary, path)
    except (ValueError, OSError, KeyError, TypeError):
        temporary.unlink(missing_ok=True)
        raise SystemExit("Invalid configuration or file access; no new credentials saved.")
    print("Saved ignored local configuration. Restrict access to your Windows user.")
    print("Run the cloud verification script before enabling production sync.")

if __name__ == "__main__":
    main()
