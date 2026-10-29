from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from velov.promote import (
    EvaluationWindow,
    ModelEvaluation,
    PromotionDecision,
    decide,
    main,
    record_promotion_audit,
)
from velov.registry import register_run_as_challenger

WINDOW = EvaluationWindow("2026-10-04T21:00:00+00:00", "2026-10-18T20:00:00+00:00")


def evaluation(
    version: str,
    mae: float,
    baseline: float = 1.9,
    window: EvaluationWindow = WINDOW,
) -> ModelEvaluation:
    return ModelEvaluation(version, f"run-{version}", mae, baseline, window)


def test_promotes_when_all_three_conditions_pass() -> None:
    result = decide(evaluation("2", 1.4), evaluation("1", 1.5))

    assert result.promote
    assert result.reason == "MAE 1.400 <= 1.470 (champion - 2%)"


def test_rejects_when_challenger_does_not_beat_persistence() -> None:
    result = decide(evaluation("2", 1.9, baseline=1.9), evaluation("1", 2.0))

    assert not result.promote
    assert result.reason == "ne bat pas la persistance"


def test_rejects_when_evaluation_windows_differ() -> None:
    other_window = EvaluationWindow("2026-10-05T21:00:00+00:00", WINDOW.end)
    result = decide(evaluation("2", 1.2, window=other_window), evaluation("1", 1.5))

    assert not result.promote
    assert result.reason == "fenêtres d'évaluation différentes"


def test_rejects_when_challenger_gain_is_below_two_percent() -> None:
    result = decide(evaluation("2", 1.48), evaluation("1", 1.5))

    assert not result.promote
    assert result.reason == "MAE 1.480 > 1.470 (champion - 2%)"


def test_promotes_exact_two_percent_boundary() -> None:
    result = decide(evaluation("2", 1.47), evaluation("1", 1.5))

    assert result.promote


def test_promotes_first_champion_after_persistence_check() -> None:
    result = decide(evaluation("1", 1.4), champion=None)

    assert result == PromotionDecision(True, "premier champion")


@pytest.mark.parametrize("value", [-0.1, float("inf"), float("nan")])
def test_rejects_invalid_challenger_metrics(value: float) -> None:
    with pytest.raises(ValueError, match="mae_model"):
        decide(evaluation("2", value), champion=None)


class FakeMlflowClient:
    def __init__(self, challenger: ModelEvaluation, champion: ModelEvaluation | None = None):
        self.versions = {
            "challenger": SimpleNamespace(version=challenger.model_version, run_id=challenger.run_id),
        }
        if champion:
            self.versions["champion"] = SimpleNamespace(version=champion.model_version, run_id=champion.run_id)
        self.runs = {
            challenger.run_id: SimpleNamespace(
                data=SimpleNamespace(
                    metrics={
                        "mae_model": challenger.mae_model,
                        "mae_baseline_persistence": challenger.mae_baseline_persistence,
                    },
                    tags={
                        "evaluation_period_start": challenger.evaluation_window.start,
                        "evaluation_period_end": challenger.evaluation_window.end,
                    },
                )
            )
        }
        if champion:
            self.runs[champion.run_id] = SimpleNamespace(
                data=SimpleNamespace(
                    metrics={"mae_model": champion.mae_model, "mae_baseline_persistence": 1.9},
                    tags={
                        "evaluation_period_start": champion.evaluation_window.start,
                        "evaluation_period_end": champion.evaluation_window.end,
                    },
                )
            )
        self.alias_changes: list[tuple[str, str]] = []
        self.tags: dict[tuple[str, str], str] = {}

    def get_model_version_by_alias(self, _name: str, alias: str):
        if alias not in self.versions:
            from mlflow.exceptions import MlflowException

            raise MlflowException("alias champion not found", error_code="INVALID_PARAMETER_VALUE")
        return self.versions[alias]

    def get_run(self, run_id: str):
        return self.runs[run_id]

    def set_registered_model_alias(self, _name: str, alias: str, version: str):
        self.alias_changes.append((alias, version))
        self.versions[alias] = SimpleNamespace(version=version, run_id=self.versions["challenger"].run_id)

    def set_tag(self, run_id: str, key: str, value: str):
        self.tags[(run_id, key)] = value

    def get_registered_model(self, _name: str):
        return SimpleNamespace(name="velov-availability")

    def create_model_version(self, name: str, source: str, run_id: str):
        return SimpleNamespace(name=name, source=source, run_id=run_id, version="3")


def test_mlflow_aliases_point_to_expected_registered_versions() -> None:
    client = FakeMlflowClient(evaluation("2", 1.4))

    registered = register_run_as_challenger("run-new", client=client)

    assert registered.version == "3"
    assert client.alias_changes == [("challenger", "3")]


def test_audit_tags_record_promotion_context() -> None:
    challenger = evaluation("2", 1.4)
    champion = evaluation("1", 1.5)
    client = FakeMlflowClient(challenger, champion)

    record_promotion_audit(client, challenger, champion, decide(challenger, champion), applied=True)

    assert client.tags[(challenger.run_id, "promotion_decision")] == "promoted"
    assert client.tags[(challenger.run_id, "promotion_previous_champion")] == "1"
    assert client.tags[(challenger.run_id, "promotion_rule_version")] == "1"


def test_default_command_does_not_change_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    challenger = evaluation("2", 1.4)
    client = FakeMlflowClient(challenger)
    monkeypatch.setattr("velov.promote.MlflowClient", lambda: client)
    monkeypatch.setattr(sys, "argv", ["velov.promote"])

    main()

    assert client.alias_changes == []
    assert client.tags[(challenger.run_id, "promotion_decision")] == "eligible"


def test_apply_changes_champion_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    challenger = evaluation("2", 1.4)
    client = FakeMlflowClient(challenger)
    monkeypatch.setattr("velov.promote.MlflowClient", lambda: client)
    monkeypatch.setattr(sys, "argv", ["velov.promote", "--apply"])

    main()

    assert client.alias_changes == [("champion", "2")]
    assert client.tags[(challenger.run_id, "promotion_decision")] == "promoted"
