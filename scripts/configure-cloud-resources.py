"""Provision only the two approved free buckets/DBRPs using a local setup token.

The setup token is prompted without echo, used only in memory, and never saved.
Runtime uses separate bucket-scoped read/write tokens via configure-cloud.py.
"""
import getpass
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


def provision(call):
    names = (PRODUCTION, TEST)
    buckets = call("GET", "/api/v2/buckets?limit=100").get("buckets", [])
    user_buckets = [b for b in buckets if b.get("type") != "system"
                    and b["name"] not in ("_monitoring", "_tasks")]
    missing = [name for name in names if not any(b["name"] == name for b in user_buckets)]
    if len(user_buckets) + len(missing) > 2:
        raise ResourceError("Free Plan capacity unavailable. Preserve existing buckets; resolve names/capacity in the UI first.")
    # Validate all existing mappings before any changes; never hijack another bucket.
    mappings = {}
    for name in names:
        mappings[name] = call("GET", "/api/v2/dbrps?" + urlencode({"db": name})).get("content", [])
        existing = next((b for b in user_buckets if b["name"] == name), None)
        if mappings[name] and (existing is None or any(m["bucketID"] != existing["id"] for m in mappings[name])):
            raise ResourceError("Existing DBRP points elsewhere; no mapping will be overwritten.")
    result = []
    rules = [{"type": "expire", "everySeconds": RETENTION_SECONDS}]
    for name in names:
        bucket = next((b for b in user_buckets if b["name"] == name), None)
        if bucket is None:
            bucket = call("POST", "/api/v2/buckets", {"name": name, "retentionRules": rules})
        elif not bucket.get("retentionRules") or any(r.get("everySeconds") != RETENTION_SECONDS for r in bucket["retentionRules"]):
            bucket = call("PATCH", "/api/v2/buckets/"+quote(bucket["id"], safe=""), {"retentionRules": rules})
        default = next((m for m in mappings[name] if m.get("default")), None)
        if default is None:
            if mappings[name]:
                call("PATCH", "/api/v2/dbrps/"+quote(mappings[name][0]["id"], safe=""), {"default": True})
            else:
                call("POST", "/api/v2/dbrps", {"bucketID": bucket["id"], "database": name,
                                               "retention_policy": "autogen", "default": True})
        verified = call("GET", "/api/v2/buckets/"+quote(bucket["id"], safe=""))
        actual_rules = verified.get("retentionRules", [])
        if not actual_rules or any(r.get("everySeconds") != RETENTION_SECONDS for r in actual_rules):
            raise ResourceError("Bucket retention readback is not 30 days")
        actual_mappings = call("GET", "/api/v2/dbrps?"+urlencode({"db": name})).get("content", [])
        if not any(m.get("default") and m["bucketID"] == bucket["id"] for m in actual_mappings):
            raise ResourceError("Default DBRP readback failed")
        result.append({"bucket": name, "retention_days": 30, "default_dbrp": True})
    return result


def main():
    if not sys.stdin.isatty():
        raise SystemExit("Run in an interactive local terminal. Never pipe a token.")
    warnings.simplefilter("error", getpass.GetPassWarning)
    if input("Billing verified as Cloud Serverless Free Plan, zero paid spend? [yes/no] ").strip().lower() != "yes":
        raise SystemExit("No changes made")
    url = serverless_url(input("Regional HTTPS URL: ").strip())
    token = getpass.getpass("Temporary setup token (bucket/DBRP management; never saved): ")
    if not token or any(c.isspace() for c in token):
        raise SystemExit("Invalid setup token format; nothing sent.")
    opener = build_opener(NoRedirect())
    def call(method, path, body=None):
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
        result = provision(call)
    except HTTPError as exc:
        code = exc.code; exc.close()
        raise SystemExit(f"Resource setup failed: HTTP {code}; no token or response body printed.") from None
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
