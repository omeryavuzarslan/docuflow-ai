from eval.runners.discrepancy_eval import run_truth, score


def test_score_counts_hits_false_alarms_and_misses() -> None:
    truth = {("a", "vat_error"), ("b", "total_error")}
    predicted = [("a", "vat_error"), ("a", "vat_error"), ("c", "total_error")]
    result = score(truth, predicted)
    assert result["true_positives"] == 1
    assert result["missed"] == [["b", "total_error"]]
    # The repeated finding and the wrong document are both false alarms.
    assert sorted(map(tuple, result["false_positives"])) == [
        ("a", "vat_error"),
        ("c", "total_error"),
    ]
    assert result["precision"] == round(1 / 3, 4)
    assert result["recall"] == 0.5
    assert result["per_type"]["total_error"] == {
        "injected": 1,
        "found": 0,
        "false_alarms": 1,
        "recall": 0.0,
        "precision": 0.0,
    }


def test_truth_mode_on_generated_sets_is_perfect() -> None:
    result = run_truth(seed=3, n_sets=22)
    assert (result["precision"], result["recall"]) == (1.0, 1.0)
    assert result["false_alarms_on_clean_sets"] == 0
