import json

from harnessforge.eval.select import classify, high_signal_set


def write_results(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for task, passes in rows.items():
            for i, p in enumerate(passes):
                f.write(json.dumps({"task_id": task, "repeat": i, "passed": p,
                                    "exit_reason": "max_steps"}) + "\n")


def test_classify_buckets(tmp_path):
    rp = tmp_path / "results.jsonl"
    write_results(rp, {"a": [True, True], "b": [False, False], "c": [True, False]})
    tc = classify(rp)
    assert tc.always_pass == ["a"]
    assert tc.always_fail == ["b"]
    assert tc.borderline == ["c"]


def test_classify_excludes_infra_errors(tmp_path):
    rp = tmp_path / "results.jsonl"
    with rp.open("w") as f:
        f.write(json.dumps({"task_id": "a", "passed": False, "exit_reason": "infra_error"}) + "\n")
        f.write(json.dumps({"task_id": "a", "passed": True, "exit_reason": "max_steps"}) + "\n")
    tc = classify(rp)
    assert tc.always_pass == ["a"]  # the infra_error run is ignored


def test_high_signal_set_focuses_on_movable_tasks(tmp_path):
    rp = tmp_path / "results.jsonl"
    write_results(rp, {
        "always1": [True, True], "always2": [True, True], "always3": [True, True],
        "always4": [True, True],
        "flaky": [True, False],
        "crack-7z-hash": [False, False],        # harness-fixable failure
        "mteb-leaderboard": [False, False],     # capability-limited: must be excluded
    })
    hs = high_signal_set(rp, n_regression_guards=2)
    assert "flaky" in hs["targets"]
    assert "crack-7z-hash" in hs["targets"]
    assert "mteb-leaderboard" not in hs["targets"]     # dropped as capability-limited
    assert len(hs["regression_guards"]) == 2
    assert set(hs["all"]) == set(hs["targets"]) | set(hs["regression_guards"])
