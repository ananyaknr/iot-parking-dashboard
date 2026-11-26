"""Provision only the two approved free buckets/DBRPs using a local setup token.

The setup token is prompted without echo, used only in memory, and never saved.
Runtime uses separate bucket-scoped read/write tokens via configure-cloud.py.
"""
import getpass
import argparse
import json
from pathlib import Path
import sys
import warnings
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cloud_storage import NoRedirect, PRODUCTION, TEST, RETENTION_SECONDS, serverless_url


class ResourceError(ValueError):
    pass


def provision(call, *, rename_empty_iot_parking=False):
    names = (PRODUCTION, TEST)
    buckets = call("GET", "/api/v2/buckets?limit=100").get("buckets", [])
    user_buckets = [b for b in buckets if b.get("type") != "system"
                    and b["name"] not in ("_monitoring", "_tasks")]
    rename = None
    if rename_empty_iot_parking and not any(b["name"] == PRODUCTION for b in user_buckets):
        rename = next((b for b in user_buckets if b["name"] == "iot_parking"), None)
        if rename is not None:
            # This flag is only for the user-approved empty bucket. Keep the
            # original ID/data; plan its name before capacity/DBRP validation.
            user_buckets = [dict(b, name=PRODUCTION) if b["id"] == rename["id"] else b
                            for b in user_buckets]
    missing = [name for name in names if not any(b["name"] == name for b in user_buckets)]
    if len(user_buckets) + len(missing) > 2:
        raise ResourceError("Free Plan capacity unavailable. Preserve existing buckets; resolve names/capacity in the UI first.")
    org_ids = {b['orgID'] for b in user_buckets if b.get('orgID')}
    if len(org_ids) != 1:
        orgs = call('GET', '/api/v2/orgs').get('orgs', [])
        org_ids = {org['id'] for org in orgs if org.get('id')}
    if len(org_ids) != 1:
        raise ResourceError('Cannot identify exactly one organization; no resources changed.')
    org_id = next(iter(org_ids))
    # Validate all existing mappings before any changes; never hijack another bucket.
    mappings = {}
    for name in names:
        mappings[name] = call("GET", "/api/v2/dbrps?" + urlencode({"orgID": org_id, "db": name})).get("content", [])
        existing = next((b for b in user_buckets if b["name"] == name), None)
        if mappings[name] and (existing is None or any(m["bucketID"] != existing["id"] for m in mappings[name])):
            raise ResourceError("Existing DBRP points elsewhere; no mapping will be overwritten.")
    result = []
    rules = [{"type": "expire", "everySeconds": RETENTION_SECONDS}]
    if rename is not None:
        renamed = call("PATCH", "/api/v2/buckets/"+quote(rename["id"], safe=""),
                       {"name": PRODUCTION, "retentionRules": rules})
        if renamed.get("id") != rename["id"] or renamed.get("name") != PRODUCTION:
            raise ResourceError("Approved bucket rename readback failed")
        user_buckets = [renamed if b["id"] == rename["id"] else b for b in user_buckets]
    for name in names:
        bucket = next((b for b in user_buckets if b["name"] == name), None)
        if bucket is None:
            bucket = call("POST", "/api/v2/buckets", {"orgID": org_id, "name": name, "retentionRules": rules})
        elif not bucket.get("retentionRules") or any(r.get("everySeconds") != RETENTION_SECONDS for r in bucket["retentionRules"]):
            bucket = call("PATCH", "/api/v2/buckets/"+quote(bucket["id"], safe=""), {"retentionRules": rules})
        default = next((m for m in mappings[name] if m.get("default")), None)
        if default is None:
            if mappings[name]:
                call("PATCH", "/api/v2/dbrps/"+quote(mappings[name][0]["id"], safe=""), {"default": True})
            else:
                call("POST", "/api/v2/dbrps", {"orgID": org_id, "bucketID": bucket["id"], "database": name,
                                               "retention_policy": "autogen", "default": True})
        verified = call("GET", "/api/v2/buckets/"+quote(bucket["id"], safe=""))
        actual_rules = verified.get("retentionRules", [])
        if not actual_rules or any(r.get("everySeconds") != RETENTION_SECONDS for r in actual_rules):
            raise ResourceError("Bucket retention readback is not 30 days")
        actual_mappings = call("GET", "/api/v2/dbrps?"+urlencode({"orgID": org_id, "db": name})).get("content", [])
        if not any(m.get("default") and m["bucketID"] == bucket["id"] for m in actual_mappings):
            raise ResourceError("Default DBRP readback failed")
        result.append({"bucket": name, "retention_days": 30, "default_dbrp": True})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--free-plan-confirmed', action='store_true')
    parser.add_argument('--rename-empty-iot-parking', action='store_true',
                        help='Use only after the user approves renaming the empty iot_parking bucket')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("Run in an interactive local terminal. Never pipe a token.")
    warnings.simplefilter("error", getpass.GetPassWarning)
    if not args.free_plan_confirmed and input("Billing verified as Cloud Serverless Free Plan, zero paid spend? [yes/no] ").strip().lower() != "yes":
        raise SystemExit("No changes made")
    url = serverless_url(args.url or input("Regional HTTPS URL: ").strip())
    print('Setting up parking_sensor_data and parking_sensor_test, 30-day retention, Free Plan only.')
    if args.rename_empty_iot_parking:
        print('Approved empty-bucket rename: iot_parking -> parking_sensor_data. No bucket deletion.')
    token = getpass.getpass("Temporary setup token (bucket/DBRP management; never saved): ")
    if not token or any(c.isspace() for c in token):
        raise SystemExit("Invalid setup token format; nothing sent.")
    opener = build_opener(NoRedirect())
    last_request = {}
    def call(method, path, body=None):
        last_request.update(method=method, endpoint=path.split('?')[0])
        print('Request:', method, path.split('?')[0], flush=True)
        headers = {"Authorization": "Token "+token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url+path, data=None if body is None else json.dumps(body).encode(),
                          headers=headers, method=method)
        with opener.open(request, timeout=10) as response:
            raw = response.read(1024*1024+1)
            if len(raw) > 1024*1024:
                raise ValueError("Unexpectedly large resource response")
            return json.loads(raw) if raw else {}
    try:
        result = provision(call, rename_empty_iot_parking=args.rename_empty_iot_parking)
    except HTTPError as exc:
        code = exc.code; exc.close()
        (ROOT/'.runtime').mkdir(exist_ok=True)
        (ROOT/'.runtime/cloud-resource-attempt.json').write_text(json.dumps(dict(last_request,http_status=code)))
        raise SystemExit(f"Resource setup failed: HTTP {code} at {last_request.get('method')} {last_request.get('endpoint')}; no token or response body printed.") from None
    except ResourceError as exc:
        raise SystemExit(str(exc)) from None
    except (ValueError, OSError):
        raise SystemExit("Resource setup network/response failure; no credentials printed.") from None
    receipt = {"verified_at_utc": datetime.now(timezone.utc).isoformat(),
               "free_plan_user_confirmed": True, "resources": result}
    (ROOT/".runtime").mkdir(exist_ok=True)
    (ROOT/".runtime/cloud-resources.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))
    print("Revoke the temporary setup token in the provider UI. Configure only bucket-scoped runtime tokens next.")


if __name__ == "__main__":
    main()
