#!/usr/bin/env python3
"""Mock weather tool returning random tokens for verification."""

import json
import sys
import uuid
from pathlib import Path

TOKEN_FILE = Path(__file__).with_name('.last_call')


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print(json.dumps({"error": "city required"}))
        sys.exit(1)

    city = sys.argv[1].strip()
    token = str(uuid.uuid4())
    TOKEN_FILE.write_text(token, encoding='utf-8')

    payload = {
        "city": city,
        "token": token,
        "temperature_c": 21,
        "condition": "clear",
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
