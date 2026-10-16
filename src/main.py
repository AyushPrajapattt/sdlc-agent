"""Vercel entrypoint: exposes the FastAPI `app` (Vercel looks for src/main.py with an `app` instance).

`src/` ships inside the function bundle, so it is put on the path rather than relying on the project being pip-installed.
On Vercel the API defaults to HACKFRONT_STATE=neo4j and HACKFRONT_SYNC=inline (see state.py and ingest/sync.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hackfront.api import app  # noqa: E402,F401
