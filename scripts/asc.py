#!/usr/bin/env python3
"""App Store Connect API helper (CLI).

Registers bundle IDs and creates app records via the App Store Connect API, so the
iOS app can be provisioned without the web UI. Reused later for build upload.

Auth via env (no secrets in the repo):
  ASC_ISSUER_ID   issuer UUID (ASC -> Users and Access -> Integrations)
  ASC_KEY_ID      key id, e.g. 42PM72NJQX
  ASC_KEY_PATH    path to AuthKey_<KEY_ID>.p8

Commands:
  python asc.py whoami                         # list teams' apps (auth check)
  python asc.py list-bundles                   # existing bundle IDs
  python asc.py register-bundle <id> <name>    # register a new bundle ID
  python asc.py create-app <bundleId> <name> <sku> [locale]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import jwt
import requests

API = "https://api.appstoreconnect.apple.com/v1"


def _token() -> str:
    issuer = os.environ["ASC_ISSUER_ID"]
    key_id = os.environ["ASC_KEY_ID"]
    key_path = os.environ["ASC_KEY_PATH"]
    private_key = Path(key_path).expanduser().read_text()
    now = int(time.time())
    payload = {"iss": issuer, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"})


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def _check(resp: requests.Response) -> dict:
    if resp.status_code >= 400:
        raise SystemExit(f"ASC API {resp.status_code}: {resp.text}")
    return resp.json() if resp.text else {}


def list_apps() -> None:
    data = _check(requests.get(f"{API}/apps?limit=200", headers=_headers()))
    for a in data.get("data", []):
        at = a["attributes"]
        print(f"  {at.get('bundleId'):40} {at.get('name'):24} sku={at.get('sku')}")
    print(f"({len(data.get('data', []))} apps)")


def list_bundles() -> None:
    data = _check(requests.get(f"{API}/bundleIds?limit=200", headers=_headers()))
    for b in data.get("data", []):
        at = b["attributes"]
        print(f"  {at.get('identifier'):40} {at.get('name'):24} [{at.get('platform')}]  id={b['id']}")
    print(f"({len(data.get('data', []))} bundle ids)")


def register_bundle(identifier: str, name: str, platform: str = "IOS") -> str:
    body = {"data": {"type": "bundleIds", "attributes": {
        "identifier": identifier, "name": name, "platform": platform, "seedId": None}}}
    data = _check(requests.post(f"{API}/bundleIds", headers=_headers(), json=body))
    bid = data["data"]["id"]
    print(f"registered bundleId {identifier!r} -> resource id {bid}")
    return bid


def _bundle_resource_id(identifier: str) -> str:
    data = _check(requests.get(
        f"{API}/bundleIds?filter[identifier]={identifier}&limit=1", headers=_headers()))
    items = data.get("data", [])
    if not items:
        raise SystemExit(f"bundle id {identifier!r} not found; register it first")
    return items[0]["id"]


def create_app(bundle_identifier: str, name: str, sku: str, locale: str = "en-US") -> None:
    bundle_rid = _bundle_resource_id(bundle_identifier)
    body = {"data": {
        "type": "apps",
        "attributes": {"name": name, "sku": sku, "primaryLocale": locale,
                       "bundleId": bundle_identifier},
        "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle_rid}}},
    }}
    data = _check(requests.post(f"{API}/apps", headers=_headers(), json=body))
    print(f"created app {name!r} (sku={sku}) -> id {data['data']['id']}")


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "whoami":
        list_apps()
    elif cmd == "list-bundles":
        list_bundles()
    elif cmd == "register-bundle":
        register_bundle(rest[0], rest[1])
    elif cmd == "create-app":
        create_app(rest[0], rest[1], rest[2], rest[3] if len(rest) > 3 else "en-US")
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
