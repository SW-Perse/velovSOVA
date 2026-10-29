"""Integration checks for the local Compose MLflow stack.

Run with:
    pytest tests/test_mlflow_stack.py -m integration
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
EVIDENCE_PATH = PROJECT_ROOT / "evidence" / "mlflow-local-stack.txt"
MLFLOW_URL = os.getenv("MLFLOW_TEST_URL", "http://localhost:5000")


def _run(*command: str) -> str:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _http_json(method: str, path: str, body: dict | None = None) -> dict:
    request = Request(
        f"{MLFLOW_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with urlopen(request, timeout=15) as response:
        assert response.status == 200
        return json.load(response)


def _metadata_counts() -> str:
    return _run(
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        'psql -U "$POSTGRES_USER" -d mlflow -At -F "|" -c "select '
        "(select count(*) from experiments), "
        "(select count(*) from runs), "
        "(select count(*) from registered_models), "
        '(select count(*) from model_versions);"',
    )


@pytest.mark.integration
def test_local_mlflow_stack_and_persistence() -> None:
    """Verify Compose, MLflow, PostgreSQL, secrets, and restart persistence."""
    evidence: list[str] = ["MLflow local stack verification"]
    evidence.append(f"MLflow URL: {MLFLOW_URL}")

    assert (PROJECT_ROOT / ".env").exists(), ".env is required for local Compose"
    ignored = subprocess.run(
        ("git", "check-ignore", "-q", ".env"),
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert ignored.returncode == 0, ".env must be ignored by Git"
    tracked = subprocess.run(
        ("git", "ls-files", "--error-unmatch", ".env"),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tracked.returncode != 0, ".env must not be tracked by Git"

    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "velov_password" not in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}" in compose
    evidence.append("Secret configuration: PASS")

    _run("docker", "compose", "config", "--quiet")
    evidence.append("Compose interpolation: PASS")

    status = _run("docker", "compose", "ps")
    evidence.append(status)
    assert "velov-db" in status
    assert "velov-mlflow" in status
    assert "velov-api" in status
    assert _run("docker", "inspect", "-f", "{{.State.Health.Status}}", "velov-db") == "healthy"
    assert _run("docker", "inspect", "-f", "{{.State.ExitCode}}", "velov-mlflow-db-create") == "0"
    assert _run("docker", "inspect", "-f", "{{.State.ExitCode}}", "velov-mlflow-db-init") == "0"
    evidence.append("Container and initialization status: PASS")

    assert _http_json("POST", "/api/2.0/mlflow/experiments/search", {"max_results": 100}) is not None
    with urlopen(f"{MLFLOW_URL}/version", timeout=15) as response:
        assert response.status == 200
    evidence.append("MLflow HTTP endpoints: PASS")

    _run(
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
    )
    _run(
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Atc "
        "\"SELECT 1 FROM pg_database WHERE datname = 'mlflow';\"",
    )
    evidence.append("PostgreSQL and MLflow database: PASS")

    before = _metadata_counts()
    _run("docker", "compose", "restart", "mlflow")
    deadline = time.monotonic() + 60
    while True:
        try:
            with urlopen(f"{MLFLOW_URL}/version", timeout=5) as response:
                if response.status == 200:
                    break
        except (HTTPError, RemoteDisconnected, URLError, OSError):
            if time.monotonic() >= deadline:
                pytest.fail("MLflow did not recover within 60 seconds after restart")
        time.sleep(2)
    after = _metadata_counts()
    assert before == after
    evidence.append(f"Metadata counts before restart: {before}")
    evidence.append(f"Metadata counts after restart: {after}")
    evidence.append("MLflow restart persistence: PASS")
    evidence.append("OVERALL: PASS")
    EVIDENCE_PATH.write_text("\n".join(evidence) + "\n", encoding="utf-8")
