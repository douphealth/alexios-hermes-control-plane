from alexios_hermes_control_plane.prompts import (
    ALL_ROLES,
    PROMPT_VERSION,
    ROLE_PROMPTS,
    SPECIALIST_ROLES,
)


def test_all_roles_have_prompts() -> None:
    for role in ALL_ROLES:
        assert role in ROLE_PROMPTS
        assert len(ROLE_PROMPTS[role]) > 400, f"prompt for {role} looks too thin"


def test_specialist_and_verifier_roles_exist() -> None:
    assert SPECIALIST_ROLES == ("diagnostician", "strategist", "chief_of_staff")
    assert "verifier" in ALL_ROLES
    assert "judge" in ALL_ROLES


def test_every_prompt_carries_the_read_only_contract() -> None:
    for role, prompt in ROLE_PROMPTS.items():
        assert "READ-ONLY" in prompt, f"{role} missing read-only contract"
        assert "NEEDS_DATA" in prompt, f"{role} missing NEEDS_DATA escape hatch"
        assert "evidence" in prompt.lower(), f"{role} missing evidence discipline"


def test_verifier_prompt_is_restricted_to_verification() -> None:
    verifier = ROLE_PROMPTS["verifier"]
    assert "GROUNDED" in verifier
    assert "UNGROUNDED" in verifier
    assert "never propose" in verifier


def test_prompt_version_bumped() -> None:
    assert PROMPT_VERSION == "2026-09-02.2"
