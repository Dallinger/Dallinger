"""Private docker-ssh hibernation controller."""

from __future__ import annotations

import json
import os
import sys


def main():
    from dallinger.hibernation import client_request, serve_from_env

    secret = os.environ.get("HIBERNATION_SECRET", "")
    if len(sys.argv) > 1 and sys.argv[1] == "client":
        action = sys.argv[2] if len(sys.argv) > 2 else "state"
        payload = client_request(action, secret)
        print(json.dumps(payload))
        return

    serve_from_env()


if __name__ == "__main__":
    main()
