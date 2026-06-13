#!/usr/bin/env python
"""Refresh the 60-day Instagram-Login access token.

Reads INSTAGRAM_ACCESS_TOKEN from .env, calls the refresh endpoint, and prints
the new token + expiry. The token must be at least 24h old to refresh.

Usage:
    python scripts/refresh_ig_token.py            # print new token (paste into .env)
    python scripts/refresh_ig_token.py --write    # rewrite the line in .env in place

Run monthly (e.g. cron) well before the ~60-day expiry.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.tools.meta_graph import MetaError, refresh_long_lived_token

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _rewrite_env(new_token: str) -> bool:
    if not _ENV_PATH.exists():
        return False
    lines = _ENV_PATH.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("INSTAGRAM_ACCESS_TOKEN="):
            lines[i] = f"INSTAGRAM_ACCESS_TOKEN={new_token}"
            updated = True
            break
    if updated:
        _ENV_PATH.write_text("\n".join(lines) + "\n")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite INSTAGRAM_ACCESS_TOKEN in .env")
    args = parser.parse_args()

    load_dotenv(_ENV_PATH)
    result = refresh_long_lived_token()

    if isinstance(result, MetaError):
        print(f"Refresh failed [{result.code}]: {result.message}", file=sys.stderr)
        print(f"  recovery: {result.recovery}", file=sys.stderr)
        return 1

    days = result.expires_in // 86400
    print(f"New token valid ~{days} days.")
    if args.write:
        if _rewrite_env(result.access_token):
            print(f"Updated INSTAGRAM_ACCESS_TOKEN in {_ENV_PATH}")
        else:
            print("Could not find INSTAGRAM_ACCESS_TOKEN line in .env; not modified.", file=sys.stderr)
            print(result.access_token)
    else:
        print("\nPaste into .env:")
        print(f"INSTAGRAM_ACCESS_TOKEN={result.access_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
