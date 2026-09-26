#!/usr/bin/env python3
r"""Render tutor Markdown (LaTeX math + plot blocks) to a printable, offline HTML page.

Usage
-----
    render.py IN.md [--out OUT.html] [--title TITLE] [--exam] [--no-open]

The tutor writes Markdown with LaTeX math and ```plot blocks; this script turns it
into a standalone page that opens in the student's browser and prints cleanly
(students take mock exams from these pages on paper).

  --out      output file, or an existing folder to write STEM.html into
             (default: IN.md's folder and stem, with .html)
  --title    page title (default: the first "# heading", else the file name)
  --exam     mock-exam layout: a header with Name / Time allowed / "no aids"
             lines; each question (a "## " heading, or a paragraph starting with
             **Q1.**) is kept on one page and followed by a ~6 cm blank work
             area.  A "## " heading whose section contains **Qn.** paragraphs is
             a section title, not a question.  A leading "# " heading becomes
             the exam title.
  --no-open  don't open a browser (same as env TUTOR_NO_OPEN=1)

stdout: the absolute path of the page on the first line, then one
"warning: FILE:LINE: ..." line per problem (e.g. a plot line that failed to parse).

How the page works
------------------
The Markdown is embedded in assets/print.html as a JSON string and rendered in
the browser by the vendored marked + KaTeX.  Those are copied next to the page
into _assets/ (only when missing or when assets/vendor/VERSIONS.txt changed) and
referenced relatively, so the page works offline and doesn't depend on where
this skill is installed.

Math: $...$ or \(...\) inline; $$...$$ or \[...\] display (may span lines);
\$ is a literal dollar sign; nothing inside `code spans` or fenced code blocks is
treated as math.  Raw HTML (e.g. an inline <svg>) passes through unchanged.

Plot blocks
-----------
Fenced ``plot`` blocks are turned into inline SVG here, at render time::

    ```plot
    title: f(x) = x^2 - 1 and its tangent at x = 1
    x: -3..3
    y: -2..8            (optional; auto-ranged with padding and outlier clipping)
    f(x) = x^2 - 1
    g(x) = 2*x - 2
    points: (1, 0), (-1, 0)
    vline: 1            (optional; also hline: 0; comma-separate several)
    ```

* One curve per line, ``name(x) = expr`` or ``y = expr``, sampled at 600
  points.  Lines break where the function is undefined and at jumps and poles
  (tan, 1/x, floor).
* ``x`` defaults to -5..5.  Range ends and coordinates may be constant
  expressions, e.g. ``x: -2*pi..2*pi`` (ticks are then labelled in multiples of pi).
* ``title`` is shown above the plot ($...$ math in it is rendered) and is the
  SVG's aria-label.  Lines starting with ``#`` are comments.
* A block that can't be drawn becomes an error note in the page plus a warning
  on stdout; a single bad line is skipped with a warning.

Expressions go through a small safe evaluator built on ``ast`` (a whitelist;
nothing is passed to eval): numbers, ``x``, ``pi``, ``e``, ``+ - * / % **``
(``^`` also means power), unary ``+``/``-``, parentheses, and calls to sin cos
tan asin acos atan sinh cosh tanh exp log ln log10 sqrt abs floor ceil.  ``log``
is the natural log (same as ``ln``); ``log(x, b)`` is log base b.  There is NO
implicit multiplication: write ``2*x``, ``3*(x + 1)``, ``x*sin(x)``, not ``2x``,
``3(x + 1)`` or ``x sin x``.  A negative number raised to a fraction with an odd
denominator gives the real root, so ``x^(1/3)`` is drawn for negative x too.
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import math
import operator
import os
import re
import shutil
import sys
import warnings as _warnings
import webbrowser
from fractions import Fraction
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
VENDOR_DIR = ASSETS_DIR / "vendor"
TEMPLATE_PATH = ASSETS_DIR / "print.html"
OUT_ASSETS_DIRNAME = "_assets"


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

class ExprError(ValueError):
    """An expression can't be parsed or uses something outside the whitelist."""


def _floor(v):
    return float(math.floor(v))


def _ceil(v):
    return float(math.ceil(v))


def _pow(base, exp):
    """base ** exp over the reals (never returns a complex number)."""
    if base < 0 and exp != math.floor(exp):
        # Real odd roots, as a graphing calculator draws them: (-8)^(1/3) = -2.
        frac = Fraction(exp).limit_denominator(99)
        if frac.denominator % 2 == 1 and abs(float(frac) - exp) < 1e-9:
            mag = (-base) ** exp
            return -mag if frac.numerator % 2 else mag
        raise ValueError("negative base with a fractional power")
    return base ** exp


FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp, "log": math.log, "ln": math.log, "log10": math.log10,
    "sqrt": math.sqrt, "abs": abs, "floor": _floor, "ceil": _ceil,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
MAX_EXPR_CHARS = 300

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: _pow,
}
_UNARYOPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_NODE_NAMES = {
    "Attribute": "attribute access (a.b)", "Subscript": "indexing (a[b])",
    "Lambda": "lambda", "ListComp": "a comprehension", "SetComp": "a comprehension",
    "DictComp": "a comprehension", "GeneratorExp": "a generator expression",
    "Compare": "a comparison", "BoolOp": "and/or", "IfExp": "if/else",
    "List": "a list", "Tuple": "a tuple (stray comma?)", "Dict": "a dict",
    "Set": "a set", "Starred": "*args", "NamedExpr": ":=", "JoinedStr": "an f-string",
    "Await": "await", "Yield": "yield", "YieldFrom": "yield",
    "BitXor": "^ as xor", "BitAnd": "&", "BitOr": "|", "LShift": "<<",
    "RShift": ">>", "FloorDiv": "//", "MatMult": "@", "Not": "not", "Invert": "~",
}
_NORMALIZE = (("\u2212", "-"), ("\u00d7", "*"), ("\u00b7", "*"), ("\u22c5", "*"),
              ("\u03c0", "pi"), ("^", "**"))
# Hints for "2x", "3.5 x", "(x+1)(x-1)", "x sin(x)": used only after a syntax error.
_IMPLICIT_MULT = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*[A-Za-z_(]|\)\s*[\w(]|\b(?:x|pi|e)\s+[\w(]")


def _describe(node):
    name = type(node).__name__
    return _NODE_NAMES.get(name, name)


def compile_expr(text, allow_x=True):
    """Compile a plot expression into a function f(x) -> float, without eval.

    Allowed: numbers, x (unless allow_x is False), pi, e, + - * / % ** (^ is
    power), unary +/-, parentheses and calls to the whitelisted FUNCTIONS.
    Multiplication must be explicit (2*x, not 2x).  Raises ExprError for
    anything else: attributes, subscripts, lambdas, comprehensions, other names,
    keyword arguments, strings, ...

    The returned function may raise ArithmeticError / ValueError (e.g. 1/0,
    sqrt(-1)); the plotter treats those x values as undefined.
    """
    src = str(text).strip()
    for old, new in _NORMALIZE:
        src = src.replace(old, new)
    if not src:
        raise ExprError("empty expression")
    if len(src) > MAX_EXPR_CHARS:
        raise ExprError("expression is too long (max %d characters)" % MAX_EXPR_CHARS)
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            tree = ast.parse(src, mode="eval")
    except SyntaxError:
        shown = str(text).strip()
        if _IMPLICIT_MULT.search(shown):
            raise ExprError("could not parse %r: multiplication must be explicit "
                            "(write 2*x, not 2x; x*sin(x), not x sin(x))" % shown) from None
        raise ExprError("could not parse %r (syntax error)" % shown) from None
    except (ValueError, RecursionError, MemoryError):
        raise ExprError("could not parse %r" % str(text).strip()) from None
    return _compile_node(tree.body, allow_x)


def _compile_node(node, allow_x):
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ExprError("only plain numbers are allowed, not %r" % (value,))
        try:
            value = float(value)  # floats, so 9**9**9 overflows instead of growing an int
        except OverflowError:
            raise ExprError("number too large") from None
        return lambda x: value

    if isinstance(node, ast.Name):
        name = node.id
        if name == "x":
            if not allow_x:
                raise ExprError("x can't be used here (a constant number is expected)")
            return lambda x: x
        if name in CONSTANTS:
            value = CONSTANTS[name]
            return lambda x: value
        if name in FUNCTIONS:
            raise ExprError("%s is a function: write %s(...)" % (name, name))
        raise ExprError("unknown name %r (allowed: x, pi, e and the functions %s)"
                        % (name, ", ".join(FUNCTIONS)))

    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ExprError("%s is not allowed" % _describe(node.op))
        left = _compile_node(node.left, allow_x)
        right = _compile_node(node.right, allow_x)
        return lambda x: op(left(x), right(x))

    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            raise ExprError("%s is not allowed" % _describe(node.op))
        operand = _compile_node(node.operand, allow_x)
        return lambda x: op(operand(x))

    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, (ast.Constant, ast.BinOp, ast.UnaryOp, ast.Call)) or (
                isinstance(func, ast.Name) and func.id in ("x", "pi", "e")):
            raise ExprError("multiplication must be explicit: write a*(b), not a(b)")
        if not isinstance(func, ast.Name):
            raise ExprError("%s is not allowed in plot expressions" % _describe(func))
        name = func.id
        if name not in FUNCTIONS:
            raise ExprError("unknown function %r (allowed: %s)" % (name, ", ".join(FUNCTIONS)))
        if node.keywords:
            raise ExprError("keyword arguments are not allowed")
        nargs = len(node.args)
        if not (nargs == 1 or (name == "log" and nargs == 2)):
            raise ExprError("%s() takes exactly one argument" % name)
        fn = FUNCTIONS[name]
        args = [_compile_node(arg, allow_x) for arg in node.args]
        if nargs == 1:
            arg0 = args[0]
            return lambda x: fn(arg0(x))
        arg0, arg1 = args
        return lambda x: fn(arg0(x), arg1(x))

    raise ExprError("%s is not allowed in plot expressions" % _describe(node))


def _safe_call(fn, x):
    """f(x) as a finite float, or None where f is undefined / infinite."""
    try:
        y = fn(x)
        if math.isfinite(y):
            return float(y)
    except (ArithmeticError, ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Plot blocks -> inline SVG
# ---------------------------------------------------------------------------

class PlotError(ValueError):
    """A plot line or block is malformed."""


PLOT_WIDTH = 560
PLOT_HEIGHT = 336                # 0.6 aspect for plot + axis labels; legend rows go below
MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM, MARGIN_LEFT = 22, 20, 30, 50
N_SAMPLES = 600
DEFAULT_X_RANGE = (-5.0, 5.0)

# Dark, print-friendly series colors, each with its own dash pattern so curves
# stay distinguishable in grayscale print.  Checked as a categorical set on
# white: slots 1-3 pass all-pairs CVD separation; slot 4 is in the 6-8 band,
# which is acceptable only because of the dash patterns + legend.  Slots 5-6
# are neutral and rely on dash pattern alone.
SERIES_STYLES = (
    ("#1d5fb8", ""),                   # blue, solid
    ("#c4410c", "7 5"),                # vermillion, dashed
    ("#12805a", "12 5 0.5 5"),         # green, dash-dot
    ("#8e3f8c", "0.5 4.5"),            # plum, dotted
    ("#474747", "16 6"),               # charcoal, long dash
    ("#474747", "9 5 0.5 5 0.5 5"),    # charcoal, dash-dot-dot
)
INK = "#1a1a1a"
INK_SOFT = "#4a4a4a"
GRID = "#e3e3e3"
FRAME = "#c6c6c6"
AXIS = "#5a5a5a"
REF_LINE = "#6e6e6e"
SANS = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
SERIF = "Georgia, 'Times New Roman', serif"

_PLOT_KEY = re.compile(r"^([A-Za-z]+)\s*:\s*(.*)$")
_PLOT_FUNC = re.compile(r"^([A-Za-z][A-Za-z0-9_']*)\s*\(\s*x\s*\)\s*=\s*(.+)$")
_PLOT_Y = re.compile(r"^y\s*=\s*(.+)$")
_KEY_ALIASES = {
    "title": "title", "x": "x", "y": "y", "points": "points", "point": "points",
    "vline": "vline", "vlines": "vline", "hline": "hline", "hlines": "hline",
}


def _split_top_level(text, sep=","):
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _const(text):
    """Evaluate a constant expression such as '-pi/2' or '3'."""
    fn = compile_expr(text, allow_x=False)
    value = _safe_call(fn, 0.0)
    if value is None:
        raise PlotError("%r is not a finite number" % text.strip())
    return value


def parse_range(text):
    """'a..b' (or 'a, b' / '[a, b]') -> (a, b) with a < b."""
    t = text.strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    if ".." in t:
        parts = t.split("..", 1)
    else:
        parts = _split_top_level(t, ",")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise PlotError("a range must look like -3..3, got %r" % text.strip())
    lo, hi = _const(parts[0]), _const(parts[1])
    if not lo < hi:
        raise PlotError("range %r must go from smaller to larger" % text.strip())
    if not hi - lo < 1e300:
        raise PlotError("range %r is too large" % text.strip())
    return lo, hi


def parse_points(text):
    """'(1, 0), (-1, 0)' -> [(1.0, 0.0), (-1.0, 0.0)]."""
    groups, outside, depth, start = [], [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise PlotError("unbalanced parentheses in points")
            if depth == 0:
                groups.append(text[start:i])
        elif depth == 0:
            outside.append(ch)
    if depth != 0:
        raise PlotError("unbalanced parentheses in points")
    if "".join(outside).strip(" \t,;") or not groups:
        raise PlotError("points must look like (1, 0), (-1, 0)")
    points = []
    for inner in groups:
        coords = _split_top_level(inner, ",")
        if len(coords) != 2:
            raise PlotError("a point needs exactly two coordinates: (%s)" % inner.strip())
        points.append((_const(coords[0]), _const(coords[1])))
    return points


def parse_numbers(text):
    values = [_const(p) for p in _split_top_level(text, ",") if p.strip()]
    if not values:
        raise PlotError("expected one or more numbers")
    return values


def parse_plot_block(lines, first_lineno=1):
    """Parse the lines inside a plot fence.

    Returns (spec, problems): problems are (line number, message) pairs for
    lines that were skipped.  A bad x/y range is not skippable (the plot would
    silently show a different window), so it goes to spec["errors"] instead.
    """
    spec = {"title": None, "x": None, "y": None, "funcs": [],
            "points": [], "vlines": [], "hlines": [], "errors": []}
    problems = []
    for offset, raw in enumerate(lines):
        lineno = first_lineno + offset
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            m = _PLOT_KEY.match(line)
            if m:
                key = _KEY_ALIASES.get(m.group(1).lower())
                value = m.group(2).strip()
                if key is None:
                    raise PlotError("unknown setting %r (known: title, x, y, points, "
                                    "vline, hline)" % m.group(1))
                if key == "title":
                    spec["title"] = value or None
                elif key in ("x", "y"):
                    try:
                        spec[key] = parse_range(value)
                    except (ExprError, PlotError) as exc:
                        spec["errors"].append((lineno, "bad %s range: %s" % (key, exc)))
                elif key == "points":
                    spec["points"].extend(parse_points(value))
                elif key == "vline":
                    spec["vlines"].extend(parse_numbers(value))
                else:
                    spec["hlines"].extend(parse_numbers(value))
                continue
            m = _PLOT_FUNC.match(line)
            if m:
                expr = m.group(2).strip()
                label = "%s(x) = %s" % (m.group(1), expr)
            else:
                m = _PLOT_Y.match(line)
                if not m:
                    raise PlotError("not a plot line (expected 'f(x) = ...', 'y = ...' "
                                    "or 'setting: value')")
                expr = m.group(1).strip()
                label = "y = %s" % expr
            spec["funcs"].append((label, compile_expr(expr), lineno))
        except (ExprError, PlotError) as exc:
            problems.append((lineno, "%s -- line skipped: %s" % (exc, line)))
    return spec, problems


def _quantile(sorted_vals, q):
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _domain_edge(fn, x_in, y_in, x_out):
    """Bisect from a defined sample toward an undefined one; return the last defined point."""
    for _ in range(48):
        xm = 0.5 * (x_in + x_out)
        if xm == x_in or xm == x_out:
            break
        ym = _safe_call(fn, xm)
        if ym is None:
            x_out = xm
        else:
            x_in, y_in = xm, ym
    return (x_in, y_in)


def _find_jump(fn, xa, ya, xb, yb, tol):
    """Is there a jump or pole between two samples?

    Bisects toward the larger change.  A continuous function's change shrinks
    below tol; a jump/pole keeps it.  Returns the two points hugging the break
    (so the curve runs right up to it) or None if the function is continuous.
    """
    for _ in range(60):
        if abs(yb - ya) <= tol:
            return None
        xm = 0.5 * (xa + xb)
        if xm == xa or xm == xb:
            break
        ym = _safe_call(fn, xm)
        if ym is None:  # undefined point inside: a gap, hug it from both sides
            return _domain_edge(fn, xa, ya, xm), _domain_edge(fn, xb, yb, xm)
        if abs(ym - ya) >= abs(yb - ym):
            xb, yb = xm, ym
        else:
            xa, ya = xm, ym
    return (xa, ya), (xb, yb)


def _trace(fn, xs, ys, scale):
    """Split samples into continuous runs, breaking at gaps, jumps and poles."""
    trigger, tol = 0.05 * scale, 0.01 * scale
    segs, cur, broken = [], [], False
    for i, y in enumerate(ys):
        if y is None:
            broken = True
            if cur:
                cur.append(_domain_edge(fn, xs[i - 1], ys[i - 1], xs[i]))
                segs.append(cur)
                cur = []
            continue
        if not cur:
            if i > 0:  # previous sample undefined: start right at the domain edge
                cur.append(_domain_edge(fn, xs[i], y, xs[i - 1]))
            cur.append((xs[i], y))
            continue
        if abs(y - ys[i - 1]) > trigger:
            jump = _find_jump(fn, xs[i - 1], ys[i - 1], xs[i], y, tol)
            if jump:
                broken = True
                cur.append(jump[0])
                segs.append(cur)
                cur = [jump[1]]
        cur.append((xs[i], y))
    if cur:
        segs.append(cur)
    return segs, broken


def _auto_y_range(series, points, hlines, xmin, xmax):
    lo, hi = math.inf, -math.inf
    for s in series:
        vals = sorted(y for y in s["ys"] if y is not None)
        a, b = vals[0], vals[-1]
        if s["broken"] and len(vals) >= 10:
            # Outlier clipping, only for curves with gaps/jumps/poles, so the
            # arms of 1/x or tan don't squash everything else flat.
            q1, q9 = _quantile(vals, 0.1), _quantile(vals, 0.9)
            spread = q9 - q1
            if spread > 0:
                a, b = max(a, q1 - spread), min(b, q9 + spread)
        lo, hi = min(lo, a), max(hi, b)
    for px_, py_ in points:
        if xmin <= px_ <= xmax:
            lo, hi = min(lo, py_), max(hi, py_)
    for h in hlines:
        lo, hi = min(lo, h), max(hi, h)
    if lo == math.inf:
        lo, hi = -1.0, 1.0
    if not hi - lo < 1e300:
        raise PlotError("the values are too large to plot; give a y range such as 'y: -10..10'")
    if hi - lo <= 1e-9 * max(1.0, abs(lo), abs(hi)):
        lo, hi = lo - 1.0, hi + 1.0
    span = hi - lo
    if 0 < lo <= 0.25 * span:        # nearly touching the x-axis: include it
        lo = 0.0
    elif 0 > hi >= -0.25 * span:
        hi = 0.0
    pad = 0.06 * (hi - lo)
    return lo - pad, hi + pad


def _nice_step(span, target):
    raw = span / target
    mag = 10.0 ** math.floor(math.log10(raw))
    for mult in (1.0, 2.0, 5.0, 10.0):
        if mult * mag >= raw * (1 - 1e-9):
            return mult * mag
    return 10.0 * mag


def _pi_step(lo, hi, target):
    """A multiple of pi as tick step, if both ends are multiples of pi/4."""
    quarter = math.pi / 4

    def is_multiple(v):
        k = v / quarter
        return abs(k - round(k)) < 1e-6

    if not (is_multiple(lo) and is_multiple(hi)):
        return None
    span = hi - lo
    candidates = ([quarter] if span <= math.pi + 1e-9 else []) + [
        math.pi / 2 * 2 ** k for k in range(12)]
    for step in candidates:
        if step >= span / target - 1e-12:
            return step
    return None


def _minus(text):
    return text.replace("-", "\u2212")


def _pi_label(v):
    frac = Fraction(v / math.pi).limit_denominator(12)
    num, den = abs(frac.numerator), frac.denominator
    if num == 0:
        return "0"
    text = "\u03c0" if num == 1 else "%d\u03c0" % num
    if den != 1:
        text += "/%d" % den
    return ("\u2212" if frac < 0 else "") + text


def _num_label(v, step):
    if abs(v) < abs(step) * 1e-6:
        return "0"
    decimals = 0
    while decimals < 8 and abs(round(step, decimals) - step) > abs(step) * 1e-6:
        decimals += 1
    if decimals >= 8 or abs(v) >= 1e7:
        return _minus("%.4g" % v)
    return _minus("%.*f" % (decimals, v))


def _ticks(lo, hi, target):
    """[(value, label)] at nice positions in [lo, hi]."""
    step = _pi_step(lo, hi, target)
    if step:
        label = _pi_label
    else:
        step = _nice_step(hi - lo, target)

        def label(v):
            return _num_label(v, step)
    k0 = int(math.ceil(lo / step - 1e-9))
    k1 = int(math.floor(hi / step + 1e-9))
    return [(k * step, label(k * step)) for k in range(k0, k1 + 1)]


def _f(v):
    """Compact SVG coordinate."""
    s = "%.1f" % v
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


def _svg_text(text):
    """Escape for HTML/SVG text and attributes.  Also hide $, \\ and ` so the
    page's math/code scanner never sees delimiters inside the SVG."""
    return (html.escape(str(text), quote=True)
            .replace("$", "&#36;").replace("\\", "&#92;").replace("`", "&#96;"))


def _plain_title(text):
    """Title without math delimiters or Markdown emphasis (for aria-label / <title>)."""
    t = re.sub(r"\\[()\[\]]", "", text)
    t = t.replace("$", "").replace("`", "").replace("**", "")
    return re.sub(r"\s+", " ", t).strip()


_SUPERSCRIPTS = str.maketrans("0123456789-", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207b")


def _superscripts(text):
    """'x^2', 'x**-1' -> 'x²', 'x⁻¹' (integer exponents only)."""
    return re.sub(r"(?:\^|\*\*)(-?\d+)(?![\d.])",
                  lambda m: m.group(1).translate(_SUPERSCRIPTS), text)


def _pretty_label(label):
    """'f(x) = 2*x^2 - 1' -> 'f(x) = 2x² − 1' for the legend."""
    s = _superscripts(label).replace("**", "^")
    s = re.sub(r"\bpi\b", "\u03c0", s)
    s = re.sub(r"\bsqrt\(", "\u221a(", s)
    s = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)\s*\*\s*(?=[xe](?![A-Za-z0-9_])|\u03c0|\()", r"\1", s)
    s = s.replace("*", "\u00b7")
    s = _minus(s)
    return s if len(s) <= 70 else s[:67] + "..."


def _simplify_offscreen(pts, ymin, ymax):
    """Drop points whose neighbours are off-screen on the same side (invisible)."""
    out, last = [], len(pts) - 1
    for i, (x, y) in enumerate(pts):
        if 0 < i < last:
            ya, yb = pts[i - 1][1], pts[i + 1][1]
            if (y > ymax and ya > ymax and yb > ymax) or (y < ymin and ya < ymin and yb < ymin):
                continue
        out.append((x, y))
    return out


class _Frame:
    """Data -> SVG pixel mapping for one plot, and where its axes are drawn."""

    def __init__(self, xmin, xmax, ymin, ymax):
        self.xmin, self.xmax, self.ymin, self.ymax = xmin, xmax, ymin, ymax
        self.left, self.right = MARGIN_LEFT, PLOT_WIDTH - MARGIN_RIGHT
        self.top, self.bottom = MARGIN_TOP, PLOT_HEIGHT - MARGIN_BOTTOM
        x_in, y_in = xmin <= 0 <= xmax, ymin <= 0 <= ymax
        self.ax = self.px(0.0) if x_in else self.left      # the y-axis
        self.ay = self.py(0.0) if y_in else self.bottom    # the x-axis
        self.origin = x_in and y_in

    def px(self, x):
        return self.left + (x - self.xmin) / (self.xmax - self.xmin) * (self.right - self.left)

    def py(self, y):
        return self.bottom - (y - self.ymin) / (self.ymax - self.ymin) * (self.bottom - self.top)

    def contains(self, x, y):
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax


def _line(x1, y1, x2, y2):
    return '<line x1="%s" y1="%s" x2="%s" y2="%s"/>' % (_f(x1), _f(y1), _f(x2), _f(y2))


def _dash_attr(dash):
    return ' stroke-dasharray="%s"' % dash if dash else ""


def _svg_grid_and_axes(fr, xticks, yticks):
    grid = [_line(fr.px(v), fr.top, fr.px(v), fr.bottom) for v, _ in xticks]
    grid += [_line(fr.left, fr.py(v), fr.right, fr.py(v)) for v, _ in yticks]
    axes = [_line(fr.left, fr.ay, fr.right, fr.ay), _line(fr.ax, fr.top, fr.ax, fr.bottom)]
    axes += [_line(fr.px(v), fr.ay - 3, fr.px(v), fr.ay + 3) for v, _ in xticks]
    axes += [_line(fr.ax - 3, fr.py(v), fr.ax + 3, fr.py(v)) for v, _ in yticks]
    return ('<g stroke="%s" stroke-width="1">%s</g>' % (GRID, "".join(grid))
            + '<rect x="%s" y="%s" width="%s" height="%s" fill="none" stroke="%s" '
              'stroke-width="1"/>' % (fr.left, fr.top, fr.right - fr.left, fr.bottom - fr.top, FRAME)
            + '<g stroke="%s" stroke-width="1.2">%s</g>' % (AXIS, "".join(axes)))


def _svg_reference_lines(fr, spec, clip_id, warnings):
    lines = []
    for v in spec["vlines"]:
        if fr.xmin <= v <= fr.xmax:
            lines.append(_line(fr.px(v), fr.top, fr.px(v), fr.bottom))
        else:
            warnings.append((None, "vline at x = %g is outside the x range" % v))
    for v in spec["hlines"]:
        if fr.ymin <= v <= fr.ymax:
            lines.append(_line(fr.left, fr.py(v), fr.right, fr.py(v)))
        else:
            warnings.append((None, "hline at y = %g is outside the y range" % v))
    if not lines:
        return ""
    return ('<g clip-path="url(#%s)" stroke="%s" stroke-width="1.25" stroke-dasharray="5 4">'
            '%s</g>' % (clip_id, REF_LINE, "".join(lines)))


def _svg_curves(fr, series, clip_id):
    span = fr.ymax - fr.ymin
    lo, hi = fr.ymin - 2 * span, fr.ymax + 2 * span   # keep coordinates sane near poles
    out = []
    for n, s in enumerate(series):
        color, dash = SERIES_STYLES[n % len(SERIES_STYLES)]
        polylines = []
        for seg in s["segs"]:
            pts = _simplify_offscreen([(x, min(max(y, lo), hi)) for x, y in seg], fr.ymin, fr.ymax)
            if len(pts) >= 2:
                polylines.append('<polyline points="%s"/>' % " ".join(
                    "%s,%s" % (_f(fr.px(x)), _f(fr.py(y))) for x, y in pts))
        out.append('<g clip-path="url(#%s)" fill="none" stroke="%s" stroke-width="2" '
                   'stroke-linecap="round" stroke-linejoin="round"%s>%s</g>'
                   % (clip_id, color, _dash_attr(dash), "".join(polylines)))
    return "".join(out)


def _svg_points(fr, points, warnings):
    dots = []
    for x, y in points:
        if fr.contains(x, y):
            dots.append('<circle cx="%s" cy="%s" r="4"/>' % (_f(fr.px(x)), _f(fr.py(y))))
        else:
            warnings.append((None, "point (%g, %g) is outside the plot range" % (x, y)))
    if not dots:
        return ""
    # A 2px white ring keeps dots legible where they sit on a curve.
    return ('<g fill="%s" stroke="#fff" stroke-width="4" paint-order="stroke">%s</g>'
            % (INK, "".join(dots)))


def _svg_tick_labels(fr, xticks, yticks):
    labels = []
    for v, text in xticks:
        if not (fr.origin and abs(v) < 1e-12):
            labels.append('<text x="%s" y="%s" text-anchor="middle">%s</text>'
                          % (_f(fr.px(v)), _f(fr.ay + 15), _svg_text(text)))
    for v, text in yticks:
        if not (fr.origin and abs(v) < 1e-12):
            labels.append('<text x="%s" y="%s" text-anchor="end" dy="0.32em">%s</text>'
                          % (_f(fr.ax - 6), _f(fr.py(v)), _svg_text(text)))
    if fr.origin:  # one "0" for both axes
        labels.append('<text x="%s" y="%s" text-anchor="end">0</text>'
                      % (_f(fr.ax - 5), _f(fr.ay + 15)))
    # White halo (paint-order stroke) so curves crossing a label don't hide it.
    return ('<g fill="%s" font-size="11.5" stroke="#fff" stroke-width="3" '
            'stroke-linejoin="round" paint-order="stroke">%s</g>'
            % (INK_SOFT, "".join(labels))
            + '<g fill="%s" font-family="%s" font-size="15" font-style="italic">'
              '<text x="%s" y="%s">x</text><text x="%s" y="%s" text-anchor="middle">y</text></g>'
              % (INK, SERIF, fr.right + 4, _f(fr.ay - 5), _f(fr.ax), fr.top - 7))


def _svg_legend(series):
    """Legend rows under the plot: a line sample in the series style, label in ink.

    Returns (svg, extra height)."""
    items, lx, row = [], MARGIN_LEFT, 0
    right = PLOT_WIDTH - MARGIN_RIGHT
    for n, s in enumerate(series):
        color, dash = SERIES_STYLES[n % len(SERIES_STYLES)]
        text = _pretty_label(s["label"])
        width = 30 + len(text) * 7.0
        if lx > MARGIN_LEFT and lx + width > right:
            lx, row = MARGIN_LEFT, row + 1
        y = PLOT_HEIGHT + 12 + row * 20
        items.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="2" '
                     'stroke-linecap="round"%s/><text x="%s" y="%s" dy="0.32em">%s</text>'
                     % (_f(lx), y, _f(lx + 24), y, color, _dash_attr(dash), _f(lx + 30), y,
                        _svg_text(text)))
        lx += width + 22
    if not items:
        return "", 0
    return '<g fill="%s" font-size="12.5">%s</g>' % (INK, "".join(items)), (row + 1) * 20 + 6


def build_plot(spec, index=1, notes=()):
    """Draw a parsed plot spec.  Returns (html, warnings); raises PlotError."""
    if not spec["funcs"] and not spec["points"]:
        raise PlotError("nothing to plot: add a curve such as 'f(x) = x^2' or "
                        "'points: (1, 2)'")
    xmin, xmax = spec["x"] or DEFAULT_X_RANGE
    warnings = []

    # 1. Sample every curve.
    xs = [xmin + (xmax - xmin) * i / (N_SAMPLES - 1) for i in range(N_SAMPLES)]
    series = []
    for label, fn, lineno in spec["funcs"]:
        ys = [_safe_call(fn, x) for x in xs]
        if all(y is None for y in ys):
            warnings.append((lineno, "%s has no real values for x in [%g, %g]; not drawn"
                             % (label, xmin, xmax)))
            continue
        series.append({"label": label, "fn": fn, "ys": ys})
    if not series and not spec["points"]:
        raise PlotError("no curve has real values on the x range")
    if len(series) > len(SERIES_STYLES):
        warnings.append((None, "more than %d curves in one plot; styles repeat"
                         % len(SERIES_STYLES)))

    # 2. Break curves at gaps/jumps/poles (this needs a rough vertical scale).
    finite = sorted(y for s in series for y in s["ys"] if y is not None)
    if spec["y"]:
        scale = spec["y"][1] - spec["y"][0]
    elif finite:
        scale = _quantile(finite, 0.9) - _quantile(finite, 0.1)
        if not scale > 0:
            scale = (finite[-1] - finite[0]) or max(1.0, abs(finite[0]))
    else:
        scale = 1.0
    for s in series:
        s["segs"], s["broken"] = _trace(s["fn"], xs, s["ys"], scale)

    # 3. Draw.
    ymin, ymax = spec["y"] or _auto_y_range(series, spec["points"], spec["hlines"], xmin, xmax)
    fr = _Frame(xmin, xmax, ymin, ymax)
    xticks, yticks = _ticks(xmin, xmax, 8), _ticks(ymin, ymax, 6)
    clip_id = "tutor-plot-%d-clip" % index
    legend, legend_height = _svg_legend(series)
    height = PLOT_HEIGHT + legend_height

    title = spec["title"]
    if title:
        aria = _plain_title(title)
    elif series:
        aria = "Graph of " + "; ".join(s["label"] for s in series)
    else:
        aria = "Plot of points"
    svg = "".join([
        '<svg xmlns="http://www.w3.org/2000/svg" class="plot-svg" role="img" aria-label="%s" '
        'width="%d" height="%d" viewBox="0 0 %d %d" font-family="%s" font-size="12">'
        % (_svg_text(aria), PLOT_WIDTH, height, PLOT_WIDTH, height, SANS),
        '<defs><clipPath id="%s"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath></defs>'
        % (clip_id, fr.left, fr.top, fr.right - fr.left, fr.bottom - fr.top),
        '<rect width="%d" height="%d" fill="#fff"/>' % (PLOT_WIDTH, height),
        _svg_grid_and_axes(fr, xticks, yticks),
        _svg_reference_lines(fr, spec, clip_id, warnings),
        _svg_curves(fr, series, clip_id),
        _svg_points(fr, spec["points"], warnings),
        _svg_tick_labels(fr, xticks, yticks),
        legend,
        "</svg>",
    ])

    parts = ['<figure class="plot">']
    if title:
        # HTML-escaped but $...$ kept, so math in the title is rendered by KaTeX;
        # a title without math just gets x^2 -> x² for readability.
        shown = title if re.search(r"\$|\\[(\[]", title) else _superscripts(title)
        parts.append("<figcaption>%s</figcaption>" % html.escape(shown, quote=False))
    parts.append(svg)
    if notes:
        parts.append('<p class="plot-note screen-only">%s</p>' % _svg_text(
            "Skipped: " + "; ".join(notes)))
    parts.append("</figure>")
    return "".join(parts), warnings


def _plot_error_html(message, lines, fence_lineno):
    source = "\n".join(["```plot"] + list(lines) + ["```"])
    return ('<div class="plot-error" role="note"><strong>Plot error</strong> (line %d): %s'
            '<pre>%s</pre></div>' % (fence_lineno, _svg_text(message),
                                     _svg_text(source).replace("\n", "&#10;")))


def render_plot_block(lines, fence_lineno=1, index=1):
    """Plot fence contents -> (one line of HTML, [(line number, warning)])."""
    spec, problems = parse_plot_block(lines, fence_lineno + 1)
    if spec["errors"]:
        lineno, message = spec["errors"][0]
        return _plot_error_html(message, lines, lineno), problems + spec["errors"]
    notes = ["line %d: %s" % item for item in problems]
    try:
        figure, more = build_plot(spec, index, notes)
    except PlotError as exc:
        message = str(exc)
    except Exception as exc:  # never let one odd plot take down the whole page
        message = "could not draw this plot (%s: %s)" % (type(exc).__name__, exc)
    else:
        return figure, problems + [(ln or fence_lineno, msg) for ln, msg in more]
    return _plot_error_html(message, lines, fence_lineno), problems + [(fence_lineno, message)]


# ---------------------------------------------------------------------------
# Markdown preprocessing
# ---------------------------------------------------------------------------

# Fences are matched leniently (any indentation, inside blockquotes); the page's
# JavaScript uses the same rules, so both agree on what is code.
_FENCE_OPEN = re.compile(r"^(?P<prefix>[ \t]*(?:>[ \t]*)*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_FENCE_CLOSE = re.compile(r"^[ \t]*(?:>[ \t]*)*(`{3,}|~{3,})[ \t]*$")
_CONTAINER_PREFIX = re.compile(r"^[ \t]*(?:>[ \t]?)*")


def _fence_open(line):
    m = _FENCE_OPEN.match(line)
    if not m or (m.group("fence")[0] == "`" and "`" in m.group("info")):
        return None
    return m


def _closes(line, fence):
    m = _FENCE_CLOSE.match(line)
    return bool(m) and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)


def convert_plot_blocks(md_text, source_name="input"):
    """Replace ```plot fences with inline SVG figures.

    Returns (markdown, warnings).  Each figure is emitted as a single line that
    starts with an HTML comment, which makes it a raw HTML block (CommonMark
    type 2) that ends on that same line, so the surrounding Markdown is
    unaffected and no blank lines are needed.
    """
    lines = md_text.split("\n")
    out, warnings, i, index = [], [], 0, 0
    while i < len(lines):
        m = _fence_open(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        fence, prefix = m.group("fence"), m.group("prefix")
        j = i + 1
        while j < len(lines) and not _closes(lines[j], fence):
            j += 1
        info = m.group("info").split()
        if info and info[0].lower() == "plot":
            index += 1
            body = lines[i + 1:j]
            if ">" in prefix:
                body = [_CONTAINER_PREFIX.sub("", line, count=1) for line in body]
            if j >= len(lines):
                warnings.append("%s:%d: plot block has no closing fence" % (source_name, i + 1))
            figure, problems = render_plot_block(body, i + 1, index)
            warnings.extend("%s:%d: %s" % (source_name, ln, msg) for ln, msg in problems)
            out.append(prefix + "<!--plot-->" + figure)
        else:
            out.extend(lines[i:j + 1])
        i = j + 1
    return "\n".join(out), warnings


def first_heading(md_text):
    """Text of the first '# ' heading outside code fences, or None."""
    fence = None
    for line in md_text.split("\n"):
        if fence:
            if _closes(line, fence):
                fence = None
            continue
        m = _fence_open(line)
        if m:
            fence = m.group("fence")
            continue
        m = re.match(r"^ {0,3}#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", line)
        if m:
            return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

def markdown_json(md_text):
    """JSON string literal that is safe inside <script type="application/json">."""
    return (json.dumps(md_text, ensure_ascii=True)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def build_page(md_text, title, exam=False, template=None):
    if template is None:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "TITLE": html.escape(_plain_title(title) or "Notes", quote=True),
        "ASSETS": OUT_ASSETS_DIRNAME,
        "BODY_CLASS": "exam" if exam else "notes",
        "MARKDOWN_JSON": markdown_json(md_text),
    }
    # One pass, so placeholder-like text inside the values is never substituted.
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _vendor_files():
    return sorted(p for p in VENDOR_DIR.rglob("*") if p.is_file())


def _assets_current(dest):
    try:
        if (dest / "VERSIONS.txt").read_bytes() != (VENDOR_DIR / "VERSIONS.txt").read_bytes():
            return False
        for src in _vendor_files():
            if (dest / src.relative_to(VENDOR_DIR)).stat().st_size != src.stat().st_size:
                return False
    except OSError:
        return False
    return True


def ensure_assets(out_dir):
    """Copy the vendored libraries to OUT_DIR/_assets unless already current.

    Returns True if files were copied.  VERSIONS.txt is copied last, so an
    interrupted copy is redone next time.
    """
    dest = Path(out_dir) / OUT_ASSETS_DIRNAME
    if _assets_current(dest):
        return False
    versions = VENDOR_DIR / "VERSIONS.txt"
    for src in _vendor_files():
        if src == versions:
            continue
        target = dest / src.relative_to(VENDOR_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    shutil.copyfile(versions, dest / "VERSIONS.txt")
    return True


def _title_from_stem(stem):
    words = re.sub(r"[_-]+", " ", stem).strip()
    return words[:1].upper() + words[1:] if words else "Notes"


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _has_display():
    # On Linux without a display, webbrowser may fall back to a console browser
    # (lynx, w3m) and wait for it to exit, which would hang the tutor's shell.
    if sys.platform.startswith("linux"):
        return any(os.environ.get(k) for k in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER"))
    return True


def output_path(in_path, out_path=None):
    """--out as given (a folder means FOLDER/STEM.html), else IN's folder and stem."""
    src = Path(in_path).expanduser()
    if not out_path:
        return src.with_suffix(".html")
    out = Path(out_path).expanduser()
    return out / (src.stem + ".html") if out.is_dir() else out


def render_file(in_path, out_path=None, title=None, exam=False):
    """Render IN.md to HTML.  Returns (output path, warnings)."""
    src = Path(in_path).expanduser()
    out = output_path(src, out_path)
    text = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    md, warnings = convert_plot_blocks(text, src.name)
    page_title = title or first_heading(text) or _title_from_stem(src.stem)
    page = build_page(md, page_title, exam=exam)
    out.parent.mkdir(parents=True, exist_ok=True)
    ensure_assets(out.parent)
    out.write_text(page, encoding="utf-8")
    return out.resolve(), warnings


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="render.py",
        description="Render tutor Markdown (LaTeX math + ```plot blocks) to a "
                    "printable, offline HTML page.")
    parser.add_argument("input", metavar="IN.md", help="Markdown file to render")
    parser.add_argument("--out", metavar="OUT.html",
                        help="output file or folder (default: next to IN.md, with .html)")
    parser.add_argument("--title", help="page title (default: first '# ' heading)")
    parser.add_argument("--exam", action="store_true",
                        help="mock-exam layout: name/time header, work area after each question")
    parser.add_argument("--no-open", action="store_true",
                        help="don't open the page in a browser (or set TUTOR_NO_OPEN=1)")
    args = parser.parse_args(argv)

    src = Path(args.input).expanduser()
    if not src.is_file():
        parser.error("input file not found: %s" % src)
    out = output_path(src, args.out)
    if out.resolve() == src.resolve():
        parser.error("the output would overwrite the input; pass --out")
    if not TEMPLATE_PATH.is_file() or not (VENDOR_DIR / "VERSIONS.txt").is_file():
        print("render.py: error: skill assets missing under %s" % ASSETS_DIR, file=sys.stderr)
        return 1
    try:
        out_path, warnings = render_file(src, out, args.title, args.exam)
    except (OSError, UnicodeDecodeError) as exc:
        print("render.py: error: %s" % exc, file=sys.stderr)
        return 1

    want_open = not args.no_open and not _env_flag("TUTOR_NO_OPEN")
    if want_open and not _has_display():
        want_open = False
        warnings.append("no graphical display found; open the file above in a browser")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(out_path)
    for warning in warnings:
        print("warning: " + warning)
    sys.stdout.flush()
    if want_open:
        try:
            webbrowser.open(Path(out_path).resolve().as_uri())
        except Exception:  # a missing browser must never fail the render
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
