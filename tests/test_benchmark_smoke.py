"""End-to-end smoke: heuristic mode must find most planted bugs."""
from benchmarks.run_benchmark import run

def test_heuristic_benchmark_finds_at_least_10_of_12():
    summary = run(mode="heuristic", max_steps=40, out_dir="benchmarks/results-ci")
    assert summary["planted"] == 12
    assert len(summary["true_positives"]) >= 10
    assert summary["precision"] >= 0.8
