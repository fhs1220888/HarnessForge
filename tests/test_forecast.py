import json

import pytest

from harnessforge.eval.forecast import beta_binomial_predictive, build_forecast


def test_v1_posterior_predictive_is_stable():
    result = beta_binomial_predictive(11, 16, 16)
    assert result["expected_passes"] == pytest.approx(10.8235)
    assert result["median_passes"] == 11
    assert result["central_95_passes"] == [5, 15]
    assert result["probability_at_least_8"] == pytest.approx(0.8951)


def test_forecast_is_explicitly_unscored():
    observed = json.loads(
        open("docs/data/tb_holdout_v1_verifier_scorecard.json", encoding="utf-8").read()
    )
    mechanism = json.loads(
        open("docs/data/budget_compaction_dev_pilot.json", encoding="utf-8").read()
    )
    forecast = build_forecast(observed, mechanism)
    assert forecast["status"] == "forecast_unscored"
    assert forecast["future_runs"] == 16
    assert forecast["controller_mechanism_observation"][
        "used_to_shift_pass_forecast"
    ] is False
    assert "holdout-v2 achieved a measured pass rate" in forecast["claims"]["forbidden"]


def test_forecast_refuses_scored_mechanism_disguised_as_partial():
    with pytest.raises(ValueError, match="explicitly unscored"):
        build_forecast(
            {"passed_runs": 11, "scored_runs": 16},
            {"status": "completed"},
        )
