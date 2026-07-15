#!/usr/bin/env python3
import argparse
import json
import os
import sys
from urllib import error, request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a project NotebookLM config into knowledge_service."
    )
    parser.add_argument("project_name", help="Project name, for example: projectA")
    parser.add_argument("notebook_env", help="Notebook environment, for example: env_a")
    parser.add_argument("notebook_id", help="NotebookLM notebook ID")
    parser.add_argument("notebooklm_auth_name", help="Auth JSON filename, for example: team-a.json")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="knowledge_service base URL. Default: http://localhost:8000",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    service_api_key = os.getenv("SERVICE_API_KEY", "").strip()
    if not service_api_key:
        print("Import failed: SERVICE_API_KEY environment variable is not configured.", file=sys.stderr)
        return 2

    payload = {
        "project_name": args.project_name,
        "notebook_env": args.notebook_env,
        "notebook_id": args.notebook_id,
        "notebooklm_auth_name": args.notebooklm_auth_name,
    }
    body = json.dumps(payload).encode("utf-8")
    endpoint = f"{args.base_url.rstrip('/')}/project-notebook-configs"
    req = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "X-API-Key": service_api_key},
        method="POST",
    )

    try:
        with request.urlopen(req) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Import failed: HTTP {exc.code}", file=sys.stderr)
        print(detail, file=sys.stderr)
        return 1
    except error.URLError as exc:
        print(f"Import failed: cannot connect to {endpoint}: {exc.reason}", file=sys.stderr)
        return 1

    print(response_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
