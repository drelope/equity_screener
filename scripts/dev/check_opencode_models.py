"""Check that OPENCODE_API_KEY is set and accepted by the OpenCode models API.

Run it deliberately:

    python -m scripts.dev.check_opencode_models

It is a manual connectivity check, not an import. It previously ran its HTTP
request and could raise SystemExit at module scope, so anything that imported it
-- a test collector, a lint-time import, `python -m` -- paid for a network round
trip or died on a missing environment variable that had nothing to do with the
importer.
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv

from src.crispdm.http_retry import request_with_backoff


def main() -> int:
    load_dotenv()

    api_key = os.getenv("OPENCODE_API_KEY")
    if not api_key:
        print(
            "OPENCODE_API_KEY is missing; set it in .env or the environment.",
            file=sys.stderr,
        )
        return 2

    session = requests.Session()
    response = request_with_backoff(
        session,
        "GET",
        "https://api.opencode.ai/v1/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        print(
            f"HTTP {response.status_code} from the models endpoint:\n{response.text[:500]}",
            file=sys.stderr,
        )
        return 1

    # A 2xx that is not JSON is a proxy, a login page or a gateway error page.
    # A diagnostic that dies with a JSONDecodeError traceback is useless for
    # telling those apart, so print whatever actually came back.
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(f"HTTP {response.status_code} with a non-JSON body:\n{response.text[:500]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
