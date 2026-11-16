from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.scanner import scan


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python backend/scripts/scan_cli.py <url>", file=sys.stderr)
        return 2
    result = asyncio.run(scan(sys.argv[1]))
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
