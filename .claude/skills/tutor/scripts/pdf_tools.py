#!/usr/bin/env python3
"""Token-cheap PDF helpers for the tutor skill.

Never bulk-read a textbook: this script does the heavy PDF work locally and prints
small, targeted results.

  setup                       install pypdf (works without pypdf)
  info FILE [FILE...]         pages, size, text layer, outline, labels, kind guess
  outline FILE                section tree:  2.4 The Chain Rule · p.25 · pdf 32
  labels FILE                 printed page labels as ranges (with the pdf offset)
  find FILE TEXT              case-insensitive, a line per page:  pdf 32 (p.25): …snippet…
  text FILE --pages SPEC      page text, separated by  --- pdf 32 (p.25) ---
  split FILE --pages SPEC --out DIR
                              chunk PDFs (<=10 pages, <=19 MB) to view as images

"pdf N" is the N-th page of the file (1-based); "p.X" is the printed page label.
SPEC lists pdf pages: 32-36 | 5,7,9-12 | 40-end.  With --printed it lists printed
pages instead: 25-29 | xii | A-1..A-3 (or A-1-A-3), resolved through the PDF's page
labels, or through --offset N (pdf = printed + N) when the PDF has no labels.

Exit codes: 0 ok, 2 usage, 3 missing dependency, 4 file/page error.
Options per command: pdf_tools.py COMMAND -h
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

EXIT_OK, EXIT_USAGE, EXIT_DEP, EXIT_FILE = 0, 2, 3, 4
SCRIPT = os.path.abspath(__file__)
REEXEC_ENV = "TUTOR_PDF_TOOLS_REEXEC"
TEXT_MIN_CHARS = 40          # a page "has text" with at least this many non-space chars
LETTER_RATIO_MIN = 0.45      # below this share of letters, text is likely math/garbled
TOC_SCAN_PAGES = 40
OUTLINE_MAX_LINES = 150
MB = 1000 * 1000

PdfReader = PdfWriter = None  # bound by load_pypdf()
PYPDF_ERRORS = ()
PYPDF_IMPORT_ERROR = None


class ToolError(Exception):
    """An expected failure: printed as one line, exits with `code`."""

    def __init__(self, message, code=EXIT_FILE):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# dependency bootstrap
# ---------------------------------------------------------------------------

def import_pypdf():
    """The pypdf module, or None when it is missing or broken."""
    global PYPDF_IMPORT_ERROR
    try:
        import pypdf
        return pypdf
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # ImportError, or e.g. a mismatched 'cryptography' panicking
        PYPDF_IMPORT_ERROR = exc
        return None


def load_pypdf():
    global PdfReader, PdfWriter, PYPDF_ERRORS
    pypdf = import_pypdf()
    if pypdf is None:
        return False
    import logging
    import warnings
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore")
    PdfReader, PdfWriter = pypdf.PdfReader, pypdf.PdfWriter
    try:
        from pypdf.errors import PyPdfError
        PYPDF_ERRORS = (PyPdfError,)
    except ImportError:
        PYPDF_ERRORS = ()
    return True


def find_root(explicit=None):
    """Project root: --root, else $TUTOR_HOME, else the first dir up from cwd with courses/."""
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get("TUTOR_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    d = os.path.abspath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, "courses")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def venv_python(venv_dir):
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _same_dir(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def reexec_or_exit(root_arg):
    """pypdf is missing: re-run under <root>/courses/.venv if it exists, else explain the fix."""
    root = find_root(root_arg)
    if root and not os.environ.get(REEXEC_ENV):
        venv_dir = os.path.join(root, "courses", ".venv")
        py = venv_python(venv_dir)
        if os.path.isfile(py) and not _same_dir(sys.prefix, venv_dir):
            os.environ[REEXEC_ENV] = "1"
            argv = [py, SCRIPT] + sys.argv[1:]
            sys.stdout.flush()
            sys.stderr.flush()
            if os.name == "nt":  # execv on Windows detaches; wait for the child instead
                sys.exit(subprocess.call(argv))
            os.execv(py, argv)
    exc = PYPDF_IMPORT_ERROR
    if exc is None or (isinstance(exc, ImportError) and getattr(exc, "name", None) == "pypdf"):
        print('pypdf is not installed. Fix: python3 "%s" setup' % SCRIPT, file=sys.stderr)
    else:
        print('pypdf is installed but fails to import (%s: %s). Fix: python3 "%s" setup'
              % (type(exc).__name__, collapse(str(exc))[:120], SCRIPT), file=sys.stderr)
    sys.exit(EXIT_DEP)


def _run(cmd, timeout=900):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return proc.returncode, proc.stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _can_import(python):
    return _run([python, "-c", "import pypdf"], timeout=120)[0] == 0


def _last_line(text):
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1][:200] if lines else "no output"


def installed_pypdf_version():
    pypdf = import_pypdf()
    return getattr(pypdf, "__version__", "?") if pypdf is not None else None


def cmd_setup(args):
    version = installed_pypdf_version()
    if version:
        print("pypdf %s is already installed for %s." % (version, sys.executable))
        return EXIT_OK
    root = find_root(getattr(args, "root", None)) or os.getcwd()
    venv_dir = os.path.join(root, "courses", ".venv")
    if os.path.isfile(venv_python(venv_dir)) and _can_import(venv_python(venv_dir)):
        print("pypdf is already installed in %s; pdf_tools.py switches to it automatically."
              % venv_dir)
        return EXIT_OK
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet"]
    cmd += [] if in_venv else ["--user"]
    rc, out = _run(cmd + ["pypdf"])
    if rc == 0 and _can_import(sys.executable):
        print("Installed pypdf for %s%s. Ready." % (sys.executable, "" if in_venv else " (--user)"))
        return EXIT_OK
    low = out.lower()
    if "externally-managed-environment" in low:   # PEP 668: Homebrew, Debian/Ubuntu, ...
        reason = "this Python is externally managed"
    elif "no module named pip" in low:
        reason = "this Python has no pip"
    elif rc == 0:
        reason = "pypdf still won't import in this Python"
    else:
        print("Could not install pypdf: %s" % _last_line(out))
        print('Fix by hand: "%s" -m pip install --user pypdf   (then re-run the command)'
              % sys.executable)
        return EXIT_DEP
    # Fall back to a private venv under courses/, which the tools re-exec into.
    os.makedirs(os.path.dirname(venv_dir), exist_ok=True)
    py = venv_python(venv_dir)
    if not os.path.isfile(py):
        rc, out = _run([sys.executable, "-m", "venv", venv_dir])
        if rc != 0 or not os.path.isfile(py):
            print("pypdf needs its own venv (%s), but creating %s failed: %s"
                  % (reason, venv_dir, _last_line(out)))
            print("Fix: install the venv module (e.g. sudo apt install python3-venv), then "
                  "re-run setup.")
            return EXIT_DEP
    rc, out = _run([py, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
                    "pypdf"])
    if rc != 0 or not _can_import(py):
        print("Created %s but installing pypdf into it failed: %s" % (venv_dir, _last_line(out)))
        return EXIT_DEP
    print("Installed pypdf into %s (%s)." % (venv_dir, reason))
    print("pdf_tools.py uses it automatically when run from this project.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# page labels
# ---------------------------------------------------------------------------

_ROMAN = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
          (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))


def int_to_roman(n):
    out = []
    for value, sym in _ROMAN:
        count, n = divmod(n, value)
        out.append(sym * count)
    return "".join(out)


def roman_to_int(s):
    """Value of a canonical roman numeral (either case, not mixed), else None."""
    if not s or not (s.islower() or s.isupper()) or not re.fullmatch(r"[ivxlcdm]+", s, re.I):
        return None
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    low = s.lower()
    total = 0
    for i, ch in enumerate(low):
        v = vals[ch]
        total += -v if i + 1 < len(low) and vals[low[i + 1]] > v else v
    return total if 0 < total < 4000 and int_to_roman(total) == low else None


def int_to_letters(n):
    reps, pos = divmod(n - 1, 26)
    return chr(ord("A") + pos) * (reps + 1)


def letters_to_int(s):
    if not s or not s.isalpha() or not s.isascii() or len(set(s.upper())) != 1:
        return None
    return (len(s) - 1) * 26 + ord(s[0].upper()) - ord("A") + 1


class LabelMap:
    """Printed page labels (the PDF /PageLabels tree) as ranges over 1-based pdf pages."""

    def __init__(self, ranges, n_pages):
        by_start = {}
        for first, style, prefix, start in ranges:
            if 1 <= first <= n_pages:
                by_start[first] = (first, style, prefix or "", max(1, int(start or 1)))
        rs = [by_start[k] for k in sorted(by_start)]
        if not rs or rs[0][0] != 1:
            rs.insert(0, (1, "/D", "", 1))
        self.n_pages = n_pages
        self.spans = []  # (first, last, style, prefix, start)
        for i, (first, style, prefix, start) in enumerate(rs):
            last = rs[i + 1][0] - 1 if i + 1 < len(rs) else n_pages
            self.spans.append((first, last, style, prefix, start))

    @staticmethod
    def _number(style, value):
        if style is None:
            return ""
        if style in ("/r", "/R") and 0 < value < 4000:
            roman = int_to_roman(value)
            return roman if style == "/r" else roman.upper()
        if style in ("/a", "/A") and value > 0:
            letters = int_to_letters(value)
            return letters.lower() if style == "/a" else letters
        return str(value)

    def label(self, pdf):
        for first, last, style, prefix, start in self.spans:
            if first <= pdf <= last:
                return prefix + self._number(style, start + pdf - first)
        return str(pdf)

    def trivial(self):
        """True when the labels just number the pages 1..N (no information)."""
        return len(self.spans) == 1 and self.spans[0][2:] == ("/D", "", 1)

    def _match(self, span, text, fold):
        first, last, style, prefix, start = span
        t, pre = (text.lower(), prefix.lower()) if fold else (text, prefix)
        if not t.startswith(pre):
            return None
        rest = t[len(pre):]
        if style is None:
            return first if rest == "" and prefix else None
        value = None
        if style in ("/r", "/R"):
            value = roman_to_int(rest)
        elif style in ("/a", "/A"):
            value = letters_to_int(rest)
        elif rest.isdigit():
            value = int(rest)
        if value is None or (not fold and self._number(style, value) != rest):
            return None
        pdf = first + value - start
        return pdf if first <= pdf <= last else None

    def lookup(self, text, after=0):
        """pdf page labelled `text` (the first one after pdf `after`, if any)."""
        text = text.strip()
        if not text:
            return None
        for fold in (False, True):
            hits = [p for p in (self._match(s, text, fold) for s in self.spans) if p]
            if hits:
                later = [p for p in hits if p > after]
                return min(later) if later else min(hits)
        return None

    def span_range(self, span):
        first, last, style, prefix, _ = span
        a, b = self.label(first), self.label(last)
        if style is None:
            return a or "(no label)"
        if first == last:
            return a
        return a + (".." if "-" in a + b else "-") + b

    def describe(self, span):
        first, last, style, prefix, start = span
        pages = "pdf %d" % first if first == last else "pdf %d-%d" % (first, last)
        text = "%s → %s" % (pages, self.span_range(span))
        if style is None and first != last:
            text += " (same label on every page)"
        if style == "/D" and not prefix:
            text += " (offset %+d)" % (first - start)
        return text

    def summary(self):
        return ", ".join(self.span_range(s) for s in self.spans)


def read_page_labels(reader, n_pages):
    """LabelMap from the PDF's /PageLabels number tree, or None when absent."""
    try:
        root = reader.trailer["/Root"]
        if "/PageLabels" not in root:
            return None
        tree = root["/PageLabels"].get_object()
    except Exception:
        return None
    ranges = []

    def walk(node, depth):
        try:
            node = node.get_object()
        except Exception:
            return
        if depth > 32 or not isinstance(node, dict):
            return
        nums = node.get("/Nums")
        if nums is not None:
            nums = nums.get_object()
            for i in range(0, len(nums) - 1, 2):
                try:
                    key, val = int(nums[i]), nums[i + 1].get_object()
                except Exception:
                    continue
                if not isinstance(val, dict):
                    continue
                style = val.get("/S")
                style = str(style) if style is not None else None
                if style is not None and style not in ("/D", "/r", "/R", "/a", "/A"):
                    style = "/D"
                try:
                    start = int(val.get("/St", 1))
                except Exception:
                    start = 1
                ranges.append((key + 1, style, str(val.get("/P", "") or ""), start))
        kids = node.get("/Kids")
        if kids is not None:
            for kid in kids.get_object():
                walk(kid, depth + 1)

    walk(tree, 0)
    return LabelMap(ranges, n_pages) if ranges else None


class Pager:
    """Maps pdf pages to printed pages: --offset (for numbers) wins over page labels."""

    def __init__(self, labels, offset=None):
        self.labels = labels if labels is not None and not labels.trivial() else None
        self.offset = offset

    @property
    def known(self):
        return self.labels is not None or self.offset is not None

    def printed(self, pdf):
        if self.offset is not None and pdf - self.offset >= 1:
            return str(pdf - self.offset)
        if self.labels is not None:
            return self.labels.label(pdf) or None
        return None

    def ref(self, pdf):
        p = self.printed(pdf)
        return "pdf %d (p.%s)" % (pdf, p) if p else "pdf %d" % pdf

    def resolve(self, token, after=0):
        """pdf page for one printed page token, or None."""
        token = token.strip()
        if not token:
            return None
        if self.offset is not None and token.isdigit():
            return int(token) + self.offset
        if self.labels is not None:
            return self.labels.lookup(token, after)
        return None


# ---------------------------------------------------------------------------
# page specs
# ---------------------------------------------------------------------------

def parse_page_spec(spec, n_pages):
    """'5,7,9-12' | '40-end' -> sorted unique 1-based pdf pages."""
    items = [s.strip() for s in str(spec).split(",") if s.strip()]
    if not items:
        raise ToolError("empty page spec: use N, N-M or lists like 5,7,9-12", EXIT_USAGE)
    pages = set()
    for item in items:
        m = re.fullmatch(r"(\d+)(?:\s*(?:-|–|\.\.)\s*(\d+|end|last))?", item, re.I)
        if not m:
            raise ToolError('bad page spec "%s": use N, N-M or lists like 5,7,9-12 (1-based '
                            'pdf pages; add --printed for printed page numbers)' % item,
                            EXIT_USAGE)
        a = int(m.group(1))
        b = a if m.group(2) is None else (
            n_pages if m.group(2).lower() in ("end", "last") else int(m.group(2)))
        if b < a:
            raise ToolError('bad page range "%s": it runs backwards' % item, EXIT_USAGE)
        if a < 1 or b > n_pages:
            raise ToolError("page %s is out of range: this PDF has pdf pages 1-%d"
                            % (item, n_pages), EXIT_FILE)
        pages.update(range(a, b + 1))
    return sorted(pages)


def resolve_printed_spec(spec, n_pages, labels=None, offset=None):
    """Printed-page SPEC ('181-186', 'xii', 'A-1..A-4', 'A-1-A-4') -> sorted pdf pages."""
    pager = labels if isinstance(labels, Pager) else Pager(labels, offset)
    if not pager.known:
        raise ToolError("--printed needs page labels, but this PDF has none (or they just "
                        "count 1..N): add --offset N, where pdf page = printed page + N "
                        "(find a heading with `find` to get N)", EXIT_USAGE)
    items = [s.strip() for s in str(spec).split(",") if s.strip()]
    if not items:
        raise ToolError("empty page spec", EXIT_USAGE)
    pages = set()
    for item in items:
        a, b = _printed_range(item, n_pages, pager)
        pages.update(range(a, b + 1))
    return sorted(pages)


def _printed_range(item, n_pages, pager):
    if ".." in item:
        a, _, b = item.partition("..")
        candidates = [(a, b)]
    else:
        candidates = [(item, None)]
        candidates += [(item[:m.start()], item[m.end():]) for m in re.finditer("[-–—]", item)]
    for a_tok, b_tok in candidates:
        pa = pager.resolve(a_tok)
        if pa is None:
            continue
        pb = pa if b_tok is None else pager.resolve(b_tok, after=pa - 1)
        if pb is None:
            continue
        if pb < pa:
            raise ToolError('bad page range "%s": printed page %s comes before %s'
                            % (item, b_tok.strip(), a_tok.strip()), EXIT_USAGE)
        for p, tok in ((pa, a_tok), (pb, b_tok or a_tok)):
            if not 1 <= p <= n_pages:
                raise ToolError("printed page %s maps to pdf %d, outside this PDF (pdf pages "
                                "1-%d); check --offset" % (tok.strip(), p, n_pages), EXIT_FILE)
        return pa, pb
    if pager.labels is None:
        raise ToolError('printed page "%s" can\'t be resolved: this PDF has no page labels, so '
                        'with --offset only numbers work (e.g. 181-186)' % item, EXIT_FILE)
    raise ToolError('printed page "%s" not found; this PDF\'s page labels are: %s'
                    % (item, pager.labels.summary()), EXIT_FILE)


def compress_pages(pages):
    """[5,7,9,10,11,12] -> '5,7,9-12'."""
    out, pages = [], sorted(pages)
    i = 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        out.append(str(pages[i]) if i == j else "%d-%d" % (pages[i], pages[j]))
        i = j + 1
    return ",".join(out)


def runs(pages):
    """Contiguous (first, last) runs of sorted pages."""
    out = []
    for p in sorted(pages):
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return [tuple(r) for r in out]


# ---------------------------------------------------------------------------
# PDF access and text helpers
# ---------------------------------------------------------------------------

class Pdf:
    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            raise ToolError("file not found: %s" % path, EXIT_FILE)
        if os.path.isdir(path):
            raise ToolError("%s is a directory, not a PDF" % path, EXIT_FILE)
        self._texts = {}
        try:
            self.reader = PdfReader(path)
            self.n = len(self.reader.pages)
        except Exception as exc:
            raise _pdf_error(path, exc)
        self._labels = False

    @property
    def labels(self):
        if self._labels is False:
            self._labels = read_page_labels(self.reader, self.n)
        return self._labels

    def pager(self, offset=None):
        return Pager(self.labels, offset)

    def text(self, pdf):
        if pdf not in self._texts:
            try:
                t = self.reader.pages[pdf - 1].extract_text() or ""
            except Exception as exc:
                if _is_decrypt_error(exc):
                    raise _pdf_error(self.path, exc)
                t = ""
            self._texts[pdf] = t
        return self._texts[pdf]

    def select(self, args):
        """Pages chosen by --pages/--printed/--offset (all pages when --pages is absent)."""
        spec = getattr(args, "pages", None)
        if not spec:
            return list(range(1, self.n + 1))
        if getattr(args, "printed", False):
            return resolve_printed_spec(spec, self.n, self.pager(args.offset))
        return parse_page_spec(spec, self.n)


def _is_decrypt_error(exc):
    return type(exc).__name__ in ("FileNotDecryptedError", "WrongPasswordError")


def _pdf_error(path, exc):
    name = type(exc).__name__
    if _is_decrypt_error(exc):
        return ToolError("%s is password-protected; pypdf can't open it without the "
                         "password (ask for an unlocked copy)" % path, EXIT_FILE)
    if name == "DependencyError":
        return ToolError('%s is AES-encrypted and pypdf needs the "cryptography" package. '
                         'Fix: "%s" -m pip install cryptography' % (path, sys.executable),
                         EXIT_DEP)
    if isinstance(exc, ToolError):
        return exc
    return ToolError("cannot read %s: %s: %s (not a PDF, or damaged)"
                     % (path, name, str(exc)[:150]), EXIT_FILE)


_NORMALIZE = str.maketrans({  # ligatures, soft hyphen, no-break space, curly quotes
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st", "\u00ad": None, "\u00a0": " ",
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


_LEADERS = re.compile(r"(?:[.·…_] ?){4,}")  # dotted TOC leaders, blanks like "Name: ____"


def collapse(s):
    return re.sub(r"\s+", " ", s or "").strip()


def normalize(s):
    return collapse((s or "").translate(_NORMALIZE))


def search_text(s):
    """Normalized page text for searching: whitespace collapsed, leaders shortened."""
    return _LEADERS.sub(lambda m: "… " if m.group(0)[0] in ".·…" else "____ ", normalize(s))


def clean_text(t):
    lines = [ln.rstrip() for ln in (t or "").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def text_quality(t):
    """None if the text layer looks fine, else 'little' or 'garbled'."""
    chars = [c for c in _LEADERS.sub("", t) if not c.isspace()]
    if len(chars) < TEXT_MIN_CHARS:
        return "little"
    letters = sum(1 for c in chars if c.isalpha())
    if letters / len(chars) < LETTER_RATIO_MIN or t.count("\ufffd") > 5 or "(cid:" in t:
        return "garbled"
    return None


QUALITY_NOTE = {
    "little": "little or no text: likely a scanned page, a figure, or a blank page",
    "garbled": "mostly symbols: likely math-heavy or a garbled text layer",
}


def quote(path):
    return '"%s"' % path


def plural(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

def sample_pages(n, k=12):
    """<=k pages spread through the document, always including pages 1 and 2."""
    if n <= k:
        return list(range(1, n + 1))
    spread = {1 + (i * (n - 1)) // (k - 2) for i in range(k - 1)}
    spread.add(2)
    return sorted(spread)[:k]


def guess_kind(n, text, landscape, n_outline, outline_titles, meta_title):
    t = (text + "\n" + " ".join(outline_titles) + "\n" + (meta_title or "")).lower()
    scores, why = {}, {}

    def add(kind, points, reason):
        scores[kind] = scores.get(kind, 0) + points
        why.setdefault(kind, []).append(reason)

    short = 1.0 if n <= 30 else 0.3   # exams, homework and syllabi are short documents
    if n >= 150:
        add("textbook", 3, "%d pages" % n)
    elif n >= 40:
        add("textbook", 1.5, "%d pages" % n)
    if re.search(r"\b(table of contents|contents)\b", t):
        add("textbook", 1.5, "table of contents")
    if re.search(r"\bchapter\s+(\d+|[ivxl]+)\b", t):
        add("textbook", 2, "chapter headings")
    if re.search(r"\b(preface|isbn|edition)\b", t):
        add("textbook", 1, "preface/edition")
    if n_outline >= 10:
        add("textbook", 1, "%d bookmarks" % n_outline)
    m = re.search(r"\b(midterm|final exam|exam|examination|quiz)\b", t)
    if m:
        add("exam", 4 * short, '"%s"' % m.group(1))
    if len(re.findall(r"[(\[]\s*\d+\s*(?:points?|pts?|marks?)\s*[)\]]", t)) >= 2:
        add("exam", 2 * short, "point values")
    if re.search(r"\bname\s*:", t):
        add("exam", 2 * short, '"Name:" line')
    if re.search(r"\b(no calculators?|closed book|time allowed|\d+\s*minutes)\b", t):
        add("exam", 1 * short, "time/calculator rules")
    m = re.search(r"\b(homework|problem set|pset|assignment|worksheet)\b", t)
    if m:
        add("homework", 4 * short, '"%s"' % m.group(1))
    if re.search(r"\b(due|submit)\b", t):
        add("homework", 1.5 * short, "due date")
    if "syllabus" in t:
        add("syllabus", 4 * short, '"syllabus"')
    if "office hours" in t:
        add("syllabus", 2 * short, "office hours")
    if re.search(r"\bgrading\b|\bgrade breakdown\b", t):
        add("syllabus", 1.5 * short, "grading policy")
    if re.search(r"\b(prerequisites?|learning (objectives|outcomes)|course description)\b", t):
        add("syllabus", 1 * short, "course info")
    if landscape:
        add("slides", 3, "landscape pages")
        if len(text) / max(1, min(n, 12)) < 900:
            add("slides", 1, "little text per page")
    if re.search(r"\blecture\b", t):
        add("notes", 2, '"lecture"')
    if re.search(r"\bnotes\b", t):
        add("notes", 1.5, '"notes"')
    if not scores:
        return "unknown", "no strong signals"
    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 2:
        return "unknown", "weak signals: " + ", ".join(why[best][:2])
    return best, ", ".join(why[best][:3])


def outline_entries(pdf):
    """Bookmarks as [(level, title, pdf_page or None)]."""
    try:
        outline = pdf.reader.outline
    except Exception:
        return []
    out = []

    def walk(items, level):
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            title = collapse(str(getattr(item, "title", "") or ""))
            try:
                idx = pdf.reader.get_destination_page_number(item)
                page = idx + 1 if idx is not None and idx >= 0 else None
            except Exception:
                page = None
            out.append((level, title, page))

    walk(outline, 0)
    return out


def info_lines(path):
    pdf = Pdf(path)
    reader, n = pdf.reader, pdf.n
    size = os.path.getsize(path) / MB
    enc = "not encrypted"
    if reader.is_encrypted:
        enc = "encrypted (opens without a password)"
    sample = sample_pages(n)
    texts = {p: pdf.text(p) for p in sample}
    with_text = sum(1 for p in sample if len(re.sub(r"\s", "", texts[p])) >= TEXT_MIN_CHARS)
    layer = "text layer %d/%d sampled pages" % (with_text, len(sample))
    if with_text < len(sample) / 2:
        layer += " (likely scanned: view pages via split)"
    entries = outline_entries(pdf)
    labels = pdf.labels
    if labels is None:
        lab = "page labels: none"
    elif labels.trivial():
        lab = "page labels: only 1-%d (same as pdf pages)" % n
    else:
        lab = 'page labels: yes, first "%s", last "%s"' % (labels.label(1), labels.label(n))
    try:
        title = collapse(str(reader.metadata.title or "")) if reader.metadata else ""
    except Exception:
        title = ""
    landscape = False
    for p in sample[:3]:
        try:
            page = reader.pages[p - 1]
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            if int(page.get("/Rotate", 0) or 0) % 180:
                w, h = h, w
            landscape = landscape or (h > 0 and w / h >= 1.2)
        except Exception:
            pass
    kind, why = guess_kind(n, "\n".join(texts.values()), landscape, len(entries),
                           [e[1] for e in entries[:60]], title)
    first = search_text(texts.get(1, ""))
    first = first[:160] + ("…" if len(first) > 160 else "")
    return [
        path,
        "  %d page%s · %.2f MB · %s · %s" % (n, "" if n == 1 else "s", size, enc, layer),
        "  outline: %d entries · %s" % (len(entries), lab),
        "  title: %s" % (title or "(none)"),
        "  kind: %s (%s)" % (kind, why),
        '  pdf 1 text: "%s"' % first if first else "  pdf 1 text: (none)",
    ]


def cmd_info(args):
    code = EXIT_OK
    for path in args.files:
        try:
            print("\n".join(info_lines(path)))
        except ToolError as exc:
            print("%s\n  error: %s" % (path, exc))
            code = code or exc.code
        sys.stdout.flush()
    return code


# ---------------------------------------------------------------------------
# outline
# ---------------------------------------------------------------------------

_TOC_PAGE = r"(?P<page>\d{1,4}|[ivxlcdm]{1,8}|[IVXLCDM]{1,8}|[A-Z]{1,2}[-–]\d{1,3})"
_TOC_LINE = re.compile(r"^(?P<title>.*?[^\s.·…])(?P<lead>\s*(?:[.·…]\s*)+|\s+)" + _TOC_PAGE + "$")
_TOC_PAGE_ONLY = re.compile(r"^(?:[.·…]\s*)*" + _TOC_PAGE + "$")
_TOC_NUM = re.compile(r"^(?P<num>(?:\d{1,3}|[A-Z])(?:\.\d{1,3})+|\d{1,3})\.?\s+(?=\S)")
_TOC_KEYWORD = re.compile(r"^(chapter|part|appendix|unit|module|lecture|book)\b", re.I)
_TOC_KEYWORD_ONLY = re.compile(r"^(chapter|part|appendix|unit|module|lecture|section)"
                               r"(\s+(\d{1,3}|[ivxlcdm]{1,6}|[A-Z]))?\s*[.:]?$", re.I)
_TOC_TOP = re.compile(r"^(preface|foreword|prologue|epilogue|contents|acknowledg|index|"
                      r"bibliography|references|glossary|answers|appendix|appendices|notation|"
                      r"symbols|list of|about the|credits|further reading|solutions)", re.I)
_TOC_SKIP = re.compile(r"^(figure|fig\.|table|plate)\s+\d", re.I)
_CONTENTS_HEAD = re.compile(r"^\s*(table of contents|contents|brief contents|contents in brief|"
                            r"detailed contents)\b", re.I | re.M)


def _toc_parse_line(line):
    m = _TOC_LINE.match(line)
    if not m:
        return None
    title, page, lead = m.group("title").strip(), m.group("page"), m.group("lead")
    if (len(re.findall(r"[^\W\d_]", title)) < 2 or len(title) > 160 or _TOC_SKIP.match(title)
            or _TOC_KEYWORD_ONLY.match(title)):
        return None   # "Chapter 3" alone is a heading, not "Chapter" on page 3
    if re.fullmatch(r"[ivxlcdm]+", page, re.I):
        value = roman_to_int(page)
        if value is None or value > 100:
            return None
        if page.isupper() and not re.search(r"[.·…]", lead):
            return None   # "Part II" is a title, not "Part" on page II
    return title, page.replace("–", "-")


def _toc_lines(text):
    raw = [collapse(ln) for ln in (text or "").splitlines()]
    raw = [ln for ln in raw if ln]
    out, i = [], 0
    while i < len(raw):
        line = raw[i]
        if (_TOC_KEYWORD_ONLY.match(line) and i + 1 < len(raw)
                and not _TOC_KEYWORD_ONLY.match(raw[i + 1])):
            line, i = line + " " + raw[i + 1], i + 1   # "Chapter 3" / "Derivatives ..... 150"
        if not _TOC_LINE.match(line) and i + 1 < len(raw):
            nxt = raw[i + 1]
            starts_entry = _TOC_NUM.match(line) or _TOC_KEYWORD.match(line)
            if _TOC_PAGE_ONLY.match(nxt):  # page number (with leaders) on its own line
                line, i = line + " " + nxt, i + 1
            elif (starts_entry and _TOC_LINE.match(nxt)
                  and not (_TOC_NUM.match(nxt) or _TOC_KEYWORD.match(nxt))):
                line, i = line + " " + nxt, i + 1   # title wrapped onto a second line
        out.append(line)
        i += 1
    return out


def find_toc(pdf):
    """Printed table of contents in the first pages: (pdf pages, [(title, printed)])."""
    blocks, cur, gap = [], None, 0
    for p in range(1, min(pdf.n, TOC_SCAN_PAGES) + 1):
        text = pdf.text(p)
        lines = _toc_lines(text)
        entries = [e for e in (_toc_parse_line(ln) for ln in lines) if e]
        ratio = len(entries) / max(1, len(lines))
        is_toc = ((_CONTENTS_HEAD.search(text) and len(entries) >= 3)
                  or (cur is not None and len(entries) >= 3 and ratio >= 0.3)
                  or (len(entries) >= 6 and ratio >= 0.4))
        if is_toc:
            if cur is None:
                cur = {"pages": [], "entries": []}
                blocks.append(cur)
            cur["pages"].append(p)
            cur["entries"].extend(entries)
            gap = 0
        else:
            cur = None
            if blocks:
                gap += 1
                if gap > 6:
                    break
    if not blocks:
        return None
    best = max(blocks, key=lambda b: len(b["entries"]))
    return best["pages"], best["entries"]


def toc_levels(entries):
    """[(title, printed)] -> [(level, title, printed)] from numbering and keywords."""
    out, in_chapter = [], False
    for title, printed in entries:
        m = _TOC_NUM.match(title)
        if _TOC_KEYWORD.match(title):
            level, in_chapter = 0, True
        elif m:
            level, in_chapter = m.group("num").count("."), True
        elif _TOC_TOP.match(title) or not in_chapter:
            level = 0
        else:
            level = 1
        out.append((level, title, printed))
    return out


def _no_labels_phrase(pdf):
    if pdf.labels is not None and pdf.labels.trivial():
        return "page labels only count 1-%d" % pdf.n
    return "no page labels"


def cmd_outline(args):
    pdf = Pdf(args.file)
    pager = pdf.pager(args.offset)
    if args.match is not None:
        try:
            match = re.compile(args.match, re.I)
        except re.error as exc:
            raise ToolError("bad --match pattern: %s" % exc, EXIT_USAGE)
    else:
        match = None

    marks = [] if args.toc else outline_entries(pdf)
    toc, use_marks = None, False
    if marks:  # a real outline has several usable entries; else prefer the printed contents
        use_marks = sum(1 for m in marks if m[2]) >= 3
        if not use_marks:
            toc = find_toc(pdf)
            use_marks = toc is None
    rows, header, notes = None, None, []
    if use_marks:
        header = "source: bookmarks"
        rows = [(lvl, title, pager.printed(page) if page else None, page)
                for lvl, title, page in marks]
        if not pager.known:
            notes.append("(%s, so printed page numbers are not shown; add --offset N to show "
                         "them, where pdf page = printed page + N)" % _no_labels_phrase(pdf))
    else:
        toc = toc or find_toc(pdf)
        if toc is None:
            print("source: none (no %stable of contents in the first %d pages)"
                  % ("" if args.toc else "bookmarks and no ", min(pdf.n, TOC_SCAN_PAGES)))
            print("hint: search headings instead, e.g. find %s \"Chapter\" --max 20"
                  % quote(args.file))
            return EXIT_OK
        toc_pages, entries = toc
        last_toc = toc_pages[-1]
        rows = []
        for level, title, printed in toc_levels(entries):
            page = pager.resolve(printed, after=last_toc)
            rows.append((level, title, printed, page if page and 1 <= page <= pdf.n else None))
        if args.offset is not None:
            how = "pdf = printed + %d from --offset" % args.offset
            if pager.labels is not None:
                how += ", other labels via page labels"
        elif pager.labels is not None:
            how = "printed→pdf via page labels"
        else:
            how = "%s, so pdf pages are unknown" % _no_labels_phrase(pdf)
        header = "source: toc-text (contents on pdf %s; %s)" % (compress_pages(toc_pages), how)
        if not pager.known:
            ref = next(((t, p) for _, t, p, _ in rows if p.isdigit()), None)
            if ref:
                notes.append('hint: find %s "%s" --pages %d-%d --max 3 gives the pdf page of '
                             'that heading; offset = that pdf page − %s; then re-run outline '
                             'with --offset <offset>'
                             % (quote(args.file), ref[0], min(last_toc + 1, pdf.n), pdf.n, ref[1]))

    print(header)
    if not rows:
        print("(outline is empty)")
        return EXIT_OK
    keep, keep_level = [], None
    for row in rows:
        if keep_level is not None and row[0] <= keep_level:
            keep_level = None
        if match is None or keep_level is not None or match.search(row[1]):
            if match is not None and keep_level is None:
                keep_level = row[0]
            keep.append(row)
    depth = args.depth
    if depth is None and match is None and len(keep) > OUTLINE_MAX_LINES:
        # too long for one read: show the deepest levels that fit
        depth, max_level = 1, max(r[0] for r in keep)
        while depth <= max_level and sum(1 for r in keep if r[0] <= depth) <= OUTLINE_MAX_LINES:
            depth += 1
        notes.insert(0, "(%d entries; showing only --depth %d; use --depth N or --match REGEX "
                        "for more)" % (len(keep), depth))
    if depth is not None:
        keep = [r for r in keep if r[0] < depth]
    if not keep:
        print("(no entries match /%s/)" % args.match if match else "(no entries)")
    shown = keep[:OUTLINE_MAX_LINES * 2]
    for level, title, printed, page in shown:
        parts = [title or "(untitled)"]
        if printed:
            parts.append("p.%s" % printed)
        parts.append("pdf %d" % page if page else "pdf ?")
        print("  " * level + " · ".join(parts))
    if len(keep) > len(shown):
        notes.insert(0, "(+%d more entries; use --depth or --match)" % (len(keep) - len(shown)))
    for note in notes:
        print(note)
    return EXIT_OK


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------

def cmd_labels(args):
    pdf = Pdf(args.file)
    labels = pdf.labels
    if labels is None:
        print("no page labels: printed page numbers are unknown (pdf N is just the N-th page).")
        print('To map them: find %s "<a heading you know the printed page of>" → offset = '
              'pdf page − printed page; then pass --offset N.' % quote(args.file))
        return EXIT_OK
    for span in labels.spans:
        print(labels.describe(span))
    if labels.trivial():
        print("note: these labels just count the pages 1..%d, so they may not match the "
              "printed page numbers; find a heading to get the real --offset." % pdf.n)
    return EXIT_OK


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------

def snippet(text, start, end, width=60):
    a, b = max(0, start - width), min(len(text), end + width)
    if a > 0:
        sp = text.find(" ", a, start)
        if sp != -1 and sp - a < 15:
            a = sp + 1
    if b < len(text):
        sp = text.rfind(" ", end, b)
        if sp != -1 and b - sp < 15:
            b = sp
    return ("…" if a > 0 else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def cmd_find(args):
    pdf = Pdf(args.file)
    pager = pdf.pager(args.offset)
    pages = pdf.select(args)
    if args.regex:
        try:
            pattern = re.compile(args.text, re.I)
        except re.error as exc:
            raise ToolError("bad --regex pattern: %s" % exc, EXIT_USAGE)
    else:
        words = normalize(args.text).split(" ")
        if not words or not words[0]:
            raise ToolError("empty search text", EXIT_USAGE)
        pattern = re.compile(r"\s?".join(re.escape(w) for w in words), re.I)
    shown, extra, low, scanned = [], 0, 0, 0
    far = max(20, 2 * args.max)
    stopped = timed_out = None
    deadline = time.time() + args.time_limit
    for i, p in enumerate(pages):
        if time.time() > deadline and i:
            timed_out = (p, len(pages) - i)
            break
        raw = pdf.text(p)
        scanned += 1
        if len(re.sub(r"\s", "", raw)) < TEXT_MIN_CHARS:
            low += 1
        text = search_text(raw)
        first, count = None, 0
        for m in pattern.finditer(text):
            if m.end() == m.start():
                continue
            first = first or m
            count += 1
            if count >= 999:
                break
        if first is None:
            continue
        if len(shown) < args.max:
            line = pager.ref(p)
            if count > 1:
                line += " [%s hits]" % ("999+" if count >= 999 else count)
            shown.append("%s: %s" % (line, snippet(text, first.start(), first.end())))
        else:
            extra += 1
            if extra >= far and i + 1 < len(pages):
                stopped = (p, len(pages) - i - 1)
                break
    for line in shown:
        print(line)
    if not shown:
        if timed_out:
            where = "the %d pages searched" % scanned
        else:
            where = "pdf %s" % compress_pages(pages) if args.pages else "%d pages" % pdf.n
        print('no hits for "%s" in %s' % (args.text, where))
    if timed_out:
        rest = compress_pages([q for q in pages if q >= timed_out[0]])
        print("(%stime limit %gs reached; pdf %s not searched — continue with --pages %s%s)"
              % ("+%s with hits; " % plural(extra, "more page") if extra else "",
                 args.time_limit, rest, rest, " without --printed" if args.printed else ""))
    elif stopped:
        print("(+%s with hits; stopped early at pdf %d, %s not searched — narrow with "
              "--pages or more specific text)"
              % (plural(extra, "more page"), stopped[0], plural(stopped[1], "page")))
    elif extra:
        print("(+%s with hits; raise --max or narrow with --pages)" % plural(extra, "more page"))
    if scanned and low / scanned > 0.2:
        print("note: %d of %d searched pages have little or no text (scanned?); hits there "
              "can't be found by text — view those pages via split." % (low, scanned))
    return EXIT_OK


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

def cmd_text(args):
    pdf = Pdf(args.file)
    pager = pdf.pager(args.offset)
    pages = pdf.select(args)
    flagged = []
    if args.out:
        parts, chars = [], 0
        for p in pages:
            t = clean_text(pdf.text(p))
            if text_quality(t):
                flagged.append(p)
            chars += len(t)
            parts.append("--- %s ---\n%s\n" % (pager.ref(p), t))
        out = os.path.abspath(args.out)
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\n".join(parts))
        except OSError as exc:
            raise ToolError("cannot write %s: %s" % (out, exc), EXIT_FILE)
        print("wrote %d chars from %d page%s (pdf %s) to %s"
              % (chars, len(pages), "" if len(pages) == 1 else "s", compress_pages(pages), out))
    else:
        used = 0
        for i, p in enumerate(pages):
            if used >= args.max_chars:
                print("[truncated at %d chars; pdf %s not shown — narrow --pages or save "
                      "everything with --out FILE]" % (args.max_chars, compress_pages(pages[i:])))
                break
            t = clean_text(pdf.text(p))
            quality = text_quality(t)
            print("--- %s ---" % pager.ref(p))
            if len(t) > args.max_chars - used:
                cut = t[:args.max_chars - used]
                space = max(cut.rfind(" "), cut.rfind("\n"))
                if space > len(cut) - 40:  # end on a word boundary
                    cut = cut[:space]
                print(cut.rstrip())
                rest = pages[i + 1:]
                print("[truncated at %d chars: rest of pdf %d cut%s — narrow --pages or save "
                      "everything with --out FILE]" % (
                          args.max_chars, p,
                          "; pdf %s not shown" % compress_pages(rest) if rest else ""))
                if quality:
                    flagged.append(p)
                break
            used += len(t)
            if quality:
                flagged.append(p)
            if not t:
                print("[no text on this page: likely a scanned page, a figure, or a blank page]")
            else:
                print(t)
                if quality:
                    print("[%s]" % QUALITY_NOTE[quality])
    if flagged:
        print("note: pdf %s may read better as an image: split %s --pages %s --out <dir>, "
              "then Read the chunk PDF." % (compress_pages(flagged), quote(args.file),
                                            compress_pages(flagged)))
    return EXIT_OK


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------

_ANNOT_DROP = ("/P", "/Parent", "/Popup", "/IRT", "/Dest", "/A", "/Next", "/StructParent")


def _add_view_page(writer, page):
    """Copy a page for viewing. Link annotations are dropped: their destinations point at
    other pages, and copying those would drag the whole book into the chunk."""
    from pypdf.generic import ArrayObject, NameObject
    new = writer.add_page(page, excluded_keys=("/Annots", "/B", "/Thumb"))
    try:
        annots = page.get("/Annots")
        annots = annots.get_object() if annots is not None else None
        keep = ArrayObject()
        for ref in annots or []:
            obj = ref.get_object()
            if not isinstance(obj, dict) or obj.get("/Subtype") in ("/Link", "/Popup"):
                continue
            keep.append(ref.clone(writer, False, _ANNOT_DROP))
        if len(keep):
            new[NameObject("/Annots")] = keep
    except Exception:
        pass  # viewing matters more than annotations


def _write_chunk(pdf, a, b, out_dir, stem, limit):
    path = os.path.abspath(os.path.join(out_dir, "%s_pdf%d-%d.pdf" % (stem, a, b)))
    writer = PdfWriter()
    for p in range(a, b + 1):
        _add_view_page(writer, pdf.reader.pages[p - 1])
    try:
        with open(path, "wb") as fh:
            writer.write(fh)
    except OSError as exc:
        raise ToolError("cannot write %s: %s" % (path, exc), EXIT_FILE)
    size = os.path.getsize(path)
    if size > limit:
        if a < b:
            os.remove(path)
            mid = (a + b) // 2
            return (_write_chunk(pdf, a, mid, out_dir, stem, limit)
                    + _write_chunk(pdf, mid + 1, b, out_dir, stem, limit))
        print("warning: pdf %d alone is %.1f MB (over --max-mb %g); it may be too large to view"
              % (a, size / MB, limit / MB), file=sys.stderr)
    return [path]


def cmd_split(args):
    pdf = Pdf(args.file)
    pages = pdf.select(args)
    if args.max_pages > 10:
        print("note: Read opens a PDF only if it has <= 10 pages", file=sys.stderr)
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as exc:
        raise ToolError("cannot create %s: %s" % (args.out, exc), EXIT_FILE)
    stem = os.path.splitext(os.path.basename(args.file))[0]
    limit = int(args.max_mb * MB)
    for first, last in runs(pages):
        s = first
        while s <= last:
            e = min(last, s + args.max_pages - 1)
            for path in _write_chunk(pdf, s, e, args.out, stem, limit):
                print(path)
            sys.stdout.flush()
            s = e + 1
    return EXIT_OK


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(EXIT_USAGE, "error: %s (see: %s -h)\n" % (message, self.prog))


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a whole number, got %r" % text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _positive_float(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a number, got %r" % text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS,
                        help="project root holding courses/ (default: $TUTOR_HOME, else the "
                             "first parent of the cwd with courses/)")
    pages = argparse.ArgumentParser(add_help=False)
    pages.add_argument("--printed", action="store_true",
                       help="SPEC lists printed page labels (181-186, xii, A-1..A-4)")
    pages.add_argument("--offset", type=int, metavar="N",
                       help="pdf page = printed page + N; for PDFs without page labels "
                            "(overrides labels for numeric pages)")

    parser = _Parser(prog=os.path.basename(SCRIPT), description=__doc__,
                     formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    parser.set_defaults(root=None)
    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("setup", parents=[common], description="install pypdf (works without it)")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("info", parents=[common], description="summary of one or more PDFs")
    p.add_argument("files", nargs="+", metavar="FILE")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("outline", parents=[common],
                       description="section tree with printed and pdf pages")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--depth", type=_positive_int, metavar="N", help="show levels < N (1 = top)")
    p.add_argument("--match", metavar="REGEX",
                   help="keep entries whose title matches (case-insensitive) + their children")
    p.add_argument("--offset", type=int, metavar="N",
                   help="pdf page = printed page + N (when the PDF has no page labels)")
    p.add_argument("--toc", action="store_true",
                   help="parse the printed table of contents even if bookmarks exist")
    p.set_defaults(func=cmd_outline)

    p = sub.add_parser("labels", parents=[common], description="printed page labels as ranges")
    p.add_argument("file", metavar="FILE")
    p.set_defaults(func=cmd_labels)

    p = sub.add_parser("find", parents=[common, pages],
                       description="case-insensitive search, one line per page with hits")
    p.add_argument("file", metavar="FILE")
    p.add_argument("text", metavar="TEXT")
    p.add_argument("--regex", action="store_true", help="TEXT is a regular expression")
    p.add_argument("--pages", metavar="SPEC", help="only search these pages")
    p.add_argument("--max", type=_positive_int, default=12, metavar="N",
                   help="show at most N pages with hits (default 12)")
    p.add_argument("--time-limit", type=_positive_float, default=90.0, metavar="SEC",
                   help="stop searching after SEC seconds and say where to continue "
                        "(default 90)")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("text", parents=[common, pages], description="text of a few pages")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--pages", required=True, metavar="SPEC")
    p.add_argument("--max-chars", type=_positive_int, default=12000, metavar="N",
                   help="stop printing after N chars of page text (default 12000)")
    p.add_argument("--out", metavar="PATH",
                   help="write all the text to PATH and print only a summary")
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("split", parents=[common, pages],
                       description="write chunk PDFs small enough to view as images")
    p.add_argument("file", metavar="FILE")
    p.add_argument("--pages", required=True, metavar="SPEC")
    p.add_argument("--out", required=True, metavar="DIR")
    p.add_argument("--max-pages", type=_positive_int, default=10, metavar="N",
                   help="pages per chunk (default 10, the most Read opens)")
    p.add_argument("--max-mb", type=_positive_float, default=19.0, metavar="MB",
                   help="max chunk size in MB (default 19)")
    p.set_defaults(func=cmd_split)
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    if args.cmd == "setup":
        return cmd_setup(args)
    if not load_pypdf():
        reexec_or_exit(args.root)
    try:
        return args.func(args)
    except ToolError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # output piped into e.g. `head`: stop quietly
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return EXIT_OK
    except Exception as exc:
        if os.environ.get("TUTOR_DEBUG"):
            raise
        if PYPDF_ERRORS and isinstance(exc, PYPDF_ERRORS):
            err = _pdf_error(getattr(args, "file", "PDF"), exc)
            print("error: %s" % err, file=sys.stderr)
            return err.code
        print("error: unexpected %s: %s (set TUTOR_DEBUG=1 for a traceback)"
              % (type(exc).__name__, str(exc)[:200]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
