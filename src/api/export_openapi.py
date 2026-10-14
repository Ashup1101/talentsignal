"""Write web/openapi.json: the API's OpenAPI description, the source of the frontend's types.

After changing an endpoint or src/api/schemas.py, regenerate both:

    python -m src.api.export_openapi      # this file
    (cd web && npm run gen:api)           # web/src/lib/api-types.ts

tests/test_api_routes.py fails while the committed web/openapi.json is out of date.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.api.main import app

OUTPUT = Path(__file__).resolve().parents[2] / "web" / "openapi.json"


def render() -> str:
    """The API's OpenAPI document as stable, diff-friendly JSON.

    Returns:
        JSON text (sorted keys, 2-space indent, trailing newline).
    """
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    """Write web/openapi.json.

    Returns:
        Process exit code.
    """
    OUTPUT.write_text(render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
