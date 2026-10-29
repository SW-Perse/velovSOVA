"""MLflow Model Registry helpers for the Vélo'v model."""

from __future__ import annotations

import argparse

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from mlflow.utils.rest_utils import ErrorCode

REGISTERED_MODEL_NAME = "velov-availability"
CHALLENGER_ALIAS = "challenger"
CHAMPION_ALIAS = "champion"


def _is_missing_resource(error: MlflowException) -> bool:
    return error.error_code in {
        "RESOURCE_DOES_NOT_EXIST",
        ErrorCode.Value("RESOURCE_DOES_NOT_EXIST"),
    }


def ensure_registered_model(
    client: MlflowClient | None = None,
    name: str = REGISTERED_MODEL_NAME,
) -> None:
    """Create the registered model if it does not exist yet."""
    registry = client or MlflowClient()
    try:
        registry.get_registered_model(name)
    except MlflowException as error:
        if not _is_missing_resource(error):
            raise
        registry.create_registered_model(name)


def register_run(
    run_id: str,
    client: MlflowClient | None = None,
    name: str = REGISTERED_MODEL_NAME,
):
    """Register the signed model logged by a run and return its model version."""
    registry = client or MlflowClient()
    ensure_registered_model(registry, name)
    return registry.create_model_version(
        name=name,
        source=f"runs:/{run_id}/model",
        run_id=run_id,
    )


def set_alias(
    alias: str,
    version: str | int,
    client: MlflowClient | None = None,
    name: str = REGISTERED_MODEL_NAME,
) -> None:
    """Point a registry alias at a model version."""
    registry = client or MlflowClient()
    registry.set_registered_model_alias(name, alias, str(version))


def get_alias(
    alias: str,
    client: MlflowClient | None = None,
    name: str = REGISTERED_MODEL_NAME,
):
    """Return the model version targeted by an alias, or None if it is absent."""
    registry = client or MlflowClient()
    try:
        return registry.get_model_version_by_alias(name, alias)
    except MlflowException as error:
        if not _is_missing_resource(error):
            raise
        return None


def register_model_uri(
    run_id: str,
    name: str = REGISTERED_MODEL_NAME,
) -> str:
    """Register a run model through MLflow's active tracking and registry URIs."""
    result = mlflow.register_model(f"runs:/{run_id}/model", name)
    return str(result.version)


def register_run_as_challenger(
    run_id: str,
    client: MlflowClient | None = None,
    name: str = REGISTERED_MODEL_NAME,
):
    """Register a run and point the challenger alias at its new version."""
    model_version = register_run(run_id, client=client, name=name)
    set_alias(CHALLENGER_ALIAS, model_version.version, client=client, name=name)
    return model_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Enregistrer un run MLflow comme challenger.")
    parser.add_argument("--run-id", required=True, help="Identifiant du run contenant l'artefact model")
    parser.add_argument("--name", default=REGISTERED_MODEL_NAME)
    args = parser.parse_args()

    version = register_run_as_challenger(args.run_id, name=args.name)
    print(f"Challenger enregistré : {args.name} v{version.version} (run {args.run_id})")


if __name__ == "__main__":
    main()
