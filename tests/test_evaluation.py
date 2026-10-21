from issue2proof.evaluate import summarize


def test_evaluation_flags_unsupported_acceptance():
    report = {
        "case": "repair",
        "verdict": "verified",
        "attempts": [
            {
                "accepted": True,
                "protected_tests_intact": True,
                "regression": {"exit_code": 0},
                "existing": {"exit_code": 0},
                "independent": {"exit_code": 1},
            }
        ],
    }
    result = summarize([report])
    assert result["unsupported_candidate_acceptances"] == 1
    assert not result["passed"]


def test_evaluation_flags_wrong_verdict():
    result = summarize([{"case": "unresolved", "verdict": "verified", "attempts": []}])
    assert result["expected_verdicts_matched"] == 0
    assert not result["passed"]
