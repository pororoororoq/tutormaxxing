"""Unit tests for the tutor state engine (run: python3 -m unittest discover tests)."""
import ast
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / ".claude" / "skills" / "tutor" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tutor_state as T  # noqa: E402

D = dt.date


def course(n=6, start="2026-09-26", exam="2026-10-17", minutes=60, weights=None, **kw):
    objs = []
    for i in range(n):
        objs.append({"id": f"o{i}", "title": f"Objective {i}", "sec": f"{1 + i // 3}.{i % 3 + 1}",
                     "weight": (weights[i] if weights else 2), "order": i})
    c = {"title": "Test", "start": start, "exam": {"date": exam, "minutes": 50}, "minutes": minutes,
         "objectives": objs}
    c.update(kw)
    return c


class Log:
    """Builds an event log the way the CLI does, keeping a live State."""

    def __init__(self, c):
        self.course = c
        self.events = []
        self.st = T.replay(c, [])

    def put(self, ev):
        ev = {"id": len(self.events) + 1, **ev}
        self.events.append(ev)
        self.st.apply(ev)
        return ev

    def session(self, day, at="17:00"):
        now = dt.datetime.fromisoformat(f"{day}T{at}")
        for e in T.ensure_session(self.st, now):
            self.put(e)
        return self.st.open_session()

    def attempt(self, obj, res="correct", ctx="learn", conf=None, hints=0, at=None):
        s = self.st.open_session()
        day = T.iso(s.day)
        return self.put({"type": "attempt", "day": day, "sess": s.id, "obj": obj, "ctx": ctx, "res": res,
                         "hints": hints, "conf": conf, "ts": at or f"{day}T17:05:00"})

    def end(self, at):
        s = self.st.open_session()
        self.put({"type": "session", "act": "end", "sess": s.id, "ts": at})

    def learn(self, obj):
        """Probe wrong, then 3 unaided correct: objective becomes learned today."""
        self.attempt(obj, "wrong", "probe", conf=1)
        for _ in range(3):
            self.attempt(obj)

    def decide(self, at, **kw):
        return T.decide(self.st, dt.datetime.fromisoformat(at), **kw)

    def run(self, at, stop=("done",), until=None, n=80):
        """Follow `decide`: probes answered wrong (so teaching happens), everything else right.
        Returns the (mode, obj) sequence, ending with the stop mode."""
        seq = []
        for _ in range(n):
            if until is not None and until():
                break
            a = self.decide(at)
            if a["mode"] in stop:
                seq.append((a["mode"], a.get("obj")))
                break
            seq.append((a["mode"], a.get("obj")))
            probe = a["mode"] == "probe"
            self.attempt(a["obj"], "wrong" if probe else "correct", T.MODE_CTX[a["mode"]], conf=1 if probe else 3)
        return seq


def past_day0(L):
    """An earlier session, so the next one has no day-0 diagnostic."""
    L.session("2026-09-25")
    L.attempt("o0", "skip", "probe")
    L.end("2026-09-25T18:00:00")


class Transitions(unittest.TestCase):
    def setUp(self):
        self.L = Log(course())

    def o(self, oid="o0"):
        return self.L.st.objs[oid]

    def test_probe_confident_correct_counts_as_known(self):
        self.L.session("2026-09-26")
        self.L.attempt("o0", "correct", "probe", conf=3)
        o = self.o()
        self.assertEqual(o.status, "reviewing")
        self.assertEqual(o.succ, [D(2026, 9, 26)])
        self.assertEqual(o.due, D(2026, 10, 3))          # 21 days left -> gap clamp(rh(7.35)) = 7

    def test_probe_outcomes_set_the_starting_point(self):
        self.L.session("2026-09-26")
        self.L.attempt("o0", "correct", "probe", conf=2)
        self.L.attempt("o1", "correct", "probe", conf=3, hints=1)
        self.L.attempt("o2", "partial", "probe", conf=2)
        self.L.attempt("o3", "wrong", "probe", conf=3)
        self.assertEqual((self.o("o0").status, self.o("o0").start, self.o("o0").streak), ("learning", "independent", 1))
        self.assertEqual(self.o("o1").start, "faded")
        self.assertEqual(self.o("o2").start, "faded")
        self.assertEqual(self.o("o3").start, "worked")
        self.assertIn("misconception", self.o("o3").flags)

    def test_three_unaided_correct_in_a_row_means_learned(self):
        self.L.session("2026-09-26")
        self.L.attempt("o0", "wrong", "probe", conf=3)
        self.L.attempt("o0")
        self.L.attempt("o0", hints=1)                  # a hinted answer does not count and resets
        self.assertEqual(self.o().streak, 0)
        for _ in range(3):
            self.L.attempt("o0")
        o = self.o()
        self.assertEqual((o.status, o.learned, o.due), ("reviewing", D(2026, 9, 26), D(2026, 9, 27)))
        self.assertNotIn("misconception", o.flags)

    def test_wheel_spinning_flags_stuck(self):
        self.L.session("2026-09-26")
        self.L.attempt("o0", "wrong", "probe")
        for _ in range(9):
            self.L.attempt("o0", "wrong")
        self.assertIn("stuck", self.o().flags)

    def test_spaced_success_next_day(self):
        self.L.session("2026-09-26")
        self.L.learn("o0")
        self.L.end("2026-09-26T18:00:00")
        self.L.session("2026-09-27")
        self.L.attempt("o0", "correct", "review", conf=2)
        o = self.o()
        self.assertEqual(o.succ, [D(2026, 9, 27)])
        self.assertEqual(o.due, D(2026, 10, 4))          # 20 days left -> gap 7

    def test_only_first_attempt_of_the_day_counts(self):
        self.L.session("2026-09-26")
        self.L.learn("o0")
        self.L.attempt("o0")                            # same day, after learning: no spaced credit
        self.assertEqual(self.o().succ, [])

    def test_same_day_guard_in_transition(self):
        env = T.Env(course())
        o = T.Obj({"id": "x", "title": "x"}, 0)
        o.status, o.learned = "reviewing", D(2026, 9, 26)
        tag = T.apply_attempt(o, {"day": "2026-09-26", "ctx": "review", "res": "correct", "conf": 3}, env, 0)
        self.assertEqual(tag, "same-day")
        self.assertEqual(o.succ, [])

    def test_lapse_then_relearn(self):
        self.L.session("2026-09-26")
        self.L.learn("o0")
        self.L.end("2026-09-26T18:00:00")
        self.L.session("2026-09-27")
        self.L.attempt("o0", "wrong", "review", conf=3)
        o = self.o()
        self.assertEqual((o.lapses, o.relearn_day, o.due), (1, D(2026, 9, 27), D(2026, 9, 28)))
        self.assertIn("hyper", o.flags)
        self.assertIs(o.last_first_firm, False)
        self.L.attempt("o0", "correct", "relearn", conf=2)
        self.assertIsNone(self.o().relearn_day)
        self.assertEqual(self.o().succ, [])             # relearning today is not a spaced success

    def test_unsure_or_aided_first_try_earns_nothing(self):
        self.L.session("2026-09-26")
        self.L.learn("o0")
        self.L.learn("o1")
        self.L.end("2026-09-26T18:00:00")
        self.L.session("2026-09-27")
        self.L.attempt("o0", "correct", "review", conf=1)
        self.L.attempt("o1", "correct", "review", conf=3, hints=1)
        for oid in ("o0", "o1"):
            o = self.o(oid)
            self.assertEqual((o.succ, o.lapses, o.due), ([], 0, D(2026, 9, 28)))
            self.assertIs(o.last_first_firm, False)

    def _to_mastery(self, mixed=True):
        self.L.session("2026-09-26")
        self.L.learn("o0")
        self.L.end("2026-09-26T18:00:00")
        for day, ctx in (("2026-09-27", "review"), ("2026-09-30", "mixed" if mixed else "review"),
                         ("2026-10-04", "review")):
            self.L.session(day)
            self.L.attempt("o0", "correct", ctx, conf=3)
            self.L.end(f"{day}T18:00:00")

    def test_mastery_needs_three_spaced_days_one_mixed_and_a_long_gap(self):
        self._to_mastery()
        o = self.o()
        self.assertEqual(o.status, "mastered")
        self.assertEqual(o.due, D(2026, 10, 11))        # mastered: weekly, capped at exam-2

    def test_no_mastery_without_mixed_practice(self):
        self._to_mastery(mixed=False)
        self.assertEqual(self.o().status, "reviewing")

    def test_mastery_is_lost_on_a_lapse(self):
        self._to_mastery()
        self.L.session("2026-10-06")
        self.L.attempt("o0", "wrong", "review", conf=2)
        self.assertEqual(self.o().status, "reviewing")

    def test_skip_changes_nothing(self):
        self.L.session("2026-09-26")
        self.L.attempt("o0", "skip", "probe")
        self.assertEqual(self.o().status, "unseen")


class DueDates(unittest.TestCase):
    def setUp(self):
        self.env = T.Env(course())                      # exam Oct 17, W = 21

    def gap(self, day):
        o = T.Obj({"id": "x", "title": "x"}, 0)
        o.status = "reviewing"
        return (T.due_after_success(o, day, self.env) - day).days

    def test_round_half_up(self):
        self.assertEqual((T.rh(2.5), T.rh(3.5), T.rh(3.49)), (3, 4, 3))

    def test_gap_scales_with_days_left(self):
        self.assertEqual(self.gap(D(2026, 9, 27)), 7)     # 20 left -> 7
        self.assertEqual(self.gap(D(2026, 10, 7)), 4)     # 10 left -> rh(3.5) = 4
        self.assertEqual(self.gap(D(2026, 10, 12)), 2)    # 5 left -> rh(1.75) = 2

    def test_never_on_or_after_exam_day(self):
        self.assertEqual(self.env.clamp_due(D(2026, 10, 20), D(2026, 10, 14)), D(2026, 10, 16))
        self.assertIsNone(self.env.clamp_due(D(2026, 10, 18), D(2026, 10, 16)))

    def test_window_constants(self):
        self.assertEqual((self.env.W, self.env.dur, self.env.deadline), (21, 3, D(2026, 10, 7)))
        short = T.Env(course(exam="2026-10-03"))
        self.assertEqual((short.W, short.dur), (7, 2))


class VoidAndReplay(unittest.TestCase):
    def test_void_reverts_the_last_attempt(self):
        L = Log(course())
        L.session("2026-09-26")
        L.learn("o0")
        self.assertEqual(L.st.objs["o0"].status, "reviewing")
        L.events.append({"id": 999, "type": "void", "ref": L.events[-1]["id"]})
        st = T.replay(L.course, L.events)
        self.assertEqual((st.objs["o0"].status, st.objs["o0"].streak), ("learning", 2))

    def test_moving_the_exam_recomputes_due_dates(self):
        L = Log(course())
        L.session("2026-09-26")
        L.attempt("o0", "correct", "probe", conf=3)
        self.assertEqual(L.st.objs["o0"].due, D(2026, 10, 3))
        moved = course(exam="2026-10-01")
        st = T.replay(moved, L.events)
        self.assertEqual(st.objs["o0"].due, D(2026, 9, 28))   # 5 days left -> gap 2


class Decide(unittest.TestCase):
    def test_first_session_probes_across_chapters_then_teaches(self):
        L = Log(course(n=10))
        L.session("2026-09-26")
        probes = []
        for _ in range(8):
            a = L.decide("2026-09-26T17:05")
            self.assertEqual(a["mode"], "probe")
            probes.append(L.st.objs[a["obj"]].chapter())
            L.attempt(a["obj"], "wrong", "probe", conf=1)
        self.assertEqual(len(set(probes[:4])), 4)          # spread over the 4 chapters first
        a = L.decide("2026-09-26T17:25")
        self.assertEqual((a["mode"], a["obj"], a["start"]), ("learn", "o0", "worked"))

    def test_keeps_teaching_the_current_objective(self):
        L = Log(course())
        L.session("2026-09-26")
        L.st.open_session().plan["probes"] = 0
        L.attempt("o3", "wrong", "learn")
        a = L.decide("2026-09-26T17:10")
        self.assertEqual((a["mode"], a["obj"], a["need"]), ("learn", "o3", 3))

    def test_no_clock_hours_away_change_nothing(self):
        L = Log(course())
        past_day0(L)
        L.session("2026-09-26", at="09:00")
        L.attempt("o3", "wrong", "learn", at="2026-09-26T09:05:00")
        a = L.decide("2026-09-26T09:06")
        b = L.decide("2026-09-26T23:30")                 # back after a long break: same item, same day
        self.assertEqual(a, b)
        self.assertEqual((b["mode"], b["obj"], b["day"]), ("learn", "o3", "2026-09-26"))
        self.assertFalse({"elapsed", "left", "minutes"} & set(b))
        self.assertEqual(T.ensure_session(L.st, dt.datetime(2026, 9, 26, 23, 30)), [])

    def test_reviews_come_before_new_material_and_hide_the_topic(self):
        L = Log(course())
        L.session("2026-09-26")
        L.learn("o0")
        L.end("2026-09-26T18:00:00")
        L.session("2026-09-27")
        a = L.decide("2026-09-27T17:01")
        self.assertEqual((a["mode"], a["obj"], a["hide_topic"], a["conf"]), ("review", "o0", True, True))

    def test_relearn_waits_for_two_other_items(self):
        L = Log(course())
        L.session("2026-09-26")
        for oid in ("o0", "o1", "o2"):
            L.learn(oid)
        L.end("2026-09-26T18:00:00")
        L.session("2026-09-27")
        seq = []
        for res in ("wrong", "correct", "correct", "correct"):
            a = L.decide("2026-09-27T17:10")
            seq.append((a["mode"], a["obj"]))
            L.attempt(a["obj"], res, "relearn" if a["mode"] == "relearn" else "review", conf=2)
        self.assertEqual(seq, [("review", "o0"), ("review", "o1"), ("review", "o2"), ("relearn", "o0")])

    def test_prerequisites_are_respected(self):
        c = course(n=3)
        c["objectives"][0].update(order=1)
        c["objectives"][1].update(order=0, prereqs=["o0"])
        L = Log(c)
        L.session("2026-09-25")
        L.attempt("o2", "skip", "probe")               # an earlier session: no diagnostic today
        L.end("2026-09-25T18:00:00")
        L.session("2026-09-26")
        a = L.decide("2026-09-26T17:01")
        self.assertEqual((a["mode"], a["obj"]), ("probe", "o0"))

    def test_behind_teaches_highest_weight_first(self):
        weights = [1] * 30 + [3] * 10
        L = Log(course(n=40, minutes=30, weights=weights))
        L.session("2026-09-25")
        L.attempt("o0", "skip", "probe")
        L.end("2026-09-25T18:00:00")
        s = L.session("2026-09-26")
        self.assertTrue(s.plan["behind"])
        a = L.decide("2026-09-26T17:01")
        self.assertEqual(L.st.objs[a["obj"]].weight, 3)

    def test_no_new_material_in_the_last_two_days(self):
        L = Log(course(n=6))
        L.session("2026-09-26")
        for oid in ("o0", "o1", "o2"):
            L.learn(oid)
        L.end("2026-09-26T18:00:00")
        L.session("2026-10-15")                          # 2 days left
        modes = set()
        for i in range(30):
            a = L.decide("2026-10-15T17:10")
            if a["mode"] == "done":
                break
            modes.add(a["mode"])
            ctx = T.MODE_CTX.get(a["mode"], "review")
            L.attempt(a["obj"], "correct", ctx, conf=3)
        self.assertFalse(modes & {"probe", "learn", "rescue"}, modes)

    def test_exam_day_warmup_then_after_exam_debrief(self):
        L = Log(course())
        L.session("2026-09-26")
        L.learn("o0")
        L.end("2026-09-26T18:00:00")
        L.session("2026-10-17")
        self.assertEqual(L.decide("2026-10-17T08:00")["mode"], "warmup")
        L.end("2026-10-17T08:10:00")
        L.session("2026-10-18")
        self.assertEqual(L.decide("2026-10-18T12:00")["mode"], "debrief")

    def test_focus_on_a_requested_objective(self):
        L = Log(course())
        L.session("2026-09-26")
        a = L.decide("2026-09-26T17:01", focus="o4")
        self.assertEqual((a["mode"], a["obj"]), ("probe", "o4"))
        with self.assertRaises(T.TutorError):
            L.decide("2026-09-26T17:01", focus="nope")


class Pace(unittest.TestCase):
    """continuous (default): new topics for as long as the student keeps going; daily: a quota a day."""

    def log(self, pace=None, n=8):
        """o0-o2 learned and reviewed earlier (none due today); o3.. still to learn; a session on 9/26."""
        c = course(n=n, start="2026-09-22")
        if pace:
            c["pace"] = pace
        L = Log(c)
        L.session("2026-09-22")
        for oid in ("o0", "o1", "o2"):
            L.learn(oid)
        L.end("2026-09-22T18:00:00")
        L.session("2026-09-23")
        for oid in ("o0", "o1", "o2"):
            L.attempt(oid, "correct", "review", conf=3)     # next due 9/30
        L.end("2026-09-23T18:00:00")
        L.session("2026-09-26")
        return L

    def learned_today(self, L):
        return sorted(o.id for o in L.st.active() if o.learned == D(2026, 9, 26))

    def test_continuous_is_the_default(self):
        self.assertEqual(T.Env(course()).pace, "continuous")
        self.assertIsNone(self.log().st.open_session().plan["quota"])

    def test_continuous_keeps_teaching_with_a_mixed_set_after_a_new_topic(self):
        L = self.log()
        seq = L.run("2026-09-26T17:10", stop=("done", "practice"))
        self.assertEqual(self.learned_today(L), ["o3", "o4", "o5", "o6", "o7"])   # daily quota would be 1
        modes = [m for m, _ in seq]
        k = modes.index("mixed")
        self.assertEqual(modes[:k], ["probe", "learn", "learn", "learn"])       # o3 first...
        self.assertEqual(modes[k:k + 4], ["mixed", "mixed", "mixed", "probe"])  # ...3 mixed, then on
        self.assertEqual({o for m, o in seq if m == "mixed"}, {"o0", "o1", "o2"})

    def test_daily_pace_stops_new_topics_at_the_quota(self):
        L = self.log("daily")
        self.assertEqual(L.st.open_session().plan["quota"], 1)   # ceil(1.2 * 5 topics / 10 study days)
        seq = L.run("2026-09-26T17:10")
        self.assertEqual(self.learned_today(L), ["o3"])
        self.assertEqual(seq[-1][0], "done")
        self.assertIn("continuous", L.decide("2026-09-26T18:00")["why"])

    def test_switching_to_daily_mid_session_applies_the_quota(self):
        L = self.log()
        L.run("2026-09-26T17:10", until=lambda: L.st.objs["o4"].status == "reviewing")
        st = T.replay(dict(L.course, pace="daily"), L.events)     # `set --pace daily` now
        self.assertEqual(T.decide(st, dt.datetime(2026, 9, 26, 18, 0))["mode"], "done")
        self.assertIn(L.decide("2026-09-26T18:00")["mode"], ("probe", "learn"))   # continuous goes on

    def test_extra_practice_once_everything_scheduled_is_done(self):
        L = self.log(n=4)
        seq = L.run("2026-09-26T17:10", stop=("done", "practice"))
        self.assertEqual(seq[-1][0], "practice")
        a = L.decide("2026-09-26T17:30")
        self.assertEqual(a["obj"], "o3")                          # the weakest topic from today
        self.assertTrue(a["extra"] and a["hide_topic"])
        self.assertFalse(a["conf"])
        before = {o.id: (o.status, o.due, list(o.succ), o.relearn_day) for o in L.st.active()}
        L.attempt("o3", "wrong", "learn")                         # extra practice never moves the schedule
        self.assertEqual({o.id: (o.status, o.due, list(o.succ), o.relearn_day) for o in L.st.active()}, before)
        self.assertEqual(self.log("daily", n=4).run("2026-09-26T17:10")[-1][0], "done")

    def test_practice_on_a_known_topic_does_not_use_up_the_daily_quota(self):
        L = self.log("daily")
        L.attempt("o5", "correct", "probe", conf=3)          # already known: straight to reviewing
        L.attempt("o5", "correct", "learn", conf=2)          # extra practice the student asked for
        self.assertIsNone(L.st.objs["o5"].first_learn)
        self.assertIn(L.decide("2026-09-26T17:20")["mode"], ("probe", "learn"))

    def test_last_day_stops_after_the_sweep(self):
        L = Log(course(n=4))
        L.session("2026-09-26")
        for oid in ("o0", "o1", "o2", "o3"):
            L.learn(oid)
        L.end("2026-09-26T18:00:00")
        L.session("2026-10-16")                             # 1 day left
        seq = L.run("2026-10-16T17:10")
        self.assertEqual([m for m, _ in seq], ["review"] * 4 + ["done"])
        self.assertIn("final sweep", L.decide("2026-10-16T17:40")["why"])

    def test_topic_order_puts_prerequisites_first(self):
        c = course(n=4, weights=[1, 3, 1, 3])
        c["objectives"][1]["prereqs"] = ["o2"]
        st = T.replay(c, [])
        self.assertEqual([o.id for o in T.topic_order(st)], ["o0", "o2", "o1", "o3"])
        self.assertEqual([o.id for o in T.topic_order(st, behind=True)], ["o3", "o0", "o2", "o1"])
        self.assertEqual(T.next_topic(st).id, "o0")


class Mocks(unittest.TestCase):
    def state(self, exam="2026-10-17", learned_frac=0.0):
        st = T.replay(course(n=10, exam=exam), [])
        for o in list(st.objs.values())[: int(10 * learned_frac)]:
            o.status = "reviewing"
        return st

    def test_windows_for_a_three_week_prep(self):
        self.assertEqual(T.mock_due(self.state(learned_frac=0.7), D(2026, 10, 10)), 1)   # 7 left, 70% learned
        self.assertIsNone(T.mock_due(self.state(learned_frac=0.7), D(2026, 10, 9)))      # 8 left
        self.assertIsNone(T.mock_due(self.state(learned_frac=0.5), D(2026, 10, 10)))
        self.assertEqual(T.mock_due(self.state(), D(2026, 10, 12)), 1)                   # forced at 5 left
        self.assertIsNone(T.mock_due(self.state(), D(2026, 10, 15)))                     # never at <=2
        st = self.state(learned_frac=0.7)
        st.mocks.append({"label": "mock-1", "day": D(2026, 10, 10), "score": 0.8, "predicted": None})
        self.assertEqual(T.mock_due(st, D(2026, 10, 13)), 2)
        self.assertIsNone(T.mock_due(st, D(2026, 10, 11)))

    def test_short_window_gets_one_mock(self):
        self.assertEqual(T.mock_due(self.state(exam="2026-10-03"), D(2026, 9, 29)), 1)  # W=7, 4 left
        self.assertIsNone(T.mock_due(self.state(exam="2026-10-03"), D(2026, 9, 28)))

    def test_mock_is_full_length(self):
        self.assertEqual(T.mock_size(T.Env(course())), (6, 50))       # 50-minute exam, ~8 min a question
        c = course()
        c["exam"]["questions"] = 9
        self.assertEqual(T.mock_size(T.Env(c)), (9, 50))


class Sessions(unittest.TestCase):
    def test_session_crossing_midnight_keeps_its_day(self):
        L = Log(course())
        L.session("2026-09-26", at="23:30")
        L.attempt("o0", "wrong", "probe", at="2026-09-26T23:50:00")
        now = dt.datetime(2026, 9, 27, 0, 20)
        self.assertEqual(T.ensure_session(L.st, now), [])
        self.assertEqual(T.decide(L.st, now)["day"], "2026-09-26")

    def test_long_break_after_midnight_starts_the_new_day(self):
        L = Log(course())
        L.session("2026-09-26", at="22:00")
        L.attempt("o0", "wrong", "probe", at="2026-09-26T22:10:00")
        evs = T.ensure_session(L.st, dt.datetime(2026, 9, 27, 4, 0))    # 6 h later
        self.assertEqual([e["act"] for e in evs], ["end", "start"])
        self.assertEqual(evs[-1]["day"], "2026-09-27")

    def test_coming_back_later_the_same_day_after_end(self):
        L = Log(course())
        L.session("2026-09-26", at="17:00")
        L.end("2026-09-26T17:40:00")
        evs = T.ensure_session(L.st, dt.datetime(2026, 9, 26, 21, 0))
        self.assertEqual([(e["act"], e["day"]) for e in evs], [("start", "2026-09-26")])
        self.assertNotIn("minutes", evs[0])
        self.assertNotIn("minutes", evs[0]["plan"])

    def test_old_time_budget_events_are_ignored(self):
        L = Log(course())
        s = L.session("2026-09-26")
        L.put({"type": "session", "act": "adjust", "sess": s.id, "minutes": 20})   # logs written before v2
        self.assertIsNone(L.st.open_session().end)
        self.assertNotEqual(L.decide("2026-09-26T23:00")["mode"], "done")

    def test_stale_session_is_closed(self):
        L = Log(course())
        L.session("2026-09-26")
        evs = T.ensure_session(L.st, dt.datetime(2026, 9, 27, 17, 0))
        self.assertEqual([(e["act"], e.get("auto")) for e in evs], [("end", True), ("start", None)])


class Readiness(unittest.TestCase):
    def test_nothing_learned_is_not_ready(self):
        rd = T.readiness(T.replay(course(), []))
        self.assertFalse(rd["ready"])
        self.assertLess(rd["R"], 0.1)

    def test_ace_needs_everything(self):
        st = T.replay(course(n=2), [])
        for o in st.objs.values():
            o.status, o.succ, o.last_first_firm = "mastered", [1, 2, 3], True
        st.mocks = [{"label": "m1", "day": D(2026, 10, 10), "score": 0.96, "predicted": 0.95},
                    {"label": "m2", "day": D(2026, 10, 13), "score": 0.97, "predicted": 0.97}]
        rd = T.readiness(st)
        self.assertTrue(rd["ready"] and rd["ace"], rd)
        st.mocks[-1]["score"] = 0.9
        self.assertFalse(T.readiness(st)["ace"])


def objectives_json(path, ids=("o0", "o1", "o2", "o3", "o4", "o5"), extra=None):
    objs = [{"id": i, "title": f"Title {i}", "sec": f"1.{n + 1}", "weight": 2} for n, i in enumerate(ids)]
    if extra:
        objs += extra
    Path(path).write_text(json.dumps(objs), encoding="utf-8")
    return path


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "inbox").mkdir()
        (self.root / "inbox" / "book.pdf").write_bytes(b"%PDF-1.4 fake")
        self.env = dict(os.environ, TUTOR_HOME=str(self.root), TUTOR_TODAY="2026-09-26",
                        CLAUDE_CODE_ENTRYPOINT="cli")
        self.env.pop("TUTOR_NOW", None)
        self.env.pop("TUTOR_MATH", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_t(self, *args, env=None, ok=True):
        p = subprocess.run([sys.executable, str(SCRIPTS / "tutor_state.py"), *args], capture_output=True,
                           text=True, env=env or self.env, cwd=str(self.root))
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def setup_course(self):
        self.run_t("init", "--slug", "calc", "--title", "Calc", "--exam", "2026-10-17")
        self.run_t("import", objectives_json(self.root / "objs.json"))

    def test_full_flow(self):
        self.setup_course()
        self.assertTrue((self.root / "courses" / "calc" / "materials" / "book.pdf").is_file())
        self.assertIn("objectives 6", self.run_t("brief").stdout)
        a = json.loads(self.run_t("next").stdout)
        self.assertEqual(a["mode"], "probe")
        out = self.run_t("record", "--obj", a["obj"], "--ctx", "probe", "--res", "wrong", "--conf", "1",
                         "--note", "forgot the inner derivative").stdout.splitlines()
        self.assertEqual(json.loads(out[0])["now"], "learning")
        self.assertIn("mode", json.loads(out[1]))
        self.assertIn("session", self.run_t("end").stdout)
        tdir = self.root / "courses" / "calc" / "tutor"
        self.assertTrue((tdir / "progress.md").is_file() and (tdir / "plan.md").is_file())
        self.assertIn("forgot the inner derivative", (tdir / "progress.md").read_text(encoding="utf-8"))
        self.assertIn("readiness", self.run_t("status").stdout)
        self.assertIn("projection", self.run_t("plan").stdout)
        self.assertIn(a["obj"] + ":", self.run_t("obj", a["obj"]).stdout)

    def test_import_rejects_bad_objectives(self):
        self.run_t("init", "--slug", "calc", "--exam", "2026-10-17")
        bad = [
            [{"id": "Bad Id", "title": "x"}],
            [{"id": "a", "title": "x"}, {"id": "a", "title": "y"}],
            [{"id": "a", "title": "x", "prereqs": ["zz"]}],
            [{"id": "a", "title": "x", "prereqs": ["b"]}, {"id": "b", "title": "y", "prereqs": ["a"]}],
            [{"id": "a", "title": "x", "weight": 5}],
        ]
        for case in bad:
            f = self.root / "bad.json"
            f.write_text(json.dumps(case), encoding="utf-8")
            p = self.run_t("import", str(f), ok=False)
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertIn("error:", p.stdout)
        c = json.loads((self.root / "courses" / "calc" / "tutor" / "course.json").read_text(encoding="utf-8"))
        self.assertEqual(c["objectives"], [])

    def test_replace_keeps_history_as_triaged(self):
        self.setup_course()
        self.run_t("record", "--obj", "o0", "--ctx", "probe", "--res", "wrong")
        self.run_t("import", "--replace", objectives_json(self.root / "o2.json", ids=("o1", "o2")))
        self.assertIn("objectives 2", self.run_t("brief").stdout)
        c = json.loads((self.root / "courses" / "calc" / "tutor" / "course.json").read_text(encoding="utf-8"))
        self.assertTrue(next(o for o in c["objectives"] if o["id"] == "o0")["triaged"])

    def test_corrupt_course_file_falls_back_to_backup(self):
        self.setup_course()
        cj = self.root / "courses" / "calc" / "tutor" / "course.json"
        cj.write_text("{broken", encoding="utf-8")
        p = self.run_t("status")
        self.assertIn("readiness", p.stdout)
        self.assertIn("course.json.bak", p.stderr)

    def test_brief_never_fails(self):
        self.setup_course()
        tdir = self.root / "courses" / "calc" / "tutor"
        (tdir / "course.json").write_text("{broken", encoding="utf-8")
        (tdir / "course.json.bak").unlink()
        p = self.run_t("brief")
        self.assertIn("state unavailable", p.stdout)

    def test_unknown_objective_is_explained(self):
        self.setup_course()
        p = self.run_t("record", "--obj", "o9x", "--ctx", "learn", "--res", "correct", ok=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("unknown objective", p.stdout)

    def test_math_mode_follows_the_app_and_can_be_overridden(self):
        self.setup_course()
        self.assertEqual(json.loads(self.run_t("next").stdout)["math"], "unicode")
        desk = dict(self.env, CLAUDE_CODE_ENTRYPOINT="claude-desktop")
        self.assertEqual(json.loads(self.run_t("next", env=desk).stdout)["math"], "latex")
        self.run_t("set", "--math", "unicode")
        self.assertEqual(json.loads(self.run_t("next", env=desk).stdout)["math"], "unicode")

    def test_void_and_mock_commands(self):
        self.setup_course()
        self.run_t("record", "--obj", "o0", "--ctx", "probe", "--res", "correct", "--conf", "3")
        self.assertIn("voided", self.run_t("void", "--reason", "wrong key").stdout)
        self.assertIn("mock-1 started", self.run_t("mock", "start").stdout)
        self.run_t("record", "--obj", "o1", "--ctx", "mock", "--res", "correct", "--conf", "2")
        out = self.run_t("mock", "result", "--score", "80", "--predicted", "90").stdout
        self.assertIn("80%", out)
        self.assertIn("+10 pts", out)

    def test_set_exam_moves_the_plan(self):
        self.setup_course()
        out = self.run_t("set", "--exam", "2026-10-10", "--skip-date", "2026-09-30").stdout
        self.assertIn("14 days left", out)

    def test_brief_shows_no_clock_times(self):
        self.setup_course()
        self.run_t("next")
        out = self.run_t("brief").stdout
        self.assertIn("open session from", out)
        self.assertNotRegex(out, r"\b\d{1,2}:\d{2}\b")

    def test_pace_setting_and_plan(self):
        self.setup_course()
        plan = self.root / "courses" / "calc" / "tutor" / "plan.md"
        self.assertIn("continuous pace", self.run_t("status").stdout)
        self.run_t("plan")
        text = plan.read_text(encoding="utf-8")
        self.assertIn("Topics, in the order you'll learn them", text)
        self.assertIn("1. Title o0 (§1.1)", text)
        self.assertNotIn("Day by day", text)
        self.assertIn("daily pace", self.run_t("set", "--pace", "daily").stdout)
        self.assertIn("1 new topic (daily pace", self.run_t("brief").stdout)
        self.run_t("plan")
        self.assertIn("## Day by day", plan.read_text(encoding="utf-8"))
        self.assertEqual(self.run_t("set", "--pace", "weekly", ok=False).returncode, 2)
        a = json.loads(self.run_t("next", "--minutes", "20").stdout)     # old option: accepted, ignored
        self.assertEqual(a["mode"], "probe")
        self.assertFalse({"elapsed", "left"} & set(a))


class Compatibility(unittest.TestCase):
    def test_scripts_parse_as_python_39(self):
        for f in sorted(SCRIPTS.glob("*.py")):
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
