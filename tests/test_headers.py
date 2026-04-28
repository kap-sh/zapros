import pytest

from zapros._headers import Connection, HeaderParseError


class TestConnection:
    def test_normalizes_case_and_dedupes(self):
        c = Connection(("Close", "CLOSE", "Upgrade"))
        assert c.options == ("close", "upgrade")  # lowercased, deduped, order kept

    def test_invalid_token_raises_value_error(self):
        with pytest.raises(ValueError):
            Connection(("close upgrade",))

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("close", ("close",)),
            ("Close, Keep-Alive", ("close", "keep-alive")),
            ("close,keep-alive", ("close", "keep-alive")),  # OWS optional
            ("  close  ,  upgrade  ", ("close", "upgrade")),  # OWS tolerated
            (",,close,,", ("close",)),  # empty elements tolerated
            ("", ()),
        ],
    )
    def test_parse_valid(self, raw, expected):
        assert Connection.parse(raw).options == expected

    @pytest.mark.parametrize("bad", ["close upgrade", "close;upgrade", '"close"'])
    def test_parse_invalid(self, bad):
        with pytest.raises(HeaderParseError):
            Connection.parse(bad)

    def test_round_trip(self):
        c = Connection.parse("  CLOSE ,Upgrade  ")
        assert c.serialize() == "close, upgrade"
        assert Connection.parse(c.serialize()) == c

    def test_predicates(self):
        c = Connection.parse("Close, Upgrade, HTTP2-Settings")
        assert c.has("close") and not c.has("keep-alive")
        assert c.has("UPGRADE") and not c.has("te")

    def test_factories(self):
        assert Connection.keepalive().serialize() == "keep-alive"

    def test_from_field_lines(self):
        line1 = "close"
        line2 = "Upgrade"
        c = Connection.from_field_lines([line1, line2])
        assert c.options == ("close", "upgrade")
