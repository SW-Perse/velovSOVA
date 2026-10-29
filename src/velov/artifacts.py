"""Utilitaires partagés pour les artefacts du modèle."""

from __future__ import annotations

import hashlib
from pathlib import Path

MODEL_FILENAME = "model.joblib"
METADATA_FILENAME = "metadata.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
