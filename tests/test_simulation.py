"""Whole-prep simulations: synthetic students study with the tutor's scheduler until exam day.

Invariants (hard rules) are checked for every run; outcome thresholds are deliberately loose
quality floors, set well below what the scheduler currently achieves (see docs/research.md).
"""
import datetime as dt
import math
import statistics
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "skills" / "tutor" / "scripts"))
import tutor_state as T  # noqa: E402

D = dt.date
START = D(2026, 9, 26)
EXAM = D(2026, 10, 17)


class Forgetful:
    """Probe knowledge, learning accuracy and an exponential forgetting curve per objective.
    Recall after a gap of g days is 0.95*exp(-g/S); each spaced success multiplies S by `growth`."""

    def __init__(self, known=0.2, learn_p=0.75, s0=5.0, growth=3.0, hyper=0.1):
        self.known, self.learn_p, self.s0, self.growth, self.hyper = known, learn_p, s0, growth, hyper
        self.mem = {}

    def answer(self, o, a, day, rng):
        if a["mode"] == "probe" and o.status == "unseen":
            if rng.random() < self.known:
                return "correct", 0, 3
            return "wrong", 0, (3 if rng.random() < self.hyper else 1)
        if o.status in ("unseen", "learning"):
            ok = rng.random() < self.learn_p
            if ok and o.streak + 1 >= T.LEARN_STREAK:
                self.mem[o.id] = (day, self.s0)
            return ("correct", 0, 2) if ok else ("wrong", 0, 1)
        last, strength = self.mem.get(o.id, (o.learned or day, self.s0))
        gap = (day - last).days
        if rng.random() < 0.95 * math.exp(-gap / strength):
            self.mem[o.id] = (day, strength * self.growth if gap >= 1 else strength)
            return "correct", 0, (3 if rng.random() < 0.6 else 2)
        self.mem[o.id] = (day, max(1.0, strength * 0.7))
        return "wrong", 0, (3 if rng.random() < self.hyper else 1)


def make_course(n=20, minutes=60, exam=EXAM, w3every=3):
    objs = []
    for i in range(n):
        objs.append({"id": f"o{i}", "title": f"Objective {i}", "sec": f"{1 + i * 3 // n}.{i + 1}",
                     "weight": 3 if i % w3every == 0 else 2, "order": i,
                     "prereqs": [f"o{i - 1}"] if i % 4 else []})
    return {"title": "Sim", "start": START.isoformat(), "exam": {"date": exam.isoformat(), "minutes": 50},
            "minutes": minutes, "objectives": objs}


def run(course=None, student=None, seed=1, **kw):
    return T.simulate(course or make_course(), [], START, student=student or Forgetful(), seed=seed, **kw)


def solid_weight(st):
    act = st.active()
    return sum(o.weight for o in act if o.solid()) / sum(o.weight for o in act)


class Invariants(unittest.TestCase):
    """Rules that must hold for every student, every seed."""

    def check(self, st, log, exam=EXAM, minutes=60):
        for e in log:
            left = (exam - e["day"]).days
            if left <= 2:
                self.assertFalse(e["new"], f"new material {left} days before the exam")
                self.assertFalse(set(e["modes"]) & {"learn", "probe", "rescue"}, (e["day"], e["modes"]))
            if left == 0:
                self.assertEqual(set(e["modes"]), {"warmup"})
            self.assertLessEqual(e["used"], e["minutes"] + 15, f"session overran on {e['day']}")
        for ev in st.events_log:
            if ev.get("type") == "attempt" and ev.get("ctx") not in ("warmup",):
                self.assertLess(T.to_date(ev["day"]), exam, "graded work on/after exam day")
        for m in st.mocks:
            self.assertGreaterEqual((exam - m["day"]).days, 3, "mock too close to the exam")

    def test_typical_students(self):
        for seed in (1, 2, 3):
            st, log = run(seed=seed)
            self.check(st, log)
            left = [(EXAM - m["day"]).days for m in st.mocks]
            self.assertEqual(len(left), 2, left)
            self.assertTrue(3 <= left[0] <= 7 and left[1] in (3, 4), left)

    def test_short_window_single_mock(self):
        exam = D(2026, 10, 3)
        st, log = run(make_course(n=8, exam=exam))
        self.check(st, log, exam=exam)
        self.assertEqual([(exam - m["day"]).days for m in st.mocks], [4])

    def test_exam_moved_earlier_mid_prep(self):
        course = make_course()
        st1, _ = run(course, until=D(2026, 10, 1))
        moved = dict(course, exam={"date": "2026-10-13", "minutes": 50})
        st2, log2 = T.simulate(moved, st1.events_log, D(2026, 10, 2), student=Forgetful(), seed=1)
        self.check(st2, log2, exam=D(2026, 10, 13))
        self.assertTrue(all(3 <= (D(2026, 10, 13) - m["day"]).days <= 7 for m in st2.mocks))


class Outcomes(unittest.TestCase):
    def test_typical_student_gets_most_of_the_course_solid(self):
        res = [run(seed=s)[0] for s in (1, 2, 3)]
        self.assertGreaterEqual(statistics.mean(solid_weight(st) for st in res), 0.8)
        self.assertGreaterEqual(statistics.mean(sum(o.status == "mastered" for o in st.active()) for st in res), 13)

    def test_strong_student_is_ready(self):
        st, _ = run(student=Forgetful(known=0.5, learn_p=0.9, s0=10, growth=4), seed=3)
        self.assertTrue(T.readiness(st)["ready"], T.readiness(st))
        self.assertGreaterEqual(sum(o.status == "mastered" for o in st.active()), 15)

    def test_extra_practice_does_not_block_mastery(self):
        """Regression: daily bonus drilling left no spacing gap, so nothing could become mastered."""
        st, log = run(student=Forgetful(known=0.5, learn_p=0.9, s0=10, growth=4), seed=3)
        early = [o for o in st.active() if o.learned and o.learned <= D(2026, 10, 2)]
        self.assertGreaterEqual(sum(o.status == "mastered" for o in early) / len(early), 0.8)

    def test_missed_days_backlog_clears_quickly(self):
        st, log = run(skip={D(2026, 9, 30), D(2026, 10, 1), D(2026, 10, 2)})
        after = [e for e in log if e["day"] > D(2026, 10, 2)]
        self.assertLessEqual(after[3]["overdue_start"], 1, [(e["day"], e["overdue_start"]) for e in after[:5]])

    def test_weak_student_gets_rescue_and_a_behind_flag_within_a_week(self):
        st, log = run(student=Forgetful(known=0.05, learn_p=0.45))
        self.assertTrue(any(e["modes"]["rescue"] for e in log[:7]))
        self.assertTrue(any(e["behind"] for e in log[:7]))

    def test_overload_teaches_high_weight_first(self):
        st, log = run(make_course(n=60, minutes=30, w3every=4))
        self.assertTrue(log[0]["behind"])

        def taught(w):
            xs = [o for o in st.active() if o.weight == w]
            return sum(o.status in ("reviewing", "mastered") for o in xs) / len(xs)

        self.assertGreater(taught(3), taught(2) + 0.3)

    def test_projection_matches_simulated_students(self):
        course = make_course()
        pr = T.projection(course, [], START)
        days = []
        for seed in range(21, 30):
            _, log = T.simulate(course, [], START, student=T.SimStudent(), seed=seed)
            t = next((e["day"] for e in log if e["to_learn"] == 0), EXAM)
            days.append((t - START).days)
        self.assertLessEqual(abs((pr["taught"] - START).days - statistics.median(days)), 2,
                             (pr["taught"], sorted(days)))


if __name__ == "__main__":
    unittest.main()
