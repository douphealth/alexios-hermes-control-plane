from alexios_hermes_control_plane.activities.implementation import (
    _deterministic_mutation_id,
    _is_noop,
)
from alexios_hermes_control_plane.schemas.execution import (
    MutationType,
    WordPressMutation,
    WordPressSnapshot,
)


def _snapshot() -> WordPressSnapshot:
    return WordPressSnapshot(
        site_id="example.com",
        post_id=42,
        post_type="posts",
        url="https://example.com/post/",
        slug="post",
        status="publish",
        title_raw="Existing title",
        content_raw="<p>Existing content</p>",
    )


def _mutation(value: str, mutation_id: str = "provider-generated") -> WordPressMutation:
    return WordPressMutation(
        mutation_id=mutation_id,
        site_id="example.com",
        target_url="https://example.com/post/",
        post_id=42,
        mutation_type=MutationType.TITLE,
        value=value,
        reason="Evidence-backed title improvement",
        evidence_ids=["e1"],
    )


def test_deterministic_mutation_id_ignores_provider_generated_id() -> None:
    first = _mutation("Better title", "random-a")
    second = _mutation("Better title", "random-b")
    assert _deterministic_mutation_id(first) == _deterministic_mutation_id(second)


def test_deterministic_mutation_id_changes_with_value() -> None:
    assert _deterministic_mutation_id(_mutation("Title A")) != _deterministic_mutation_id(
        _mutation("Title B")
    )


def test_noop_title_is_filtered() -> None:
    assert _is_noop(_mutation(" Existing title "), _snapshot()) is True
    assert _is_noop(_mutation("Improved title"), _snapshot()) is False
