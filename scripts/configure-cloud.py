"""Local credential setup. No token is printed, committed or passed on CLI."""
import getpass
import csv
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cloud_storage import load_config, PRODUCTION, TEST


def restrict_file(path):
    if os.name == "nt":
        identity = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader([identity.strip()]))[-1]
        if not sid.startswith("S-1-"):
            raise OSError("Cannot identify Windows user")
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        f"*{sid}:(F)", "*S-1-5-18:(F)"], check=True, capture_output=True)
    else:
        path.chmod(0o600)

def main():
    if not sys.stdin.isatty():
        raise SystemExit("Run this script in an interactive local terminal; tokens must not be piped or echoed.")
    warnings.simplefilter("error", getpass.GetPassWarning)
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
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.stem+"-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            restrict_file(temporary)
            json.dump(config, file)
        load_config(temporary, testing=testing)
        os.replace(temporary, path)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise SystemExit("Invalid configuration or file access; no new credentials saved.")
    print("Saved ignored local configuration with restricted file permissions.")
    print("Run the cloud verification script before enabling production sync.")

if __name__ == "__main__":
    main()
