#!/usr/bin/env python3
"""Call the knowledge_service spreadsheet ingestion API."""

import argparse
import json
import os
import sys
from urllib import error, request

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest a spreadsheet through knowledge_service."
    )
    parser.add_argument("project_name", help="Project name, for example: projectA")
    parser.add_argument("notebook_env", help="Notebook environment, for example: env_a")
    parser.add_argument("spreadsheet_id", help="Google Spreadsheet file ID")
    parser.add_argument("output_name", help="Markdown output filename, for example: sales.md")
    basePort = f"{os.getenv('VIRTUAL_PORT', '8000').strip()}" 
    baseUrl = f"http://{os.getenv('VIRTUAL_HOST', 'localhost').strip()}:{basePort}"
    print(f"Debug: {baseUrl}")
    parser.add_argument(
        "--base-url",
        default=baseUrl,
        help="knowledge_service base URL. Default: http://localhost:8000",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds. Default: 120",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service_api_key = os.getenv("SERVICE_API_KEY", "").strip()
    if not service_api_key:
        print("Ingest failed: SERVICE_API_KEY environment variable is not configured.", file=sys.stderr)
        return 2
    payload = {
        "project_name": args.project_name,
        "notebook_env": args.notebook_env,
        "spreadsheet_id": args.spreadsheet_id,
        "output_name": args.output_name,
    }
    body = json.dumps(payload).encode("utf-8")
    endpoint = f"{args.base_url.rstrip('/')}/ingest-spreadsheet"
    req = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "X-API-Key": service_api_key},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=args.timeout) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Ingest failed: HTTP {exc.code}", file=sys.stderr)
        print(detail, file=sys.stderr)
        return 1
    except error.URLError as exc:
        print(f"Ingest failed: cannot connect to {endpoint}: {exc.reason}", file=sys.stderr)
        return 1
    except TimeoutError:
        print(f"Ingest failed: request timed out after {args.timeout:g}s", file=sys.stderr)
        return 1

    print(response_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
