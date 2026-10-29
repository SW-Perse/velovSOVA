"""Pure promotion decision for registered Vélo'v models."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from math import isfinite

from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from mlflow.utils.rest_utils import ErrorCode

from velov.registry import (
    CHALLENGER_ALIAS,
    CHAMPION_ALIAS,
    REGISTERED_MODEL_NAME,
    _is_missing_resource,
    set_alias,
)

DEFAULT_MIN_GAIN = 0.02
PROMOTION_RULE_VERSION = "1"


@dataclass(frozen=True)
class EvaluationWindow:
    """The exact period on which a candidate's metrics were measured."""

    start: str
    end: str


@dataclass(frozen=True)
class ModelEvaluation:
    """Metrics and evaluation context needed by the promotion rule."""

    model_version: str
    run_id: str
    mae_model: float
    mae_baseline_persistence: float
    evaluation_window: EvaluationWindow


@dataclass(frozen=True)
class PromotionDecision:
    """Explainable result of evaluating a challenger against a champion."""

    promote: bool
    reason: str


def decide(
    challenger: ModelEvaluation,
    champion: ModelEvaluation | None,
    min_gain: float = DEFAULT_MIN_GAIN,
) -> PromotionDecision:
    """Apply the three-condition promotion rule without changing MLflow state."""
    if not 0 < min_gain < 1:
        raise ValueError("min_gain doit être strictement compris entre 0 et 1")
    for metric_name, value in (
        ("mae_model", challenger.mae_model),
        ("mae_baseline_persistence", challenger.mae_baseline_persistence),
    ):
        if not isfinite(value) or value < 0:
            raise ValueError(f"{metric_name} doit être un nombre fini positif ou nul")
    if champion is not None and (
        challenger.evaluation_window != champion.evaluation_window
    ):
        return PromotionDecision(False, "fenêtres d'évaluation différentes")
    if challenger.mae_model >= challenger.mae_baseline_persistence:
        return PromotionDecision(False, "ne bat pas la persistance")
    if champion is None:
        return PromotionDecision(True, "premier champion")
    if not isfinite(champion.mae_model) or champion.mae_model < 0:
        raise ValueError("champion.mae_model doit être un nombre fini positif ou nul")
    target = champion.mae_model * (1 - min_gain)
    if challenger.mae_model > target:
        return PromotionDecision(
            False,
            f"MAE {challenger.mae_model:.3f} > {target:.3f} (champion - {min_gain:.0%})",
        )
    return PromotionDecision(
        True,
        f"MAE {challenger.mae_model:.3f} <= {target:.3f} (champion - {min_gain:.0%})",
    )


def evaluation_from_version(client: MlflowClient, version) -> ModelEvaluation:
    """Build the promotion input from a registered model version's MLflow run."""
    run = client.get_run(version.run_id)
    metrics = run.data.metrics
    tags = run.data.tags
    required_metrics = ("mae_model", "mae_baseline_persistence")
    missing_metrics = [name for name in required_metrics if name not in metrics]
    required_tags = ("evaluation_period_start", "evaluation_period_end")
    missing_tags = [name for name in required_tags if name not in tags]
    if missing_metrics or missing_tags:
        missing = ", ".join(missing_metrics + missing_tags)
        raise ValueError(f"Le run {version.run_id} ne contient pas : {missing}")
    return ModelEvaluation(
        model_version=str(version.version),
        run_id=version.run_id,
        mae_model=float(metrics["mae_model"]),
        mae_baseline_persistence=float(metrics["mae_baseline_persistence"]),
        evaluation_window=EvaluationWindow(
            start=tags["evaluation_period_start"],
            end=tags["evaluation_period_end"],
        ),
    )


def evaluate_registered_models(
    client: MlflowClient,
    name: str = REGISTERED_MODEL_NAME,
    min_gain: float = DEFAULT_MIN_GAIN,
) -> tuple[ModelEvaluation, ModelEvaluation | None, PromotionDecision]:
    """Evaluate the challenger alias against the champion alias."""
    challenger_version = client.get_model_version_by_alias(name, CHALLENGER_ALIAS)
    champion_version = None
    try:
        champion_version = client.get_model_version_by_alias(name, CHAMPION_ALIAS)
    except MlflowException as error:
        if not (
            _is_missing_resource(error)
            or error.error_code
            in {"INVALID_PARAMETER_VALUE", ErrorCode.Value("INVALID_PARAMETER_VALUE")}
            or "alias" in str(error).lower() and "not found" in str(error).lower()
        ):
            raise
    challenger = evaluation_from_version(client, challenger_version)
    champion = evaluation_from_version(client, champion_version) if champion_version else None
    return challenger, champion, decide(challenger, champion, min_gain=min_gain)


def record_promotion_audit(
    client: MlflowClient,
    challenger: ModelEvaluation,
    champion: ModelEvaluation | None,
    decision: PromotionDecision,
    applied: bool,
) -> None:
    """Record the promotion decision on the challenger run."""
    if decision.promote and applied:
        outcome = "promoted"
    elif decision.promote:
        outcome = "eligible"
    else:
        outcome = "rejected"
    client.set_tag(challenger.run_id, "promotion_decision", outcome)
    client.set_tag(challenger.run_id, "promotion_reason", decision.reason)
    client.set_tag(
        challenger.run_id,
        "promotion_previous_champion",
        champion.model_version if champion else "none",
    )
    client.set_tag(challenger.run_id, "promotion_rule_version", PROMOTION_RULE_VERSION)


def main() -> None:
    parser = argparse.ArgumentParser(description="Décider de la promotion du challenger MLflow.")
    parser.add_argument("--apply", action="store_true", help="Appliquer la décision en déplaçant l'alias champion")
    parser.add_argument("--name", default=REGISTERED_MODEL_NAME)
    parser.add_argument("--min-gain", type=float, default=DEFAULT_MIN_GAIN)
    args = parser.parse_args()

    client = MlflowClient()
    challenger, champion, decision = evaluate_registered_models(
        client,
        name=args.name,
        min_gain=args.min_gain,
    )
    print(f"Challenger : v{challenger.model_version}, run {challenger.run_id}, MAE {challenger.mae_model:.3f}")
    if champion:
        print(f"Champion   : v{champion.model_version}, run {champion.run_id}, MAE {champion.mae_model:.3f}")
    else:
        print("Champion   : aucun (première promotion)")
    print(f"Fenêtre    : {challenger.evaluation_window.start} -> {challenger.evaluation_window.end}")
    print(f"Décision   : {'PROMOUVOIR' if decision.promote else 'REJETER'} ({decision.reason})")
    applied = decision.promote and args.apply
    record_promotion_audit(client, challenger, champion, decision, applied)
    if applied:
        set_alias(CHAMPION_ALIAS, challenger.model_version, client=client, name=args.name)
        print(f"Alias champion appliqué : v{challenger.model_version}")
    elif decision.promote:
        print("Aucune modification appliquée : relancer avec --apply pour promouvoir.")


if __name__ == "__main__":
    main()
