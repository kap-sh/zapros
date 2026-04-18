import re
from dataclasses import dataclass
from typing import ClassVar

from zapros._errors import HeaderParseError

# RFC 9110 tchar: !#$%&'*+-.^_`|~ DIGIT ALPHA
_TCHAR = r"!#$%&'*+\-.^_`|~0-9A-Za-z"
_TOKEN_RE = re.compile(rf"[{_TCHAR}]+")
_NOT_TOKEN_RE = re.compile(rf"[^{_TCHAR}]")


def quote_if_needed(s: str) -> str:
    """Quote a parameter value if it's not a valid token."""
    if s and not _NOT_TOKEN_RE.search(s):
        return s
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class Tokenizer:
    """Tiny cursor-based parser for RFC 9110 media-type grammar."""

    __slots__ = ("text", "pos")

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def eof(self) -> bool:
        return self.pos >= len(self.text)

    def skip_ows(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def expect(self, ch: str) -> None:
        if self.peek() != ch:
            raise HeaderParseError(f"Expected {ch!r} at position {self.pos} in {self.text!r}")
        self.pos += 1

    def read_token(self) -> str:
        m = _TOKEN_RE.match(self.text, self.pos)
        if not m:
            raise HeaderParseError(f"Expected token at position {self.pos} in {self.text!r}")
        self.pos = m.end()
        return m.group(0)

    def read_quoted_string(self) -> str:
        self.expect('"')
        out: list[str] = []
        while self.pos < len(self.text):
            c = self.text[self.pos]
            if c == "\\":
                if self.pos + 1 >= len(self.text):
                    raise HeaderParseError("Unterminated escape in quoted-string")
                out.append(self.text[self.pos + 1])
                self.pos += 2
            elif c == '"':
                self.pos += 1
                return "".join(out)
            else:
                out.append(c)
                self.pos += 1
        raise HeaderParseError("Unterminated quoted-string")


@dataclass(frozen=True, slots=True)
class ContentType:
    name: ClassVar[str] = "Content-Type"

    type: str
    subtype: str
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        # type/subtype are case-insensitive — normalize for equality/hashing
        object.__setattr__(self, "type", self.type.lower())
        object.__setattr__(self, "subtype", self.subtype.lower())

        if not _TOKEN_RE.fullmatch(self.type):
            raise ValueError(f"Invalid type: {self.type!r}")
        if not _TOKEN_RE.fullmatch(self.subtype):
            raise ValueError(f"Invalid subtype: {self.subtype!r}")

        # Parameter names are case-insensitive; last occurrence wins
        normalized: dict[str, str] = {}
        for k, v in self.parameters:
            lk = k.lower()
            if not _TOKEN_RE.fullmatch(lk):
                raise ValueError(f"Invalid parameter name: {k!r}")
            normalized[lk] = v
        object.__setattr__(self, "parameters", tuple(normalized.items()))

        # Semantic validation: multipart/* requires boundary
        if self.type == "multipart" and self.boundary is None:
            raise ValueError("multipart/* requires a 'boundary' parameter")
        if self.boundary is not None:
            self._validate_boundary(self.boundary)

    @staticmethod
    def _validate_boundary(b: str) -> None:
        # RFC 2046 §5.1.1: 1–70 chars, no trailing whitespace
        if not (1 <= len(b) <= 70):
            raise ValueError("boundary must be 1–70 characters")
        if b != b.rstrip():
            raise ValueError("boundary must not end with whitespace")

    @property
    def media_type(self) -> str:
        """'type/subtype' with no parameters."""
        return f"{self.type}/{self.subtype}"

    @property
    def charset(self) -> str | None:
        v = self.get_parameter("charset")
        return v.lower() if v is not None else None

    @property
    def boundary(self) -> str | None:
        return self.get_parameter("boundary")

    def get_parameter(self, name: str) -> str | None:
        name = name.lower()
        for k, v in self.parameters:
            if k == name:
                return v
        return None

    def matches(self, type_: str, subtype: str = "*") -> bool:
        """Wildcard-aware match, e.g. ct.matches('application', '*')."""
        return (type_ == "*" or type_.lower() == self.type) and (subtype == "*" or subtype.lower() == self.subtype)

    @classmethod
    def parse(cls, value: str) -> "ContentType":
        try:
            t = Tokenizer(value)
            t.skip_ows()
            type_ = t.read_token()
            t.expect("/")
            subtype = t.read_token()

            params: list[tuple[str, str]] = []
            while True:
                t.skip_ows()
                if t.eof():
                    break
                t.expect(";")
                t.skip_ows()
                if t.eof():  # tolerate trailing ";"
                    break
                name = t.read_token()
                t.expect("=")
                pval = t.read_quoted_string() if t.peek() == '"' else t.read_token()
                params.append((name, pval))

            return cls(type=type_, subtype=subtype, parameters=tuple(params))
        except HeaderParseError:
            raise
        except ValueError as e:
            raise HeaderParseError(f"Invalid Content-Type {value!r}: {e}") from e

    def serialize(self) -> str:
        parts = [f"{self.type}/{self.subtype}"]
        parts.extend(f"{k}={quote_if_needed(v)}" for k, v in self.parameters)
        return "; ".join(parts)

    @classmethod
    def json(cls, charset: str | None = None) -> "ContentType":
        params = (("charset", charset),) if charset else ()
        return cls("application", "json", params)

    @classmethod
    def form_urlencoded(cls) -> "ContentType":
        return cls("application", "x-www-form-urlencoded")

    @classmethod
    def multipart_form_data(cls, boundary: str) -> "ContentType":
        return cls("multipart", "form-data", (("boundary", boundary),))

    @classmethod
    def text(cls, subtype: str = "plain", charset: str = "utf-8") -> "ContentType":
        return cls("text", subtype, (("charset", charset),))
