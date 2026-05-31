"""Push a packaged SkyGuardian dataset into Palantir Foundry (post-mission, ONLINE).

Requires internet + Foundry credentials. Env:
  FOUNDRY_HOST            e.g. https://<tenant>.palantirfoundry.com
  FOUNDRY_TOKEN           a Foundry bearer token (never commit this)
  FOUNDRY_ONTOLOGY_RID    ri.ontology.main.ontology.<...>
  FOUNDRY_DATASET_RID     ri.foundry.main.dataset.<...> (backing dataset for files)
Optional action-name / tuning overrides: FOUNDRY_ACTION_MISSION, FOUNDRY_ACTION_CLASS,
  FOUNDRY_ACTION_MISSION_EDIT, FOUNDRY_ACTION_CLASS_EDIT, FOUNDRY_TIMEOUT_S, FOUNDRY_MAX_RETRIES.

The CaptureMission + DetectionClass object types and their create-/edit- actions must
already exist in the Foundry ontology (see the design spec for the schema).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.capture.foundry_export import FoundryClient, FoundryConfig, export_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Export a packaged dataset to Palantir Foundry.")
    ap.add_argument("--dataset", required=True, type=Path,
                    help="path to a packaged dataset dir (contains manifest.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate config + payloads and write the report WITHOUT any network call")
    args = ap.parse_args()

    try:
        config = FoundryConfig.from_env()
    except ValueError as exc:
        print(f"[foundry] config error: {exc}", file=sys.stderr)
        return 2

    client = None if args.dry_run else FoundryClient(config)
    # In dry-run, export_dataset never touches the client; pass a harmless stub.
    if client is None:
        class _NoCall:
            def __getattr__(self, _):
                raise AssertionError("network call attempted during --dry-run")
        client = _NoCall()

    report = export_dataset(args.dataset, client, config,
                            dry_run=args.dry_run, report_t=time.time())
    print(f"[foundry] {json.dumps({k: report[k] for k in ('dry_run', 'mission', 'files_uploaded', 'files_planned') if k in report})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
