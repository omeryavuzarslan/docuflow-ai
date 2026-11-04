"""Write the API's OpenAPI schema to a file, for generating the frontend's TypeScript types.

uv run python -m backend.app.api.export_openapi frontend/src/api/openapi.json
"""

import json
import sys
from pathlib import Path

from backend.app.api.main import app


def main() -> int:
    out = Path(sys.argv[1])
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
