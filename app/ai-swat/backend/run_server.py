"""Run the FastAPI server: uvicorn from the backend directory."""
import os
import sys

# Windows: force UTF-8 for stdout/stderr and Python 3.7+ UTF-8 mode
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
