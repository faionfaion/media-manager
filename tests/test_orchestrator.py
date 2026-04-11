"""Tests for orchestrator: cron matching, dedup, lock files."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.orchestrator.runner import _cron_matches, _field_matches


class TestCronMatching:
    """Verify cron expression matching for all pipeline schedules."""

    # NeroMedia: generate hourly 7-19 UTC
    def test_neromedia_generate_in_range(self):
        assert _cron_matches("0 7-19 * * *", 10, 0)

    def test_neromedia_generate_before_range(self):
        assert not _cron_matches("0 7-19 * * *", 6, 0)

    def test_neromedia_generate_after_range(self):
        assert not _cron_matches("0 7-19 * * *", 20, 0)

    def test_neromedia_generate_wrong_minute(self):
        assert not _cron_matches("0 7-19 * * *", 10, 5)

    def test_neromedia_generate_boundary_start(self):
        assert _cron_matches("0 7-19 * * *", 7, 0)

    def test_neromedia_generate_boundary_end(self):
        assert _cron_matches("0 7-19 * * *", 19, 0)

    # Pashtelka: publish at 8,11,14,17:05
    def test_pashtelka_publish_match(self):
        assert _cron_matches("5 8,11,14,17 * * *", 11, 5)

    def test_pashtelka_publish_wrong_hour(self):
        assert not _cron_matches("5 8,11,14,17 * * *", 10, 5)

    def test_pashtelka_publish_wrong_minute(self):
        assert not _cron_matches("5 8,11,14,17 * * *", 11, 0)

    # Pashtelka: generate at 6:00
    def test_pashtelka_generate(self):
        assert _cron_matches("0 6 * * *", 6, 0)

    def test_pashtelka_generate_wrong(self):
        assert not _cron_matches("0 6 * * *", 7, 0)

    # LongLife: digest at 20:05
    def test_longlife_digest(self):
        assert _cron_matches("5 20 * * *", 20, 5)

    # Field matching edge cases
    def test_wildcard(self):
        assert _field_matches("*", 0)
        assert _field_matches("*", 59)

    def test_step(self):
        assert _field_matches("*/5", 0)
        assert _field_matches("*/5", 15)
        assert not _field_matches("*/5", 3)

    def test_range(self):
        assert _field_matches("7-19", 7)
        assert _field_matches("7-19", 13)
        assert _field_matches("7-19", 19)
        assert not _field_matches("7-19", 6)
        assert not _field_matches("7-19", 20)

    def test_list(self):
        assert _field_matches("8,11,14,17", 8)
        assert _field_matches("8,11,14,17", 17)
        assert not _field_matches("8,11,14,17", 9)

    def test_exact(self):
        assert _field_matches("5", 5)
        assert not _field_matches("5", 6)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
