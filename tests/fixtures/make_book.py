#!/usr/bin/env python3
"""Build deterministic PDF fixtures for the tutor skill's pdf_tools.py tests.

Usage: python make_book.py OUTDIR

Writes into OUTDIR:
  book.pdf           54-page first-year calculus textbook: nested bookmarks and page
                     labels  Cover | i-vi | 1-42 | A-1..A-5  (body page 1 = pdf 8)
  book_plain.pdf     the same pages with NO bookmarks and NO page labels
  practice_exam.pdf  2-page "MATH 101 — Midterm 1 (Practice)"
  truth.json         ground truth for assertions (offset, section pages, answers, ...)

Needs fpdf2 and pypdf. Uses DejaVu Sans when it can find it; otherwise falls back to
the core Helvetica font with the math rewritten in Latin-1-safe ASCII.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from io import BytesIO

try:
    from fpdf import FPDF
    from pypdf import PdfReader, PdfWriter
except ImportError as exc:  # pragma: no cover - reported to the caller
    sys.exit("make_book.py needs fpdf2 and pypdf (%s): pip install fpdf2 pypdf" % exc)

FIXED_DATE = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
BOOK_TITLE = "Calculus: A First Course"
AUTHORS = "A. N. Example and I. M. Placeholder"
EXAM_TITLE = "MATH 101 — Midterm 1 (Practice)"
LOG_SENTENCE = "Throughout this book, log x denotes the natural logarithm."

FONT_DIRS = [
    os.environ.get("MAKE_BOOK_FONT_DIR", ""),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/local/share/fonts",
    "/opt/homebrew/share/fonts",
    os.path.expanduser("~/Library/Fonts"),
    "/Library/Fonts",
]


def find_dejavu():
    """Return (regular, bold) DejaVu Sans paths, or None."""
    if os.environ.get("MAKE_BOOK_CORE_FONTS"):
        return None
    for d in FONT_DIRS:
        if not d:
            continue
        reg, bold = os.path.join(d, "DejaVuSans.ttf"), os.path.join(d, "DejaVuSans-Bold.ttf")
        if os.path.isfile(reg) and os.path.isfile(bold):
            return reg, bold
    return None


# ---------------------------------------------------------------------------
# Book content
# ---------------------------------------------------------------------------
# Paragraph items are plain strings, or (run-in heading, text) tuples rendered bold.

PREFACE = [
    [
        "This book is a first course in differential calculus for students of science, "
        "engineering and economics. It assumes a working knowledge of algebra and "
        "trigonometry and develops the subject in three short chapters: limits, "
        "derivatives, and applications of derivatives.",
        "Each section opens with the main ideas, states the key definition or theorem in "
        "a shaded box, and then works through at least one example step by step. Every "
        "section ends with eight exercises. The odd-numbered exercises have answers in "
        "Appendix A, so you can check your work; the even-numbered exercises are intended "
        "for homework and quizzes.",
        ("To the student.", "Mathematics is not a spectator sport. Read each worked "
         "example with a pencil in hand, cover the solution, and try the next step "
         "yourself before reading on. When you get stuck on an exercise, return to the "
         "boxed definitions and theorems: most exercises apply one of them directly."),
        ("To the instructor.", "The three chapters fit comfortably in the first half of a "
         "semester. Sections 1.1 to 1.3 can be covered in a week and a half; the chain "
         "rule in Section 2.4 deserves two full lectures."),
    ],
    [
        ("Conventions.", LOG_SENTENCE + " Angles are measured in radians unless degrees "
         "are stated explicitly. Intervals use the usual notation: [a, b] is closed and "
         "(a, b) is open."),
        "Limits are written lim_{x→a} f(x); derivatives are written f′(x), dy/dx or "
        "d/dx f(x). A table of derivatives appears in Appendix B.",
        ("Acknowledgments.", "We thank the many students whose questions shaped this "
         "edition, and the reviewers who read every exercise twice."),
        "— The Authors",
    ],
]

CHAPTERS = [
    {
        "num": 1,
        "title": "Limits",
        "intro": [
            "Calculus begins with a single question: what value does a function approach "
            "as its input approaches a given number? The answer is called a limit, and "
            "every idea in this book (slopes, rates of change, optimization) is built on it.",
            "In this chapter we first develop an intuitive understanding of limits using "
            "tables and graphs, then state the laws that let us compute limits "
            "algebraically, and finally use limits to make precise what it means for a "
            "function to be continuous.",
            ("What you will learn.", "How to estimate a limit numerically and "
             "graphically; how to evaluate limits with the limit laws, factoring and "
             "rationalizing; how to recognize one-sided limits and limits that do not "
             "exist; how to test a function for continuity and apply the Intermediate "
             "Value Theorem."),
        ],
        "sections": [
            {
                "num": "1.1",
                "title": "Limits of Functions",
                "pages": 4,
                "intro": [
                    "Consider the function f(x) = (x² − 4)/(x − 2). It is not defined at "
                    "x = 2, because substituting x = 2 produces the meaningless expression "
                    "0/0. Yet the values of f(x) behave very predictably when x is close to "
                    "2: if x = 1.99 then f(x) = 3.99, and if x = 2.01 then f(x) = 4.01. As x "
                    "gets closer and closer to 2 from either side, f(x) gets closer and "
                    "closer to 4. We say that the limit of f(x) as x approaches 2 is 4.",
                    "The limit describes what happens near a point, not at the point. The "
                    "value f(a) may be different from the limit, or f(a) may not be defined "
                    "at all; neither affects the limit. This is the key idea that lets "
                    "calculus handle expressions such as 0/0, which arise whenever we "
                    "compute slopes and rates of change.",
                ],
                "box": ("Definition (Limit of a Function)", [
                    "We write lim_{x→a} f(x) = L, read “the limit of f(x), as x approaches "
                    "a, equals L”, if we can make the values of f(x) arbitrarily close to L "
                    "by taking x sufficiently close to a, but not equal to a.",
                    "One-sided limits: lim_{x→a⁻} f(x) = L means x approaches a from the "
                    "left (x < a); lim_{x→a⁺} f(x) = L means x approaches a from the right "
                    "(x > a). The two-sided limit exists if and only if both one-sided "
                    "limits exist and are equal.",
                ]),
                "discussion": [
                    ("Estimating limits numerically.", "A table of values is often the "
                     "quickest way to guess a limit. Choose inputs on both sides of a, such "
                     "as a − 0.1, a − 0.01, a − 0.001 and a + 0.001, a + 0.01, a + 0.1, and "
                     "watch the outputs. For lim_{x→0} (sin x)/x, with x in radians, the "
                     "outputs are 0.99833, 0.99998 and 0.9999998, which suggests that the "
                     "limit is 1. A table suggests a limit but does not prove it."),
                    ("Estimating limits graphically.", "On a graph, the limit is the height "
                     "that the curve approaches as you trace it toward x = a from both "
                     "sides. An open circle at (a, L) means the point is missing, but the "
                     "limit is still L. A jump in the graph at x = a means that the "
                     "one-sided limits differ, so the two-sided limit does not exist."),
                    ("When limits fail to exist.", "There are three common ways: the "
                     "one-sided limits are different (a jump); the values grow without "
                     "bound, as 1/x² does near 0, where we write lim_{x→0} 1/x² = ∞ to "
                     "describe the behavior; or the values oscillate forever, as sin(1/x) "
                     "does near 0."),
                ],
                "box2": ("Caution", [
                    "Writing lim_{x→a} f(x) = ∞ does not mean that the limit exists. It "
                    "describes the particular way in which the limit fails to exist.",
                ]),
                "examples": [{
                    "problem": "Find lim_{x→2} (x² − 4)/(x − 2), first by estimating and "
                               "then by algebra.",
                    "steps": [
                        "Try direct substitution: (2² − 4)/(2 − 2) = 0/0, which is "
                        "undefined. The limit may still exist, so we look more closely.",
                        "Make a table: x = 1.9, 1.99, 1.999 give f(x) = 3.9, 3.99, 3.999, "
                        "and x = 2.1, 2.01, 2.001 give 4.1, 4.01, 4.001. The values approach "
                        "4 from both sides.",
                        "Confirm algebraically: for x ≠ 2, (x² − 4)/(x − 2) = "
                        "(x − 2)(x + 2)/(x − 2) = x + 2.",
                        "Since x + 2 → 4 as x → 2, we conclude that "
                        "lim_{x→2} (x² − 4)/(x − 2) = 4.",
                    ],
                    "answer": "The limit is 4, even though f(2) is undefined.",
                }],
                "exercise_intro": "In Exercises 1–8, evaluate the limit or explain why it "
                                  "does not exist.",
                "exercises": [
                    ("lim_{x→3} (2x + 1)", "7"),
                    ("lim_{x→1} (x² − 1)/(x − 1)", "2"),
                    ("lim_{x→0} |x|/x",
                     "Does not exist: the left-hand limit is −1 and the right-hand limit is 1."),
                    ("lim_{x→0⁺} |x|/x", "1"),
                    ("lim_{x→4} (x² − 16)/(x − 4)", "8"),
                    ("lim_{x→0} (sin x)/x, using a table of values with x in radians", "1"),
                    ("Let f(x) = x + 1 for x < 2 and f(x) = 5 for x ≥ 2. Find "
                     "lim_{x→2⁻} f(x) and lim_{x→2⁺} f(x). Does lim_{x→2} f(x) exist?",
                     "3 and 5; the limit does not exist."),
                    ("lim_{x→0} 1/x²", "Does not exist: 1/x² → ∞ as x → 0."),
                ],
            },
            {
                "num": "1.2",
                "title": "Limit Laws",
                "pages": 3,
                "intro": [
                    "Tables and graphs suggest the value of a limit, but to compute limits "
                    "reliably we use the limit laws. They say that limits respect the usual "
                    "arithmetic operations: the limit of a sum is the sum of the limits, the "
                    "limit of a product is the product of the limits, and so on, as long as "
                    "the individual limits exist.",
                    "Combined with the two basic limits lim_{x→a} c = c and lim_{x→a} x = a, "
                    "the laws show that lim_{x→a} p(x) = p(a) for every polynomial p. The "
                    "same direct substitution property holds for a rational function "
                    "whenever its denominator is not zero at a.",
                ],
                "box": ("Theorem (Limit Laws)", [
                    "Suppose lim_{x→a} f(x) = L and lim_{x→a} g(x) = M, and let c be a "
                    "constant. Then:",
                    "1. Sum and difference: lim [f(x) ± g(x)] = L ± M",
                    "2. Constant multiple: lim [c·f(x)] = c·L",
                    "3. Product: lim [f(x)·g(x)] = L·M",
                    "4. Quotient: lim [f(x)/g(x)] = L/M, provided M ≠ 0",
                    "5. Power: lim [f(x)]ⁿ = Lⁿ for every positive integer n",
                ]),
                "after_box": [
                    "When direct substitution gives 0/0, rewrite the expression before "
                    "applying the laws. The two most useful techniques are factoring and "
                    "cancelling a common factor, and multiplying by a conjugate to "
                    "rationalize a numerator or a denominator.",
                    ("The Squeeze Theorem.", "If g(x) ≤ f(x) ≤ h(x) for x near a and "
                     "lim_{x→a} g(x) = lim_{x→a} h(x) = L, then lim_{x→a} f(x) = L."),
                ],
                "examples": [{
                    "problem": "Evaluate lim_{x→9} (√x − 3)/(x − 9).",
                    "steps": [
                        "Direct substitution gives (3 − 3)/(9 − 9) = 0/0, so the Quotient "
                        "Law cannot be used yet.",
                        "Multiply the numerator and the denominator by the conjugate √x + 3, "
                        "using (√x − 3)(√x + 3) = x − 9.",
                        "The expression becomes (x − 9)/[(x − 9)(√x + 3)] = 1/(√x + 3) "
                        "for x ≠ 9.",
                        "Now substitute: lim_{x→9} 1/(√x + 3) = 1/(3 + 3) = 1/6.",
                    ],
                    "answer": "1/6",
                }],
                "exercise_intro": "In Exercises 1–8, evaluate the limit.",
                "exercises": [
                    ("lim_{x→2} (3x² − 5x + 1)", "3"),
                    ("lim_{x→−1} (x³ + 2x)", "−3"),
                    ("lim_{x→3} (x² − 9)/(x − 3)", "6"),
                    ("lim_{x→1} (x² + 3x − 4)/(x − 1)", "5"),
                    ("lim_{x→0} (√(x + 4) − 2)/x", "1/4"),
                    ("lim_{x→2} (x³ − 8)/(x − 2)", "12"),
                    ("lim_{x→0} x² sin(1/x). (Hint: use the Squeeze Theorem.)", "0"),
                    ("lim_{h→0} [(3 + h)² − 9]/h", "6"),
                ],
            },
            {
                "num": "1.3",
                "title": "Continuity",
                "pages": 4,
                "intro": [
                    "Many functions have graphs with no breaks, jumps or holes: you can draw "
                    "them without lifting your pencil. Continuity makes this idea precise "
                    "using limits. It matters because continuous functions are predictable: "
                    "small changes in the input produce small changes in the output.",
                ],
                "box": ("Definition (Continuity)", [
                    "A function f is continuous at a number a if all three conditions hold:",
                    "1. f(a) is defined;",
                    "2. lim_{x→a} f(x) exists;",
                    "3. lim_{x→a} f(x) = f(a).",
                    "f is continuous on an interval if it is continuous at every number in "
                    "the interval.",
                ]),
                "after_box": [
                    "Polynomials are continuous everywhere, rational functions are "
                    "continuous wherever they are defined, and sin x, cos x, eˣ and √x are "
                    "continuous on their domains. Sums, products, compositions and "
                    "quotients (where the denominator is not zero) of continuous functions "
                    "are continuous.",
                ],
                "discussion": [
                    ("Types of discontinuity.", "If condition 3 fails only because a single "
                     "point is missing or misplaced, the discontinuity is removable: "
                     "defining or redefining f(a) as the limit makes f continuous. For "
                     "example, (x² − 1)/(x − 1) has a removable discontinuity at x = 1. If "
                     "the one-sided limits exist but differ, the graph has a jump "
                     "discontinuity. If the values grow without bound, as 1/(x − 3)² does "
                     "near x = 3, the discontinuity is infinite."),
                    ("Piecewise functions.", "To check continuity where the formula "
                     "changes, compute the left-hand limit with the left piece and the "
                     "right-hand limit with the right piece, and compare both with the "
                     "value of the function at that point."),
                ],
                "box2": ("Theorem (Intermediate Value Theorem)", [
                    "Suppose f is continuous on the closed interval [a, b] and N is any "
                    "number strictly between f(a) and f(b). Then there is at least one "
                    "number c in (a, b) with f(c) = N.",
                    "In particular, if f(a) and f(b) have opposite signs, the equation "
                    "f(x) = 0 has a root in (a, b).",
                ]),
                "examples": [{
                    "problem": "Find the value of c that makes f(x) = cx + 1 for x ≤ 2, "
                               "f(x) = x² − c for x > 2, continuous at x = 2.",
                    "steps": [
                        "The left piece gives f(2) = 2c + 1, and it also gives the "
                        "left-hand limit: lim_{x→2⁻} f(x) = 2c + 1.",
                        "The right piece gives the right-hand limit: "
                        "lim_{x→2⁺} f(x) = 2² − c = 4 − c.",
                        "For continuity the two must agree: 2c + 1 = 4 − c, so 3c = 3 "
                        "and c = 1.",
                        "Check: with c = 1 both one-sided limits equal 3 and f(2) = 3, so "
                        "all three conditions of the definition hold.",
                    ],
                    "answer": "c = 1",
                }],
                "exercise_intro": "Answer each question about continuity.",
                "exercises": [
                    ("Find all numbers at which f(x) = (x + 1)/(x² − 4) is discontinuous.",
                     "x = −2 and x = 2"),
                    ("Classify the discontinuity of f(x) = (x² − 1)/(x − 1) at x = 1.",
                     "Removable; the limit there is 2."),
                    ("Find k so that f(x) = kx² for x ≤ 1 and f(x) = 2x + 3 for x > 1 is "
                     "continuous everywhere.", "k = 5"),
                    ("Is f(x) = |x|/x continuous at x = 0? Classify any discontinuity.",
                     "No: f(0) is undefined and the one-sided limits are −1 and 1, so it is "
                     "a jump discontinuity."),
                    ("Use the Intermediate Value Theorem to show that x³ − x − 1 = 0 has a "
                     "root in the interval [1, 2].",
                     "f(x) = x³ − x − 1 is continuous, f(1) = −1 < 0 and f(2) = 5 > 0, so by "
                     "the IVT there is a root in (1, 2)."),
                    ("Where is f(x) = 1/(x − 3)² discontinuous, and what type of "
                     "discontinuity is it?", "At x = 3; an infinite discontinuity."),
                    ("Find a and b so that f(x) = x + 1 for x < 1, f(x) = ax + b for "
                     "1 ≤ x < 2, and f(x) = 3x for x ≥ 2 is continuous everywhere.",
                     "a = 4, b = −2"),
                    ("Explain why f(x) = x⁵ − 3x + 1 has a root between 0 and 1.",
                     "f is a polynomial, hence continuous; f(0) = 1 > 0 and f(1) = −1 < 0, "
                     "so the IVT gives a root in (0, 1)."),
                ],
            },
        ],
    },
    {
        "num": 2,
        "title": "Derivatives",
        "intro": [
            "The derivative measures how fast a function changes. Geometrically it is the "
            "slope of the tangent line to a graph; physically it is an instantaneous rate "
            "of change, such as velocity. In this chapter the derivative is defined as a "
            "limit, and then a small set of rules makes computing derivatives fast and "
            "mechanical.",
            "We begin with the limit definition and the geometric meaning of the "
            "derivative. We then develop the power, sum and constant multiple rules, the "
            "product and quotient rules for combinations of functions, and finally the "
            "chain rule for compositions, the rule used most often in practice.",
            ("What you will learn.", "How to compute a derivative from the definition; "
             "how to find tangent lines; how to differentiate polynomials, products, "
             "quotients and compositions quickly and correctly."),
        ],
        "sections": [
            {
                "num": "2.1",
                "title": "The Derivative",
                "pages": 4,
                "intro": [
                    "Suppose a car's position at time t is s(t). Its average velocity over "
                    "the time interval from t = a to t = a + h is the difference quotient "
                    "[s(a + h) − s(a)]/h. Letting h shrink to 0 gives the instantaneous "
                    "velocity at time a. The same limit gives the slope of the tangent line "
                    "to the graph of s at (a, s(a)): the slopes of the secant lines through "
                    "(a, s(a)) and (a + h, s(a + h)) approach the slope of the tangent line.",
                ],
                "box": ("Definition (The Derivative)", [
                    "The derivative of a function f at a number a is "
                    "f′(a) = lim_{h→0} [f(a + h) − f(a)]/h, provided this limit exists.",
                    "The tangent line to y = f(x) at (a, f(a)) is the line through that "
                    "point with slope f′(a): y − f(a) = f′(a)(x − a).",
                ]),
                "after_box": [
                    "If the limit exists we say that f is differentiable at a. Letting a "
                    "vary gives a new function f′, the derivative of f. Other common "
                    "notations for the derivative of y = f(x) are dy/dx, df/dx and "
                    "d/dx f(x).",
                ],
                "discussion": [
                    ("Differentiability and continuity.", "If f is differentiable at a, "
                     "then f is continuous at a. The converse is false: a function can be "
                     "continuous at a point without having a derivative there."),
                    ("Where derivatives fail to exist.", "The standard example is "
                     "f(x) = |x| at x = 0. The difference quotient |h|/h equals 1 for h > 0 "
                     "and −1 for h < 0, so the one-sided limits disagree and f′(0) does not "
                     "exist; the graph has a corner at the origin. A function is also not "
                     "differentiable where its graph has a vertical tangent line, as "
                     "y = x^(1/3) does at x = 0, and wherever it is discontinuous."),
                    ("Interpreting the derivative.", "The units of f′(x) are the units of f "
                     "per unit of x. If C(q) is the cost in dollars of producing q items, "
                     "then C′(100) is measured in dollars per item and estimates the cost of "
                     "producing the 101st item."),
                ],
                "examples": [{
                    "problem": "Use the definition of the derivative to find f′(x) for "
                               "f(x) = x², and find the tangent line at x = 3.",
                    "steps": [
                        "Compute f(x + h) = (x + h)² = x² + 2xh + h².",
                        "Form the difference quotient: [f(x + h) − f(x)]/h = "
                        "(2xh + h²)/h = 2x + h for h ≠ 0.",
                        "Take the limit: f′(x) = lim_{h→0} (2x + h) = 2x.",
                        "At x = 3 the slope is f′(3) = 6, so the tangent line is "
                        "y − 9 = 6(x − 3), that is, y = 6x − 9.",
                    ],
                    "answer": "f′(x) = 2x; tangent line y = 6x − 9.",
                }],
                "exercise_intro": "In Exercises 1–5 and 7, use the limit definition of the "
                                  "derivative to find f′(x).",
                "exercises": [
                    ("f(x) = 3x + 2", "f′(x) = 3"),
                    ("f(x) = x² + x", "f′(x) = 2x + 1"),
                    ("f(x) = 1/x", "f′(x) = −1/x²"),
                    ("f(x) = √x", "f′(x) = 1/(2√x)"),
                    ("f(x) = x³", "f′(x) = 3x²"),
                    ("Find an equation of the tangent line to y = x² + x at x = 1.",
                     "y = 3x − 1"),
                    ("f(x) = 2x² − 3x", "f′(x) = 4x − 3"),
                    ("Show that f(x) = |x| is not differentiable at x = 0.",
                     "The difference quotient |h|/h is 1 for h > 0 and −1 for h < 0, so its "
                     "limit as h → 0 does not exist."),
                ],
            },
            {
                "num": "2.2",
                "title": "Basic Differentiation Rules",
                "pages": 3,
                "intro": [
                    "Computing every derivative from the limit definition would be slow. "
                    "Fortunately the derivatives of the most common functions follow a few "
                    "simple patterns, and the rules in this section let us differentiate "
                    "any polynomial at a glance.",
                ],
                "box": ("Theorem (Basic Differentiation Rules)", [
                    "Constant rule: d/dx c = 0",
                    "Power rule: d/dx xⁿ = n·xⁿ⁻¹ for every real number n",
                    "Constant multiple rule: d/dx [c·f(x)] = c·f′(x)",
                    "Sum and difference rules: d/dx [f(x) ± g(x)] = f′(x) ± g′(x)",
                    "Special functions: d/dx sin x = cos x, d/dx cos x = −sin x, "
                    "d/dx eˣ = eˣ",
                ]),
                "after_box": [
                    "The power rule holds for negative and fractional exponents as well, so "
                    "rewrite roots and reciprocals as powers before differentiating: "
                    "√x = x^(1/2) and 1/x³ = x⁻³.",
                    ("Higher derivatives.", "The derivative of f′ is the second derivative "
                     "f″, and the process can be repeated. For a position function s(t), "
                     "s′(t) is the velocity and s″(t) is the acceleration."),
                ],
                "examples": [{
                    "problem": "Differentiate f(x) = 4x⁵ − 3x² + 7x − 2 and find f″(x).",
                    "steps": [
                        "By the sum and difference rules, differentiate term by term.",
                        "Power and constant multiple rules: d/dx 4x⁵ = 20x⁴, "
                        "d/dx 3x² = 6x, d/dx 7x = 7, and d/dx 2 = 0.",
                        "So f′(x) = 20x⁴ − 6x + 7.",
                        "Differentiate again: f″(x) = 80x³ − 6.",
                    ],
                    "answer": "f′(x) = 20x⁴ − 6x + 7 and f″(x) = 80x³ − 6.",
                }],
                "exercise_intro": "In Exercises 1–7, find f′(x). In Exercise 8, find f″(x).",
                "exercises": [
                    ("f(x) = x⁷", "7x⁶"),
                    ("f(x) = 5x³ − 2x + 9", "15x² − 2"),
                    ("f(x) = √x", "1/(2√x)"),
                    ("f(x) = 1/x³", "−3/x⁴"),
                    ("f(x) = 3 sin x + 2 cos x", "3 cos x − 2 sin x"),
                    ("f(x) = eˣ + x⁴", "eˣ + 4x³"),
                    ("f(x) = (x² + 1)/x (simplify first)", "1 − 1/x²"),
                    ("f(x) = x⁴ − 2x³", "f″(x) = 12x² − 12x"),
                ],
            },
            {
                "num": "2.3",
                "title": "The Product and Quotient Rules",
                "pages": 4,
                "intro": [
                    "The derivative of a sum is the sum of the derivatives, but the "
                    "derivative of a product is not the product of the derivatives. For "
                    "example, d/dx (x·x) = d/dx x² = 2x, while (d/dx x)·(d/dx x) = 1. The "
                    "correct formulas for products and quotients are below.",
                ],
                "box": ("Theorem (Product and Quotient Rules)", [
                    "If f and g are differentiable, then",
                    "Product rule: (f·g)′ = f′·g + f·g′",
                    "Quotient rule: (f/g)′ = (f′·g − f·g′)/g², wherever g(x) ≠ 0",
                ]),
                "after_box": [
                    "A helpful way to remember the quotient rule is “low d-high minus "
                    "high d-low, over the square of what's below.” The order in the "
                    "numerator matters: reversing it changes the sign of the answer.",
                ],
                "discussion": [
                    ("When to simplify first.", "Sometimes an expression can be simplified "
                     "so that no product or quotient rule is needed. For example, "
                     "(x² + x)/x = x + 1 for x ≠ 0, whose derivative is 1. Simplifying first "
                     "usually saves time and reduces errors."),
                    ("The other trigonometric functions.", "Writing tan x = sin x/cos x and "
                     "applying the quotient rule gives d/dx tan x = "
                     "(cos x·cos x + sin x·sin x)/cos² x = 1/cos² x = sec² x. In the same "
                     "way, d/dx sec x = sec x tan x, d/dx cot x = −csc² x and "
                     "d/dx csc x = −csc x cot x."),
                    ("Products of three functions.", "Applying the product rule twice gives "
                     "(fgh)′ = f′gh + fg′h + fgh′: differentiate one factor at a time and "
                     "add the results."),
                ],
                "examples": [{
                    "problem": "Differentiate h(x) = (x² + 1)/(x − 3).",
                    "steps": [
                        "The numerator is f(x) = x² + 1 and the denominator is g(x) = x − 3, "
                        "so f′(x) = 2x and g′(x) = 1.",
                        "Apply the quotient rule: h′(x) = [2x(x − 3) − (x² + 1)(1)]/(x − 3)².",
                        "Expand the numerator: 2x² − 6x − x² − 1 = x² − 6x − 1.",
                        "Therefore h′(x) = (x² − 6x − 1)/(x − 3)² for x ≠ 3.",
                    ],
                    "answer": "h′(x) = (x² − 6x − 1)/(x − 3)²",
                }],
                "exercise_intro": "In Exercises 1–8, find the derivative.",
                "exercises": [
                    ("f(x) = x² sin x", "2x sin x + x² cos x"),
                    ("f(x) = (3x + 1)(x² − 2)", "9x² + 2x − 6"),
                    ("f(x) = x·eˣ", "(x + 1)eˣ"),
                    ("f(x) = x/(x + 1)", "1/(x + 1)²"),
                    ("f(x) = (sin x)/x", "(x cos x − sin x)/x²"),
                    ("f(x) = tan x, using tan x = sin x/cos x", "sec² x"),
                    ("f(x) = (x² + 1)/(x² − 1)", "−4x/(x² − 1)²"),
                    ("f(x) = eˣ cos x", "eˣ(cos x − sin x)"),
                ],
            },
            {
                "num": "2.4",
                "title": "The Chain Rule",
                "pages": 5,
                "intro": [
                    "How do we differentiate a composition such as (3x² + 1)⁵ or sin(x³)? "
                    "Expanding (3x² + 1)⁵ is tedious, and sin(x³) cannot be expanded at all. "
                    "The chain rule handles every composition in one step: differentiate the "
                    "outer function, leaving the inner function alone, and multiply by the "
                    "derivative of the inner function.",
                ],
                "box": ("Theorem (The Chain Rule)", [
                    "If g is differentiable at x and f is differentiable at g(x), then the "
                    "composite function F(x) = f(g(x)) is differentiable at x and",
                    "d/dx f(g(x)) = f′(g(x))·g′(x).",
                    "In Leibniz notation, if y = f(u) and u = g(x), then "
                    "dy/dx = (dy/du)·(du/dx).",
                ]),
                "after_box": [
                    "The chain rule is the most frequently used rule of differentiation, "
                    "because most functions met in practice are built by composing simpler "
                    "ones. Rates multiply: if u changes 3 times as fast as x and y changes "
                    "2 times as fast as u, then y changes 6 times as fast as x.",
                ],
                "discussion": [
                    ("Outer and inner functions.", "To apply the chain rule, first decide "
                     "which function is applied last; that is the outer function f. "
                     "Everything inside it is the inner function g. In sin(x³) the outer "
                     "function is sin u and the inner function is u = x³, so the derivative "
                     "is cos(x³)·3x²."),
                    ("Common mistakes.", "The most common error is forgetting the factor "
                     "g′(x): the derivative of sin(x³) is not cos(x³). Another is "
                     "evaluating the outer derivative at x instead of at g(x): the "
                     "derivative of (3x² + 1)⁵ is 5(3x² + 1)⁴·6x, not 5x⁴·6x."),
                    ("Longer chains.", "For y = f(g(h(x))), apply the rule repeatedly: "
                     "y′ = f′(g(h(x)))·g′(h(x))·h′(x). For example, "
                     "d/dx sin²(3x) = 2 sin(3x)·cos(3x)·3 = 6 sin(3x) cos(3x)."),
                ],
                "box2": ("Generalized Power Rule", [
                    "If n is any real number and u = g(x) is differentiable, then "
                    "d/dx [g(x)]ⁿ = n[g(x)]ⁿ⁻¹·g′(x).",
                ]),
                "examples": [
                    {
                        "problem": "Differentiate y = (3x² + 1)⁵.",
                        "steps": [
                            "The outer function is u⁵ and the inner function is u = 3x² + 1.",
                            "Differentiate the outer function: d/du u⁵ = 5u⁴, which gives "
                            "5(3x² + 1)⁴.",
                            "Differentiate the inner function: du/dx = 6x.",
                            "Multiply: dy/dx = 5(3x² + 1)⁴·6x = 30x(3x² + 1)⁴.",
                        ],
                        "answer": "dy/dx = 30x(3x² + 1)⁴",
                    },
                    {
                        "problem": "Differentiate y = 1/(x² + 4)³.",
                        "steps": [
                            "Write y = (x² + 4)⁻³; the outer function is u⁻³ and the inner "
                            "function is u = x² + 4.",
                            "The outer derivative is −3u⁻⁴ = −3(x² + 4)⁻⁴.",
                            "The inner derivative is 2x.",
                            "Multiply: dy/dx = −3(x² + 4)⁻⁴·2x = −6x/(x² + 4)⁴.",
                        ],
                        "answer": "dy/dx = −6x/(x² + 4)⁴",
                    },
                ],
                "exercise_intro": "In Exercises 1–8, differentiate the function. For "
                                  "Exercise 7, recall the convention for log stated in the "
                                  "Preface.",
                "exercises": [
                    ("y = (2x + 1)⁵", "10(2x + 1)⁴"),
                    ("y = sin(3x)", "3 cos(3x)"),
                    ("y = √(x² + 1)", "x/√(x² + 1)"),
                    ("y = e^(x²)", "2x·e^(x²)"),
                    ("y = cos(x³)", "−3x² sin(x³)"),
                    ("y = (x² − 3x)⁴", "4(x² − 3x)³(2x − 3)"),
                    ("y = log(x² + 1)", "2x/(x² + 1)"),
                    ("y = sin² x", "2 sin x cos x (= sin 2x)"),
                ],
            },
        ],
    },
    {
        "num": 3,
        "title": "Applications",
        "intro": [
            "Derivatives are useful because they measure change. In this chapter we use "
            "them to relate the rates at which connected quantities change, to locate the "
            "largest and smallest values of a function, and to solve practical "
            "optimization problems in geometry, economics and design.",
            "Each section follows the same pattern: translate a word problem into a "
            "function, differentiate, and interpret the result in the original context. "
            "Drawing a picture and naming the variables is always the first step.",
            ("What you will learn.", "How to solve related rates problems; how to find "
             "critical numbers and absolute extreme values; how to set up and solve "
             "optimization problems."),
        ],
        "sections": [
            {
                "num": "3.1",
                "title": "Related Rates",
                "pages": 4,
                "intro": [
                    "In a related rates problem, two or more quantities change with time "
                    "and are linked by an equation. If we know how fast one quantity "
                    "changes, we can find how fast another changes by differentiating the "
                    "equation with respect to time t. For example, as air is pumped into a "
                    "spherical balloon, its volume and radius both increase, and their "
                    "rates are related through V = (4/3)πr³.",
                ],
                "box": ("Strategy (Solving Related Rates Problems)", [
                    "1. Draw a diagram and name every quantity that changes with time.",
                    "2. Write the given rates and the unknown rate as derivatives with "
                    "respect to t.",
                    "3. Write an equation that relates the quantities.",
                    "4. Differentiate both sides with respect to t, using the chain rule.",
                    "5. Substitute the known values and solve for the unknown rate.",
                ]),
                "after_box": [
                    "Substitute numerical values only after differentiating. If you "
                    "substitute too early, a changing quantity becomes a constant and its "
                    "rate of change is lost.",
                ],
                "discussion": [
                    ("Differentiating with respect to time.", "When we differentiate r³ "
                     "with respect to t, the chain rule gives 3r²·dr/dt, because r is itself "
                     "a function of t. Every variable that changes with time contributes "
                     "such a factor."),
                    ("Similar triangles.", "In problems about cones, shadows and ladders, "
                     "similar triangles often give the extra equation needed to eliminate a "
                     "variable. For a conical tank whose radius is half its height, r = h/2 "
                     "at every water level."),
                    ("Signs matter.", "A negative rate means the quantity is decreasing. If "
                     "the top of a sliding ladder moves down, dy/dt is negative; state the "
                     "final answer in words, for example “the top slides down at 3/4 ft/s.”"),
                ],
                "examples": [{
                    "problem": "A 10-ft ladder leans against a vertical wall. The bottom "
                               "slides away from the wall at 1 ft/s. How fast is the top "
                               "sliding down the wall when the bottom is 6 ft from the wall?",
                    "steps": [
                        "Let x be the distance from the wall to the bottom of the ladder and "
                        "y the height of the top. Then x² + y² = 100 and dx/dt = 1.",
                        "Differentiate with respect to t: 2x·dx/dt + 2y·dy/dt = 0.",
                        "When x = 6, y = √(100 − 36) = 8.",
                        "Substitute: 2(6)(1) + 2(8)·dy/dt = 0, so dy/dt = −12/16 = −3/4.",
                    ],
                    "answer": "The top slides down the wall at 3/4 ft/s.",
                }],
                "exercise_intro": "Solve each related rates problem. Include units in your "
                                  "answer.",
                "exercises": [
                    ("The radius of a circle increases at 2 cm/s. How fast is the area "
                     "increasing when r = 5 cm?", "20π cm²/s"),
                    ("The side of a square increases at 3 in/s. How fast is the area "
                     "increasing when the side is 4 in?", "24 in²/s"),
                    ("The volume of a spherical balloon increases at 100 cm³/s. How fast is "
                     "the radius increasing when r = 5 cm?", "1/π cm/s ≈ 0.32 cm/s"),
                    ("A 13-ft ladder leans against a wall and its bottom slides away at "
                     "2 ft/s. How fast is the top sliding down when the bottom is 5 ft from "
                     "the wall?", "5/6 ft/s"),
                    ("The edge of a cube increases at 1 cm/s. How fast is the volume "
                     "increasing when the edge is 3 cm?", "27 cm³/s"),
                    ("If x² + y² = 25 and dx/dt = 3, find dy/dt when x = 3 and y = 4.",
                     "dy/dt = −9/4"),
                    ("Water flows at 2 m³/min into a conical tank, vertex down, that is "
                     "10 m tall with a top radius of 5 m. How fast is the water level rising "
                     "when the water is 4 m deep?", "1/(2π) m/min ≈ 0.16 m/min"),
                    ("Two cars leave an intersection at the same time, one driving north at "
                     "30 mi/h and the other east at 40 mi/h. How fast is the distance "
                     "between them increasing after 2 hours?", "50 mi/h"),
                ],
            },
            {
                "num": "3.2",
                "title": "Extreme Values",
                "pages": 4,
                "intro": [
                    "Many problems ask for the largest or smallest value of a function: the "
                    "maximum profit, the minimum cost, the greatest height. A function f has "
                    "an absolute maximum at c if f(c) ≥ f(x) for all x in its domain, and a "
                    "local maximum at c if f(c) ≥ f(x) for all x near c. Absolute and local "
                    "minimums are defined in the same way; together they are called extreme "
                    "values.",
                ],
                "box": ("Theorem (Extreme Value Theorem)", [
                    "If f is continuous on a closed interval [a, b], then f attains an "
                    "absolute maximum value f(c) and an absolute minimum value f(d) at some "
                    "numbers c and d in [a, b].",
                ]),
                "after_box": [
                    "The theorem guarantees that extreme values exist, but not where they "
                    "are. Fermat's Theorem narrows the search: if f has a local maximum or "
                    "minimum at c and f′(c) exists, then f′(c) = 0.",
                ],
                "discussion": [
                    ("Critical numbers.", "A critical number of f is a number c in the "
                     "domain of f where f′(c) = 0 or f′(c) does not exist. Local extreme "
                     "values occur only at critical numbers, but not every critical number "
                     "gives one: f(x) = x³ has f′(0) = 0 and no extreme value at 0."),
                    ("Always check the endpoints.", "On a closed interval the absolute "
                     "maximum or minimum often occurs at an endpoint, where the derivative "
                     "need not be zero."),
                ],
                "box2": ("The Closed Interval Method", [
                    "To find the absolute maximum and minimum of a continuous function f "
                    "on [a, b]:",
                    "1. Find the values of f at the critical numbers of f in (a, b).",
                    "2. Find the values f(a) and f(b) at the endpoints.",
                    "3. The largest value from steps 1 and 2 is the absolute maximum; the "
                    "smallest is the absolute minimum.",
                ]),
                "examples": [{
                    "problem": "Find the absolute maximum and minimum values of "
                               "f(x) = x³ − 3x² + 1 on [−1, 4].",
                    "steps": [
                        "Differentiate: f′(x) = 3x² − 6x = 3x(x − 2), so the critical "
                        "numbers are x = 0 and x = 2, both in (−1, 4).",
                        "Evaluate at the critical numbers: f(0) = 1 and "
                        "f(2) = 8 − 12 + 1 = −3.",
                        "Evaluate at the endpoints: f(−1) = −1 − 3 + 1 = −3 and "
                        "f(4) = 64 − 48 + 1 = 17.",
                        "Compare: the largest value is 17 and the smallest is −3.",
                    ],
                    "answer": "Absolute maximum 17 at x = 4; absolute minimum −3 at x = −1 "
                              "and at x = 2.",
                }],
                "exercise_intro": "In Exercises 1, 2, 5 and 8, find the critical numbers. In "
                                  "Exercises 3, 4, 6 and 7, find the absolute maximum and "
                                  "minimum values on the given interval.",
                "exercises": [
                    ("f(x) = x² − 6x + 5", "x = 3"),
                    ("f(x) = x³ − 12x", "x = −2 and x = 2"),
                    ("f(x) = x² − 4x + 1 on [0, 3]", "Maximum 1 at x = 0; minimum −3 at x = 2"),
                    ("f(x) = 2x³ − 3x² − 12x + 1 on [−2, 3]",
                     "Maximum 8 at x = −1; minimum −19 at x = 2"),
                    ("f(x) = x^(2/3)", "x = 0 (f′ does not exist there)"),
                    ("f(x) = x + 4/x on [1, 4]",
                     "Maximum 5 at x = 1 and x = 4; minimum 4 at x = 2"),
                    ("f(x) = sin x + cos x on [0, π/2]",
                     "Maximum √2 at x = π/4; minimum 1 at x = 0 and x = π/2"),
                    ("f(x) = x⁴ − 4x³", "x = 0 and x = 3"),
                ],
            },
            {
                "num": "3.3",
                "title": "Optimization",
                "pages": 4,
                "intro": [
                    "Optimization problems ask for the best way to do something: the largest "
                    "area that can be enclosed with a given length of fence, the cheapest can "
                    "that holds a given volume, the shortest path between two points. The "
                    "methods of the previous section solve such problems once they are "
                    "translated into mathematics.",
                ],
                "box": ("Strategy (Solving Optimization Problems)", [
                    "1. Identify the quantity to be maximized or minimized.",
                    "2. Draw a diagram and name the variables.",
                    "3. Write the quantity as a function of the variables (the objective "
                    "function).",
                    "4. Use the given condition (the constraint) to write it as a function "
                    "of one variable, and find its domain.",
                    "5. Find the absolute maximum or minimum on that domain.",
                ]),
                "after_box": [
                    "Step 4 is where most of the work lies. The constraint equation, such as "
                    "a fixed perimeter or a fixed volume, lets you eliminate every variable "
                    "but one.",
                ],
                "discussion": [
                    ("The first derivative test for absolute extrema.", "If the domain is "
                     "an open interval there are no endpoints to check. If f′(x) > 0 for all "
                     "x < c and f′(x) < 0 for all x > c in the domain, then f(c) is the "
                     "absolute maximum; the reverse sign pattern gives the absolute minimum."),
                    ("The second derivative test.", "If f′(c) = 0 and f″(c) < 0, then f has "
                     "a local maximum at c; if f″(c) > 0, a local minimum. When c is the only "
                     "critical number in an interval, a local extremum there is also the "
                     "absolute one."),
                    ("Check your answer.", "Make sure the answer is reasonable, satisfies "
                     "the constraint and answers the question that was asked, with units: "
                     "the problem may ask for the dimensions of a box rather than its "
                     "volume."),
                ],
                "examples": [{
                    "problem": "A farmer has 2400 ft of fencing and wants to fence a "
                               "rectangular field that borders a straight river. No fence is "
                               "needed along the river. What are the dimensions of the field "
                               "with the largest area?",
                    "steps": [
                        "Let x be the length of each side perpendicular to the river and y "
                        "the length of the side parallel to it. We want to maximize A = xy.",
                        "The constraint is 2x + y = 2400, so y = 2400 − 2x and "
                        "A(x) = 2400x − 2x² for 0 ≤ x ≤ 1200.",
                        "Differentiate: A′(x) = 2400 − 4x = 0 gives x = 600. At the "
                        "endpoints A(0) = A(1200) = 0.",
                        "So x = 600 ft, y = 2400 − 1200 = 1200 ft, and the largest area is "
                        "720,000 ft².",
                    ],
                    "answer": "600 ft by 1200 ft, with the 1200-ft side along the river.",
                }],
                "exercise_intro": "Solve each optimization problem.",
                "exercises": [
                    ("Find two positive numbers whose sum is 20 and whose product is as "
                     "large as possible.", "10 and 10"),
                    ("Find the dimensions of a rectangle with perimeter 40 m and the largest "
                     "possible area.", "A 10 m by 10 m square"),
                    ("Find two positive numbers whose product is 64 and whose sum is as small "
                     "as possible.", "8 and 8"),
                    ("An open box is made from a 12 in by 12 in sheet of cardboard by cutting "
                     "equal squares from the corners and folding up the sides. What size "
                     "squares give the largest volume?", "2-in squares (volume 128 in³)"),
                    ("A rectangular garden of area 200 ft² is fenced on three sides; the "
                     "fourth side is a wall. Find the dimensions that use the least fencing.",
                     "10 ft by 20 ft, with the 20-ft side along the wall (40 ft of fencing)"),
                    ("A cylindrical can must hold 1000 cm³. Find the radius and height that "
                     "minimize its surface area, including the top and bottom.",
                     "r = (500/π)^(1/3) ≈ 5.42 cm and h = 2r ≈ 10.84 cm"),
                    ("Find the points on the parabola y = x² that are closest to the point "
                     "(0, 2).", "(±√(3/2), 3/2)"),
                    ("A rectangle has its base on the x-axis and its upper corners on the "
                     "parabola y = 12 − x². What is the largest possible area?",
                     "32 (width 4, height 8)"),
                ],
            },
        ],
    },
]

DERIVATIVE_TABLE = [
    ("c (constant)", "0"),
    ("xⁿ", "n·xⁿ⁻¹"),
    ("eˣ", "eˣ"),
    ("aˣ (a > 0)", "aˣ·log a"),
    ("log x (x > 0)", "1/x"),
    ("log |x|", "1/x"),
    ("sin x", "cos x"),
    ("cos x", "−sin x"),
    ("tan x", "sec² x"),
    ("sec x", "sec x tan x"),
    ("csc x", "−csc x cot x"),
    ("cot x", "−csc² x"),
    ("arcsin x", "1/√(1 − x²)"),
    ("arctan x", "1/(1 + x²)"),
]

RULES_TABLE = [
    ("Constant multiple", "(c·f)′ = c·f′"),
    ("Sum and difference", "(f ± g)′ = f′ ± g′"),
    ("Product rule", "(f·g)′ = f′·g + f·g′"),
    ("Quotient rule", "(f/g)′ = (f′·g − f·g′)/g²"),
    ("Chain rule", "d/dx f(g(x)) = f′(g(x))·g′(x)"),
    ("Generalized power rule", "d/dx [g(x)]ⁿ = n[g(x)]ⁿ⁻¹·g′(x)"),
]

EXAM = {
    "course": "MATH 101",
    "title": EXAM_TITLE,
    "minutes": 50,
    "questions": [
        {"n": 1, "points": 15, "sections": ["1.2"],
         "text": "Evaluate lim_{x→3} (x² − 9)/(x² − x − 6), or explain why the limit does "
                 "not exist.",
         "answer": "6/5"},
        {"n": 2, "points": 15, "sections": ["1.3"],
         "text": "Find the value of k for which f(x) = x² + k for x < 2 and f(x) = 3x − 1 "
                 "for x ≥ 2 is continuous at x = 2. Justify your answer using the "
                 "definition of continuity.",
         "answer": "k = 1"},
        {"n": 3, "points": 20, "sections": ["2.1"],
         "text": "Use the limit definition of the derivative to find f′(x) for "
                 "f(x) = 3x² − x. No credit will be given for using differentiation rules.",
         "answer": "f′(x) = 6x − 1"},
        {"n": 4, "points": 15, "sections": ["2.3"],
         "text": "Differentiate: (a) g(x) = x³ cos x;  (b) h(x) = (2x + 1)/(x² + 1).",
         "answer": "(a) 3x² cos x − x³ sin x; (b) (−2x² − 2x + 2)/(x² + 1)²"},
        {"n": 5, "points": 15, "sections": ["2.4"],
         "text": "Use the chain rule to find dy/dx: (a) y = (x³ − 2x)⁵;  "
                 "(b) y = √(4x² + 9).",
         "answer": "(a) 5(x³ − 2x)⁴(3x² − 2); (b) 4x/√(4x² + 9)"},
        {"n": 6, "points": 20, "sections": ["2.1", "2.2"],
         "text": "Find an equation of the tangent line to the curve y = x³ − 2x + 1 at the "
                 "point where x = 1.",
         "answer": "y = x − 1"},
    ],
}

# ---------------------------------------------------------------------------
# Page plan: every page is laid out explicitly, so printed numbers are known up front.
# ---------------------------------------------------------------------------

FRONT = ["cover", "title", "preface-1", "preface-2", "contents-1", "contents-2", "blank"]
OFFSET = len(FRONT)            # pdf page = printed page + OFFSET for the body
ANSWER_PAGES = 3               # A-1..A-3
DERIV_PAGES = 2                # A-4..A-5
ANSWER_GROUPS = [["1.1", "1.2", "1.3", "2.1"], ["2.2", "2.3", "2.4", "3.1"], ["3.2", "3.3"]]
CONTENTS_SPLIT = 2             # chapters on the first contents page


def section_page_kinds(sec):
    n = sec["pages"]
    kinds = ["intro"]
    if n >= 4:
        kinds.append("discussion")
    kinds += ["example:%d" % i for i in range(len(sec["examples"]))]
    kinds.append("exercises")
    if len(kinds) != n:
        raise SystemExit("section %s: plan has %d pages, content %d" % (sec["num"], n, len(kinds)))
    return kinds


def plan_book():
    printed = 1
    for ch in CHAPTERS:
        ch["printed_start"] = printed
        printed += 1  # chapter opener
        for sec in ch["sections"]:
            sec["printed_start"] = printed
            sec["printed_end"] = printed + sec["pages"] - 1
            printed += sec["pages"]
        ch["printed_end"] = printed - 1
    body_pages = printed - 1
    appendix_start = OFFSET + body_pages + 1
    return {
        "body_pages": body_pages,
        "answers_pdf": (appendix_start, appendix_start + ANSWER_PAGES - 1),
        "deriv_pdf": (appendix_start + ANSWER_PAGES, appendix_start + ANSWER_PAGES + DERIV_PAGES - 1),
        "total": OFFSET + body_pages + ANSWER_PAGES + DERIV_PAGES,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SUPERSCRIPTS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6",
                 "⁷": "7", "⁸": "8", "⁹": "9", "ⁿ": "n", "⁻": "-", "⁺": "+", "ˣ": "x"}
_ASCII = {"′": "'", "″": "''", "·": "*", "→": "->", "≤": "<=", "≥": ">=", "≠": "!=",
          "±": "+/-", "∞": "infinity", "√": "sqrt", "π": "pi", "−": "-", "—": "-", "–": "-",
          "…": "...", "≈": "~", "“": '"', "”": '"', "’": "'", "‘": "'", "©": "(c)",
          "•": "*", "×": "x"}


def ascii_math(s):
    """Latin-1-safe rendering for the core-font fallback."""
    s = re.sub("[%s]+" % "".join(_SUPERSCRIPTS),
               lambda m: "^" + "".join(_SUPERSCRIPTS[c] for c in m.group(0)), s)
    s = "".join(_ASCII.get(c, c) for c in s)
    return s.encode("latin-1", "replace").decode("latin-1")


class Doc(FPDF):
    """FPDF with a running header/footer driven by per-page metadata."""

    def __init__(self, fonts):
        super().__init__(format="letter", unit="mm")
        self.set_creation_date(FIXED_DATE)
        self.set_margins(25, 25, 25)
        self.set_auto_page_break(True, margin=24)
        if fonts:
            self.add_font("DejaVu", "", fonts[0])
            self.add_font("DejaVu", "B", fonts[1])
            self.fam = "DejaVu"
            self.t = lambda s: s
        else:
            self.fam = "helvetica"
            self.t = ascii_math
        self._next = {}
        self.page_meta = {}

    # -- page furniture --------------------------------------------------
    def start_page(self, label="", left="", right="", footer=None):
        self._next = {"label": label, "left": left, "right": right,
                      "footer": label if footer is None else footer}
        self.add_page()
        return self.page_no()

    def header(self):
        meta = dict(self._next)
        self.page_meta[self.page_no()] = meta
        if meta.get("left") or meta.get("right"):
            width = self.w - self.l_margin - self.r_margin
            self.set_font(self.fam, "", 8.5)
            self.set_text_color(90, 90, 90)
            self.set_xy(self.l_margin, 12)
            self.cell(width / 2, 5, self.t(meta.get("left", "")))
            self.cell(width / 2, 5, self.t(meta.get("right", "")), align="R")
            self.set_draw_color(170, 170, 170)
            self.line(self.l_margin, 18, self.w - self.r_margin, 18)
            self.set_text_color(0, 0, 0)
        self.set_xy(self.l_margin, self.t_margin)

    def footer(self):
        text = self.page_meta.get(self.page_no(), {}).get("footer")
        if text:
            self.set_y(-16)
            self.set_font(self.fam, "", 9)
            self.cell(0, 5, self.t(text), align="C")

    # -- text helpers ----------------------------------------------------
    @property
    def body_w(self):
        return self.w - self.l_margin - self.r_margin

    def heading(self, text, size=16, space=4):
        self.set_font(self.fam, "B", size)
        self.multi_cell(0, size * 0.5, self.t(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(space)

    def para(self, item, size=11, space=2.6):
        self.set_font(self.fam, "", size)
        if isinstance(item, tuple):
            head, text = item
            if any(m in head + text for m in ("**", "__", "--", "~~", "](")):
                raise SystemExit("markdown-sensitive text: %r" % (head + text))
            self.multi_cell(0, 5.8, "**%s** %s" % (self.t(head), self.t(text)),
                            markdown=True, new_x="LMARGIN", new_y="NEXT")
        else:
            self.multi_cell(0, 5.8, self.t(item), new_x="LMARGIN", new_y="NEXT")
        self.ln(space)

    def box(self, title, lines):
        pad, lh, w = 3.5, 5.8, self.body_w
        inner = w - 2 * pad
        self.set_font(self.fam, "B", 11)
        height = self.multi_cell(inner, lh, self.t(title), dry_run=True, output="HEIGHT")
        self.set_font(self.fam, "", 11)
        for line in lines:
            height += self.multi_cell(inner, lh, self.t(line), dry_run=True, output="HEIGHT")
        height += 2 * pad + 1
        x, y = self.l_margin, self.get_y()
        self.set_fill_color(234, 240, 250)
        self.set_draw_color(70, 100, 170)
        self.set_line_width(0.4)
        self.rect(x, y, w, height, style="DF")
        self.set_xy(x + pad, y + pad)
        self.set_font(self.fam, "B", 11)
        self.multi_cell(inner, lh, self.t(title), new_x="LEFT", new_y="NEXT")
        self.ln(1)
        self.set_font(self.fam, "", 11)
        for line in lines:
            self.set_x(x + pad)
            self.multi_cell(inner, lh, self.t(line), new_x="LEFT", new_y="NEXT")
        self.set_xy(self.l_margin, y + height + 4)
        self.set_line_width(0.2)

    def numbered(self, label, text, label_w=9, size=11, lh=5.8, space=2.2):
        self.set_font(self.fam, "B", size)
        self.cell(label_w, lh, self.t(label))
        self.set_font(self.fam, "", size)
        self.multi_cell(self.body_w - label_w, lh, self.t(text), align="L",
                        new_x="LMARGIN", new_y="NEXT")
        self.ln(space)

    def check_page(self, expected, what):
        if self.page_no() != expected:
            raise SystemExit("layout overflow in %s: on pdf page %d, expected %d"
                             % (what, self.page_no(), expected))


def render_book(fonts, plan):
    pdf = Doc(fonts)
    pdf.set_title(BOOK_TITLE)
    pdf.set_author(AUTHORS)
    pdf.set_subject("Differential calculus: limits, derivatives, applications")
    pdf.set_creator("tests/fixtures/make_book.py")
    pdf.set_producer("fpdf2 (tutor test fixture)")
    t = pdf.t
    links = {}

    def link_for(key):
        if key not in links:
            links[key] = pdf.add_link()
        return links[key]

    def body_pdf(printed):
        return printed + OFFSET

    # Cover (label "Cover", no footer)
    pdf.start_page(label="Cover", footer="")
    pdf.set_fill_color(28, 52, 104)
    pdf.rect(0, 0, pdf.w, 95, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(pdf.l_margin, 38)
    pdf.set_font(pdf.fam, "B", 40)
    pdf.cell(0, 16, "CALCULUS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(pdf.fam, "", 20)
    pdf.cell(0, 12, "A First Course", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, 120)
    pdf.set_font(pdf.fam, "", 16)
    pdf.cell(0, 10, "Second Edition", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(pdf.fam, "", 13)
    pdf.cell(0, 9, t(AUTHORS), new_x="LMARGIN", new_y="NEXT")
    pdf.check_page(1, "cover")

    # Title page (i)
    pdf.start_page(label="i")
    pdf.ln(30)
    pdf.heading(BOOK_TITLE, size=24, space=6)
    pdf.set_font(pdf.fam, "", 13)
    pdf.cell(0, 8, "Second Edition", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, t(AUTHORS), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(60)
    pdf.set_font(pdf.fam, "", 9.5)
    pdf.multi_cell(0, 5, t("Fixture Press · 2026. Copyright © 2026 by the authors. This "
                          "book was generated as a software test fixture; any resemblance "
                          "to a real textbook is coincidental."), new_x="LMARGIN", new_y="NEXT")
    pdf.check_page(2, "title page")

    # Preface (ii-iii); the log convention is on the second page
    for i, paras in enumerate(PREFACE):
        pdf.start_page(label=int_to_roman(2 + i))
        if i == 0:
            pdf.set_link(link_for("preface"), page=pdf.page_no())
            pdf.heading("Preface", size=20, space=6)
        else:
            pdf.heading("Preface (continued)", size=14, space=4)
        for item in paras:
            pdf.para(item)
        pdf.check_page(3 + i, "preface")

    # Contents (iv-v), with dotted leaders and internal links
    toc_rows = [("Preface", "ii", 0, True, "preface")]
    for ch in CHAPTERS:
        toc_rows.append(("Chapter %d %s" % (ch["num"], ch["title"]), str(ch["printed_start"]),
                         0, True, "ch%d" % ch["num"]))
        for sec in ch["sections"]:
            toc_rows.append(("%s %s" % (sec["num"], sec["title"]), str(sec["printed_start"]),
                             1, False, sec["num"]))
    toc_rows.append(("Appendix A: Answers to Odd-Numbered Exercises", "A-1", 0, True, "appA"))
    toc_rows.append(("Appendix B: Table of Derivatives", "A-%d" % (ANSWER_PAGES + 1), 0, True,
                     "appB"))
    split_at = next(i for i, r in enumerate(toc_rows)
                    if r[0].startswith("Chapter %d " % (CONTENTS_SPLIT + 1)))
    for part, rows in enumerate((toc_rows[:split_at], toc_rows[split_at:])):
        pdf.start_page(label=int_to_roman(4 + part))
        pdf.heading("Contents" if part == 0 else "Contents (continued)",
                    size=20 if part == 0 else 14, space=6)
        x1 = pdf.w - pdf.r_margin
        for title, page, level, bold, key in rows:
            if level == 0:
                pdf.ln(3)
            pdf.set_font(pdf.fam, "B" if bold else "", 11)
            indent = 8 * level
            text = t(title) + " "
            w_title = pdf.get_string_width(text)
            w_page = pdf.get_string_width(" " + page)
            w_dot = pdf.get_string_width(".")
            dots = int((x1 - pdf.l_margin - indent - w_title - w_page) // w_dot)
            pdf.set_x(pdf.l_margin + indent)
            pdf.cell(w_title + dots * w_dot, 7, text + "." * dots, link=link_for(key))
            pdf.cell(x1 - pdf.get_x(), 7, page, align="R", link=link_for(key),
                     new_x="LMARGIN", new_y="NEXT")
        pdf.check_page(5 + part, "contents")

    # Blank page (vi): no footer, very little text
    pdf.start_page(label="vi", footer="")
    pdf.set_y(130)
    pdf.set_font(pdf.fam, "", 10)
    pdf.cell(0, 6, "This page intentionally left blank.", align="C")
    pdf.check_page(OFFSET, "blank page")

    # Body
    for ch in CHAPTERS:
        opener = pdf.start_page(label=str(ch["printed_start"]))
        pdf.set_link(link_for("ch%d" % ch["num"]), page=opener)
        pdf.ln(25)
        pdf.set_font(pdf.fam, "B", 15)
        pdf.set_text_color(70, 100, 170)
        pdf.cell(0, 9, "Chapter %d" % ch["num"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.heading(ch["title"], size=30, space=4)
        pdf.set_draw_color(70, 100, 170)
        pdf.set_line_width(0.8)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.set_line_width(0.2)
        pdf.ln(8)
        for item in ch["intro"]:
            pdf.para(item)
        pdf.check_page(body_pdf(ch["printed_start"]), "chapter %d opener" % ch["num"])

        left = "Chapter %d · %s" % (ch["num"], ch["title"])
        for sec in ch["sections"]:
            right = "%s %s" % (sec["num"], sec["title"])
            for i, kind in enumerate(section_page_kinds(sec)):
                printed = sec["printed_start"] + i
                page = pdf.start_page(label=str(printed), left=left, right=right)
                if kind == "intro":
                    pdf.set_link(link_for(sec["num"]), page=page)
                    pdf.heading("%s %s" % (sec["num"], sec["title"]), size=17, space=5)
                    for item in sec["intro"]:
                        pdf.para(item)
                    pdf.ln(1)
                    pdf.box(*sec["box"])
                    for item in sec.get("after_box", []):
                        pdf.para(item)
                elif kind == "discussion":
                    for item in sec["discussion"]:
                        pdf.para(item)
                    if sec.get("box2"):
                        pdf.ln(1)
                        pdf.box(*sec["box2"])
                elif kind.startswith("example:"):
                    k = int(kind.split(":")[1])
                    ex = sec["examples"][k]
                    many = len(sec["examples"]) > 1
                    pdf.heading("Worked Example" + (" %d" % (k + 1) if many else ""),
                                size=14, space=3)
                    pdf.para(("Problem.", ex["problem"]))
                    pdf.set_font(pdf.fam, "B", 11)
                    pdf.cell(0, 7, "Solution.", new_x="LMARGIN", new_y="NEXT")
                    for n, step in enumerate(ex["steps"], 1):
                        pdf.numbered("Step %d." % n, step, label_w=18)
                    pdf.ln(2)
                    pdf.para(("Answer:", ex["answer"]))
                else:  # exercises
                    pdf.heading("Exercises", size=14, space=3)
                    pdf.para(sec["exercise_intro"])
                    for n, (text, _answer) in enumerate(sec["exercises"], 1):
                        pdf.numbered("%d." % n, text)
                pdf.check_page(body_pdf(printed), "section %s page %d" % (sec["num"], i + 1))

    # Appendix A: answers to odd-numbered exercises
    sections = {sec["num"]: sec for ch in CHAPTERS for sec in ch["sections"]}
    a_first, _ = plan["answers_pdf"]
    for i, group in enumerate(ANSWER_GROUPS):
        page = pdf.start_page(label="A-%d" % (i + 1), left="Appendix A",
                              right="Answers to Odd-Numbered Exercises")
        if i == 0:
            pdf.set_link(link_for("appA"), page=page)
            pdf.heading("Appendix A: Answers to Odd-Numbered Exercises", size=16, space=5)
        for num in group:
            sec = sections[num]
            pdf.set_font(pdf.fam, "B", 11.5)
            pdf.cell(0, 7, "Section %s  %s" % (num, sec["title"]), new_x="LMARGIN", new_y="NEXT")
            for n, (_text, answer) in enumerate(sec["exercises"], 1):
                if n % 2 == 1:
                    pdf.numbered("%d." % n, answer, size=10.5, lh=5.4, space=0.8)
            pdf.ln(3)
        pdf.check_page(a_first + i, "answers page %d" % (i + 1))

    # Appendix B: table of derivatives
    b_first, _ = plan["deriv_pdf"]
    for i, (title, rows, heads) in enumerate((
            ("Appendix B: Table of Derivatives", DERIVATIVE_TABLE, ("f(x)", "f′(x)")),
            ("Differentiation Rules", RULES_TABLE, ("Rule", "Formula")))):
        page = pdf.start_page(label="A-%d" % (ANSWER_PAGES + 1 + i), left="Appendix B",
                              right="Table of Derivatives")
        if i == 0:
            pdf.set_link(link_for("appB"), page=page)
        pdf.heading(title, size=16, space=4)
        if i == 0:
            pdf.para("In this table log denotes the logarithm used throughout the book "
                     "(see the Preface), and a is a positive constant.")
        widths = (70, pdf.body_w - 70)
        pdf.set_font(pdf.fam, "B", 11)
        pdf.set_fill_color(234, 240, 250)
        pdf.cell(widths[0], 8, t(heads[0]), border=1, fill=True)
        pdf.cell(widths[1], 8, t(heads[1]), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.fam, "", 11)
        for a, b in rows:
            pdf.cell(widths[0], 8, t(a), border=1)
            pdf.cell(widths[1], 8, t(b), border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.check_page(b_first + i, "derivatives page %d" % (i + 1))

    if pdf.page_no() != plan["total"]:
        raise SystemExit("expected %d pages, rendered %d" % (plan["total"], pdf.page_no()))
    return bytes(pdf.output())


def render_exam(fonts):
    pdf = Doc(fonts)
    pdf.set_title(EXAM_TITLE)
    pdf.set_author("Department of Mathematics")
    pdf.set_creator("tests/fixtures/make_book.py")
    pdf.set_producer("fpdf2 (tutor test fixture)")
    t = pdf.t
    total = sum(q["points"] for q in EXAM["questions"])
    qs = EXAM["questions"]
    for page_no, chunk in ((1, qs[:3]), (2, qs[3:])):
        pdf.start_page(footer="Page %d of 2" % page_no)
        if page_no == 1:
            pdf.set_font(pdf.fam, "B", 17)
            pdf.cell(0, 10, t(EXAM_TITLE), align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(pdf.fam, "", 11)
            pdf.cell(0, 6, t("Calculus I · Fall 2026 · Covers Sections 1.1–2.4"), align="C",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            pdf.cell(0, 7, t("Time allowed: %d minutes. No calculators, notes, or phones."
                             % EXAM["minutes"]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            pdf.cell(0, 8, "Name: ______________________________     Student ID: ______________",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            pdf.para("Instructions: Answer all six questions in the space provided. Show all "
                     "of your work; answers without supporting work may receive no credit. "
                     "Point values are shown in parentheses. Total: %d points." % total,
                     size=10.5)
            # grading grid
            pdf.set_font(pdf.fam, "B", 9.5)
            cols = ["Question"] + [str(q["n"]) for q in qs] + ["Total"]
            w = pdf.body_w / len(cols)
            for c in cols:
                pdf.cell(w, 6.5, c, border=1, align="C")
            pdf.ln()
            pdf.set_font(pdf.fam, "", 9.5)
            for c in ["Points"] + [str(q["points"]) for q in qs] + [str(total)]:
                pdf.cell(w, 6.5, c, border=1, align="C")
            pdf.ln()
            for c in ["Score"] + [""] * (len(qs) + 1):
                pdf.cell(w, 6.5, c, border=1, align="C")
            pdf.ln(10)
        for q in chunk:
            pdf.numbered("%d." % q["n"], "(%d points) %s" % (q["points"], q["text"]))
            pdf.ln(38 if page_no == 1 else 50)
        pdf.check_page(page_no, "exam page %d" % page_no)
    return bytes(pdf.output())


def int_to_roman(n):
    out = ""
    for value, sym in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
                       (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"),
                       (4, "iv"), (1, "i")):
        count, n = divmod(n, value)
        out += sym * count
    return out


def add_navigation(base, plan):
    """book.pdf = base + nested bookmarks + page labels (via pypdf)."""
    writer = PdfWriter(clone_from=PdfReader(BytesIO(base)))
    add = writer.add_outline_item
    add("Preface", 2)
    add("Contents", 4)
    count = 2
    for ch in CHAPTERS:
        parent = add("Chapter %d %s" % (ch["num"], ch["title"]), ch["printed_start"] + OFFSET - 1)
        count += 1
        for sec in ch["sections"]:
            add("%s %s" % (sec["num"], sec["title"]), sec["printed_start"] + OFFSET - 1,
                parent=parent)
            count += 1
    add("Appendix A: Answers to Odd-Numbered Exercises", plan["answers_pdf"][0] - 1)
    add("Appendix B: Table of Derivatives", plan["deriv_pdf"][0] - 1)
    count += 2
    last = plan["total"] - 1
    writer.set_page_label(0, 0, prefix="Cover")
    writer.set_page_label(1, OFFSET - 1, style="/r")
    writer.set_page_label(OFFSET, OFFSET + plan["body_pages"] - 1, style="/D")
    writer.set_page_label(plan["answers_pdf"][0] - 1, last, style="/D", prefix="A-")
    out = BytesIO()
    writer.write(out)
    return out.getvalue(), count


def build_truth(plan, outline_count, fonts):
    sections, chapters, exercises = {}, {}, []
    for ch in CHAPTERS:
        chapters[str(ch["num"])] = {
            "title": ch["title"], "printed_start": ch["printed_start"],
            "printed_end": ch["printed_end"], "pdf_start": ch["printed_start"] + OFFSET,
            "pdf_end": ch["printed_end"] + OFFSET}
        for sec in ch["sections"]:
            sections[sec["num"]] = {
                "title": sec["title"], "printed_start": sec["printed_start"],
                "printed_end": sec["printed_end"], "pdf_start": sec["printed_start"] + OFFSET,
                "pdf_end": sec["printed_end"] + OFFSET}
            for n, (text, answer) in enumerate(sec["exercises"], 1):
                exercises.append({"sec": sec["num"], "n": n, "text": text, "answer": answer,
                                  "answer_in_book": n % 2 == 1})
    a0, a1 = plan["answers_pdf"]
    b0, b1 = plan["deriv_pdf"]
    return {
        "book_title": BOOK_TITLE,
        "pages": plan["total"],
        "offset": OFFSET,
        "fonts": "DejaVuSans" if fonts else "core-helvetica-ascii",
        "cover_pdf_page": 1,
        "preface_pdf_pages": [3, 4],
        "toc_pdf_pages": [5, 6],
        "blank_pdf_page": OFFSET,
        "log_convention_pdf_page": 4,
        "log_convention": LOG_SENTENCE,
        "label_ranges": [
            {"pdf_start": 1, "pdf_end": 1, "first": "Cover", "last": "Cover"},
            {"pdf_start": 2, "pdf_end": OFFSET, "first": "i", "last": int_to_roman(OFFSET - 1)},
            {"pdf_start": OFFSET + 1, "pdf_end": OFFSET + plan["body_pages"], "first": "1",
             "last": str(plan["body_pages"])},
            {"pdf_start": a0, "pdf_end": b1, "first": "A-1",
             "last": "A-%d" % (ANSWER_PAGES + DERIV_PAGES)},
        ],
        "outline_entries": outline_count,
        "chapters": chapters,
        "sections": sections,
        "answers_appendix": {"label": "A-1", "pdf_start": a0, "pdf_end": a1,
                             "title": "Appendix A: Answers to Odd-Numbered Exercises"},
        "derivatives_appendix": {"label": "A-%d" % (ANSWER_PAGES + 1), "pdf_start": b0,
                                 "pdf_end": b1, "title": "Appendix B: Table of Derivatives"},
        "exercises": exercises,
        "exam": {"file": "practice_exam.pdf", "pages": 2, "title": EXAM_TITLE,
                 "minutes": EXAM["minutes"],
                 "total_points": sum(q["points"] for q in EXAM["questions"]),
                 "questions": EXAM["questions"]},
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    outdir = argv[0]
    os.makedirs(outdir, exist_ok=True)
    fonts = find_dejavu()
    plan = plan_book()
    base = render_book(fonts, plan)
    book, outline_count = add_navigation(base, plan)
    exam = render_exam(fonts)
    for name, data in (("book.pdf", book), ("book_plain.pdf", base), ("practice_exam.pdf", exam)):
        with open(os.path.join(outdir, name), "wb") as fh:
            fh.write(data)
    truth = build_truth(plan, outline_count, fonts)
    with open(os.path.join(outdir, "truth.json"), "w", encoding="utf-8") as fh:
        json.dump(truth, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
