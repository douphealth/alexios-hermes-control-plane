from alexios_hermes_control_plane.services.verifier_normalization import normalize_verifier_value


def test_normalizes_bare_verdict_list() -> None:
    value = [
        {
            "findingId": "f1",
            "verification": "verified",
            "rationale": "e1 directly supports the claim",
        }
    ]
    assert normalize_verifier_value(value) == {
        "verdicts": [
            {
                "finding_id": "f1",
                "verdict": "GROUNDED",
                "reason": "e1 directly supports the claim",
            }
        ]
    }


def test_normalizes_results_wrapper_and_aliases() -> None:
    value = {
        "results": [
            {
                "id": "f2",
                "status": "partially_supported",
                "explanation": "only part is evidenced",
            },
            {
                "finding_id": "f3",
                "status": "unsupported",
                "reason": "evidence does not support it",
            },
        ]
    }
    assert normalize_verifier_value(value) == {
        "verdicts": [
            {
                "finding_id": "f2",
                "verdict": "PARTIAL",
                "reason": "only part is evidenced",
            },
            {
                "finding_id": "f3",
                "verdict": "UNGROUNDED",
                "reason": "evidence does not support it",
            },
        ]
    }


def test_unknown_verdict_is_not_upgraded() -> None:
    value = {"results": [{"id": "f4", "status": "probably", "reason": "uncertain"}]}
    assert normalize_verifier_value(value) is value
