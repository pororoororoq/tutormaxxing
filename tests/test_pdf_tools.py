"""Tests for the tutor skill's PDF helper (.claude/skills/tutor/scripts/pdf_tools.py).

Run:  cd <repo> && .venv/bin/python -m unittest tests/test_pdf_tools.py -v

The CLI is exercised through subprocesses (with this interpreter, so the venv's pypdf is
used) against fixtures built by tests/fixtures/make_book.py; page-spec and label parsing
are also tested directly by importing the module.
"""
import argparse
import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".claude", "skills", "tutor", "scripts", "pdf_tools.py")
MAKE_BOOK = os.path.join(ROOT, "tests", "fixtures", "make_book.py")
SYSTEM_PYTHON = "/usr/bin/python3"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("pdf_tools_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pdf_tools = load_tool_module()


def run_tool(*args, python=None, cwd=None, env=None, timeout=180):
    """Run pdf_tools.py; returns CompletedProcess with text stdout/stderr."""
    environ = dict(os.environ)
    for key in ("TUTOR_HOME", "TUTOR_PDF_TOOLS_REEXEC", "TUTOR_DEBUG"):
        environ.pop(key, None)
    environ["PYTHONIOENCODING"] = "utf-8"
    environ.update(env or {})
    return subprocess.run([python or sys.executable, SCRIPT] + [str(a) for a in args],
                          cwd=cwd or ROOT, env=environ, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, encoding="utf-8", timeout=timeout)


def hit_pages(stdout):
    return [int(m.group(1)) for m in re.finditer(r"^pdf (\d+)\b", stdout, re.M)]


def system_python_without_pypdf():
    """Path of a python3 that lacks pypdf, or None."""
    if not os.path.exists(SYSTEM_PYTHON):
        return None
    probe = subprocess.run([SYSTEM_PYTHON, "-c", "import pypdf"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir())
    return SYSTEM_PYTHON if probe.returncode != 0 else None


# ---------------------------------------------------------------------------
# unit level: page specs, labels, TOC lines (no PDFs needed)
# ---------------------------------------------------------------------------

def book_labels():
    """Labels like the fixture book: Cover | i-vi | 1-42 | A-1..A-5 over 54 pages."""
    return pdf_tools.LabelMap([(1, None, "Cover", 1), (2, "/r", "", 1), (8, "/D", "", 1),
                               (50, "/D", "A-", 1)], 54)


class PageSpecTest(unittest.TestCase):
    def assertToolError(self, code, func, *args, **kwargs):
        with self.assertRaises(pdf_tools.ToolError) as ctx:
            func(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))
        return str(ctx.exception)

    def test_pdf_specs(self):
        parse = pdf_tools.parse_page_spec
        self.assertEqual(parse("197-206", 300), list(range(197, 207)))
        self.assertEqual(parse("5,7,9-12", 20), [5, 7, 9, 10, 11, 12])
        self.assertEqual(parse(" 3 , 1-2 ,", 20), [1, 2, 3])
        self.assertEqual(parse("7,5-7", 20), [5, 6, 7])
        self.assertEqual(parse("5..7", 20), [5, 6, 7])
        self.assertEqual(parse("40-end", 54), list(range(40, 55)))

    def test_pdf_spec_errors(self):
        for bad in ("", " , ", "abc", "1-2-3", "x-4", "-4", "3-", "A-1", "xii"):
            msg = self.assertToolError(2, pdf_tools.parse_page_spec, bad, 54)
            self.assertIn("page spec", msg)
        self.assertIn("backwards", self.assertToolError(2, pdf_tools.parse_page_spec, "9-5", 54))
        for bad in ("0", "55", "50-60"):
            msg = self.assertToolError(4, pdf_tools.parse_page_spec, bad, 54)
            self.assertIn("1-54", msg)

    def test_roman_and_letters(self):
        self.assertEqual(pdf_tools.roman_to_int("xiv"), 14)
        self.assertEqual(pdf_tools.roman_to_int("XLII"), 42)
        for bad in ("iiii", "Mix", "abc", "", "vx"):
            self.assertIsNone(pdf_tools.roman_to_int(bad), bad)
        self.assertEqual(pdf_tools.int_to_roman(1994), "mcmxciv")
        letters = pdf_tools.LabelMap([(1, "/A", "", 1)], 30)
        self.assertEqual([letters.label(p) for p in (1, 26, 27, 28)], ["A", "Z", "AA", "BB"])
        self.assertEqual(letters.lookup("AA"), 27)

    def test_label_map(self):
        labels = book_labels()
        self.assertEqual([labels.label(p) for p in (1, 2, 7, 8, 49, 50, 54)],
                         ["Cover", "i", "vi", "1", "42", "A-1", "A-5"])
        self.assertEqual(labels.lookup("iv"), 5)
        self.assertEqual(labels.lookup("IV"), 5)          # case-insensitive fallback
        self.assertEqual(labels.lookup("A-3"), 52)
        self.assertEqual(labels.lookup("Cover"), 1)
        self.assertIsNone(labels.lookup("xii"))
        self.assertIsNone(labels.lookup("A-9"))
        self.assertEqual([labels.describe(s) for s in labels.spans],
                         ["pdf 1 → Cover", "pdf 2-7 → i-vi", "pdf 8-49 → 1-42 (offset +7)",
                          "pdf 50-54 → A-1..A-5"])
        self.assertFalse(labels.trivial())
        self.assertTrue(pdf_tools.LabelMap([(1, "/D", "", 1)], 10).trivial())

    def test_printed_specs_with_labels(self):
        resolve, labels = pdf_tools.resolve_printed_spec, book_labels()
        self.assertEqual(resolve("25-29", 54, labels), list(range(32, 37)))
        self.assertEqual(resolve("ii-iv", 54, labels), [3, 4, 5])
        self.assertEqual(resolve("A-1..A-3", 54, labels), [50, 51, 52])
        self.assertEqual(resolve("A-1-A-3", 54, labels), [50, 51, 52])
        self.assertEqual(resolve("a-2", 54, labels), [51])
        self.assertEqual(resolve("vi,1, Cover", 54, labels), [1, 7, 8])
        self.assertEqual(resolve("V", 54, labels), [6])   # case-insensitive fallback
        msg = self.assertToolError(4, resolve, "xii", 54, labels)
        self.assertIn("Cover, i-vi, 1-42, A-1..A-5", msg)
        self.assertToolError(4, resolve, "A-9", 54, labels)
        self.assertIn("before", self.assertToolError(2, resolve, "29-25", 54, labels))
        self.assertToolError(2, resolve, " , ", 54, labels)

    def test_printed_specs_with_offset(self):
        resolve = pdf_tools.resolve_printed_spec
        self.assertEqual(resolve("25-29", 54, None, 7), list(range(32, 37)))
        self.assertEqual(resolve("1,3", 54, None, 7), [8, 10])
        self.assertEqual(resolve("181-183", 5, None, -180), [1, 2, 3])  # excerpt PDFs
        self.assertIn("no page labels", self.assertToolError(4, resolve, "ii", 54, None, 7))
        self.assertIn("outside", self.assertToolError(4, resolve, "60", 54, None, 7))
        self.assertIn("--offset", self.assertToolError(2, resolve, "25", 54, None, None))
        # trivial labels (1..N) carry no information: an offset is required
        trivial = pdf_tools.LabelMap([(1, "/D", "", 1)], 54)
        self.assertToolError(2, resolve, "25", 54, trivial, None)
        # an explicit offset wins for numbers; other labels still use the page labels
        self.assertEqual(resolve("25,A-1", 54, book_labels(), 0), [25, 50])

    def test_compress_and_runs(self):
        self.assertEqual(pdf_tools.compress_pages([12, 5, 7, 9, 10, 11]), "5,7,9-12")
        self.assertEqual(pdf_tools.runs([5, 7, 9, 10, 11]), [(5, 5), (7, 7), (9, 11)])

    def test_toc_line_parsing(self):
        parse = pdf_tools._toc_parse_line
        self.assertEqual(parse("3.4 The Chain Rule ........ 181"), ("3.4 The Chain Rule", "181"))
        self.assertEqual(parse("3.4 The Chain Rule........181"), ("3.4 The Chain Rule", "181"))
        self.assertEqual(parse("Chapter 3 Derivatives 150"), ("Chapter 3 Derivatives", "150"))
        self.assertEqual(parse("Preface . . . . . . xii"), ("Preface", "xii"))
        self.assertEqual(parse("Preface ix"), ("Preface", "ix"))
        self.assertEqual(parse("Appendix A Tables ......... A-1"), ("Appendix A Tables", "A-1"))
        for not_toc in ("Part II", "3.4 181", "Figure 3.2 Graph of f ..... 12", "Just words"):
            self.assertIsNone(parse(not_toc), not_toc)
        levels = pdf_tools.toc_levels([("Preface", "ix"), ("Chapter 3 Derivatives", "150"),
                                       ("3.4 The Chain Rule", "181"), ("3.4.1 Proof", "185"),
                                       ("Review Exercises", "190"), ("Index", "I-1")])
        self.assertEqual([lvl for lvl, _, _ in levels], [0, 0, 1, 2, 1, 0])
        # a title wrapped onto two lines, a page number on its own line, and a chapter
        # number on its own line
        lines = pdf_tools._toc_lines("3.4 The Chain Rule and Its\nApplications ...... 181\n"
                                     "3.5 Implicit Differentiation\n190\n"
                                     "Chapter 4\nApplications of Derivatives . . . . 201")
        self.assertEqual([parse(ln) for ln in lines],
                         [("3.4 The Chain Rule and Its Applications", "181"),
                          ("3.5 Implicit Differentiation", "190"),
                          ("Chapter 4 Applications of Derivatives", "201")])
        self.assertIsNone(parse("Chapter 3"))

    def test_python39_compatible_syntax(self):
        with open(SCRIPT, encoding="utf-8") as fh:
            ast.parse(fh.read(), filename=SCRIPT, feature_version=(3, 9))


class SetupLogicTest(unittest.TestCase):
    """`setup` decision logic with pip/venv calls stubbed out (no network)."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="setup_root_")
        self.venv_dir = os.path.join(self.root, "courses", ".venv")
        self.venv_py = pdf_tools.venv_python(self.venv_dir)
        self.calls = []
        self.saved = {name: getattr(pdf_tools, name)
                      for name in ("installed_pypdf_version", "_run", "_can_import")}
        pdf_tools.installed_pypdf_version = lambda: None

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(pdf_tools, name, value)
        shutil.rmtree(self.root, ignore_errors=True)

    def run_setup(self, run, can_import):
        def fake_run(cmd, timeout=900):
            self.calls.append(cmd)
            return run(cmd)
        pdf_tools._run, pdf_tools._can_import = fake_run, can_import
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pdf_tools.cmd_setup(argparse.Namespace(root=self.root))
        self.assertLessEqual(len(out.getvalue().strip().splitlines()), 3, out.getvalue())
        return code, out.getvalue()

    def test_user_install(self):
        code, out = self.run_setup(lambda cmd: (0, ""), lambda py: True)
        self.assertEqual(code, 0)
        self.assertIn("Installed pypdf", out)
        pip = self.calls[0]
        self.assertEqual(pip[:4], [sys.executable, "-m", "pip", "install"])
        self.assertEqual(pip[-1], "pypdf")
        self.assertEqual("--user" in pip, sys.prefix == getattr(sys, "base_prefix", sys.prefix))

    def test_externally_managed_python_gets_a_courses_venv(self):
        def run(cmd):
            if cmd[0] == sys.executable and cmd[1:3] == ["-m", "pip"]:
                return 1, "error: externally-managed-environment\n\nx This environment is ..."
            if cmd[1:3] == ["-m", "venv"]:
                os.makedirs(os.path.dirname(self.venv_py))
                open(self.venv_py, "w").close()
                return 0, ""
            return (0, "") if cmd[0] == self.venv_py else (1, "unexpected call")
        code, out = self.run_setup(run, lambda py: py == self.venv_py)
        self.assertEqual(code, 0, out)
        self.assertIn(self.venv_dir, out)
        self.assertEqual(self.calls[1], [sys.executable, "-m", "venv", self.venv_dir])
        self.assertEqual(self.calls[2][:4], [self.venv_py, "-m", "pip", "install"])

    def test_existing_courses_venv_is_reused(self):
        os.makedirs(os.path.dirname(self.venv_py))
        open(self.venv_py, "w").close()
        code, out = self.run_setup(lambda cmd: (1, "should not be called"), lambda py: True)
        self.assertEqual(code, 0)
        self.assertIn("already installed in", out)
        self.assertEqual(self.calls, [])

    def test_failures_exit_3_with_the_reason(self):
        code, out = self.run_setup(
            lambda cmd: (1, "ERROR: No matching distribution found for pypdf"), lambda py: False)
        self.assertEqual(code, 3)
        self.assertIn("No matching distribution", out)

        def no_venv(cmd):
            if cmd[1:3] == ["-m", "venv"]:
                return 1, "Error: ensurepip is not available"
            return 1, "error: externally-managed-environment"
        self.calls = []
        code, out = self.run_setup(no_venv, lambda py: False)
        self.assertEqual(code, 3)
        self.assertIn("ensurepip is not available", out)
        self.assertIn("python3-venv", out)


# ---------------------------------------------------------------------------
# CLI against the fixture PDFs
# ---------------------------------------------------------------------------

class PdfToolsCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import fpdf  # noqa: F401
            import pypdf  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest("needs pypdf and fpdf2 (%s)" % exc)
        cls.tmp = tempfile.mkdtemp(prefix="pdf_tools_test_")
        subprocess.run([sys.executable, MAKE_BOOK, cls.tmp], check=True)
        with open(os.path.join(cls.tmp, "truth.json"), encoding="utf-8") as fh:
            cls.truth = json.load(fh)
        cls.book = os.path.join(cls.tmp, "book.pdf")
        cls.plain = os.path.join(cls.tmp, "book_plain.pdf")
        cls.exam = os.path.join(cls.tmp, "practice_exam.pdf")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ok(self, *args, **kwargs):
        proc = run_tool(*args, **kwargs)
        self.assertEqual(proc.returncode, 0, "%s\nstdout:\n%s\nstderr:\n%s"
                         % (args, proc.stdout, proc.stderr))
        self.assertNotIn("Traceback", proc.stderr)
        return proc.stdout

    def line_with(self, stdout, needle):
        lines = [ln for ln in stdout.splitlines() if needle in ln]
        self.assertTrue(lines, "no line with %r in:\n%s" % (needle, stdout))
        return lines[0]

    # -- info ----------------------------------------------------------------
    def test_info(self):
        out = self.ok("info", self.book, self.plain, self.exam)
        blocks, cur = [], None
        for line in out.splitlines():
            if not line.startswith("  "):
                cur = [line]
                blocks.append(cur)
            else:
                cur.append(line)
        self.assertEqual([b[0] for b in blocks], [self.book, self.plain, self.exam])
        for block in blocks:
            self.assertLessEqual(len(block), 6, block)
        book, plain, exam = ("\n".join(b) for b in blocks)
        self.assertIn("%d pages" % self.truth["pages"], book)
        self.assertRegex(book, r"outline: [1-9]\d* entries")
        self.assertIn("outline: %d entries" % self.truth["outline_entries"], book)
        self.assertIn('first "Cover", last "A-5"', book)
        self.assertIn("kind: textbook", book)
        self.assertIn("outline: 0 entries · page labels: none", plain)
        self.assertIn("kind: textbook", plain)
        self.assertIn("2 pages", exam)
        self.assertIn("kind: exam", exam)
        self.assertIn("Midterm 1 (Practice)", exam)

    # -- outline -------------------------------------------------------------
    def test_outline_from_bookmarks(self):
        out = self.ok("outline", self.book)
        lines = out.splitlines()
        self.assertEqual(lines[0], "source: bookmarks")
        for num, sec in self.truth["sections"].items():
            line = self.line_with(out, "%s %s" % (num, sec["title"]))
            self.assertEqual(line, "  %s %s · p.%d · pdf %d"
                             % (num, sec["title"], sec["printed_start"], sec["pdf_start"]))
        self.assertIn("Chapter 2 Derivatives · p.13 · pdf 20", lines)
        self.assertIn("Appendix A: Answers to Odd-Numbered Exercises · p.A-1 · pdf %d"
                      % self.truth["answers_appendix"]["pdf_start"], lines)
        self.assertIn("Preface · p.ii · pdf 3", lines)

    def test_outline_toc_text_fallback_with_offset(self):
        out = self.ok("outline", self.plain, "--offset", self.truth["offset"])
        self.assertTrue(out.startswith("source: toc-text"), out)
        self.assertIn("pdf 5-6", out.splitlines()[0])  # where the contents were found
        for num, sec in self.truth["sections"].items():
            line = self.line_with(out, "%s %s" % (num, sec["title"]))
            self.assertIn("p.%d · pdf %d" % (sec["printed_start"], sec["pdf_start"]), line)
            self.assertTrue(line.startswith("  " + num), line)
        # roman / appendix pages can't be mapped with a plain offset
        self.assertIn("Preface · p.ii · pdf ?", out)

    def test_outline_toc_text_fallback_without_offset(self):
        out = self.ok("outline", self.plain)
        self.assertTrue(out.startswith("source: toc-text"), out)
        self.assertIn("2.4 The Chain Rule · p.25 · pdf ?", out)
        hint = self.line_with(out, "hint:")
        self.assertIn("find", hint)
        self.assertIn("--offset", hint)

    def test_outline_toc_text_with_labels(self):
        out = self.ok("outline", self.book, "--toc")
        self.assertTrue(out.startswith("source: toc-text"), out)
        self.assertIn("Preface · p.ii · pdf 3", out)
        self.assertIn("2.4 The Chain Rule · p.25 · pdf 32", out)
        self.assertIn("Appendix B: Table of Derivatives · p.A-4 · pdf %d"
                      % self.truth["derivatives_appendix"]["pdf_start"], out)

    def test_outline_match_and_depth(self):
        lines = self.ok("outline", self.book, "--match", "Chain").splitlines()
        self.assertEqual(lines, ["source: bookmarks", "  2.4 The Chain Rule · p.25 · pdf 32"])
        lines = self.ok("outline", self.book, "--match", "^chapter 3").splitlines()
        self.assertEqual(len(lines), 1 + 1 + 3, lines)   # source, chapter, its 3 sections
        self.assertTrue(lines[1].startswith("Chapter 3 Applications"))
        lines = self.ok("outline", self.book, "--depth", "1").splitlines()[1:]
        self.assertTrue(lines and not any(ln.startswith(" ") for ln in lines), lines)

    # -- labels --------------------------------------------------------------
    def test_labels(self):
        lines = self.ok("labels", self.book).splitlines()
        self.assertEqual(len(lines), len(self.truth["label_ranges"]), lines)
        for line, rng in zip(lines, self.truth["label_ranges"]):
            if rng["pdf_start"] == rng["pdf_end"]:
                self.assertTrue(line.startswith("pdf %d → %s" % (rng["pdf_start"], rng["first"])))
            else:
                sep = ".." if "-" in rng["first"] else "-"
                self.assertTrue(line.startswith("pdf %d-%d → %s%s%s" % (
                    rng["pdf_start"], rng["pdf_end"], rng["first"], sep, rng["last"])), line)
        self.assertIn("(offset +%d)" % self.truth["offset"], lines[2])
        out = self.ok("labels", self.plain)
        self.assertIn("no page labels", out)
        self.assertLessEqual(len(out.splitlines()), 2)

    # -- find ----------------------------------------------------------------
    def test_find_convention_in_preface(self):
        out = self.ok("find", self.book, "natural logarithm")
        self.assertEqual(hit_pages(out), [self.truth["log_convention_pdf_page"]])
        self.assertIn("pdf 4 (p.iii): ", out)
        self.assertIn("log x denotes the natural logarithm", out)

    def test_find_chain_rule(self):
        sec = self.truth["sections"]["2.4"]
        out = self.ok("find", self.book, "Chain Rule")
        pages = hit_pages(out)
        self.assertIn(sec["pdf_start"], pages)
        self.assertIn(self.truth["toc_pdf_pages"][0], pages)
        self.assertEqual(pages, sorted(pages))

    def test_find_printed_pages_filter(self):
        sec = self.truth["sections"]["2.4"]
        want = set(range(sec["pdf_start"], sec["pdf_end"] + 1))
        spec = "%d-%d" % (sec["printed_start"], sec["printed_end"])
        for args in ((self.book, "chain rule", "--pages", spec, "--printed"),
                     (self.plain, "chain rule", "--pages", spec, "--printed",
                      "--offset", self.truth["offset"])):
            pages = hit_pages(self.ok("find", *args))
            self.assertIn(sec["pdf_start"], pages)
            self.assertTrue(set(pages) <= want, pages)

    def test_find_truncation_and_misses(self):
        out = self.ok("find", self.book, "the", "--max", "2")
        self.assertEqual(len(hit_pages(out)), 2)
        self.assertRegex(out.splitlines()[2], r"^\(\+\d+ more")
        self.assertIn('no hits for "zebra"', self.ok("find", self.book, "zebra"))
        out = self.ok("find", self.book, r"f[′']\(g\(x\)\)[·*]g[′']\(x\)", "--regex")
        self.assertIn(self.truth["sections"]["2.4"]["pdf_start"], hit_pages(out))

    # -- text ----------------------------------------------------------------
    def test_text_printed_section_starts(self):
        secs = self.truth["sections"]
        spec = ",".join(str(s["printed_start"]) for s in secs.values())
        out = self.ok("text", self.book, "--pages", spec, "--printed", "--max-chars", "100000")
        chunks = re.split(r"^--- (pdf \d+ \(p\.[^)]+\)) ---$", out, flags=re.M)[1:]
        pages = dict(zip(chunks[0::2], chunks[1::2]))
        self.assertEqual(len(pages), len(secs))
        for num, sec in secs.items():
            ref = "pdf %d (p.%d)" % (sec["pdf_start"], sec["printed_start"])
            self.assertIn("%s %s" % (num, sec["title"]), pages[ref])
        one = self.ok("text", self.plain, "--pages", "25", "--printed", "--offset", "7")
        self.assertTrue(one.startswith("--- pdf 32 (p.25) ---\n"), one[:80])
        self.assertIn("2.4 The Chain Rule", one)

    def test_text_limits_notes_and_out(self):
        out = self.ok("text", self.book, "--pages", "32-36", "--max-chars", "300")
        self.assertIn("[truncated at 300 chars", out)
        self.assertLess(len(out), 1200)
        out = self.ok("text", self.book, "--pages", "vi", "--printed")
        self.assertIn("little or no text", out)
        self.assertIn("split", self.line_with(out, "note:"))
        dest = os.path.join(self.tmp, "out", "sec.txt")
        out = self.ok("text", self.book, "--pages", "32-36", "--out", dest)
        self.assertLessEqual(len(out.strip().splitlines()), 2)
        with open(dest, encoding="utf-8") as fh:
            saved = fh.read()
        self.assertEqual(len(re.findall(r"^--- pdf \d+", saved, re.M)), 5)
        self.assertIn("recall the convention for", saved)

    # -- split ---------------------------------------------------------------
    def test_split_chunks(self):
        from pypdf import PdfReader
        out_dir = os.path.join(self.tmp, "chunks")
        paths = self.ok("split", self.book, "--pages", "3-30", "--out", out_dir).split()
        self.assertEqual(len(paths), 3)
        total, source = 0, PdfReader(self.book)
        for path in paths:
            self.assertTrue(os.path.isabs(path) and os.path.isfile(path), path)
            m = re.fullmatch(r"book_pdf(\d+)-(\d+)\.pdf", os.path.basename(path))
            self.assertTrue(m, path)
            first, last = int(m.group(1)), int(m.group(2))
            reader = PdfReader(path)
            self.assertEqual(len(reader.pages), last - first + 1)
            self.assertLessEqual(len(reader.pages), 10)
            self.assertEqual(reader.pages[0].extract_text(),
                             source.pages[first - 1].extract_text())
            total += len(reader.pages)
        self.assertEqual(total, 28)
        # printed ranges, several runs
        paths = self.ok("split", self.book, "--pages", "25-29,A-1..A-2", "--printed",
                        "--out", out_dir).split()
        self.assertEqual([os.path.basename(p) for p in paths],
                         ["book_pdf32-36.pdf", "book_pdf50-51.pdf"])

    def test_split_drops_links_and_honors_size_limit(self):
        from pypdf import PdfReader
        out_dir = os.path.join(self.tmp, "chunks_small")
        # the contents page links to every chapter; copying links would drag those pages in
        (path,) = self.ok("split", self.book, "--pages", "5", "--out", out_dir).split()
        self.assertLess(os.path.getsize(path), 0.6 * os.path.getsize(self.book))
        self.assertEqual(len(PdfReader(path).pages), 1)
        proc = run_tool("split", self.book, "--pages", "8-9", "--out", out_dir,
                        "--max-mb", "0.001")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([os.path.basename(p) for p in proc.stdout.split()],
                         ["book_pdf8-8.pdf", "book_pdf9-9.pdf"])
        self.assertIn("warning: pdf 8 alone is", proc.stderr)

    # -- errors --------------------------------------------------------------
    def assertFails(self, code, *args):
        proc = run_tool(*args)
        self.assertEqual(proc.returncode, code, "%s -> %s" % (args, proc.stderr))
        self.assertNotIn("Traceback", proc.stderr + proc.stdout)
        err = proc.stderr.strip()
        self.assertTrue(err.startswith("error:"), err)
        self.assertEqual(len(err.splitlines()), 1, err)
        return err

    def test_errors(self):
        self.assertIn("not found", self.assertFails(4, "text", self.book + ".missing",
                                                    "--pages", "1"))
        self.assertFails(2, "text", self.book, "--pages", "3-x")
        self.assertIn("1-54", self.assertFails(4, "text", self.book, "--pages", "99"))
        self.assertFails(4, "text", self.book, "--pages", "xii", "--printed")
        self.assertFails(2, "text", self.plain, "--pages", "25", "--printed")
        self.assertFails(2, "find", self.book, "(", "--regex")
        self.assertFails(2, "outline", self.book, "--match", "(")
        self.assertFails(2, "split", self.book, "--pages", "1")          # --out missing
        self.assertFails(2, "frobnicate")
        not_pdf = os.path.join(self.tmp, "notes.pdf")
        with open(not_pdf, "w") as fh:
            fh.write("just text, not a PDF\n")
        self.assertIn("cannot read", self.assertFails(4, "text", not_pdf, "--pages", "1"))
        proc = run_tool("info", self.book, not_pdf)
        self.assertEqual(proc.returncode, 4)
        self.assertIn("54 pages", proc.stdout)
        self.assertIn("error: cannot read", proc.stdout)

    def test_setup_when_already_installed(self):
        out = self.ok("setup")
        self.assertIn("already installed", out)

    # -- dependency handling -------------------------------------------------
    def test_missing_dependency(self):
        python = system_python_without_pypdf()
        if python is None:
            self.skipTest("%s is missing or already has pypdf" % SYSTEM_PYTHON)
        cwd = tempfile.mkdtemp(prefix="no_courses_")
        try:
            proc = run_tool("info", self.book, python=python, cwd=cwd)
            self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
            output = (proc.stdout + proc.stderr).strip()
            self.assertEqual(output, 'pypdf is not installed. Fix: python3 "%s" setup' % SCRIPT)
            # help and usage errors work without pypdf
            self.assertEqual(run_tool("-h", python=python, cwd=cwd).returncode, 0)
            self.assertEqual(run_tool("text", python=python, cwd=cwd).returncode, 2)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "POSIX shell wrapper")
    def test_reexec_into_courses_venv(self):
        python = system_python_without_pypdf()
        if python is None:
            self.skipTest("%s is missing or already has pypdf" % SYSTEM_PYTHON)
        root = tempfile.mkdtemp(prefix="tutor_root_")
        try:
            bin_dir = os.path.join(root, "courses", ".venv", "bin")
            os.makedirs(bin_dir)
            os.makedirs(os.path.join(root, "courses", "calc1"))
            fake = os.path.join(bin_dir, "python")   # stands in for a venv with pypdf
            with open(fake, "w") as fh:
                fh.write('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable)
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            # found by walking up from a directory inside the project
            proc = run_tool("labels", self.book, python=python,
                            cwd=os.path.join(root, "courses", "calc1"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("pdf 8-49 → 1-42 (offset +7)", proc.stdout)
            # found through --root (after the subcommand) from an unrelated directory
            proc = run_tool("labels", self.book, "--root", root, python=python,
                            cwd=tempfile.gettempdir())
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("A-1..A-5", proc.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
