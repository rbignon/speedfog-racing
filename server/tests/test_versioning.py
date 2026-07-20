"""Tests for version parsing and mod compatibility decisions."""

from speedfog_racing.versioning import ModCompat, evaluate_mod_compat, parse_version


class TestParseVersion:
    def test_release(self):
        assert parse_version("1.17.0") == (1, 17, 0)

    def test_protocol_two_segments(self):
        assert parse_version("1.0") == (1, 0)

    def test_none(self):
        assert parse_version(None) is None

    def test_empty(self):
        assert parse_version("") is None

    def test_garbage(self):
        assert parse_version("abc") is None

    def test_trailing_non_numeric_ignored(self):
        assert parse_version("1.2.0-rc1") == (1, 2)

    def test_whitespace(self):
        assert parse_version(" 1.2.3 ") == (1, 2, 3)


class TestEvaluateModCompat:
    def test_absent_protocol_assumed_1_0(self):
        compat = evaluate_mod_compat(
            None, None, server_protocol="1.0", server_release="1.19.0", min_release=None
        )
        assert compat == ModCompat(reject_reason=None, update_available=False)

    def test_same_protocol_no_notice(self):
        compat = evaluate_mod_compat(
            "1.0", "1.17.0", server_protocol="1.0", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is None
        assert compat.update_available is False

    def test_older_minor_notice(self):
        compat = evaluate_mod_compat(
            "1.0", "1.17.0", server_protocol="1.2", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is None
        assert compat.update_available is True

    def test_newer_minor_no_notice(self):
        compat = evaluate_mod_compat(
            "1.3", "1.17.0", server_protocol="1.2", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is None
        assert compat.update_available is False

    def test_same_release_suppresses_notice_despite_older_minor(self):
        # A deploy that only bumps PROTOCOL_VERSION while the release stays
        # put (e.g. both sides on 1.19.0) must not claim an update exists.
        compat = evaluate_mod_compat(
            "1.0", "1.19.0", server_protocol="1.2", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is None
        assert compat.update_available is False

    def test_missing_release_with_older_minor_still_notifies(self):
        # Pre-versioning mods that omit their release can never "match" the
        # server release, so they keep getting the notice.
        compat = evaluate_mod_compat(
            "1.0", None, server_protocol="1.2", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is None
        assert compat.update_available is True

    def test_older_major_rejected(self):
        compat = evaluate_mod_compat(
            "1.0", None, server_protocol="2.0", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is not None
        assert "not compatible" in compat.reject_reason
        assert compat.update_available is False

    def test_newer_major_rejected(self):
        compat = evaluate_mod_compat(
            "3.0", None, server_protocol="2.0", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is not None

    def test_absent_protocol_rejected_after_major_bump(self):
        # Pre-versioning mods (assumed 1.0) get rejected once the server goes 2.x.
        compat = evaluate_mod_compat(
            None, None, server_protocol="2.0", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is not None

    def test_unparsable_protocol_assumed_1_0(self):
        compat = evaluate_mod_compat(
            "garbage", None, server_protocol="1.0", server_release="1.19.0", min_release=None
        )
        assert compat.reject_reason is None

    def test_min_release_gate_rejects_older(self):
        compat = evaluate_mod_compat(
            "1.0",
            "1.17.0",
            server_protocol="1.0",
            server_release="1.19.0",
            min_release="1.18.0",
        )
        assert compat.reject_reason is not None
        assert "no longer supported" in compat.reject_reason

    def test_min_release_gate_rejects_absent(self):
        compat = evaluate_mod_compat(
            "1.0", None, server_protocol="1.0", server_release="1.19.0", min_release="1.18.0"
        )
        assert compat.reject_reason is not None

    def test_min_release_gate_accepts_equal(self):
        compat = evaluate_mod_compat(
            "1.0",
            "1.18.0",
            server_protocol="1.0",
            server_release="1.19.0",
            min_release="1.18.0",
        )
        assert compat.reject_reason is None

    def test_min_release_gate_unparsable_disables_gate_with_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            compat = evaluate_mod_compat(
                "1.0",
                "0.0.1",
                server_protocol="1.0",
                server_release="1.19.0",
                min_release="v1.18.0",
            )
        assert compat.reject_reason is None
        assert "min_mod_version" in caplog.text

    def test_protocol_reject_wins_over_min_release(self):
        compat = evaluate_mod_compat(
            "2.0",
            "1.0.0",
            server_protocol="1.0",
            server_release="1.19.0",
            min_release="1.18.0",
        )
        assert "not compatible" in (compat.reject_reason or "")
