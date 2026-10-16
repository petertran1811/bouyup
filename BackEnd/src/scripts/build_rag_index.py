"""Download the embedding model and build the passage vectors of every law corpus (Chinese and
Vietnamese) once, so the first review does not wait. Uses BUOYUP_RAG_MODEL / BUOYUP_RAG_CACHE
like the app (the .env file is read too).

    cd BackEnd/src && ../.venv/bin/python scripts/build_rag_index.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import rag  # noqa: E402

ok = True
for j in rag.available():
    t = time.time()
    ix = rag.index(j)
    ready = ix.dense_ready()
    ok &= ready
    print(f"{j}: passages={len(ix.passages)} model={rag.MODEL} dense={ready} seconds={time.time() - t:.0f}")
sys.exit(0 if ok else 1)
