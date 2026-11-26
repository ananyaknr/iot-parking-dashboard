"""Local credential setup. No token is printed, committed or passed on CLI."""
import getpass
import argparse
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
from cloud_storage import load_config, PRODUCTION, TEST, CloudClient, CloudError


def validate_read_scope(config):
    response = json.loads(CloudClient(config).request('/api/v2/buckets', {'limit':100}, 'read_token'))
    names = {bucket['name'] for bucket in response.get('buckets', [])}
    if names != {config['bucket']}:
        raise ValueError('read_scope_mismatch')


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--url')
    parser.add_argument('--free-plan-confirmed', action='store_true')
    replacement = parser.add_mutually_exclusive_group()
    replacement.add_argument('--replace-write', action='store_true',
                        help='Preserve saved settings/read token and replace only the write token')
    replacement.add_argument('--replace-read', action='store_true',
                        help='Preserve saved settings/write token and replace only the read token')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("Run this script in an interactive local terminal; tokens must not be piped or echoed.")
    warnings.simplefilter("error", getpass.GetPassWarning)
    testing = args.test
    path = ROOT / ".secrets" / ("cloud-test.json" if testing else "cloud.json")
    if not args.free_plan_confirmed and input("Confirmed InfluxDB Cloud Serverless Free Plan, no paid upgrade? [yes/no] ").strip().lower() != "yes":
        raise SystemExit("No configuration changed.")
    bucket = TEST if testing else PRODUCTION
    print("Create/verify bucket:", bucket, "(30-day retention) and default DBRP mapping before continuing.")
    if args.replace_write or args.replace_read:
        try:
            config = load_config(path, testing=testing)
        except (ValueError, OSError, KeyError, TypeError):
            raise SystemExit('Existing configuration unavailable; no credentials changed.') from None
        if args.url and args.url.rstrip('/') != config['url']:
            raise SystemExit('Regional URL differs from saved configuration; no credentials changed.')
        role = 'read' if args.replace_read else 'write'
        config[role+'_token'] = getpass.getpass('New '+role+'-only token for '+bucket+': ')
    else:
        config = {"url": args.url or input("Regional HTTPS URL from InfluxDB: ").strip(), "bucket": bucket,
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
        print('Checking read-token bucket scope...', flush=True)
        validate_read_scope(config)
        os.replace(temporary, path)
    except CloudError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise SystemExit('Read-token verification unavailable ('+str(exc.code)+'). No credentials changed.') from None
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if isinstance(exc, ValueError) and str(exc) == 'read_scope_mismatch':
            raise SystemExit('Read token must access only '+bucket+'. No new credentials saved.') from None
        raise SystemExit("Invalid configuration or file access; no new credentials saved.")
    print("Saved ignored local configuration with restricted file permissions.")
    print("Run the cloud verification script before enabling production sync.")

if __name__ == "__main__":
    main()
