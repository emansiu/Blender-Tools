"""LaTeX math -> positioned glyphs and filled polygons. No bpy in here.

This is a small TeX: a parser for the math subset of LaTeX, and a layout
engine that follows The TeXbook's Appendix G closely enough to look right --
atom classes and the inter-atom spacing table, the style ladder (display ->
text -> script -> scriptscript), the superscript/subscript, fraction and
radical rules, and delimiters sized to their contents.

It needs no LaTeX install. Glyphs come from one Unicode math font (Blender
ships Noto Sans Math), so math italic is the font's own Mathematical Italic
block rather than a slanted roman, and stretchy delimiters are assembled from
the font's extensible pieces (U+239B...) the way TeX builds them from cmex.

The caller supplies a `metrics(ch)` function that returns a Glyph (ink box and
advance at size 1) or None for a glyph the font lacks; layout() returns a Box
whose items are what to draw:

    ("g", ch, x, y, sx, sy)      glyph `ch`, origin at (x, y), scaled (sx, sy)
    ("p", ((x, y), ...))         filled polygon -- fraction bars, radicals

Everything is in the font's own units at text size 1, baseline at y = 0, so a
formula comes out the size a Blender text object of size 1 would be.
"""

ORD, OP, BIN, REL, OPEN, CLOSE, PUNCT, INNER = range(8)


class LatexError(ValueError):
    """Input that can't be parsed. The message is meant for the user."""


class Glyph:
    __slots__ = ("advance", "xmin", "xmax", "ymin", "ymax")

    def __init__(self, advance, xmin, xmax, ymin, ymax):
        self.advance = advance
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax


# -----------------------------------------------------------------------------
# Symbol tables
# -----------------------------------------------------------------------------

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "varkappa": "ϰ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

_SYMBOLS = {
    # ordinary
    "infty": ("∞", ORD), "partial": ("𝜕", ORD), "nabla": ("∇", ORD), "hbar": ("ℏ", ORD),
    "hslash": ("ℏ", ORD), "ell": ("ℓ", ORD), "Re": ("ℜ", ORD), "Im": ("ℑ", ORD), "aleph": ("ℵ", ORD),
    "wp": ("℘", ORD), "emptyset": ("∅", ORD), "varnothing": ("∅", ORD), "forall": ("∀", ORD),
    "exists": ("∃", ORD), "nexists": ("∄", ORD), "neg": ("¬", ORD), "lnot": ("¬", ORD),
    "angle": ("∠", ORD), "triangle": ("△", ORD), "prime": ("′", ORD), "degree": ("°", ORD),
    "dagger": ("†", ORD), "ddagger": ("‡", ORD), "top": ("⊤", ORD), "bot": ("⊥", ORD),
    "ldots": ("…", INNER), "dots": ("…", INNER), "cdots": ("⋯", INNER), "vdots": ("⋮", ORD),
    "ddots": ("⋱", INNER), "imath": ("𝚤", ORD), "jmath": ("𝚥", ORD), "Box": ("□", ORD),
    "square": ("□", ORD), "checkmark": ("✓", ORD), "S": ("§", ORD), "P": ("¶", ORD),
    "backslash": ("\\", ORD), "vert": ("|", ORD), "Vert": ("‖", ORD), "|": ("‖", ORD),
    "#": ("#", ORD), "$": ("$", ORD), "%": ("%", ORD), "&": ("&", ORD), "_": ("_", ORD),
    "{": ("{", OPEN), "}": ("}", CLOSE), "lbrace": ("{", OPEN), "rbrace": ("}", CLOSE),
    "langle": ("⟨", OPEN), "rangle": ("⟩", CLOSE), "lfloor": ("⌊", OPEN), "rfloor": ("⌋", CLOSE),
    "lceil": ("⌈", OPEN), "rceil": ("⌉", CLOSE), "lvert": ("|", OPEN), "rvert": ("|", CLOSE),
    "lVert": ("‖", OPEN), "rVert": ("‖", CLOSE), "colon": (":", PUNCT),
    # binary operators
    "pm": ("±", BIN), "mp": ("∓", BIN), "times": ("×", BIN), "div": ("÷", BIN), "cdot": ("⋅", BIN),
    "circ": ("∘", BIN), "bullet": ("∙", BIN), "ast": ("∗", BIN), "star": ("⋆", BIN),
    "cup": ("∪", BIN), "cap": ("∩", BIN), "wedge": ("∧", BIN), "land": ("∧", BIN),
    "vee": ("∨", BIN), "lor": ("∨", BIN), "oplus": ("⊕", BIN), "ominus": ("⊖", BIN),
    "otimes": ("⊗", BIN), "oslash": ("⊘", BIN), "odot": ("⊙", BIN), "setminus": ("∖", BIN),
    "sqcup": ("⊔", BIN), "sqcap": ("⊓", BIN), "diamond": ("⋄", BIN), "uplus": ("⊎", BIN),
    "triangleleft": ("◁", BIN), "triangleright": ("▷", BIN), "wr": ("≀", BIN), "amalg": ("⨿", BIN),
    # relations
    "leq": ("≤", REL), "le": ("≤", REL), "geq": ("≥", REL), "ge": ("≥", REL), "neq": ("≠", REL),
    "ne": ("≠", REL), "leqslant": ("⩽", REL), "geqslant": ("⩾", REL), "approx": ("≈", REL),
    "equiv": ("≡", REL), "sim": ("∼", REL), "simeq": ("≃", REL), "cong": ("≅", REL),
    "propto": ("∝", REL), "ll": ("≪", REL), "gg": ("≫", REL), "in": ("∈", REL), "notin": ("∉", REL),
    "ni": ("∋", REL), "subset": ("⊂", REL), "supset": ("⊃", REL), "subseteq": ("⊆", REL),
    "supseteq": ("⊇", REL), "sqsubseteq": ("⊑", REL), "sqsupseteq": ("⊒", REL), "mid": ("∣", REL),
    "parallel": ("∥", REL), "perp": ("⊥", REL), "models": ("⊨", REL), "vdash": ("⊢", REL),
    "dashv": ("⊣", REL), "prec": ("≺", REL), "succ": ("≻", REL), "preceq": ("⪯", REL),
    "succeq": ("⪰", REL), "doteq": ("≐", REL), "asymp": ("≍", REL), "coloneqq": ("≔", REL),
    "to": ("→", REL), "rightarrow": ("→", REL), "leftarrow": ("←", REL), "gets": ("←", REL),
    "Rightarrow": ("⇒", REL), "Leftarrow": ("⇐", REL), "leftrightarrow": ("↔", REL),
    "Leftrightarrow": ("⇔", REL), "iff": ("⟺", REL), "implies": ("⟹", REL), "impliedby": ("⟸", REL),
    "mapsto": ("↦", REL), "longrightarrow": ("⟶", REL), "longleftarrow": ("⟵", REL),
    "Longrightarrow": ("⟹", REL), "Longleftarrow": ("⟸", REL), "longmapsto": ("⟼", REL),
    "uparrow": ("↑", REL), "downarrow": ("↓", REL), "updownarrow": ("↕", REL),
    "Uparrow": ("⇑", REL), "Downarrow": ("⇓", REL), "nearrow": ("↗", REL), "searrow": ("↘", REL),
    "swarrow": ("↙", REL), "nwarrow": ("↖", REL), "hookrightarrow": ("↪", REL),
    "hookleftarrow": ("↩", REL), "rightleftharpoons": ("⇌", REL), "leadsto": ("⇝", REL),
}

# \not X for the X that have a precomposed negation.
_NEGATED = {
    "=": "≠", "<": "≮", ">": "≯", "≤": "≰", "≥": "≱", "∈": "∉", "∋": "∌", "≡": "≢", "∼": "≁",
    "≃": "≄", "≈": "≉", "≅": "≇", "⊂": "⊄", "⊃": "⊅", "⊆": "⊈", "⊇": "⊉", "∣": "∤", "∥": "∦",
    "∃": "∄", "→": "↛", "←": "↚", "⇒": "⇏", "⇔": "⇎", "↔": "↮", "⊢": "⊬", "⊨": "⊭",
}

# name -> (glyph, takes limits in display style, display scale)
_BIG_OPS = {
    "sum": ("∑", True, 1.45), "prod": ("∏", True, 1.45), "coprod": ("∐", True, 1.45),
    "bigcup": ("⋃", True, 1.45), "bigcap": ("⋂", True, 1.45), "bigvee": ("⋁", True, 1.45),
    "bigwedge": ("⋀", True, 1.45), "bigoplus": ("⨁", True, 1.45), "bigotimes": ("⨂", True, 1.45),
    "bigodot": ("⨀", True, 1.45), "biguplus": ("⨄", True, 1.45), "bigsqcup": ("⨆", True, 1.45),
    "int": ("∫", False, 1.6), "iint": ("∬", False, 1.6), "iiint": ("∭", False, 1.6),
    "oint": ("∮", False, 1.6), "oiint": ("∯", False, 1.6),
}

# \sin and friends: name -> takes limits in display style
_FUNCTIONS = {
    "sin": False, "cos": False, "tan": False, "cot": False, "sec": False, "csc": False,
    "arcsin": False, "arccos": False, "arctan": False, "sinh": False, "cosh": False,
    "tanh": False, "coth": False, "log": False, "ln": False, "lg": False, "exp": False,
    "deg": False, "dim": False, "hom": False, "ker": False, "arg": False,
    "det": True, "gcd": True, "lim": True, "liminf": True, "limsup": True, "max": True,
    "min": True, "sup": True, "inf": True, "Pr": True,
}
_FUNCTION_TEXT = {"liminf": "lim inf", "limsup": "lim sup"}

# Plain characters typed directly.
_CHAR_CLASS = {
    "+": BIN, "-": BIN, "*": BIN, "/": ORD, "=": REL, "<": REL, ">": REL, ":": REL, ",": PUNCT,
    ";": PUNCT, "(": OPEN, "[": OPEN, ")": CLOSE, "]": CLOSE, "!": CLOSE, "?": CLOSE,
}
_CHAR_MAP = {"-": "−", "*": "∗"}
# Unicode symbols typed directly get the class their command would give them.
_UNICODE_CLASS = {ch: cls for ch, cls in _SYMBOLS.values() if cls != ORD}

_DELIMS = {
    "(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "/": "/", "<": "⟨", ">": "⟩",
    "{": "{", "}": "}", "lbrace": "{", "rbrace": "}", "langle": "⟨", "rangle": "⟩",
    "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉", "vert": "|", "lvert": "|",
    "rvert": "|", "Vert": "‖", "lVert": "‖", "rVert": "‖", "|": "‖", "backslash": "\\",
    "uparrow": "↑", "downarrow": "↓", "updownarrow": "↕", "Uparrow": "⇑", "Downarrow": "⇓",
    "lbrack": "[", "rbrack": "]",
}

# \big( and friends: name -> (size index, class)
_BIG_DELIMS = {}
for _i, _size in enumerate(("big", "Big", "bigg", "Bigg")):
    _BIG_DELIMS[_size] = (_i, ORD)
    _BIG_DELIMS[_size + "l"] = (_i, OPEN)
    _BIG_DELIMS[_size + "r"] = (_i, CLOSE)
    _BIG_DELIMS[_size + "m"] = (_i, REL)

# name -> (combining glyph, fallback spacing glyph, stretches to the base's width)
_ACCENTS = {
    "hat": ("̂", "^", False), "widehat": ("̂", "^", True),
    "tilde": ("̃", "~", False), "widetilde": ("̃", "~", True),
    "bar": ("̄", "¯", False), "vec": ("⃗", "→", False), "dot": ("̇", "˙", False),
    "ddot": ("̈", "¨", False), "dddot": ("⃛", "⋯", False), "acute": ("́", "´", False),
    "grave": ("̀", "`", False), "breve": ("̆", "˘", False), "check": ("̌", "ˇ", False),
    "mathring": ("̊", "˚", False),
}
# Stretched across the base: name -> (glyph, above?)
_WIDE_MARKS = {
    "overrightarrow": ("→", True), "overleftarrow": ("←", True), "overleftrightarrow": ("↔", True),
    "underrightarrow": ("→", False), "underleftarrow": ("←", False),
    "overbrace": ("⏞", True), "underbrace": ("⏟", False),
}

_VARIANT_COMMANDS = {
    "mathrm": "rm", "mathup": "rm", "mathit": "it", "mathbf": "bf", "boldsymbol": "bfit",
    "bm": "bfit", "mathbb": "bb", "mathcal": "cal", "mathscr": "cal", "mathfrak": "frak",
    "mathsf": "sf", "mathtt": "tt", "mathnormal": "math",
}
_TEXT_COMMANDS = {"text": "rm", "textrm": "rm", "mbox": "rm", "textnormal": "rm", "textup": "rm",
                  "textbf": "bf", "textit": "it", "textsf": "sf", "texttt": "tt", "emph": "it"}
_CLASS_COMMANDS = {"mathord": ORD, "mathop": OP, "mathbin": BIN, "mathrel": REL, "mathopen": OPEN,
                   "mathclose": CLOSE, "mathpunct": PUNCT, "mathinner": INNER}
_STYLE_COMMANDS = {"displaystyle": 0, "textstyle": 1, "scriptstyle": 2, "scriptscriptstyle": 3}

# name -> ("mu", n) or ("em", n)
_SPACES = {
    ",": ("mu", 3), "thinspace": ("mu", 3), ":": ("mu", 4), ">": ("mu", 4), "medspace": ("mu", 4),
    ";": ("mu", 5), "thickspace": ("mu", 5), "!": ("mu", -3), "negthinspace": ("mu", -3),
    " ": ("em", 1 / 3), "quad": ("em", 1), "qquad": ("em", 2), "enspace": ("em", 0.5),
}

# Environment -> (left delim, right delim, column alignments or None for all-centre)
_MATRIX_ENVS = {
    "matrix": (None, None), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"), "smallmatrix": (None, None),
}

# Unicode Mathematical Alphanumeric Symbols: variant -> start of A..Za..z
_LATIN = {"bf": 0x1D400, "it": 0x1D434, "bfit": 0x1D468, "cal": 0x1D49C, "frak": 0x1D504,
          "bb": 0x1D538, "sf": 0x1D5A0, "tt": 0x1D670}
_DIGITS = {"bf": 0x1D7CE, "bb": 0x1D7D8, "sf": 0x1D7E2, "tt": 0x1D7F6}
# Letters that were encoded before the block existed, so the block has holes.
_LATIN_HOLES = {
    ("it", "h"): "ℎ",
    ("cal", "B"): "ℬ", ("cal", "E"): "ℰ", ("cal", "F"): "ℱ", ("cal", "H"): "ℋ", ("cal", "I"): "ℐ",
    ("cal", "L"): "ℒ", ("cal", "M"): "ℳ", ("cal", "R"): "ℛ", ("cal", "e"): "ℯ", ("cal", "g"): "ℊ",
    ("cal", "o"): "ℴ",
    ("frak", "C"): "ℭ", ("frak", "H"): "ℌ", ("frak", "I"): "ℑ", ("frak", "R"): "ℜ", ("frak", "Z"): "ℨ",
    ("bb", "C"): "ℂ", ("bb", "H"): "ℍ", ("bb", "N"): "ℕ", ("bb", "P"): "ℙ", ("bb", "Q"): "ℚ",
    ("bb", "R"): "ℝ", ("bb", "Z"): "ℤ",
}
# variant -> (start of capital Greek, start of small Greek)
_GREEK_BLOCKS = {"bf": (0x1D6A8, 0x1D6C2), "it": (0x1D6E2, 0x1D6FC), "bfit": (0x1D71C, 0x1D736)}
_GREEK_EXTRA = "∂ϵϑϰϕϱϖ"   # follow the 25 small letters in each block, in this order


def styled(ch, variant):
    """`ch` in math alphabet `variant` ("math" is TeX's default: italic
    letters and small Greek, upright capital Greek and digits)."""
    if variant == "math":
        if "Α" <= ch <= "Ω":
            return ch
        variant = "it"
    if variant == "rm":
        return ch
    if ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
        hole = _LATIN_HOLES.get((variant, ch))
        if hole:
            return hole
        start = _LATIN.get(variant)
        if start is None:
            return ch
        index = ord(ch) - 65 if ch <= "Z" else ord(ch) - 97 + 26
        return chr(start + index)
    if "0" <= ch <= "9":
        start = _DIGITS.get(variant)
        return chr(start + ord(ch) - 48) if start else ch
    block = _GREEK_BLOCKS.get(variant)
    if block:
        if "Α" <= ch <= "Ω":
            return chr(block[0] + ord(ch) - 0x391)
        if "α" <= ch <= "ω":
            return chr(block[1] + ord(ch) - 0x3B1)
        if ch in _GREEK_EXTRA:
            return chr(block[1] + 25 + _GREEK_EXTRA.index(ch))
    return ch


def _is_letter(ch):
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("Α" <= ch <= "ω") or ch in "ϵϑϰϕϱϖ"


# -----------------------------------------------------------------------------
# Parse tree
# -----------------------------------------------------------------------------

class Sym:
    __slots__ = ("ch", "cls", "italic")

    def __init__(self, ch, cls=ORD, italic=False):
        self.ch, self.cls, self.italic = ch, cls, italic


class Group:
    __slots__ = ("nodes", "cls")

    def __init__(self, nodes, cls=ORD):
        self.nodes, self.cls = nodes, cls


class Space:
    __slots__ = ("unit", "amount")

    def __init__(self, unit, amount):
        self.unit, self.amount = unit, amount   # unit is "mu", "em" or "glyph" (amount = the char)


class StyleChange:
    __slots__ = ("level",)

    def __init__(self, level):
        self.level = level


class Scripts:
    __slots__ = ("nucleus", "sup", "sub")

    def __init__(self, nucleus, sup=None, sub=None):
        self.nucleus, self.sup, self.sub = nucleus, sup, sub


class BigOp:
    __slots__ = ("ch", "limits", "scale")

    def __init__(self, ch, limits, scale):
        self.ch, self.limits, self.scale = ch, limits, scale


class OpName:
    __slots__ = ("text", "limits")

    def __init__(self, text, limits):
        self.text, self.limits = text, limits


class Frac:
    __slots__ = ("num", "den", "bar", "level")

    def __init__(self, num, den, bar=True, level=None):
        self.num, self.den, self.bar, self.level = num, den, bar, level


class Sqrt:
    __slots__ = ("body", "index")

    def __init__(self, body, index=None):
        self.body, self.index = body, index


class LeftRight:
    __slots__ = ("left", "body", "right", "min_size")

    def __init__(self, left, body, right, min_size=0.0):
        self.left, self.body, self.right, self.min_size = left, body, right, min_size


class Delim:
    __slots__ = ("ch", "size", "cls")

    def __init__(self, ch, size, cls):
        self.ch, self.size, self.cls = ch, size, cls


class Accent:
    __slots__ = ("mark", "fallback", "wide", "body")

    def __init__(self, mark, fallback, wide, body):
        self.mark, self.fallback, self.wide, self.body = mark, fallback, wide, body


class WideMark:
    __slots__ = ("ch", "above", "body")

    def __init__(self, ch, above, body):
        self.ch, self.above, self.body = ch, above, body


class Rule:
    """\\overline / \\underline."""

    __slots__ = ("above", "body")

    def __init__(self, above, body):
        self.above, self.body = above, body


class Stack:
    """\\overset / \\underset / \\stackrel: a small line set above or below."""

    __slots__ = ("base", "over", "under", "cls")

    def __init__(self, base, over, under, cls):
        self.base, self.over, self.under, self.cls = base, over, under, cls


class Array:
    __slots__ = ("rows", "kind", "align")

    def __init__(self, rows, kind, align=None):
        self.rows, self.kind, self.align = rows, kind, align


# -----------------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------------

_T_CMD, _T_CHAR, _T_SYM, _T_SPACE = "cmd", "char", "sym", "space"
_STOP_RIGHT = ((_T_CMD, "right"),)
_STOP_BRACE = ((_T_SYM, "}"),)
_STOP_BRACKET = ((_T_CHAR, "]"),)
_STOP_CELL = ((_T_SYM, "&"), (_T_CMD, "\\"), (_T_CMD, "end"))


class _Parser:
    def __init__(self, src):
        self.src = src
        self.pos = 0
        self.variant = "math"
        self.chars = set()   # every glyph the tree uses, so they can be measured in one batch

    # -- tokens ---------------------------------------------------------------

    def _read(self):
        src, n = self.src, len(self.src)
        while True:
            if self.pos >= n:
                return None
            c = src[self.pos]
            if c == "%":   # comment to end of line
                while self.pos < n and src[self.pos] != "\n":
                    self.pos += 1
                continue
            break
        start = self.pos
        self.pos += 1
        if c.isspace():
            while self.pos < n and src[self.pos].isspace():
                self.pos += 1
            return (_T_SPACE, " ")
        if c == "\\":
            if self.pos >= n:
                raise LatexError("The formula ends with a lone backslash")
            if src[self.pos].isalpha():
                while self.pos < n and src[self.pos].isalpha():
                    self.pos += 1
                return (_T_CMD, src[start + 1:self.pos])
            self.pos += 1
            return (_T_CMD, src[self.pos - 1])
        if c in "{}^_&~'":
            return (_T_SYM, c)
        return (_T_CHAR, c)

    def peek(self, skip_space=True):
        save = self.pos
        tok = self.next(skip_space)
        self.pos = save
        return tok

    def next(self, skip_space=True):
        tok = self._read()
        while skip_space and tok is not None and tok[0] == _T_SPACE:
            tok = self._read()
        return tok

    def expect(self, tok, what):
        got = self.next()
        if got != tok:
            raise LatexError(f"Expected {what}{self._where()}")

    def _where(self):
        return f" near {self.src[max(0, self.pos - 12):self.pos]!r}"

    def raw_group(self):
        """The literal text of a {...} argument, for \\text and names."""
        self.expect((_T_SYM, "{"), "'{'")
        depth, start = 1, self.pos
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c == "\\":
                self.pos += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return self.src[start:self.pos - 1]
            self.pos += 1
        raise LatexError("Missing '}'")

    # -- structure ------------------------------------------------------------

    def sym(self, ch, cls=ORD, italic=False):
        self.chars.add(ch)
        return Sym(ch, cls, italic)

    def parse(self):
        rows = self.rows(top_level=True)
        if len(rows) == 1 and len(rows[0]) == 1:
            return Group(rows[0][0])
        aligned = any(len(row) > 1 for row in rows)
        return Array(rows, "aligned" if aligned else "gathered")

    def rows(self, top_level=False, env=None):
        rows, row = [], []
        while True:
            row.append(self.expr(_STOP_CELL))
            tok = self.next()
            if tok == (_T_SYM, "&"):
                continue
            if tok == (_T_CMD, "\\"):
                if self.peek() == (_T_CHAR, "["):   # \\[2pt]: the extra row gap is ignored
                    tok = self.next()
                    while tok not in (None, (_T_CHAR, "]")):
                        tok = self.next()
                rows.append(row)
                row = []
                continue
            if tok is None:
                if not top_level:
                    raise LatexError(f"\\begin{{{env}}} has no \\end{{{env}}}")
            elif tok == (_T_CMD, "end"):
                name = self.raw_group()
                if top_level or name != env:
                    raise LatexError(f"\\end{{{name}}} doesn't match" + (f" \\begin{{{env}}}" if env else " any \\begin"))
            elif tok == (_T_SYM, "}"):
                raise LatexError("Unmatched '}'")
            else:
                raise LatexError(f"Unexpected {tok[1]!r}{self._where()}")
            rows.append(row)
            break
        # A trailing \\ leaves one empty row behind; LaTeX drops it too.
        if len(rows) > 1 and len(rows[-1]) == 1 and not rows[-1][0]:
            rows.pop()
        return rows

    def expr(self, stop):
        nodes = []
        while True:
            tok = self.peek()
            if tok is None or tok in stop:
                return nodes
            if tok[0] == _T_SYM and tok[1] in "^_":
                self.next()
                self.attach_script(nodes, tok[1])
                continue
            if tok == (_T_SYM, "'"):
                self.next()
                nodes.append(self.sym("′"))
                continue
            if tok == (_T_SYM, "}") or tok == (_T_SYM, "&") or tok in ((_T_CMD, "\\"), (_T_CMD, "end"), (_T_CMD, "right")):
                if tok == (_T_SYM, "}"):
                    raise LatexError("Unmatched '}'")
                if tok == (_T_CMD, "right"):
                    raise LatexError("\\right without a matching \\left")
                raise LatexError(f"{tok[1]!r} only works inside an environment or at the top level")
            if tok in ((_T_CMD, "limits"), (_T_CMD, "nolimits")):
                self.next()
                target = nodes[-1] if nodes else None
                if isinstance(target, Scripts):
                    target = target.nucleus
                if not isinstance(target, (BigOp, OpName)):
                    raise LatexError(f"\\{tok[1]} must follow an operator like \\sum")
                target.limits = tok[1] == "limits"
                continue
            nodes.append(self.atom())

    def attach_script(self, nodes, kind):
        last = nodes[-1] if nodes else None
        if isinstance(last, (StyleChange, Space)):
            last = None   # x\,^2 or \displaystyle^2: script an empty base, as TeX does
        if not isinstance(last, Scripts):
            last = Scripts(last if last is not None else Group([]))
            if nodes and nodes[-1] is last.nucleus:
                nodes[-1] = last
            else:
                nodes.append(last)
        arg = self.argument()
        if kind == "^":
            if last.sup is not None:
                raise LatexError("Double superscript -- group them with braces, e.g. x^{ab}")
            last.sup = arg
        else:
            if last.sub is not None:
                raise LatexError("Double subscript -- group them with braces, e.g. x_{ab}")
            last.sub = arg

    def argument(self):
        """One argument: a {group} or a single token."""
        tok = self.peek()
        if tok is None:
            raise LatexError("Missing argument at the end of the formula")
        if tok == (_T_SYM, "{"):
            self.next()
            nodes = self.expr(_STOP_BRACE)
            self.expect((_T_SYM, "}"), "'}'")
            return Group(nodes)
        if tok[0] == _T_SYM and tok[1] in "}^_&":
            raise LatexError(f"Missing argument before {tok[1]!r}{self._where()}")
        return self.atom()

    def optional(self):
        if self.peek() != (_T_CHAR, "["):
            return None
        self.next()
        nodes = self.expr(_STOP_BRACKET)
        self.expect((_T_CHAR, "]"), "']'")
        return Group(nodes)

    def with_variant(self, variant, fn):
        saved = self.variant
        self.variant = variant
        try:
            return fn()
        finally:
            self.variant = saved

    def atom(self):
        tok = self.next()
        kind, value = tok
        if kind == _T_SYM:
            if value == "{":
                nodes = self.expr(_STOP_BRACE)
                self.expect((_T_SYM, "}"), "'}'")
                return Group(nodes)
            if value == "~":
                return Space("em", 1 / 3)
            raise LatexError(f"Unexpected {value!r}{self._where()}")
        if kind == _T_CHAR:
            return self.char(value)
        return self.command(value)

    def char(self, ch):
        if _is_letter(ch):
            out = styled(ch, self.variant)
            return self.sym(out, ORD, italic=out != ch and self.variant in ("math", "it", "bfit"))
        if "0" <= ch <= "9":
            return self.sym(styled(ch, self.variant))
        cls = _CHAR_CLASS.get(ch, _UNICODE_CLASS.get(ch, ORD))
        return self.sym(_CHAR_MAP.get(ch, ch), cls)

    def text(self, variant):
        nodes = []
        for ch in self.raw_group().replace("\\ ", " ").replace("\\{", "{").replace("\\}", "}"):
            if ch.isspace():
                nodes.append(Space("glyph", " "))
                self.chars.add(" ")
            elif variant != "rm" and (("A" <= ch <= "Z") or ("a" <= ch <= "z") or "0" <= ch <= "9"):
                nodes.append(self.sym(styled(ch, variant), italic=variant in ("it", "bfit")))
            else:
                nodes.append(self.sym(_CHAR_MAP.get(ch, ch) if ch == "-" else ch))
        return Group(nodes)

    def delim(self):
        tok = self.next()
        if tok is None:
            raise LatexError("Missing delimiter at the end of the formula")
        if tok == (_T_CHAR, "."):
            return None
        ch = _DELIMS.get(tok[1]) if tok[0] in (_T_CHAR, _T_CMD) else None
        if ch is None:
            raise LatexError(f"{tok[1]!r} can't be used as a delimiter")
        self.chars.add(ch)
        return ch

    def command(self, name):
        if name in _GREEK:
            ch = _GREEK[name]
            out = styled(ch, self.variant)
            return self.sym(out, italic=out != ch)
        if name in _SYMBOLS:
            ch, cls = _SYMBOLS[name]
            return self.sym(ch, cls)
        if name in _SPACES:
            return Space(*_SPACES[name])
        if name in _BIG_OPS:
            ch, limits, scale = _BIG_OPS[name]
            self.chars.add(ch)
            return BigOp(ch, limits, scale)
        if name in _FUNCTIONS:
            text = _FUNCTION_TEXT.get(name, name)
            self.chars.update(text)
            return OpName(text, _FUNCTIONS[name])
        if name == "operatorname":
            star = self.peek(skip_space=False) == (_T_CHAR, "*")
            if star:
                self.next()
            text = self.raw_group().replace("\\,", " ").replace("\\ ", " ")
            self.chars.update(text)
            return OpName(text, star)
        if name in ("frac", "dfrac", "tfrac", "cfrac", "binom", "dbinom", "tbinom"):
            num, den = self.argument(), self.argument()
            level = 0 if name[0] in "dc" else (1 if name[0] == "t" else None)
            if name.endswith("binom"):
                self.chars.update("()")
                return LeftRight("(", [Frac(num, den, bar=False, level=level)], ")")
            return Frac(num, den, level=level)
        if name == "sqrt":
            index = self.optional()
            return Sqrt(self.argument(), index)
        if name == "left":
            left = self.delim()
            body = self.expr(_STOP_RIGHT)
            if self.next() != (_T_CMD, "right"):
                raise LatexError("\\left without a matching \\right")
            return LeftRight(left, body, self.delim())
        if name in _BIG_DELIMS:
            size, cls = _BIG_DELIMS[name]
            return Delim(self.delim(), size, cls)
        if name in _ACCENTS:
            mark, fallback, wide = _ACCENTS[name]
            self.chars.update((mark, fallback))
            return Accent(mark, fallback, wide, self.argument())
        if name in _WIDE_MARKS:
            ch, above = _WIDE_MARKS[name]
            self.chars.add(ch)
            return WideMark(ch, above, self.argument())
        if name in ("overline", "underline"):
            return Rule(name == "overline", self.argument())
        if name in ("overset", "underset", "stackrel"):
            small, base = self.argument(), self.argument()
            if name == "underset":
                return Stack(base, None, small, ORD)
            return Stack(base, small, None, REL if name == "stackrel" else ORD)
        if name in _VARIANT_COMMANDS:
            return self.with_variant(_VARIANT_COMMANDS[name], self.argument)
        if name in _TEXT_COMMANDS:
            return self.text(_TEXT_COMMANDS[name])
        if name in _CLASS_COMMANDS:
            arg = self.argument()
            return Group([arg], _CLASS_COMMANDS[name])
        if name in _STYLE_COMMANDS:
            return StyleChange(_STYLE_COMMANDS[name])
        if name == "not":
            nxt = self.atom()
            if isinstance(nxt, Sym) and nxt.ch in _NEGATED:
                return self.sym(_NEGATED[nxt.ch], REL)
            raise LatexError("\\not only works before a relation such as = or \\in")
        if name == "begin":
            return self.environment(self.raw_group())
        if name in ("right", "end", "\\"):
            raise LatexError(f"Unexpected \\{name}{self._where()}")
        raise LatexError(f"Unknown command \\{name}")

    def environment(self, env):
        if env in _MATRIX_ENVS:
            left, right = _MATRIX_ENVS[env]
            array = Array(self.rows(env=env), "small" if env == "smallmatrix" else "matrix")
            if left is None:
                return array
            self.chars.update((left, right))
            return LeftRight(left, [array], right)
        if env == "cases":
            self.chars.add("{")
            return LeftRight("{", [Array(self.rows(env=env), "cases", "ll")], None)
        if env == "array":
            spec = "".join(c for c in self.raw_group() if c in "lcr")
            return Array(self.rows(env=env), "matrix", spec or None)
        base = env.rstrip("*")
        if base in ("aligned", "align", "split", "alignat", "eqnarray"):
            if base == "alignat":
                self.raw_group()
            return Array(self.rows(env=env), "aligned")
        if base in ("gathered", "gather", "equation", "displaymath"):
            return Array(self.rows(env=env), "gathered")
        raise LatexError(f"Unknown environment {env!r}")


def parse(src):
    """(tree, set of every glyph the tree names)."""
    parser = _Parser(src)
    return parser.parse(), parser.chars


# -----------------------------------------------------------------------------
# Layout
# -----------------------------------------------------------------------------

_SIZES = (1.0, 1.0, 0.7, 0.5)


class Style:
    """TeX's D, T, S, SS (levels 0-3), each cramped or not."""

    __slots__ = ("level", "cramped")

    def __init__(self, level, cramped=False):
        self.level, self.cramped = level, cramped

    @property
    def size(self):
        return _SIZES[self.level]

    def sup(self):
        return Style((2, 2, 3, 3)[self.level], self.cramped)

    def sub(self):
        return Style((2, 2, 3, 3)[self.level], True)

    def num(self):
        return Style((1, 2, 3, 3)[self.level], self.cramped)

    def den(self):
        return Style((1, 2, 3, 3)[self.level], True)

    def cramp(self):
        return Style(self.level, True)


# Appendix G inter-atom spacing. 0 none, 1 thin, 2 medium, 3 thick; negative
# means "only in display and text style".
_SPACING = (
    # Ord Op  Bin Rel Open Close Punct Inner
    (0, 1, -2, -3, 0, 0, 0, -1),          # Ord
    (1, 1, 0, -3, 0, 0, 0, -1),           # Op
    (-2, -2, 0, 0, -2, 0, 0, -2),         # Bin
    (-3, -3, 0, 0, -3, 0, 0, -3),         # Rel
    (0, 0, 0, 0, 0, 0, 0, 0),             # Open
    (0, 1, -2, -3, 0, 0, 0, -1),          # Close
    (-1, -1, 0, -1, -1, -1, -1, -1),      # Punct
    (-1, 1, -2, -3, -1, 0, -1, -1),       # Inner
)
_SPACING_MU = (0, 3, 4, 5)

# Extensible delimiters from the font's U+239B.. pieces: (top, extender, bottom, middle)
_ASSEMBLY = {
    "(": ("⎛", "⎜", "⎝", None), ")": ("⎞", "⎟", "⎠", None),
    "[": ("⎡", "⎢", "⎣", None), "]": ("⎤", "⎥", "⎦", None),
    "{": ("⎧", "⎪", "⎩", "⎨"), "}": ("⎫", "⎪", "⎭", "⎬"),
    "⌈": ("⎡", "⎢", "⎢", None), "⌉": ("⎤", "⎥", "⎥", None),
    "⌊": ("⎢", "⎢", "⎣", None), "⌋": ("⎥", "⎥", "⎦", None),
}
_STRAIGHT_DELIMS = "|‖"            # stretch vertically only
_WIDE_DELIMS = "⟨⟩/\\"              # stretch in x a fair bit too, or they turn into needles
_BIG_SIZES = (1.2, 1.8, 2.4, 3.0)  # \big \Big \bigg \Bigg, total height in TeX em

# Glyphs layout() may ask for that the parse tree doesn't name.
LAYOUT_CHARS = set("xM−| ′") | {c for p in _ASSEMBLY.values() for c in p if c}


class Box:
    __slots__ = ("width", "height", "depth", "items", "italic")

    def __init__(self, width=0.0, height=0.0, depth=0.0):
        self.width, self.height, self.depth = width, height, depth
        self.items = []
        self.italic = 0.0

    def add(self, box, dx, dy):
        for item in box.items:
            if item[0] == "g":
                _, ch, x, y, sx, sy = item
                self.items.append(("g", ch, x + dx, y + dy, sx, sy))
            else:
                self.items.append(("p", tuple((x + dx, y + dy) for x, y in item[1])))

    def rect(self, x0, y0, x1, y1):
        self.items.append(("p", ((x0, y0), (x1, y0), (x1, y1), (x0, y1))))


def _hbox(boxes):
    out = Box()
    x = 0.0
    for box in boxes:
        out.add(box, x, 0.0)
        x += box.width
        out.height = max(out.height, box.height)
        out.depth = max(out.depth, box.depth)
    out.width = x
    return out


class _Layout:
    def __init__(self, metrics):
        self.metrics = metrics
        self.missing = set()
        x, m, minus = metrics("x"), metrics("M"), metrics("−")
        self.xh = x.ymax if x else 0.45
        self.em = m.ymax / 0.7 if m else self.xh / 0.52
        # TeX's vertical parameters are tuned to Computer Modern's x-height
        # (0.4306 em). Expressing them in x-heights keeps scripts and
        # fractions sitting right on a font with a much taller x-height.
        self.v = self.xh / 0.4306
        if minus:
            self.axis = (minus.ymin + minus.ymax) / 2
            self.rule = min(max(minus.ymax - minus.ymin, 0.03 * self.em), 0.09 * self.em)
        else:
            self.axis, self.rule = 0.25 * self.v, 0.05 * self.em

    def glyph(self, ch):
        g = self.metrics(ch)
        if g is None:
            self.missing.add(ch)
        return g

    # -- atoms ----------------------------------------------------------------

    def char(self, ch, s, italic=False, sx=None):
        g = self.glyph(ch)
        if g is None:
            return Box(0.5 * self.em * s, 0.7 * self.em * s, 0.0)
        sx = s if sx is None else sx
        box = Box(g.advance * sx, max(g.ymax, 0.0) * s, max(-g.ymin, 0.0) * s)
        box.items.append(("g", ch, 0.0, 0.0, sx, s))
        if italic:
            box.italic = max(0.0, g.xmax - g.advance) * sx
        return box

    def node(self, node, st):
        """(box, atom class); class None means 'glue', invisible to spacing."""
        s = st.size
        if isinstance(node, Sym):
            return self.char(node.ch, s, node.italic), node.cls
        if isinstance(node, Group):
            return self.hlist(node.nodes, st), node.cls
        if isinstance(node, Space):
            if node.unit == "glyph":
                g = self.glyph(node.amount)
                return Box((g.advance if g else 0.25 * self.em) * s), None
            width = node.amount * self.em * s / (18 if node.unit == "mu" else 1)
            return Box(width), None
        if isinstance(node, Scripts):
            return self.scripts(node, st)
        if isinstance(node, BigOp):
            return self.bigop(node, st), OP
        if isinstance(node, OpName):
            return self.opname(node, st), OP
        if isinstance(node, Frac):
            return self.frac(node, st), INNER
        if isinstance(node, Sqrt):
            return self.sqrt(node, st), ORD
        if isinstance(node, LeftRight):
            return self.left_right(node, st), INNER
        if isinstance(node, Delim):
            return self.delim(node.ch, _BIG_SIZES[node.size] * self.v * s, s), node.cls
        if isinstance(node, Accent):
            return self.accent(node, st), ORD
        if isinstance(node, WideMark):
            return self.wide_mark(node, st), ORD
        if isinstance(node, Rule):
            return self.overline(node, st), ORD
        if isinstance(node, Stack):
            base, _ = self.node(node.base, st)
            return self.limits(base, node.over, node.under, st), node.cls
        if isinstance(node, Array):
            return self.array(node, st), ORD
        raise TypeError(node)

    def hlist(self, nodes, st):
        atoms = []   # [class, box, style]
        for node in nodes:
            if isinstance(node, StyleChange):
                st = Style(node.level, st.cramped)
                continue
            box, cls = self.node(node, st)
            if isinstance(node, Sym) and box.italic:
                # Rule 17: a bare italic letter keeps its italic correction,
                # so the f in f(x) doesn't lean into the parenthesis. (With a
                # script attached, scripts() spends it on the superscript.)
                box.width += box.italic
                box.italic = 0.0
            atoms.append([cls, box, st])

        # Rule 5/6: a Bin with nothing to operate on is an Ord.
        prev = None
        for atom in atoms:
            cls = atom[0]
            if cls is None:
                continue
            if cls == BIN and (prev is None or prev[0] in (BIN, OP, REL, OPEN, PUNCT)):
                atom[0] = cls = ORD
            if cls in (REL, CLOSE, PUNCT) and prev is not None and prev[0] == BIN:
                prev[0] = ORD
            prev = atom
        if prev is not None and prev[0] == BIN:
            prev[0] = ORD

        out = Box()
        x, prev = 0.0, None
        for cls, box, ast in atoms:
            if cls is not None:
                if prev is not None:
                    code = _SPACING[prev][cls]
                    if code < 0:
                        code = -code if ast.level <= 1 else 0
                    x += _SPACING_MU[code] * self.em * ast.size / 18
                prev = cls
            out.add(box, x, 0.0)
            x += box.width
            out.height = max(out.height, box.height)
            out.depth = max(out.depth, box.depth)
        out.width = x
        if atoms:
            out.italic = atoms[-1][1].italic
        return out

    # -- scripts, operators ---------------------------------------------------

    def scripts(self, node, st):
        nuc_node = node.nucleus
        if isinstance(nuc_node, (BigOp, OpName)) and nuc_node.limits and st.level == 0:
            base = self.bigop(nuc_node, st) if isinstance(nuc_node, BigOp) else self.opname(nuc_node, st)
            return self.limits(base, node.sup, node.sub, st), OP
        nuc, cls = self.node(nuc_node, st)
        s, v, xh = st.size, self.v, self.xh * st.size
        sup = self.node(node.sup, st.sup())[0] if node.sup is not None else None
        sub = self.node(node.sub, st.sub())[0] if node.sub is not None else None

        if isinstance(nuc_node, Sym):
            u = d = 0.0
        else:
            u = nuc.height - 0.386 * v * st.sup().size
            d = nuc.depth + 0.05 * v * st.sub().size

        if sup is None:
            d = max(d, 0.15 * v * s, sub.height - 0.8 * xh)
        else:
            p = 0.413 if st.level == 0 else (0.289 if st.cramped else 0.363)
            u = max(u, p * v * s, sup.depth + 0.25 * xh)
            if sub is not None:
                d = max(d, 0.247 * v * s)
                gap = (u - sup.depth) - (sub.height - d)
                if gap < 4 * self.rule * s:
                    d += 4 * self.rule * s - gap
                    psi = 0.8 * xh - (u - sup.depth)
                    if psi > 0:
                        u += psi
                        d -= psi

        out = Box()
        out.add(nuc, 0.0, 0.0)
        out.height, out.depth = nuc.height, nuc.depth
        script_space = 0.05 * self.em * s
        width = nuc.width
        if sup is not None:
            x = nuc.width + nuc.italic
            out.add(sup, x, u)
            out.height = max(out.height, u + sup.height)
            width = max(width, x + sup.width + script_space)
        if sub is not None:
            # Integrals lean right; tuck the lower limit back under the slant.
            x = nuc.width - (nuc.italic if isinstance(nuc_node, BigOp) else 0.0)
            out.add(sub, x, -d)
            out.depth = max(out.depth, d + sub.depth)
            width = max(width, x + sub.width + script_space)
        out.width = width
        return out, cls

    def bigop(self, node, st):
        s = st.size * (node.scale if st.level == 0 else 1.0)
        g = self.glyph(node.ch)
        if g is None:
            return Box(self.em * s)
        dy = self.axis * st.size - (g.ymin + g.ymax) / 2 * s
        box = Box(g.advance * s, g.ymax * s + dy, -(g.ymin * s + dy))
        box.items.append(("g", node.ch, 0.0, dy, s, s))
        box.italic = max(0.0, g.xmax - g.advance) * s
        return box

    def opname(self, node, st):
        s = st.size
        boxes = []
        for ch in node.text:
            if ch == " ":
                boxes.append(Box(3 * self.em * s / 18))
            else:
                boxes.append(self.char(ch, s))
        return _hbox(boxes)

    def limits(self, base, over, under, st):
        """Limits stacked over and under `base`, everything centred."""
        v = self.v * st.size
        sup = self.node(over, st.sup())[0] if over is not None else None
        sub = self.node(under, st.sub())[0] if under is not None else None
        width = max(base.width, sup.width if sup else 0.0, sub.width if sub else 0.0)
        out = Box(width, base.height, base.depth)
        out.add(base, (width - base.width) / 2, 0.0)
        if sup is not None:
            y = base.height + max(0.111 * v, 0.2 * v - sup.depth) + sup.depth
            out.add(sup, (width - sup.width) / 2 + base.italic / 2, y)
            out.height = y + sup.height + 0.1 * v
        if sub is not None:
            y = base.depth + max(0.167 * v, 0.6 * v - sub.height) + sub.height
            out.add(sub, (width - sub.width) / 2 - base.italic / 2, -y)
            out.depth = y + sub.depth + 0.1 * v
        return out

    # -- fractions, radicals --------------------------------------------------

    def frac(self, node, st):
        if node.level is not None:
            st = Style(node.level, st.cramped)
        s, v = st.size, self.v * st.size
        num = self.node(node.num, st.num())[0]
        den = self.node(node.den, st.den())[0]
        theta = self.rule * s
        axis = self.axis * s
        display = st.level == 0
        u = (0.677 if display else 0.394) * v
        d = (0.686 if display else 0.345) * v
        if node.bar:
            phi = (3 if display else 1) * theta
            clear = (u - num.depth) - (axis + theta / 2)
            if clear < phi:
                u += phi - clear
            clear = (axis - theta / 2) - (den.height - d)
            if clear < phi:
                d += phi - clear
        else:
            phi = (7 if display else 3) * theta
            gap = (u - num.depth) - (den.height - d)
            if gap < phi:
                u += (phi - gap) / 2
                d += (phi - gap) / 2
        pad = 0.12 * self.em * s   # \nulldelimiterspace on each side
        inner = max(num.width, den.width)
        out = Box(inner + 2 * pad, u + num.height, d + den.depth)
        out.add(num, pad + (inner - num.width) / 2, u)
        out.add(den, pad + (inner - den.width) / 2, -d)
        if node.bar:
            out.rect(pad, axis - theta / 2, pad + inner, axis + theta / 2)
        return out

    def sqrt(self, node, st):
        s = st.size
        body = self.node(node.body, st.cramp())[0]
        theta = self.rule * s
        phi = self.xh * s if st.level == 0 else theta
        psi = theta + phi / 4
        top = body.height + psi + theta             # top edge of the vinculum
        bottom = -(body.depth + psi * 0.6)
        height = top - bottom
        em = self.em * s
        # The sign: a short rising tick, a heavy stroke down to the vertex, a
        # hairline up to the vinculum. One polygon with the bar, so the 2D
        # fill has no overlapping pieces to punch holes through.
        w = min(0.62 * em, 0.42 * em + 0.08 * height)
        hs = min(height, 0.55 * self.v * s + 0.12 * height)
        t = theta
        vx = 0.42 * w                               # vertex x
        # Clearance before the body: italic letters overhang to the left (the
        # tail of a y), and any ink that overlaps the sign cancels out in a
        # filled 2D curve instead of merging.
        body_x = w + 0.07 * em
        bar_end = body_x + body.width + 0.04 * em
        notch_y = bottom + 0.18 * hs                # where the hairline's inner edge meets the heavy stroke
        notch_x = vx + 0.5 * t + (w - t - vx) * (notch_y - bottom) / height
        poly = (
            (0.0, bottom + 0.44 * hs),
            (0.05 * w, bottom + 0.50 * hs),
            (0.17 * w, bottom + 0.57 * hs),
            (notch_x, notch_y),
            (w - 1.1 * t, top),
            (bar_end, top),
            (bar_end, top - t),
            (w - 0.1 * t, top - t),
            (vx + 1.6 * t, bottom),
            (vx, bottom),
            (0.11 * w, bottom + 0.46 * hs),
            (0.06 * w, bottom + 0.42 * hs),
        )
        offset = 0.0
        out = Box()
        if node.index is not None:
            index = self.node(node.index, Style(3))[0]
            raise_y = bottom + 0.6 * height + index.depth
            offset = max(0.0, index.width - 0.55 * w)
            out.add(index, offset + 0.55 * w - index.width, raise_y)
            out.height = raise_y + index.height
        out.items.append(("p", tuple((x + offset, y) for x, y in poly)))
        out.add(body, offset + body_x, 0.0)
        out.width = offset + bar_end + 0.04 * em
        out.height = max(out.height, top)
        out.depth = max(-bottom, body.depth)
        return out

    # -- delimiters -----------------------------------------------------------

    def left_right(self, node, st):
        s = st.size
        body = self.hlist(node.body, st)
        axis = self.axis * s
        delta = max(body.height - axis, body.depth + axis)
        total = max(2 * delta * 0.901, 2 * delta - 0.5 * self.v * s, node.min_size)
        left = self.delim(node.left, total, s)
        right = self.delim(node.right, total, s)
        out = _hbox([left, body, right])
        return out

    def delim(self, ch, total, s):
        """Delimiter `ch` at least `total` tall, centred on the math axis."""
        if ch is None:
            return Box(0.12 * self.em * s)
        g = self.glyph(ch)
        if g is None:
            return Box(0.3 * self.em * s)
        axis = self.axis * s
        ink = (g.ymax - g.ymin) * s
        if total <= ink * 1.08:
            dy = axis - (g.ymin + g.ymax) / 2 * s
            box = Box(g.advance * s, g.ymax * s + dy, -(g.ymin * s + dy))
            box.items.append(("g", ch, 0.0, dy, s, s))
            return box
        pieces = _ASSEMBLY.get(ch)
        if pieces and total > ink * 1.6:
            box = self.assemble(pieces, total, s)
            if box is not None:
                return box
        sy = total / (g.ymax - g.ymin)
        stretch = sy / s - 1
        if ch in _STRAIGHT_DELIMS:
            sx = s
        elif ch in _WIDE_DELIMS:
            sx = s * min(1 + 0.5 * stretch, 2.5)
        else:
            sx = s * min(1 + 0.2 * stretch, 1.6)
        y0 = axis - total / 2
        box = Box(g.advance * sx, y0 + total, -y0)
        box.items.append(("g", ch, 0.0, y0 - g.ymin * sy, sx, sy))
        return box

    def assemble(self, pieces, total, s):
        top_ch, ext_ch, bot_ch, mid_ch = pieces
        glyphs = [self.metrics(c) for c in (top_ch, ext_ch, bot_ch)]
        mid = self.metrics(mid_ch) if mid_ch else None
        if None in glyphs or (mid_ch and mid is None):
            return None
        top, ext, bot = glyphs
        fixed = (top.ymax - top.ymin) + (bot.ymax - bot.ymin) + ((mid.ymax - mid.ymin) if mid else 0.0)
        fixed *= s
        k = min(1.0, total / fixed)
        gap = max(0.0, total - fixed) / (2 if mid else 1)
        y = self.axis * s - total / 2
        out = Box(max(top.advance, ext.advance, bot.advance, mid.advance if mid else 0.0) * s, y + total, -y)

        def piece(ch, g, height):
            nonlocal y
            sy = height / (g.ymax - g.ymin)
            out.items.append(("g", ch, 0.0, y - g.ymin * sy, s, sy))
            y += height

        def extender():
            if gap > 1e-6:
                piece(ext_ch, ext, gap)

        piece(bot_ch, bot, (bot.ymax - bot.ymin) * s * k)
        extender()
        if mid:
            piece(mid_ch, mid, (mid.ymax - mid.ymin) * s * k)
            extender()
        piece(top_ch, top, (top.ymax - top.ymin) * s * k)
        return out

    # -- accents --------------------------------------------------------------

    def accent(self, node, st):
        s = st.size
        base = self.node(node.body, st.cramp())[0]
        mark = node.mark
        g = self.metrics(mark)
        if g is None:
            mark, g = node.fallback, self.glyph(node.fallback)
            if g is None:
                return base
            # A spacing accent sits wherever the font put it; lift it so its
            # ink starts just above the x-height, like the combining marks.
            lift = self.xh * 1.08 - g.ymin
        else:
            lift = 0.0
        ink_w = (g.xmax - g.xmin) * s
        sx = s
        if node.wide and base.width * 0.9 > ink_w:
            sx = s * min(base.width * 0.9 / ink_w, 3.0)
        # Combining marks are drawn for an x-height letter; raise them by
        # however much taller the base is (TeX's rule 12 in reverse).
        dy = max(0.0, base.height - self.xh * s) + lift * s
        skew = base.italic * 0.6
        cx = base.width / 2 + skew
        x = cx - (g.xmin + g.xmax) / 2 * sx
        out = Box(base.width, max(base.height, g.ymax * s + dy), base.depth)
        out.add(base, 0.0, 0.0)
        out.items.append(("g", mark, x, dy, sx, s))
        out.italic = base.italic
        return out

    def wide_mark(self, node, st):
        s = st.size
        base = self.node(node.body, st.cramp() if node.above else st)[0]
        g = self.glyph(node.ch)
        if g is None:
            return base
        ink_w = g.xmax - g.xmin
        sx = max(s, base.width / ink_w)
        gap = 0.1 * self.v * s
        out = Box(base.width, base.height, base.depth)
        out.add(base, 0.0, 0.0)
        x = (base.width - ink_w * sx) / 2 - g.xmin * sx
        if node.above:
            y = base.height + gap - g.ymin * s
            out.height = y + g.ymax * s
        else:
            y = -base.depth - gap - g.ymax * s
            out.depth = -(y + g.ymin * s)
        out.items.append(("g", node.ch, x, y, sx, s))
        return out

    def overline(self, node, st):
        s = st.size
        base = self.node(node.body, st.cramp() if node.above else st)[0]
        theta = self.rule * s
        out = Box(base.width, base.height, base.depth)
        out.add(base, 0.0, 0.0)
        if node.above:
            y = base.height + 3 * theta
            out.rect(0.0, y, base.width, y + theta)
            out.height = y + 2 * theta
        else:
            y = -base.depth - 3 * theta
            out.rect(0.0, y - theta, base.width, y)
            out.depth = -y + 2 * theta
        return out

    # -- arrays ---------------------------------------------------------------

    def array(self, node, st):
        kind = node.kind
        if kind == "small":
            cell_st = Style(2)
        elif kind in ("aligned", "gathered"):
            cell_st = Style(st.level)
        else:
            cell_st = Style(max(st.level, 1))
        s = cell_st.size if kind == "small" else st.size
        em, v = self.em * s, self.v * s
        ncols = max(len(row) for row in node.rows)

        if node.align:
            align = (node.align + node.align[-1] * ncols)[:ncols]
        elif kind == "aligned":
            align = "rl" * ncols
        else:
            align = "c" * ncols

        boxes = []
        for row in node.rows:
            out_row = []
            for c, cell in enumerate(row):
                if kind == "aligned" and c % 2 == 1:
                    cell = [Group([]), *cell]   # so a leading = gets its space, as in amsmath
                out_row.append(self.hlist(cell, cell_st))
            boxes.append(out_row)

        col_w = [0.0] * ncols
        for row in boxes:
            for c, box in enumerate(row):
                col_w[c] = max(col_w[c], box.width)

        if kind == "aligned":
            gaps = [0.0 if c % 2 == 0 else 2 * em for c in range(ncols - 1)]
        elif kind == "cases":
            gaps = [1 * em] * (ncols - 1)
        elif kind == "small":
            gaps = [0.5 * em] * (ncols - 1)
        else:
            gaps = [1 * em] * (ncols - 1)
        col_x = [0.0]
        for c in range(1, ncols):
            col_x.append(col_x[-1] + col_w[c - 1] + gaps[c - 1])
        width = col_x[-1] + col_w[-1] if ncols else 0.0

        baseline = 1.2 * v
        jot = 0.3 * v if kind in ("aligned", "gathered") else 0.0
        row_h = [max([b.height for b in row] + [0.7 * baseline]) for row in boxes]
        row_d = [max([b.depth for b in row] + [0.3 * baseline]) for row in boxes]
        total = sum(row_h) + sum(row_d) + jot * (len(boxes) - 1)
        top = self.axis * st.size + total / 2
        out = Box(width, top, total - top)
        y = top
        for r, row in enumerate(boxes):
            y -= row_h[r]
            for c, box in enumerate(row):
                a = align[c]
                slack = col_w[c] - box.width
                x = col_x[c] + (slack if a == "r" else slack / 2 if a == "c" else 0.0)
                out.add(box, x, y)
            y -= row_d[r] + jot
        return out


def layout(tree, metrics):
    """(Box at display style, set of glyphs the font couldn't supply)."""
    engine = _Layout(metrics)
    box = engine.node(tree, Style(0))[0]
    return box, engine.missing
