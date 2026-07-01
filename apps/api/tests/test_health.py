"""Health harness tests for the Aether API (P1-S00)."""
from app.health import get_health


def test_sanity_green():
    # GREEN: harness proven; assert a true statement.
    assert 1 + 1 == 2


def test_get_health_returns_ok():
    health = get_health("1.2.3")
    assert health["status"] == "ok"
    assert health["service"] == "api"
    assert health["version"] == "1.2.3"
