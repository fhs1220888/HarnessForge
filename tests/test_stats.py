from harnessforge.eval.stats import (
    paired_bootstrap_continuous,
    paired_bootstrap_delta,
    suite_hash,
    wilson_interval,
)


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(5, 10)
    assert 0 <= lo < 0.5 < hi <= 1
    assert wilson_interval(0, 0) == (0.0, 0.0)
    # all successes -> upper bound at 1, lower bound below 1
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and lo < 1.0


def test_bootstrap_zero_delta_ci_contains_zero():
    same = {f"t{i}": [True, False] for i in range(8)}
    res = paired_bootstrap_delta(same, same, n_boot=2000, seed=1)
    assert res["mean_delta"] == 0.0
    assert res["ci_low"] <= 0 <= res["ci_high"]


def test_bootstrap_clear_improvement_positive_ci():
    before = {f"t{i}": [False, False, False] for i in range(10)}
    after = {f"t{i}": [True, True, True] for i in range(10)}
    res = paired_bootstrap_delta(before, after, n_boot=2000, seed=1)
    assert res["mean_delta"] == 1.0
    assert res["ci_low"] > 0.5  # unambiguously positive


def test_bootstrap_noisy_small_effect_ci_crosses_zero():
    # one task improves, one regresses, rest flat -> effect indistinguishable from 0
    before = {"a": [False], "b": [True], "c": [True], "d": [False]}
    after = {"a": [True], "b": [False], "c": [True], "d": [False]}
    res = paired_bootstrap_delta(before, after, n_boot=3000, seed=2)
    assert res["ci_low"] < 0 < res["ci_high"]


def test_continuous_clear_reduction_is_significant():
    # every task drops from ~25 steps to ~18 -> unambiguous negative delta
    before = {f"t{i}": [25, 24, 26] for i in range(8)}
    after = {f"t{i}": [18, 17, 19] for i in range(8)}
    r = paired_bootstrap_continuous(before, after, n_boot=3000, seed=1)
    assert r["mean_delta"] < 0
    assert r["ci_high"] < 0            # CI entirely below zero
    assert r["pct_change"] < 0


def test_continuous_reports_pct_change():
    before = {"a": [10.0], "b": [10.0]}
    after = {"a": [8.0], "b": [8.0]}
    r = paired_bootstrap_continuous(before, after, n_boot=1000, seed=0)
    assert r["pct_change"] == -20.0


def test_suite_hash_order_invariant():
    assert suite_hash(["a", "b", "c"]) == suite_hash(["c", "a", "b"])
    assert suite_hash(["a", "b"]) != suite_hash(["a", "b", "c"])
