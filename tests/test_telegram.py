from alexios_hermes_control_plane.services.telegram import parse_portfolio_command


def test_parse_portfolio_command() -> None:
    assert parse_portfolio_command("hello") is None
    assert parse_portfolio_command("/portfolio audit revenue pages") == "audit revenue pages"
    assert parse_portfolio_command("/portfolio") is not None
