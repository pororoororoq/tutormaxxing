"""Tests for the printable-page renderer, scripts/render.py (stdlib only).

Run: python3 -m unittest tests/test_render.py -v   (or: python3 -m unittest discover tests)

The browser tests load the pages in headless Chromium (env CHROME_BIN overrides the
default path) and are skipped when it isn't installed.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / ".claude" / "skills" / "tutor" / "scripts"
RENDER = SCRIPTS / "render.py"
sys.path.insert(0, str(SCRIPTS))
import render as R  # noqa: E402

CHROME = os.environ.get("CHROME_BIN") or (
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell")
HAVE_CHROME = os.path.isfile(CHROME) and os.access(CHROME, os.X_OK)

SAMPLE = r"""# Chain rule warm-up

Steps:

- differentiate the outer function
- multiply by the derivative of the inner one

If $y = \sin(x^2)$ then $\frac{dy}{dx} = 2x\cos(x^2)$.

$$\int_0^1 x^2\,dx = \frac{1}{3}$$

$$
A = \begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}
$$

Products stay math: $a_1 * b_2 + a_2 * b_1$.

A coffee costs \$5 here.

Code stays literal: `$x$` and `</script>` too.

```text
fenced $y$ stays too
```

```plot
title: f(x) = x^2 - 1 and its tangent at x = 1
x: -3..3
y: -2..8
f(x) = x^2 - 1
g(x) = 2*x - 2
points: (1, 0), (-1, 0)
vline: 1
```

A raw diagram: <svg id="raw-svg" width="40" height="30" viewBox="0 0 40 30"><polygon points="2,28 38,28 20,2" fill="none" stroke="black"/></svg>
"""

EXAM = r"""# Mock Midterm 1

Answer every question and show your work.

**Q1.** Differentiate $f(x) = x^3 - 2x$.

**Q2.** Evaluate $\int_0^2 3x^2\,dx$.

## Q3. Limits

Compute $\lim_{x \to 0} \frac{\sin x}{x}$.
"""


def run_render(md_path, *args):
    env = dict(os.environ, TUTOR_NO_OPEN="1")
    return subprocess.run([sys.executable, str(RENDER), str(md_path), "--no-open"] + list(args),
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)


def embedded_json(page_html):
    """(raw JSON text, decoded Markdown) of the page's <script type="application/json">."""
    m = re.search(r'<script type="application/json" id="md-source">(.*?)</script>', page_html, re.S)
    return m.group(1), json.loads(m.group(1))


def dump_dom(page):
    cmd = [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
           "--virtual-time-budget=8000", "--dump-dom", Path(page).resolve().as_uri()]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120)
    return proc.stdout


def main_content(dom):
    """Only the rendered <main>, not the embedded JSON source (which also contains '$x$')."""
    m = re.search(r'<main[^>]*id="content"[^>]*>(.*?)</main>', dom, re.S)
    return m.group(1) if m else ""


class RenderCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tutor-render-"))
        cls.md = cls.tmp / "page.md"
        cls.md.write_text(SAMPLE, encoding="utf-8")
        cls.proc = run_render(cls.md)
        cls.page = cls.tmp / "page.html"
        cls.html = cls.page.read_text(encoding="utf-8") if cls.page.exists() else ""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_prints_output_path_and_no_warnings(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        lines = self.proc.stdout.splitlines()
        self.assertEqual(lines, [str(self.page.resolve())])

    def test_html_exists_and_assets_copied(self):
        self.assertTrue(self.page.is_file())
        assets = self.tmp / "_assets"
        for rel in ("VERSIONS.txt", "katex/katex.min.js", "katex/katex.min.css",
                    "katex/fonts/KaTeX_Main-Regular.woff2", "katex/LICENSE",
                    "marked/marked.umd.js", "marked/LICENSE"):
            self.assertTrue((assets / rel).is_file(), rel)
        # Linked relatively, so the page works offline and wherever the skill lives.
        self.assertIn('href="_assets/katex/katex.min.css"', self.html)
        self.assertIn('src="_assets/katex/katex.min.js"', self.html)
        self.assertIn('src="_assets/marked/marked.umd.js"', self.html)
        self.assertNotIn("{{", self.html)

    def test_markdown_embedded_as_json(self):
        raw, md = embedded_json(self.html)
        self.assertIn(r"$\frac{dy}{dx} = 2x\cos(x^2)$", md)
        self.assertIn(r"$a_1 * b_2 + a_2 * b_1$", md)
        self.assertIn(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}", md)
        self.assertIn("`</script>`", md)
        self.assertNotIn("<", raw)  # so "</script>" in the Markdown can't end the tag

    def test_plot_became_inline_svg(self):
        _, md = embedded_json(self.html)
        self.assertNotIn("```plot", md)
        svg = re.search(r"<svg [^>]*class=\"plot-svg\".*?</svg>", md, re.S)
        self.assertIsNotNone(svg)
        svg = svg.group(0)
        self.assertIn('role="img"', svg)
        self.assertIn('aria-label="f(x) = x^2 - 1 and its tangent at x = 1"', svg)
        self.assertGreaterEqual(svg.count("<polyline"), 2)   # one per function
        self.assertEqual(svg.count("<circle"), 2)            # the two points
        self.assertIn("f(x) = x² − 1", svg)        # legend label
        self.assertIn("<figcaption>", md)

    def test_assets_copied_only_when_missing_or_changed(self):
        tmp = Path(tempfile.mkdtemp(prefix="tutor-render-assets-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        md = tmp / "a.md"
        md.write_text("# A\n\n$x$\n", encoding="utf-8")
        self.assertEqual(run_render(md).returncode, 0)
        js = tmp / "_assets" / "katex" / "katex.min.js"
        os.utime(js, (1_000_000_000, 1_000_000_000))
        self.assertEqual(run_render(md).returncode, 0)
        self.assertEqual(js.stat().st_mtime, 1_000_000_000)      # up to date: not copied
        (tmp / "_assets" / "VERSIONS.txt").write_text("old\n", encoding="utf-8")
        self.assertEqual(run_render(md).returncode, 0)
        self.assertNotEqual(js.stat().st_mtime, 1_000_000_000)   # VERSIONS changed: copied
        self.assertEqual((tmp / "_assets" / "VERSIONS.txt").read_bytes(),
                         (R.VENDOR_DIR / "VERSIONS.txt").read_bytes())

    def test_out_and_title_options(self):
        tmp = Path(tempfile.mkdtemp(prefix="tutor-render-out-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        md = tmp / "notes.md"
        md.write_text("Some <b>text</b>.\n", encoding="utf-8")
        out = tmp / "print" / "sheet.html"
        proc = run_render(md, "--out", str(out), "--title", "Formula <sheet>")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[0], str(out.resolve()))
        html = out.read_text(encoding="utf-8")
        self.assertIn("<title>Formula &lt;sheet&gt;</title>", html)
        self.assertIn('<body class="notes">', html)
        self.assertTrue((tmp / "print" / "_assets" / "VERSIONS.txt").is_file())
        proc = run_render(md, "--out", str(tmp / "print"))   # a folder: FOLDER/notes.html
        self.assertEqual(proc.stdout.splitlines()[0], str((tmp / "print" / "notes.html").resolve()))
        self.assertIn("<title>Notes</title>", (tmp / "print" / "notes.html").read_text(encoding="utf-8"))

    def test_bad_plot_line_gives_warning_line(self):
        tmp = Path(tempfile.mkdtemp(prefix="tutor-render-warn-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        md = tmp / "w.md"
        md.write_text("Intro\n\n```plot\nx: -2..2\nf(x) = x^2\ng(x) = 2x\n```\n", encoding="utf-8")
        proc = run_render(md)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0], str((tmp / "w.html").resolve()))
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("warning: w.md:6: "), lines[1])
        self.assertIn("explicit", lines[1])

    def test_missing_input_fails(self):
        proc = run_render(Path(tempfile.gettempdir()) / "definitely-missing-tutor.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not found", proc.stderr)

    def test_browser_opening_respects_flags(self):
        tmp = Path(tempfile.mkdtemp(prefix="tutor-render-open-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        md = tmp / "o.md"
        md.write_text("# O\n", encoding="utf-8")
        with mock.patch.object(R.webbrowser, "open") as opener, \
                mock.patch("sys.stdout", new=open(os.devnull, "w", encoding="utf-8")) as devnull:
            self.addCleanup(devnull.close)
            with mock.patch.dict(os.environ, {"TUTOR_NO_OPEN": "1", "DISPLAY": ":0"}):
                R.main([str(md)])
            with mock.patch.dict(os.environ, {"TUTOR_NO_OPEN": "", "DISPLAY": ":0"}):
                R.main([str(md), "--no-open"])
            self.assertEqual(opener.call_count, 0)
            with mock.patch.dict(os.environ, {"TUTOR_NO_OPEN": "", "DISPLAY": ":0"}):
                R.main([str(md)])
            opener.assert_called_once_with((tmp / "o.html").resolve().as_uri())


class SafeEvaluatorTest(unittest.TestCase):
    def test_valid_expression(self):
        f = R.compile_expr("sin(x)^2 + 1/x")
        for x in (1.0, 2.5, -0.3):
            self.assertAlmostEqual(f(x), math.sin(x) ** 2 + 1 / x)
        self.assertAlmostEqual(R.compile_expr("2*pi*e + log10(100) + ln(e) + abs(-2)")(0), 2 * math.pi * math.e + 5)

    def test_rejects_unsafe_or_unknown_syntax(self):
        for src in ("__import__('os')", "x.__class__", "(lambda: 1)()", "[x for x in y]",
                    "open('f')", "x if x else 1", "'abc'", "True", "x < 1", "f(x)",
                    "sin(x=1)", "(1, 2)", "x[0]", "", "2x", "3(x+1)", "x(x+1)", "y"):
            with self.subTest(src=src):
                with self.assertRaises(R.ExprError):
                    R.compile_expr(src)

    def test_implicit_multiplication_message(self):
        with self.assertRaises(R.ExprError) as ctx:
            R.compile_expr("2x + 1")
        self.assertIn("explicit", str(ctx.exception))

    def test_undefined_points_are_none(self):
        self.assertIsNone(R._safe_call(R.compile_expr("sqrt(x)"), -1.0))
        self.assertIsNone(R._safe_call(R.compile_expr("1/x"), 0.0))
        self.assertIsNone(R._safe_call(R.compile_expr("ln(x)"), 0.0))
        self.assertIsNone(R._safe_call(R.compile_expr("x^0.5"), -4.0))   # never complex
        self.assertIsNone(R._safe_call(R.compile_expr("9^9^9"), 0.0))    # overflow, no hang

    def test_real_odd_roots(self):
        self.assertAlmostEqual(R.compile_expr("x^(1/3)")(-8.0), -2.0)
        self.assertAlmostEqual(R.compile_expr("x^(2/3)")(-8.0), 4.0)

    def test_constant_ranges(self):
        self.assertEqual(R.parse_range("-3..3"), (-3.0, 3.0))
        lo, hi = R.parse_range("-2*pi..2*pi")
        self.assertAlmostEqual(hi, 2 * math.pi)
        self.assertAlmostEqual(lo, -2 * math.pi)
        with self.assertRaises(R.ExprError):
            R.parse_range("-x..3")


class PlotBlockTest(unittest.TestCase):
    def test_tan_breaks_at_poles(self):
        html, warnings = R.render_plot_block(["x: -3..3", "y: -5..5", "f(x) = tan(x)"])
        self.assertEqual(warnings, [])
        self.assertEqual(html.count("<polyline"), 3)   # split at -pi/2 and pi/2

    def test_auto_range_and_pi_ticks(self):
        html, warnings = R.render_plot_block(["x: -2*pi..2*pi", "y = 1/x", "f(x) = sin(x)"])
        self.assertEqual(warnings, [])
        self.assertIn("<svg", html)
        self.assertIn("π/2", html)                # ticks in multiples of pi
        self.assertIn('aria-label="Graph of y = 1/x; f(x) = sin(x)"', html)

    def test_bad_line_is_skipped(self):
        html, warnings = R.render_plot_block(["f(x) = x^2", "g(x) = 2x", "colour: red"], fence_lineno=10)
        self.assertEqual([ln for ln, _ in warnings], [12, 13])
        self.assertIn("<svg", html)
        self.assertEqual(html.count("<polyline"), 1)
        self.assertIn('class="plot-note screen-only"', html)

    def test_malformed_block_becomes_error_note(self):
        for lines in (["x: 3..-3", "f(x) = x"], ["title: nothing here"], ["x: -1..1", "f(x) = sqrt(x - 5)"],
                      ["x: 0..1", "f(x) = 1e308*x", "g(x) = -1e308*x"]):
            with self.subTest(lines=lines):
                html, warnings = R.render_plot_block(lines)
                self.assertIn('class="plot-error"', html)
                self.assertNotIn("<svg", html)
                self.assertTrue(warnings)
                self.assertNotIn("$", html)

    def test_plots_inside_code_fences_are_left_alone(self):
        md = "````markdown\n```plot\nf(x) = x\n```\n````\n"
        out, warnings = R.convert_plot_blocks(md)
        self.assertEqual(out, md)
        self.assertEqual(warnings, [])

    def test_title_and_json_helpers(self):
        self.assertEqual(R.first_heading("```\n# not this\n```\n\n# Real title #\n"), "Real title")
        raw = R.markdown_json("</script><!-- & -->")
        self.assertNotIn("<", raw)
        self.assertEqual(json.loads(raw), "</script><!-- & -->")


@unittest.skipUnless(HAVE_CHROME, "headless Chromium not found (set CHROME_BIN)")
class BrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tutor-render-browser-"))
        (cls.tmp / "page.md").write_text(SAMPLE, encoding="utf-8")
        (cls.tmp / "exam.md").write_text(EXAM, encoding="utf-8")
        for name, args in (("page.md", ()), ("exam.md", ("--exam",))):
            proc = run_render(cls.tmp / name, *args)
            assert proc.returncode == 0, proc.stderr
        cls.dom = dump_dom(cls.tmp / "page.html")
        cls.main = main_content(cls.dom)
        cls.exam_dom = dump_dom(cls.tmp / "exam.html")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_math_rendered_without_errors(self):
        self.assertIn('data-render="ok"', self.dom)
        self.assertGreaterEqual(len(re.findall(r'class="katex"', self.main)), 4)
        self.assertNotIn("katex-error", self.main)
        self.assertEqual(self.main.count('class="katex-display"'), 2)

    def test_code_and_literal_dollars_untouched(self):
        self.assertIn("<code>$x$</code>", self.main)
        self.assertIn("<code>&lt;/script&gt;</code>", self.main)
        self.assertIn("fenced $y$ stays too", self.main)
        self.assertIn("costs $5 here", self.main)

    def test_both_svgs_present(self):
        self.assertRegex(self.main, r'<svg [^>]*class="plot-svg')
        self.assertIn('id="raw-svg"', self.main)

    def test_subscripts_and_stars_survive_markdown(self):
        self.assertTrue("<msub>" in self.main or "vlist" in self.main)
        self.assertIn(">a_1 * b_2 + a_2 * b_1</annotation>", self.main)
        self.assertNotIn("<em>", self.main)   # the * and _ were not read as emphasis

    def test_pmatrix_rows(self):
        self.assertIn("\\begin{pmatrix}", self.main)
        self.assertEqual(self.main.count("<mtr>"), 2)

    def test_exam_layout(self):
        main = main_content(self.exam_dom)
        self.assertIn('<body class="exam">', self.exam_dom)
        self.assertEqual(main.count('class="question"'), 3)
        self.assertEqual(main.count('class="work-area"'), 3)
        self.assertRegex(self.exam_dom, r'<h1 class="exam-title">Mock Midterm 1</h1>')
        self.assertIn("Time allowed:", self.exam_dom)
        self.assertNotIn("katex-error", main)

    def test_raw_markdown_fallback_without_assets(self):
        lone = self.tmp / "moved"
        lone.mkdir()
        shutil.copy(self.tmp / "page.html", lone / "page.html")   # no _assets next to it
        dom = dump_dom(lone / "page.html")
        self.assertIn('data-render="fallback"', dom)
        pre = re.search(r'<pre class="md-fallback">(.*?)</pre>', dom, re.S)
        self.assertIsNotNone(pre)
        self.assertIn(r"\frac{dy}{dx}", pre.group(1))


if __name__ == "__main__":
    unittest.main()
