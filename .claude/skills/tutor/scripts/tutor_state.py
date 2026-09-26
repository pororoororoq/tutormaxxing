#!/usr/bin/env python3
"""State + scheduling engine for the `tutor` skill (Python 3.9+, standard library only).

Storage, per course, in <root>/courses/<slug>/tutor/:
  course.json   exam info, settings, objectives (rewritten atomically; previous copy kept as .bak)
  events.jsonl  append-only log of attempt / session / mock / void events

Everything about the learner (status, streaks, due dates, readiness) is DERIVED by replaying
the log. So `void`, rule changes and exam-date changes apply retroactively, and there is no
second copy of the truth that could drift out of sync.

The caller is the tutor (an LLM): `next` and `record` print one JSON line each; the other
commands print a few lines of text. Run `tutor_state.py <command> -h` for arguments.
Dates: --today / $TUTOR_TODAY override the date; $TUTOR_NOW overrides date and time.
Scheduling parameters are explained where they are defined; sources are in docs/research.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------------------
# Scheduling parameters
# --------------------------------------------------------------------------------------
LEARN_STREAK = 3          # consecutive unaided correct answers => "learned" (successive-relearning
                          # criterion; ASSISTments/ALEKS also use 3 in a row)
MASTERY_DAYS = 3          # first-try unaided successes on separate later days => durable (Rawson & Dunlosky)
GAP_RATIO = 0.35          # review gap ~35% of days left before the exam (Cepeda 2008: 20-40%, err longer)
GAP_MIN, GAP_MAX = 2, 7   # keep a not-yet-mastered objective within a week
DUR_RATIO = 0.15          # mastery needs one success gap >= 15% of the prep window (clamped to 2-3 days)
TEACH_BY = 0.55           # finish first teaching by 55% of the window so late objectives still get spaced
REVIEW_SHARE = 0.60       # reviews may use <=60% of a session so new learning keeps moving
STUCK_TRIES = 10          # ~10 tries without learning = wheel-spinning (Beck & Gong 2013) -> rescue
MAX_TRIES_SESSION = 12    # stop hammering one objective within a single session (fatigue)
RELEARN_TRIES = 3         # attempts allowed to re-earn a failed review the same day
RELEARN_GAP = 2           # other items in between before re-testing a failed review
DAY0_PROBES = 8           # first-session diagnostic sample
FRONTLOAD = 1.2           # start new objectives ~20% faster than an even spread
NEW_MINUTES = 25          # time budget per new objective when capping a day's quota
MIN_PER = {"probe": 2, "learn": 4, "review": 3, "relearn": 3, "mixed": 4, "mock": 6, "warmup": 2}
TEACH_OVERHEAD = {"worked": 8, "faded": 4, "independent": 0, None: 4}   # explanation before practice
NEW_COST = {None: 20, "worked": 28, "faded": 18, "independent": 10}    # est. minutes to first-teach
                                                                        # (probe + teaching + ~4 practice items)
NEW_SHARE = 0.60          # average share of a day's minutes available for new material (rest: reviews, mixed)
MIXED_CTX = ("mixed", "mock")
CTXS = ("probe", "learn", "review", "relearn", "mixed", "mock", "warmup")
RESULTS = ("correct", "partial", "wrong", "skip")
ERRS = ("concept", "procedure", "careless", "misread", "time")
RANK = {"unseen": 0, "learning": 1, "reviewing": 2, "mastered": 3}
DESKTOP_ENTRYPOINTS = ("claude-desktop", "claude-desktop-3p", "remote_desktop")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ONE = dt.timedelta(days=1)


class TutorError(Exception):
    """An expected problem, reported as a one-line error."""


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def rh(x):
    """Round half up (Python's round() rounds half to even)."""
    return int(math.floor(x + 0.5))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def to_date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def to_dt(v):
    return v if isinstance(v, dt.datetime) else dt.datetime.fromisoformat(str(v))


def iso(d):
    return d.isoformat() if d else None


def stamp(t):
    return t.replace(microsecond=0).isoformat()


def fmt_day(d):
    return f"{d.strftime('%a %b')} {d.day}"


def pct(x):
    return f"{rh(100 * x)}%"


def mins(a, b):
    return (b - a).total_seconds() / 60.0


def jline(obj):
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def parse_date(text, today):
    """ISO date, M/D or M/D/YYYY (M/D means the next such date)."""
    s = str(text).strip()
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        if m.group(3):
            yr = int(m.group(3))
            yr = yr + 2000 if yr < 100 else yr
            return dt.date(yr, mo, da)
        d = dt.date(today.year, mo, da)
        return d if d >= today else dt.date(today.year + 1, mo, da)
    raise TutorError(f"can't read date '{text}' (use YYYY-MM-DD)")


def get_now(args=None):
    env_now = os.environ.get("TUTOR_NOW")
    if env_now:
        return dt.datetime.fromisoformat(env_now)
    day = getattr(args, "today", None) or os.environ.get("TUTOR_TODAY")
    now = dt.datetime.now()
    if day:
        return dt.datetime.combine(dt.date.fromisoformat(day), now.time())
    return now


def math_mode(course=None):
    m = (os.environ.get("TUTOR_MATH") or (course or {}).get("math") or "auto").lower()
    if m in ("latex", "unicode"):
        return m
    return "latex" if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "") in DESKTOP_ENTRYPOINTS else "unicode"


# Repeated in every `next`/`record` output: models drift back to LaTeX habits unless reminded in-band.
MATH_FORMAT = {
    "unicode": "plain-text math ONLY: x², √(x+1), (a+b)/(c+d), ∫₀¹, θ, Δv; no $ signs, no backslashes",
    "latex": "LaTeX: inline $…$; display $$…$$ on its own line; never $$ mid-sentence; avoid \\, \\; \\!",
}


def with_math(a, course):
    mode = math_mode(course)
    a["math"] = mode
    a["format"] = MATH_FORMAT[mode]
    return a


# --------------------------------------------------------------------------------------
# Paths and storage
# --------------------------------------------------------------------------------------
def find_root(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.environ.get("TUTOR_HOME"):
        return Path(os.environ["TUTOR_HOME"]).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for p in (cwd, *cwd.parents):
        if (p / "courses" / ".active").is_file():
            return p
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj and Path(proj).is_dir():
        return Path(proj).resolve()
    return cwd


class Paths:
    def __init__(self, root, slug=None):
        self.root = Path(root)
        self.courses = self.root / "courses"
        self.inbox = self.root / "inbox"
        self.active_file = self.courses / ".active"
        if slug is None and self.active_file.is_file():
            slug = self.active_file.read_text(encoding="utf-8").strip() or None
        self.slug = slug
        base = self.courses / (slug or "_none_")
        self.dir = base
        self.materials = base / "materials"
        self.tdir = base / "tutor"
        self.course_json = self.tdir / "course.json"
        self.events = self.tdir / "events.jsonl"
        self.notes = self.tdir / "notes"

    def exists(self):
        return bool(self.slug) and self.course_json.is_file()


def paths_from(args):
    return Paths(find_root(getattr(args, "root", None)), getattr(args, "course", None))


def load_course(P):
    if not P.slug:
        raise TutorError("no active course yet: set one up first (onboarding -> `init`)")
    if not P.course_json.is_file():
        raise TutorError(f"course '{P.slug}' has no course.json at {P.course_json}")
    try:
        return json.loads(P.course_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        bak = P.course_json.with_name("course.json.bak")
        if bak.is_file():
            sys.stderr.write(f"warning: course.json unreadable ({e}); using course.json.bak\n")
            return json.loads(bak.read_text(encoding="utf-8"))
        raise TutorError(f"course.json is corrupt ({e}) and there is no backup")


def save_course(P, course):
    P.tdir.mkdir(parents=True, exist_ok=True)
    tmp = P.course_json.with_name("course.json.tmp")
    tmp.write_text(json.dumps(course, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if P.course_json.is_file():
        shutil.copy2(P.course_json, P.course_json.with_name("course.json.bak"))
    os.replace(tmp, P.course_json)


def load_events(P):
    evs = []
    if not P.events.is_file():
        return evs
    with open(P.events, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                evs.append(json.loads(line))
            except json.JSONDecodeError:
                sys.stderr.write(f"warning: skipped unreadable line {n} of events.jsonl\n")
    return evs


def append_events(P, events, new):
    """Give events ids and append them to the log (and to `events`). Returns the stored copies."""
    nxt = max((int(e.get("id", 0)) for e in events), default=0) + 1
    stored = []
    P.tdir.mkdir(parents=True, exist_ok=True)
    with open(P.events, "a", encoding="utf-8") as f:
        for e in new:
            e = {"id": nxt, **{k: v for k, v in e.items() if k != "id"}}
            nxt += 1
            stored.append(e)
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    events.extend(stored)
    return stored


def load_all(args):
    P = paths_from(args)
    course = load_course(P)
    return P, course, load_events(P)


# --------------------------------------------------------------------------------------
# Derived state
# --------------------------------------------------------------------------------------
class Env:
    """Course-level constants derived from course.json."""

    def __init__(self, course):
        ex = course.get("exam") or {}
        if not ex.get("date"):
            raise TutorError("course.json has no exam date: run `set --exam YYYY-MM-DD`")
        self.exam = to_date(ex["date"])
        self.start = to_date(course.get("start") or course.get("created") or ex["date"])
        self.W = max(1, (self.exam - self.start).days)
        self.dur = clamp(rh(DUR_RATIO * self.W), 2, 3)
        self.deadline = self.start + dt.timedelta(days=int(TEACH_BY * self.W))
        self.minutes = int(course.get("minutes") or 60)
        self.off = {str(w).strip().lower()[:3] for w in course.get("off_days") or []}
        self.skip = {to_date(s) for s in course.get("skip_dates") or []}
        self.target = float(course.get("target") or 0.95)
        self.exam_minutes = int(ex.get("minutes") or 50)
        self.exam_questions = int(ex.get("questions") or 0)
        self.formats = {k: float(v) for k, v in (ex.get("formats") or {}).items() if float(v) > 0}

    def days_left(self, day):
        return (self.exam - day).days

    def study_day(self, day):
        return WEEKDAYS[day.weekday()] not in self.off and day not in self.skip

    def study_days(self, a, b):
        n, d = 0, a
        while d <= b:
            n += self.study_day(d)
            d += ONE
        return n

    def clamp_due(self, due, today):
        """Reviews happen at the latest on the day before the exam."""
        last = self.exam - ONE
        if due > last:
            return last if today < last else None
        return due

    def next_study_day(self, after):
        d = after + ONE
        while d <= self.exam:
            if d == self.exam or self.study_day(d):
                return d
            d += ONE
        return None


class Obj:
    """Derived learning state of one objective."""

    def __init__(self, spec, pos):
        self.spec = spec
        self.id = spec["id"]
        self.title = spec.get("title") or self.id
        self.weight = int(spec.get("weight") or 2)
        self.order = int(spec.get("order", pos))
        self.prereqs = list(spec.get("prereqs") or [])
        self.confusable = list(spec.get("confusable") or [])
        self.triaged = bool(spec.get("triaged"))
        self.status = "unseen"
        self.start = None             # where first teaching begins: worked | faded | independent
        self.streak = 0
        self.tries = 0                # attempts while learning
        self.learned = None           # date it became learned
        self.succ = []                # dates of spaced first-try successes
        self.mixed_ok = False         # succeeded first-try in a mixed set or mock
        self.lapses = 0
        self.last_first_firm = None   # was the latest first-try-of-the-day review firm?
        self.flags = set()            # misconception | hyper (confident error) | stuck
        self.due = None
        self.last_day = None
        self.relearn_day = None
        self.relearn_at = 0
        self.relearn_tries = 0
        self.items = []               # (day, item) presented
        self.misses = []              # (day, err, note)
        self.attempts = 0
        self.correct = 0

    def chapter(self):
        sec = str(self.spec.get("sec") or "")
        return sec.split(".")[0] if sec else self.id.split("-")[0]

    def max_gap(self):
        days = sorted(set(([self.learned] if self.learned else []) + self.succ))
        return max(((b - a).days for a, b in zip(days, days[1:])), default=0)

    def p(self):
        """Rough chance of solving an exam item on this objective (used for readiness)."""
        base = {"unseen": 0.05, "learning": 0.30, "mastered": 0.92}.get(self.status)
        if base is None:
            base = 0.55 + 0.10 * min(len(self.succ), MASTERY_DAYS)
        return min(base, 0.45) if self.last_first_firm is False else base

    def solid(self):
        return self.status == "mastered" or (len(self.succ) >= 2 and self.last_first_firm is not False)


def refresh(o, env):
    if o.status in ("reviewing", "mastered"):
        ok = (len(o.succ) >= MASTERY_DAYS and o.mixed_ok and o.last_first_firm is True
              and o.max_gap() >= env.dur)
        o.status = "mastered" if ok else "reviewing"


def due_after_success(o, day, env):
    if o.status == "mastered":   # keep warm weekly, then the final sweep
        due = max(day + 2 * ONE, min(day + 7 * ONE, env.exam - 2 * ONE))
    else:
        due = day + dt.timedelta(days=clamp(rh(GAP_RATIO * env.days_left(day)), GAP_MIN, GAP_MAX))
    return env.clamp_due(due, day)


def apply_attempt(o, ev, env, idx):
    """Transition one objective for one attempt. Returns a short outcome tag."""
    day = to_date(ev["day"])
    ctx = ev.get("ctx") or "learn"
    res = ev.get("res") or "wrong"
    hints = int(ev.get("hints") or 0)
    conf = ev.get("conf")
    conf = int(conf) if conf not in (None, "") else None
    o.attempts += 1
    if ev.get("item"):
        o.items.append((day, str(ev["item"])))
    if res == "skip" or ctx == "warmup":
        return "logged"
    unaided = res == "correct" and hints == 0
    firm = unaided and (conf is None or conf >= 2)
    sure = conf == 3
    if unaided:
        o.correct += 1
    elif ev.get("err") or ev.get("note"):
        o.misses.append((day, ev.get("err"), ev.get("note")))
    first = o.last_day != day
    o.last_day = day

    if o.status == "unseen":                       # first contact acts as the diagnostic probe
        if unaided and sure:
            o.status, o.start, o.learned, o.succ = "reviewing", "independent", day, [day]
            o.last_first_firm = True
            o.mixed_ok = ctx in MIXED_CTX
            refresh(o, env)
            o.due = due_after_success(o, day, env)
            return "known"
        o.status, o.tries = "learning", 1
        if unaided:
            o.streak, o.start = 1, "independent"
        elif res == "wrong":
            o.start = "worked"
            if sure:
                o.flags.add("misconception")
        else:
            o.start = "faded"
        return "to-learn"

    if o.status == "learning":
        o.tries += 1
        if unaided:
            o.streak += 1
            if o.streak >= LEARN_STREAK:
                o.status, o.learned, o.streak = "reviewing", day, 0
                o.flags -= {"stuck", "misconception"}
                o.due = env.clamp_due(day + ONE, day)
                return "learned"
            return "streak"
        o.streak = 0
        if res == "wrong" and sure:
            o.flags.add("misconception")
        if o.tries >= STUCK_TRIES:
            o.flags.add("stuck")
        return "miss"

    # reviewing / mastered: only the first attempt of a day measures retention
    if not first:
        if o.relearn_day == day:
            o.relearn_tries += 1
            if unaided:
                o.relearn_day = None
                return "relearned"
            return "relearn-miss"
        return "extra"
    if firm and day > o.learned:
        if day not in o.succ:
            o.succ.append(day)
        o.mixed_ok = o.mixed_ok or ctx in MIXED_CTX
        o.last_first_firm = True
        o.flags.discard("hyper")
        refresh(o, env)
        o.due = due_after_success(o, day, env)
        return "mastered" if o.status == "mastered" else "success"
    o.due = env.clamp_due(day + ONE, day)
    if firm:                                       # same day it was learned: no spaced credit
        return "same-day"
    o.last_first_firm = False
    if res == "wrong":
        o.lapses += 1
        if sure:
            o.flags.add("hyper")
        o.relearn_day, o.relearn_at, o.relearn_tries = day, idx, 0
        refresh(o, env)
        return "lapse"
    refresh(o, env)
    return "shaky"


class Session:
    def __init__(self, ev):
        self.id = ev["id"]
        self.day = to_date(ev["day"])
        self.start = to_dt(ev["ts"])
        self.last = self.start
        self.minutes = int(ev.get("minutes") or 60)
        self.plan = dict(ev.get("plan") or {})
        self.end = None
        self.n = 0
        self.correct = 0
        self.tries = Counter()
        self.ctx = Counter()
        self.learn_order = []
        self.last_learn = None
        self.probed = []
        self.mixed_objs = []
        self.tags = Counter()
        self.learned = []
        self.lapsed = []


class State:
    def __init__(self, course):
        self.course = course
        self.env = Env(course)
        specs = list(course.get("objectives") or [])
        ordered = sorted(enumerate(specs), key=lambda t: (int(t[1].get("order", t[0])), t[0]))
        self.objs = {s["id"]: Obj(s, pos) for pos, s in ordered}
        self.sessions = []
        self.mocks = []
        self.n_attempts = 0
        self.last_tag = None
        self.notes_dir = None

    def active(self):
        return [o for o in self.objs.values() if not o.triaged]

    def session(self, sid):
        for s in reversed(self.sessions):
            if s.id == sid:
                return s
        return None

    def open_session(self):
        s = self.sessions[-1] if self.sessions else None
        return s if s and s.end is None else None

    def open_mock(self):
        m = self.mocks[-1] if self.mocks else None
        return m if m and m["score"] is None else None

    def apply(self, ev):
        t = ev.get("type")
        if t == "attempt":
            self._attempt(ev)
        elif t == "session":
            act = ev.get("act")
            if act == "start":
                self.sessions.append(Session(ev))
            else:
                s = self.session(ev.get("sess"))
                if s is not None:
                    if act == "end":
                        s.end = to_dt(ev["ts"])
                    elif act == "adjust":
                        s.minutes = int(ev.get("minutes") or s.minutes)
        elif t == "mock":
            if ev.get("act") == "start":
                self.mocks.append({"id": ev["id"], "label": ev.get("label") or f"mock-{len(self.mocks) + 1}",
                                   "day": to_date(ev["day"]), "start": to_dt(ev["ts"]), "n": ev.get("n"),
                                   "minutes": ev.get("minutes"), "score": None, "predicted": None})
            elif ev.get("act") == "result" and self.mocks:
                m = self.open_mock() or self.mocks[-1]
                m["score"] = float(ev["score"])
                m["predicted"] = None if ev.get("predicted") is None else float(ev["predicted"])

    def _attempt(self, ev):
        idx = self.n_attempts
        self.n_attempts += 1
        o = self.objs.get(ev.get("obj"))
        s = self.session(ev.get("sess")) or self.open_session()
        if o is None:
            self.last_tag = "unknown-objective"
            return
        tag = apply_attempt(o, ev, self.env, idx)
        self.last_tag = tag
        if s is None:
            return
        ctx = ev.get("ctx") or "learn"
        s.n += 1
        s.last = max(s.last, to_dt(ev["ts"]))
        s.tries[o.id] += 1
        s.ctx[ctx] += 1
        s.tags[tag] += 1
        if ev.get("res") == "correct" and not int(ev.get("hints") or 0):
            s.correct += 1
        if ctx == "learn":
            if o.id not in s.learn_order:
                s.learn_order.append(o.id)
            s.last_learn = o.id
        elif ctx == "probe" and o.id not in s.probed:
            s.probed.append(o.id)
        elif ctx == "mixed":
            s.mixed_objs.append(o.id)
        if tag == "learned":
            s.learned.append(o.id)
        elif tag == "lapse":
            s.lapsed.append(o.id)


def replay(course, events):
    voided = {e.get("ref") for e in events if e.get("type") == "void"}
    st = State(course)
    for e in events:
        if e.get("type") != "void" and e.get("id") not in voided:
            st.apply(e)
    return st


# --------------------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------------------
def to_learn(st):
    return [o for o in st.active() if o.status in ("unseen", "learning")]


def learn_cost(o):
    if o.status == "unseen":
        return NEW_COST[None]
    return NEW_COST.get(o.start, NEW_COST[None]) * (LEARN_STREAK - o.streak) / LEARN_STREAK


def is_behind(st, today):
    """True if first-teaching everything left won't fit before the teach-by deadline."""
    need = sum(learn_cost(o) for o in to_learn(st))
    if need <= 0:
        return False
    env = st.env
    if today > env.deadline:
        return True
    return need > env.study_days(today, env.deadline) * NEW_SHARE * env.minutes


def due_today(st, today, s=None):
    return [o for o in st.active() if o.status in ("reviewing", "mastered") and o.due is not None
            and o.due <= today and o.last_day != today and (s is None or not s.tries[o.id])]


def review_order(today):
    """Confident errors first, then fragile before already-mastered, then most overdue and heaviest."""
    return lambda o: ("hyper" not in o.flags, "misconception" not in o.flags, o.status == "mastered",
                      -(today - o.due).days, -o.weight, o.order)


def mock_due(st, today):
    env = st.env
    d = env.days_left(today)
    if d <= 2 or st.open_mock():
        return None
    done = [m for m in st.mocks if m["score"] is not None]
    act = st.active()
    tw = sum(o.weight for o in act) or 1
    learned = sum(o.weight for o in act if o.status in ("reviewing", "mastered")) / tw
    if env.W >= 10:
        if not done and ((d <= 7 and learned >= 0.7) or d <= 5):
            return 1
        if len(done) == 1 and d in (3, 4) and (today - done[0]["day"]).days >= 2:
            return 2
    elif not done and d <= 4:
        return 1
    return None


def mock_size(env, session_minutes):
    minutes = env.exam_minutes
    if session_minutes - 15 < minutes:          # leave time to grade
        minutes = max(20, session_minutes - 15)
    nq = env.exam_questions or max(4, rh(env.exam_minutes / 8))
    return max(3, rh(nq * minutes / env.exam_minutes)), minutes


def session_plan(st, today, minutes):
    env = st.env
    d = env.days_left(today)
    tl = to_learn(st)
    end = env.deadline if today <= env.deadline else env.exam - 3 * ONE
    days = max(1, env.study_days(today, end)) if end >= today else 1
    mixed_n = 3 if d > 0.45 * env.W else 5
    due_n = len(due_today(st, today))
    quota = 0
    if tl and d > 2:
        quota = math.ceil(FRONTLOAD * len(tl) / days)
        review_min = min(REVIEW_SHARE * minutes, MIN_PER["review"] * due_n)
        cap = int((minutes - review_min - mixed_n * MIN_PER["mixed"]) // NEW_MINUTES)
        quota = max(1, min(quota, cap))
    first = not any(s.n for s in st.sessions)
    probes = min(DAY0_PROBES, sum(o.status == "unseen" for o in tl)) if first and d > 2 else 0
    return {"quota": quota, "mixed": mixed_n, "probes": probes, "due": due_n,
            "mock": mock_due(st, today), "behind": is_behind(st, today)}


def ensure_session(st, now, minutes=None):
    """Events needed so that a session for `now` is open (closes a stale one first)."""
    evs = []
    s = st.open_session()
    if s is not None:
        same = s.day == now.date() or (mins(s.last, now) < 360 and mins(s.start, now) < 720)
        if same:
            if minutes:
                total = rh(mins(s.start, now)) + int(minutes)
                if total != s.minutes:
                    evs.append({"type": "session", "act": "adjust", "sess": s.id, "minutes": total,
                                "ts": stamp(now)})
            return evs
        evs.append({"type": "session", "act": "end", "sess": s.id, "ts": stamp(s.last), "auto": True})
    today = now.date()
    used = sum(mins(x.start, x.end) for x in st.sessions if x.day == today and x.end)
    if minutes:
        m = int(minutes)
    else:
        m = st.env.minutes if used < 1 else max(15, rh(st.env.minutes - used))
    evs.append({"type": "session", "act": "start", "day": iso(today), "minutes": m,
                "plan": session_plan(st, today, m), "ts": stamp(now)})
    return evs


def prereqs_ok(st, o, level):
    for pid in o.prereqs:
        q = st.objs.get(pid)
        if q is not None and not q.triaged and RANK[q.status] < level:
            return False
    return True


def pick_probe(st, s, unseen):
    probed = Counter(st.objs[i].chapter() for i in s.probed)
    fresh = [o for o in unseen if not s.tries[o.id]]
    if not fresh:
        return None
    return sorted(fresh, key=lambda o: (probed[o.chapter()], -o.weight, o.order))[0]


def is_recent(o, today):
    return o.learned is not None and (today - o.learned).days <= 3


def pick_mixed(st, today, s, pool):
    pool = [o for o in pool if o.last_day != today and not s.tries[o.id]]
    if not pool:
        return None
    prev = st.objs.get(s.mixed_objs[-1]) if s.mixed_objs else None
    n_recent = sum(is_recent(st.objs[i], today) for i in s.mixed_objs)
    want_recent = n_recent < math.ceil((len(s.mixed_objs) + 1) / 3)

    def key(o):
        sc = 0.0
        if not o.mixed_ok:
            sc += 3
        if prev is not None and (o.id in prev.confusable or prev.id in o.confusable):
            sc += 2
        if is_recent(o, today) == want_recent:
            sc += 1
        if o.due is not None and o.due <= today + ONE:
            sc += 1
        if o.last_day is not None and (today - o.last_day).days < 2:
            sc -= 2                                    # seen yesterday: let spacing do its work
        sc += 0.5 * o.weight - (0.5 if o.status == "mastered" else 0)
        return (-sc, o.order)

    return sorted(pool, key=key)[0]


def pick_format(env, k):
    """Cycle exam formats in proportion to the blueprint (largest-remainder allocation of 10)."""
    if not env.formats:
        return "exam-style"
    total = sum(env.formats.values())
    raw = {f: 10 * v / total for f, v in env.formats.items()}
    alloc = {f: int(v) for f, v in raw.items()}
    for f in sorted(raw, key=lambda f: raw[f] - alloc[f], reverse=True)[: 10 - sum(alloc.values())]:
        alloc[f] += 1
    seq = [f for f in sorted(alloc, key=lambda f: -alloc[f]) for _ in range(alloc[f])]
    return seq[k % len(seq)]


def decide(st, now, focus=None):
    """The next thing the tutor should do. Pure: reads state, never writes."""
    env = st.env
    s = st.open_session()
    if s is None:
        return {"mode": "none", "why": "no open session"}
    today = s.day
    d = env.days_left(today)
    elapsed = mins(s.start, now)
    left = s.minutes - elapsed
    act_objs = st.active()
    base = {"day": iso(today), "days_left": d, "elapsed": max(0, rh(elapsed)), "left": max(0, rh(left))}

    def act(mode, o=None, why="", **kw):
        a = {"mode": mode}
        if o is not None:
            a["obj"] = o.id
            a["title"] = o.title
            for k in ("sec", "pages"):
                if o.spec.get(k):
                    a[k] = o.spec[k]
            recent = [it for (dd, it) in o.items if (today - dd).days <= 5]
            if recent:
                a["avoid"] = recent[-6:]
            if st.notes_dir is not None:
                note = st.notes_dir / f"{o.id}.md"
                a["notes"] = str(note)
                a["notes_exist"] = note.is_file()
            if o.flags:
                a["flags"] = sorted(o.flags)
        if why:
            a["why"] = why
        a.update(kw)
        a.update(base)
        return a

    def learn_act(o, why):
        mode = "rescue" if "stuck" in o.flags else "learn"
        return act(mode, o, why, start=o.start, streak=o.streak, need=LEARN_STREAK - o.streak,
                   tries=o.tries, conf=False)

    if d < 0:
        return act("debrief", why=f"the exam was {fmt_day(env.exam)}: ask how it went, record the score")
    if d == 0:
        if s.ctx["warmup"] >= 5:
            return act("done", why="warm-up finished: wish them luck, remind them to sleep/eat, stop")
        pool = [o for o in act_objs if o.status in ("reviewing", "mastered") and not s.tries[o.id]]
        pool.sort(key=lambda o: (o.status != "mastered", -o.weight, o.order))
        if not pool:
            return act("done", why="exam day: nothing to warm up with; rest")
        return act("warmup", pool[0], why="exam-day warm-up: an easy confidence builder, no teaching",
                   k=s.ctx["warmup"] + 1, of=5)
    m = st.open_mock()
    if m is not None:
        return act("mock", why="mock in progress: collect answers or photos, grade every part, "
                   "record each, then `mock result`", phase="grade", label=m["label"],
                   started=m["start"].strftime("%H:%M"), minutes=m.get("minutes"))
    if s.plan.get("mock") and not any(x["day"] == today for x in st.mocks):
        n, mm = mock_size(env, s.minutes)
        return act("mock", why=f"scheduled mock exam #{s.plan['mock']} ({d} days left)", phase="start",
                   label=f"mock-{len(st.mocks) + 1}", n=n, minutes=mm)

    if focus:
        o = st.objs.get(focus)
        if o is None:
            raise TutorError(f"unknown objective '{focus}'" + suggest(focus, st.objs))
        if o.status == "unseen":
            return act("probe", o, "student asked for this topic: probe first", conf=True)
        if o.status == "learning":
            return learn_act(o, "student asked for this topic")
        if o.last_day != today and not s.tries[o.id]:
            return act("review", o, "student asked for this topic (counts as today's review)", conf=True)
        return act("practice", o, "student asked for extra practice (no effect on the schedule)", conf=False)

    relearn = [o for o in act_objs if o.relearn_day == today and o.relearn_tries < RELEARN_TRIES]
    relearn.sort(key=lambda o: (-o.weight, o.order))
    for o in relearn:
        if st.n_attempts - o.relearn_at - 1 >= RELEARN_GAP:
            return act("relearn", o, "missed on review earlier today: one fresh item" +
                       ("; missed on 2+ reviews, so reteach the core idea first" if o.lapses >= 2 else ""),
                       conf=True)

    cur = st.objs.get(s.last_learn) if s.last_learn else None
    if (cur is not None and cur.status == "learning" and not cur.triaged
            and s.tries[cur.id] < MAX_TRIES_SESSION and left > 5):
        return learn_act(cur, f"continue until {LEARN_STREAK} unaided correct in a row")
    if left <= 0:
        return act("wrap", why=f"time's up ({rh(elapsed)}/{s.minutes} min): end on a success, then `end`")

    tl = [o for o in act_objs if o.status in ("unseen", "learning")]
    due = sorted(due_today(st, today, s), key=review_order(today))
    cap = math.inf if (d <= 2 or not tl) else int(REVIEW_SHARE * s.minutes // MIN_PER["review"])
    mixed_left = max(0, int(s.plan.get("mixed", 3)) - s.ctx["mixed"])
    if due and s.ctx["review"] < cap:
        o = due[0]
        why = "due for spaced review"
        if o.due < today:
            why += f" ({(today - o.due).days}d overdue)"
        if "hyper" in o.flags:
            why += "; last time a CONFIDENT error, re-test it"
        return act("review", o, why, conf=True, hide_topic=True)

    # when behind, an untaught objective is worth more than mixed practice: don't reserve time for it
    reserve = (0 if s.plan.get("behind") else mixed_left * MIN_PER["mixed"]) + 10
    if d > 2 and left > reserve:
        unseen = [o for o in tl if o.status == "unseen"]
        if s.plan.get("probes") and s.ctx["probe"] < s.plan["probes"] and unseen:
            o = pick_probe(st, s, unseen)
            if o is not None:
                return act("probe", o, f"diagnostic {s.ctx['probe'] + 1}/{s.plan['probes']}: one exam-style "
                           "question, no teaching yet", conf=True)
        if len(s.learn_order) < s.plan.get("quota", 1):
            cands = [o for o in tl if s.tries[o.id] < MAX_TRIES_SESSION
                     and not (o.status == "unseen" and s.tries[o.id])]
            ok = []
            for level in (2, 1, 0):
                ok = [o for o in cands if prereqs_ok(st, o, level)]
                if ok:
                    break
            if ok:
                key = (lambda o: (-o.weight, o.order)) if s.plan.get("behind") else (lambda o: o.order)
                o = sorted(ok, key=key)[0]
                if o.status == "unseen":
                    return act("probe", o, "first contact: a quick probe decides where teaching starts",
                               conf=True)
                return learn_act(o, "next objective in the plan" + (" (behind: highest weight first)"
                                                                     if s.plan.get("behind") else ""))

    learned = [o for o in act_objs if o.status in ("reviewing", "mastered")]
    if mixed_left > 0 and len(learned) >= 3 and left > 0:
        o = pick_mixed(st, today, s, learned)
        if o is not None:
            k = s.ctx["mixed"]
            return act("mixed", o, "interleaved exam-style practice: don't name the topic", conf=True,
                       hide_topic=True, k=k + 1, of=int(s.plan.get("mixed", 3)), fmt=pick_format(env, k))

    if relearn:
        return act("relearn", relearn[0], "missed on review earlier today: one fresh item", conf=True)
    if due and left > 0:
        return act("review", due[0], "due for spaced review", conf=True, hide_topic=True)
    if d > 2 and left > 15:                        # spare time: front-load the next new objective
        cands = [o for o in tl if s.tries[o.id] < MAX_TRIES_SESSION
                 and not (o.status == "unseen" and s.tries[o.id]) and prereqs_ok(st, o, 1)]
        if cands:
            o = sorted(cands, key=lambda o: o.order)[0]
            if o.status == "unseen":
                return act("probe", o, "ahead of schedule: quick probe of the next objective", conf=True)
            return learn_act(o, "ahead of schedule: time left, so start the next objective")
    if left > 5 and learned:
        # extra practice only on objectives that have rested: daily drilling would leave no
        # spacing gap to prove durable memory (and overlearning in one sitting fades fast)
        rested = [o for o in learned if o.last_day is None or (today - o.last_day).days >= env.dur]
        o = pick_mixed(st, today, s, rested)
        if o is not None:
            return act("mixed", o, "bonus: today's plan is done; a harder exam-level variant", conf=True,
                       hide_topic=True, hard=True, fmt=pick_format(env, s.ctx["mixed"]))
    nxt = env.next_study_day(today)
    return act("done", why="today's plan is complete (stopping early is fine: spacing beats cramming); "
               "run `end`", next=iso(nxt))


# --------------------------------------------------------------------------------------
# Readiness and simulation
# --------------------------------------------------------------------------------------
def readiness(st):
    objs = st.active()
    done = [m for m in st.mocks if m["score"] is not None]
    if not objs:
        return {"R": 0.0, "ready": False, "ace": False, "unmet_ready": ["no objectives yet"],
                "unmet_ace": ["no objectives yet"], "last_mock": None}
    tw = sum(o.weight for o in objs)
    R = sum(o.weight * o.p() for o in objs) / tw
    last = done[-1] if done else None
    if last is not None:
        R = 0.5 * R + 0.5 * last["score"]
    ur = []
    if R < 0.85:
        ur.append(f"readiness {pct(R)} < 85%")
    if last is None:
        ur.append("no mock exam yet")
    elif last["score"] < 0.80:
        ur.append(f"last mock {pct(last['score'])} < 80%")
    weak3 = [o.id for o in objs if o.weight == 3 and not o.solid()]
    if weak3:
        ur.append(f"{len(weak3)} high-weight objective(s) not solid yet: " + ", ".join(weak3[:4]))
    ua = []
    nm = [o for o in objs if o.status != "mastered"]
    if nm:
        ua.append(f"{len(nm)} objective(s) not mastered")
    t = st.env.target
    top = [x for x in done[-2:] if x["score"] >= t]
    if len(done) < 2 or len(top) < 2:
        ua.append(f"last 2 mocks must both be >= {pct(t)}")
    if last is not None and last.get("predicted") is not None and abs(last["predicted"] - last["score"]) > 0.10:
        ua.append(f"calibration: predicted {pct(last['predicted'])} vs actual {pct(last['score'])}")
    flagged = [o.id for o in objs if o.flags & {"hyper", "misconception"}]
    if flagged:
        ua.append("open confident errors: " + ", ".join(flagged[:4]))
    return {"R": R, "ready": not ur, "ace": not ur and not ua, "unmet_ready": ur, "unmet_ace": ua,
            "last_mock": None if last is None else last["score"]}


class SimStudent:
    """Answers with fixed accuracy; `known` = chance a probe shows prior knowledge."""

    def __init__(self, p=0.8, known=0.25):
        self.p, self.known = p, known

    def answer(self, o, a, day, rng):
        if a["mode"] == "probe":
            if rng.random() < self.known:
                return "correct", 0, 3
            r = rng.random()
            return ("wrong", 0, 1) if r < 0.5 else (("partial", 0, 2) if r < 0.8 else ("correct", 0, 2))
        if rng.random() < self.p:
            return "correct", 0, (3 if rng.random() < 0.7 else 2)
        return "wrong", 0, (2 if rng.random() < 0.3 else 1)


MODE_CTX = {"probe": "probe", "learn": "learn", "rescue": "learn", "practice": "learn", "review": "review",
            "relearn": "relearn", "mixed": "mixed", "warmup": "warmup"}


def simulate(course, events, start, student=None, seed=7, minutes=None, skip=(), until=None):
    """Drive `decide` day by day with a synthetic student. Returns (state, per-day log)."""
    rng = random.Random(seed)
    student = student or SimStudent()
    st = replay(course, events)
    env = st.env
    nid = max((int(e.get("id", 0)) for e in events), default=0) + 1
    log = []
    day = start
    last = min(env.exam, until) if until else env.exam
    skip = set(skip)

    st.events_log = list(events)

    def put(ev):
        nonlocal nid
        ev = {"id": nid, **ev}
        nid += 1
        st.apply(ev)
        st.events_log.append(ev)
        return ev

    while day <= last:
        if day in skip or (day != env.exam and not env.study_day(day)):
            day += ONE
            continue
        now = dt.datetime.combine(day, dt.time(17, 0))
        for ev in ensure_session(st, now, minutes):
            put(ev)
        s = st.open_session()
        due0 = due_today(st, day)
        entry = {"day": day, "modes": Counter(), "learned": [], "new": [], "mock": None,
                 "minutes": s.minutes, "due_start": len(due0), "behind": bool(s.plan.get("behind")),
                 "overdue_start": sum(1 for o in due0 if o.due < day)}
        for _ in range(400):
            a = decide(st, now)
            mode = a["mode"]
            if mode in ("wrap", "done", "debrief", "none"):
                break
            if mode == "mock":
                ev = put({"type": "mock", "act": "start", "day": iso(day), "label": a["label"], "n": a["n"],
                          "minutes": a["minutes"], "ts": stamp(now)})
                pool = [o for o in st.active()]
                weights = [o.weight for o in pool]
                right = 0
                for o in rng.choices(pool, weights=weights, k=a["n"]):
                    res, hints, conf = student.answer(o, {"mode": "mixed"}, day, rng)
                    right += res == "correct"
                    put({"type": "attempt", "day": iso(day), "sess": s.id, "obj": o.id, "ctx": "mock",
                         "res": res, "hints": hints, "conf": conf, "ts": stamp(now)})
                score = right / a["n"]
                now += dt.timedelta(minutes=a["minutes"] + 10)
                put({"type": "mock", "act": "result", "score": score,
                     "predicted": min(1.0, score + rng.uniform(-0.05, 0.15)), "ts": stamp(now)})
                entry["mock"] = (ev["label"], score)
                continue
            o = st.objs[a["obj"]]
            first_learn = mode in ("learn", "rescue") and o.id not in s.learn_order
            res, hints, conf = student.answer(o, a, day, rng)
            if mode in ("learn", "rescue") and first_learn:
                entry["new"].append(o.id)
            put({"type": "attempt", "day": iso(day), "sess": s.id, "obj": o.id, "ctx": MODE_CTX[mode],
                 "res": res, "hints": hints, "conf": conf, "ts": stamp(now)})
            entry["modes"][mode] += 1
            if st.last_tag == "learned":
                entry["learned"].append(o.id)
            cost = MIN_PER.get(MODE_CTX[mode], 4)
            if first_learn:
                cost += TEACH_OVERHEAD.get(o.start, 4)
            now += dt.timedelta(minutes=cost)
        put({"type": "session", "act": "end", "sess": s.id, "ts": stamp(now)})
        entry["used"] = rh(mins(s.start, now))
        entry["to_learn"] = len(to_learn(st))
        log.append(entry)
        day += ONE
    return st, log


def projection(course, events, start, minutes=None, runs=5):
    """Simulate several synthetic students (different seeds); return the median run plus the spread.
    A single run is noisy: with 80% accuracy, finishing first-teaching varies by about a week."""
    nothing_left = not to_learn(replay(course, events))
    results = []
    for seed in (7, 11, 13, 17, 19)[:runs]:
        st, log = simulate(course, events, start, minutes=minutes, seed=seed)
        taught = start if nothing_left else next((e["day"] for e in log if e["to_learn"] == 0), None)
        results.append({"state": st, "log": log, "taught": taught, "all_taught": not to_learn(st),
                        "readiness": readiness(st), "mastered": sum(o.status == "mastered" for o in st.active()),
                        "mocks": [(m["day"], m["score"]) for m in st.mocks if m["score"] is not None]})
    results.sort(key=lambda r: r["taught"] or dt.date.max)
    med = results[len(results) // 2]
    med["taught_range"] = (results[0]["taught"], results[-1]["taught"])
    return med


def minutes_needed(course, events, start):
    env = Env(course)
    for m in (30, 45, 60, 75, 90, 105, 120, 150, 180):
        pr = projection(course, events, start, minutes=m, runs=3)
        if pr["taught"] is not None and pr["taught"] <= max(env.deadline, start):
            return m
    return None


# --------------------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------------------
def counts(st):
    c = Counter(o.status for o in st.active())
    tri = sum(o.triaged for o in st.objs.values())
    txt = (f"mastered {c['mastered']} · reviewing {c['reviewing']} · learning {c['learning']} · "
           f"unseen {c['unseen']}")
    return txt + (f" · triaged {tri}" if tri else "")


def status_word(o):
    if o.status == "reviewing":
        return f"reviewing {len(o.succ)}/{MASTERY_DAYS}"
    if o.status == "learning":
        return f"learning {o.streak}/{LEARN_STREAK}"
    return o.status


def plan_lines(course, events, start, title_of):
    pr = projection(course, events, start)
    env = Env(course)
    out = []
    for e in pr["log"]:
        parts = []
        if e["modes"]["review"]:
            parts.append(f"{e['modes']['review']} reviews")
        if e["new"]:
            parts.append("new: " + ", ".join(title_of(i) for i in e["new"]))
        if e["modes"]["probe"]:
            parts.append(f"{e['modes']['probe']} probes")
        if e["modes"]["mixed"]:
            parts.append(f"{e['modes']['mixed']} mixed")
        if e["mock"]:
            parts.append(f"MOCK EXAM ({e['mock'][0]})")
        if e["day"] == env.exam:
            parts = ["EXAM DAY: 5 warm-up items, then go"]
        elif env.days_left(e["day"]) == 1:
            parts.insert(0, "final sweep, formula sheet, early night")
        out.append(f"- {fmt_day(e['day'])}: " + (" · ".join(parts) if parts else "light review"))
    return pr, out


def write_plan(P, course, events, start):
    st = replay(course, events)
    title_of = lambda i: st.objs[i].title if i in st.objs else i  # noqa: E731
    pr, lines = plan_lines(course, events, start, title_of)
    env = st.env
    head = [f"# Study plan: {course.get('title', P.slug)}",
            f"_Projection from {fmt_day(start)} assuming ~80% accuracy and {env.minutes} min/day. "
            "It is recomputed after every session, so it adapts to how you actually do._", ""]
    if pr["taught"]:
        head.append(f"- Everything first-taught by about **{fmt_day(pr['taught'])}** "
                    f"({span(pr['taught_range'])}; target {fmt_day(env.deadline)})")
    else:
        head.append(f"- Not everything can be first-taught before the exam at this pace "
                    f"(target {fmt_day(env.deadline)}): the tutor teaches the highest-weight topics first")
    for d, sc in pr["mocks"]:
        head.append(f"- Mock exam around {fmt_day(d)}")
    head.append(f"- Projected at exam day: {pr['mastered']}/{len(st.active())} mastered, "
                f"readiness ~{pct(pr['readiness']['R'])}")
    (P.tdir / "plan.md").write_text("\n".join(head + ["", "## Day by day", ""] + lines) + "\n",
                                    encoding="utf-8")
    return pr


def write_progress(P, course, st, now):
    env = st.env
    rd = readiness(st)
    today = now.date()
    d = env.days_left(today)
    lines = [f"# {course.get('title', P.slug)}: progress",
             f"_Updated {fmt_day(today)} · exam {fmt_day(env.exam)} ({max(d, 0)} days left)_", "",
             f"**Readiness {pct(rd['R'])}** · ready: {'yes' if rd['ready'] else 'not yet'} · "
             f"ace-ready: {'yes' if rd['ace'] else 'not yet'}", "", counts(st), "",
             "| Objective | § | Weight | Status | Next review | Flags |", "|---|---|---|---|---|---|"]
    for o in sorted(st.objs.values(), key=lambda o: o.order):
        if o.triaged:
            continue
        lines.append(f"| {o.title} | {o.spec.get('sec', '')} | {'★' * o.weight} | {status_word(o)} | "
                     f"{fmt_day(o.due) if o.due else ''} | {', '.join(sorted(o.flags))} |")
    traps = list(course.get("learner") or [])
    misses = sorted(((m[0], o.title, m[1], m[2]) for o in st.active() for m in o.misses if m[2]),
                    key=lambda t: t[0], reverse=True)
    lines += ["", "## Your traps", ""]
    lines += [f"- {t}" for t in traps] + [f"- {t} ({e or 'error'}): {n}" for _, t, e, n in misses[:10]]
    if not traps and not misses:
        lines.append("- none recorded yet")
    done = [m for m in st.mocks if m["score"] is not None]
    if done:
        lines += ["", "## Mock exams", "", "| Mock | Date | Score | You predicted |", "|---|---|---|---|"]
        for m in done:
            pr = "" if m["predicted"] is None else pct(m["predicted"])
            lines.append(f"| {m['label']} | {fmt_day(m['day'])} | {pct(m['score'])} | {pr} |")
    if rd["unmet_ready"] or rd["unmet_ace"]:
        lines += ["", "## Still to do before the exam", ""]
        lines += [f"- {u}" for u in rd["unmet_ready"] + rd["unmet_ace"]]
    (P.tdir / "progress.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def span(rng):
    lo, hi = rng
    if lo is None:
        return "not reached in simulation"
    if hi is None:
        return f"from {fmt_day(lo)}, some runs never finish"
    return f"range {fmt_day(lo)}–{fmt_day(hi)}" if lo != hi else "all runs agree"


def suggest(name, objs):
    close = difflib.get_close_matches(name, list(objs), n=3)
    return f" (did you mean: {', '.join(close)}?)" if close else ""


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------
def inbox_summary(P):
    if not P.inbox.is_dir():
        return "inbox/ is empty (no folder yet)"
    files = [f for f in sorted(P.inbox.iterdir()) if f.is_file() and not f.name.startswith(".")]
    if not files:
        return "inbox/ is empty"
    return "inbox/: " + ", ".join(f"{f.name} ({f.stat().st_size / 1e6:.1f} MB)" for f in files[:12])


def pypdf_status(P):
    try:
        import pypdf  # noqa: F401
        return "pypdf ✓"
    except Exception:
        venv = P.courses / ".venv"
        for py in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
            if py.is_file():
                return "pypdf ✓ (courses/.venv)"
        return "pypdf ✗ (run pdf_tools.py setup before reading PDFs)"


def brief_lines(P, now):
    today = now.date()
    if not P.exists():
        others = sorted(p.name for p in P.courses.glob("*/tutor/course.json")) if P.courses.is_dir() else []
        lines = ["tutor: no course set up yet.", inbox_summary(P),
                 f"python {sys.version.split()[0]} · {pypdf_status(P)} · math: {math_mode()}"]
        if others:
            lines.append("existing courses (use `use <slug>`): " + ", ".join(sorted(
                p.parent.parent.name for p in P.courses.glob("*/tutor/course.json"))))
        lines.append("next: onboarding (read references/onboarding.md)")
        return lines
    course = load_course(P)
    events = load_events(P)
    st = replay(course, events)
    env = st.env
    d = env.days_left(today)
    ex_time = (course.get("exam") or {}).get("time")
    lines = [f"tutor · {course.get('title', P.slug)} ({P.slug}) · exam {fmt_day(env.exam)}"
             f"{' ' + ex_time if ex_time else ''} · {d} days left · today {fmt_day(today)} · "
             f"math: {math_mode(course)} ({MATH_FORMAT[math_mode(course)]})"]
    if not st.objs:
        lines.append("setup incomplete: no objectives yet (continue onboarding at the objectives step)")
        lines.append(inbox_summary(P))
        return lines
    rd = readiness(st)
    lines.append(f"objectives {len(st.active())}: {counts(st)} · readiness {pct(rd['R'])}")
    if d < 0:
        lines.append("the exam is over: debrief (record the real score, capture lessons)")
    elif d == 0:
        lines.append("EXAM DAY: 5 easy warm-up items at most, then logistics and encouragement")
    else:
        sp = session_plan(st, today, env.minutes)
        bits = [f"{sp['due']} reviews due", f"{sp['quota']} new"]
        if sp["probes"]:
            bits.insert(0, f"first session: {sp['probes']} diagnostic probes")
        if sp["mock"]:
            bits.append(f"MOCK EXAM #{sp['mock']}")
        bits.append(f"mixed {sp['mixed']}")
        lines.append(f"today (~{env.minutes} min): " + " · ".join(bits) +
                     (" · BEHIND: highest weight first" if sp["behind"] else ""))
    past = [s for s in st.sessions if s.day < today and s.n]
    if past:
        gap = (today - past[-1].day).days
        missed = env.study_days(past[-1].day + ONE, today - ONE) if gap > 1 else 0
        lines.append(f"last session {fmt_day(past[-1].day)}" +
                     (f" ({missed} study day(s) missed: the schedule already absorbed it)" if missed else ""))
    s = st.open_session()
    if s is not None:
        lines.append(f"open session from {fmt_day(s.day)} {s.start.strftime('%H:%M')} "
                     f"({s.n} items so far)" + ("" if s.day == today else ": `next` closes it"))
    fl = [f"{o.id}({','.join(sorted(o.flags))})" for o in st.active() if o.flags]
    if fl:
        lines.append("flags: " + " ".join(fl[:6]))
    if course.get("learner"):
        lines.append("learner notes: " + "; ".join(course["learner"][:4]))
    have = [n for n in ("blueprint.md", "conventions.md") if (P.tdir / n).is_file()]
    lines.append(f"files: {P.tdir}" + (f" ({', '.join(have)})" if have else " (no blueprint/conventions yet)"))
    return lines


def cmd_brief(args):
    try:
        lines = brief_lines(paths_from(args), get_now(args))
    except Exception as e:  # the brief is injected at skill load: it must never fail
        lines = [f"tutor: state unavailable ({type(e).__name__}: {e}). Run the `doctor` command."]
    print("\n".join(lines[:12]))
    return 0


def cmd_doctor(args):
    P = paths_from(args)
    ok = sys.version_info >= (3, 9)
    print(f"python {sys.version.split()[0]} {'✓' if ok else '✗ (need 3.9+)'} · {pypdf_status(P)} · "
          f"poppler {'✓' if shutil.which('pdftoppm') else '— (not needed)'}")
    try:
        P.root.mkdir(parents=True, exist_ok=True)
        probe = P.root / ".tutor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        w = "writable ✓"
    except Exception as e:
        w = f"NOT writable ({e})"
    print(f"root {P.root} ({w}) · active course: {P.slug or '—'}")
    ep = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "?")
    course = load_course(P) if P.exists() else None
    print(f"entrypoint {ep} → math: {math_mode(course)}"
          + (f" · TUTOR_TODAY={os.environ['TUTOR_TODAY']}" if os.environ.get("TUTOR_TODAY") else ""))
    print(inbox_summary(P))
    return 0


def adopt_inbox(P):
    moved = []
    if not P.inbox.is_dir():
        return moved
    P.materials.mkdir(parents=True, exist_ok=True)
    for f in sorted(P.inbox.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        dest = P.materials / f.name
        k = 2
        while dest.exists():
            dest = P.materials / f"{f.stem}-{k}{f.suffix}"
            k += 1
        shutil.move(str(f), str(dest))
        moved.append(dest)
    return moved


def cmd_init(args):
    root = find_root(args.root)
    now = get_now(args)
    today = now.date()
    slug = args.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise TutorError("slug must be lowercase letters, digits and hyphens, e.g. calc1")
    P = Paths(root, slug)
    if P.course_json.is_file() and not args.force:
        raise TutorError(f"course '{slug}' already exists (use `use {slug}` or pick another slug)")
    start = parse_date(args.start, today) if args.start else today
    exam = parse_date(args.exam, today)
    if exam <= start:
        raise TutorError(f"exam date {exam} must be after the start date {start}")
    for sub in ("notes", "mocks", "print", "scratch"):
        (P.tdir / sub).mkdir(parents=True, exist_ok=True)
    P.materials.mkdir(parents=True, exist_ok=True)
    course = {
        "v": 1, "slug": slug, "title": args.title or slug, "created": iso(today), "start": iso(start),
        "exam": {"date": iso(exam), "time": args.exam_time, "minutes": args.exam_minutes,
                 "questions": args.questions, "aids": args.aids, "scope": args.scope, "formats": {}},
        "minutes": args.minutes, "off_days": split_days(args.off), "skip_dates": [], "math": "auto",
        "target": 0.95, "materials": {}, "book": {}, "objectives": [], "learner": [], "actual": None,
    }
    save_course(P, course)
    P.events.touch()
    P.courses.mkdir(parents=True, exist_ok=True)
    P.active_file.write_text(slug + "\n", encoding="utf-8")
    moved = [] if args.no_adopt else adopt_inbox(P)
    for f in moved:
        course["materials"][str(f.relative_to(P.dir))] = "unknown"
    if moved:
        save_course(P, course)
    print(f"created course '{slug}': exam {fmt_day(exam)} ({(exam - today).days} days), "
          f"{args.minutes} min/day · folder {P.dir}")
    for f in moved:
        print(f"adopted {f}")
    print("next: classify materials (`set --material PATH=KIND`), then build objectives and `import` them")
    return 0


def cmd_adopt(args):
    P, course, _ = load_all(args)
    moved = adopt_inbox(P)
    for f in moved:
        course.setdefault("materials", {})[str(f.relative_to(P.dir))] = "unknown"
    save_course(P, course)
    for f in moved:
        print(f"adopted {f}")
    print(f"{len(moved)} file(s) moved into {P.materials}" if moved else "inbox/ is empty: nothing to adopt")
    return 0


def split_days(text):
    if not text:
        return []
    out = []
    for w in re.split(r"[,\s]+", text.strip().lower()):
        if w and w[:3] in WEEKDAYS:
            out.append(w[:3])
        elif w:
            raise TutorError(f"unknown weekday '{w}' (use mon,tue,...)")
    return out


def cmd_use(args):
    root = find_root(args.root)
    courses = sorted(p.parent.parent.name for p in (root / "courses").glob("*/tutor/course.json"))
    if not args.slug:
        active = Paths(root).slug
        print("courses: " + (", ".join(f"{c}{' (active)' if c == active else ''}" for c in courses)
                             if courses else "none"))
        return 0
    if args.slug not in courses:
        raise TutorError(f"no course '{args.slug}'" + (f" (have: {', '.join(courses)})" if courses else ""))
    (root / "courses" / ".active").write_text(args.slug + "\n", encoding="utf-8")
    print(f"active course: {args.slug}")
    return 0


def validate_objectives(objs):
    errors, warnings = [], []
    ids = []
    for i, o in enumerate(objs):
        oid = o.get("id")
        if not isinstance(oid, str) or not ID_RE.match(oid):
            errors.append(f"#{i + 1}: id '{oid}' must be lowercase letters/digits/hyphens (e.g. c2-chain-rule)")
            continue
        if oid in ids:
            errors.append(f"duplicate id '{oid}'")
        ids.append(oid)
        if not o.get("title"):
            errors.append(f"{oid}: missing title")
        w = o.get("weight", 2)
        if w not in (1, 2, 3):
            errors.append(f"{oid}: weight must be 1, 2 or 3")
        for k in ("prereqs", "confusable"):
            if not isinstance(o.get(k, []), list):
                errors.append(f"{oid}: {k} must be a list")
    idset = set(ids)
    graph = {}
    for o in objs:
        oid = o.get("id")
        if oid not in idset:
            continue
        pre = [p for p in o.get("prereqs") or [] if isinstance(p, str)]
        for p in pre:
            if p not in idset:
                errors.append(f"{oid}: unknown prereq '{p}'")
            elif p == oid:
                errors.append(f"{oid}: lists itself as a prereq")
        graph[oid] = [p for p in pre if p in idset and p != oid]
        bad = [c for c in o.get("confusable") or [] if c not in idset]
        if bad:
            warnings.append(f"{oid}: dropped unknown confusable {bad}")
            o["confusable"] = [c for c in o.get("confusable") or [] if c in idset]
    state = {}

    def visit(n, stack):
        state[n] = 1
        for p in graph.get(n, []):
            if state.get(p) == 1:
                errors.append("prereq cycle: " + " -> ".join(stack + [n, p]))
            elif not state.get(p):
                visit(p, stack + [n])
        state[n] = 2

    for n in graph:
        if not state.get(n):
            visit(n, [])
    return errors, warnings


def cmd_import(args):
    P, course, events = load_all(args)
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise TutorError(f"can't read {args.file}: {e}")
    incoming = data.get("objectives") if isinstance(data, dict) else data
    if not isinstance(incoming, list):
        raise TutorError("expected a JSON list of objectives (or {\"objectives\": [...]})")
    existing = {o["id"]: o for o in course.get("objectives") or []}
    added = updated = kept = 0
    if args.replace:
        new_ids = {o.get("id") for o in incoming}
        seen = {e.get("obj") for e in events if e.get("type") == "attempt"}
        merged = [dict(o) for o in incoming]
        for oid, o in existing.items():
            if oid not in new_ids and oid in seen:
                merged.append(dict(o, triaged=True))
                kept += 1
        added = sum(1 for o in incoming if o.get("id") not in existing)
        updated = len(incoming) - added
    else:
        merged = [dict(o) for o in existing.values()]
        index = {o["id"]: o for o in merged}
        for o in incoming:
            if o.get("id") in index:
                index[o["id"]].update(o)
                updated += 1
            else:
                merged.append(dict(o))
                added += 1
    for pos, o in enumerate(merged):
        o.setdefault("order", pos)
        o.setdefault("weight", 2)
    errors, warnings = validate_objectives(merged)
    if errors:
        for e in errors[:20]:
            print("error: " + e)
        print("nothing imported: fix the file and run import again")
        return 1
    course["objectives"] = merged
    save_course(P, course)
    st = replay(course, events)
    extra = f", {kept} kept as triaged (they have history)" if kept else ""
    print(f"ok {len(st.active())} active objectives (+{added} new, ~{updated} updated{extra})")
    for w in warnings:
        print("warning: " + w)
    today = get_now(args).date()
    need = sum(learn_cost(o) for o in to_learn(st)) / 60
    have = st.env.study_days(today, st.env.deadline) * NEW_SHARE * st.env.minutes / 60
    print(f"first-teaching load ~{need:.1f} h vs ~{have:.1f} h available by {fmt_day(st.env.deadline)} → "
          + ("BEHIND: run `plan` and discuss options" if is_behind(st, today) else "on track"))
    return 0


def cmd_set(args):
    P, course, events = load_all(args)
    today = get_now(args).date()
    ex = course.setdefault("exam", {})
    msgs = []
    if args.exam:
        ex["date"] = iso(parse_date(args.exam, today))
        msgs.append(f"exam → {fmt_day(to_date(ex['date']))}")
    for key, val in (("time", args.exam_time), ("minutes", args.exam_minutes), ("questions", args.questions),
                     ("aids", args.aids), ("scope", args.scope)):
        if val is not None:
            ex[key] = val
            msgs.append(f"exam {key} → {val}")
    if args.formats:
        fm = {}
        for part in args.formats.split(","):
            k, _, v = part.partition("=")
            fm[k.strip()] = float(v)
        ex["formats"] = fm
        msgs.append(f"formats → {fm}")
    if args.start:
        course["start"] = iso(parse_date(args.start, today))
    if args.title:
        course["title"] = args.title
    if args.minutes:
        course["minutes"] = args.minutes
        msgs.append(f"{args.minutes} min/day")
    if args.off is not None:
        course["off_days"] = split_days(args.off)
        msgs.append(f"days off → {course['off_days'] or 'none'}")
    for d in args.skip_date or []:
        sd = iso(parse_date(d, today))
        if sd not in course.setdefault("skip_dates", []):
            course["skip_dates"].append(sd)
        msgs.append(f"skipping {sd}")
    for d in args.unskip_date or []:
        sd = iso(parse_date(d, today))
        course["skip_dates"] = [x for x in course.get("skip_dates", []) if x != sd]
    if args.math:
        course["math"] = args.math
        msgs.append(f"math → {args.math}")
    if args.target:
        course["target"] = args.target / 100 if args.target > 1 else args.target
    ids = {o["id"] for o in course.get("objectives") or []}
    for flag, val in (("triage", True), ("untriage", False)):
        raw = getattr(args, flag)
        if raw:
            want = [x.strip() for x in raw.split(",") if x.strip()]
            unknown = [w for w in want if w not in ids]
            if unknown:
                raise TutorError(f"unknown objective(s) {unknown}")
            for o in course["objectives"]:
                if o["id"] in want:
                    o["triaged"] = val
            msgs.append(f"{flag}d {len(want)}")
    if args.actual is not None:
        course["actual"] = args.actual / 100 if args.actual > 1 else args.actual
        msgs.append(f"actual exam score {pct(course['actual'])}")
    for m in args.material or []:
        path, _, kind = m.partition("=")
        course.setdefault("materials", {})[path.strip()] = kind.strip() or "unknown"
    book = course.setdefault("book", {})
    for key, val in (("path", args.book), ("offset", args.book_offset), ("answers", args.book_answers),
                     ("tables", args.book_tables)):
        if val is not None:
            book[key] = val
            msgs.append(f"book {key} → {val}")
    Env(course)  # validates the exam date
    if course.get("start") and to_date(course["start"]) >= to_date(ex["date"]):
        raise TutorError("the exam must be after the start date")
    save_course(P, course)
    st = replay(course, events)
    sp = session_plan(st, today, st.env.minutes)
    print("saved: " + ("; ".join(msgs) if msgs else "no changes"))
    print(f"now: {st.env.days_left(today)} days left · teach-by {fmt_day(st.env.deadline)} · "
          f"today: {sp['quota']} new, {sp['due']} due" + (" · BEHIND" if sp["behind"] else ""))
    return 0


def cmd_next(args):
    P, course, events = load_all(args)
    now = get_now(args)
    st = replay(course, events)
    st.notes_dir = P.notes
    for ev in append_events(P, events, ensure_session(st, now, args.minutes)):
        st.apply(ev)
    a = decide(st, now, focus=args.focus)
    jline(with_math(a, course))
    return 0


def cmd_record(args):
    P, course, events = load_all(args)
    now = get_now(args)
    st = replay(course, events)
    st.notes_dir = P.notes
    if args.obj not in st.objs:
        raise TutorError(f"unknown objective '{args.obj}'" + suggest(args.obj, st.objs))
    for ev in append_events(P, events, ensure_session(st, now)):
        st.apply(ev)
    s = st.open_session()
    o = st.objs[args.obj]
    was = o.status
    ev = {"type": "attempt", "ts": stamp(now), "day": iso(s.day), "sess": s.id, "obj": args.obj,
          "ctx": args.ctx, "res": args.res, "hints": args.hints, "conf": args.conf, "err": args.err,
          "item": args.item, "key": args.key, "note": args.note}
    ev = {k: v for k, v in ev.items() if v is not None}
    stored = append_events(P, events, [ev])[0]
    st.apply(stored)
    o = st.objs[args.obj]
    out = {"recorded": stored["id"], "obj": o.id, "outcome": st.last_tag, "was": was, "now": o.status}
    if o.status == "learning":
        out["streak"] = f"{o.streak}/{LEARN_STREAK}"
    elif o.status in ("reviewing", "mastered"):
        out["spaced"] = f"{len(o.succ)}/{MASTERY_DAYS}"
        out["due"] = iso(o.due)
    if o.flags:
        out["flags"] = sorted(o.flags)
    jline(out)
    a = decide(st, now)
    jline(with_math(a, course))
    return 0


def cmd_void(args):
    P, course, events = load_all(args)
    voided = {e.get("ref") for e in events if e.get("type") == "void"}
    if args.id:
        target = next((e for e in events if e.get("id") == args.id), None)
        if target is None or target.get("type") == "void":
            raise TutorError(f"no voidable event {args.id}")
    else:
        target = next((e for e in reversed(events) if e.get("type") in ("attempt", "mock")
                       and e.get("id") not in voided), None)
        if target is None:
            raise TutorError("nothing to void")
    if target["id"] in voided:
        raise TutorError(f"event {target['id']} is already void")
    append_events(P, events, [{"type": "void", "ref": target["id"], "reason": args.reason,
                               "ts": stamp(get_now(args))}])
    st = replay(course, events)
    what = target.get("obj") or target.get("label") or target["type"]
    now_state = st.objs[target["obj"]].status if target.get("obj") in st.objs else ""
    print(f"voided event {target['id']} ({what}, {target.get('res', target.get('act', ''))})"
          + (f": {what} is now {now_state}" if now_state else ""))
    return 0


def cmd_note(args):
    P, course, _ = load_all(args)
    notes = course.setdefault("learner", [])
    text = " ".join(args.text).strip()
    if args.remove:
        course["learner"] = [n for n in notes if n != text]
    elif text and text not in notes:
        notes.append(text)
    save_course(P, course)
    print("learner notes: " + ("; ".join(course["learner"]) or "none"))
    return 0


def cmd_mock(args):
    P, course, events = load_all(args)
    now = get_now(args)
    st = replay(course, events)
    for ev in append_events(P, events, ensure_session(st, now)):
        st.apply(ev)
    s = st.open_session()
    if args.action == "start":
        if st.open_mock():
            raise TutorError(f"{st.open_mock()['label']} is still open: record its result first")
        n, mm = mock_size(st.env, s.minutes)
        label = args.label or f"mock-{len(st.mocks) + 1}"
        append_events(P, events, [{"type": "mock", "act": "start", "day": iso(s.day), "label": label,
                                   "n": args.n or n, "minutes": args.minutes or mm, "ts": stamp(now)}])
        print(f"{label} started {now.strftime('%H:%M')}: {args.n or n} questions, {args.minutes or mm} min. "
              "Grade every part with `record --ctx mock`, then `mock result`.")
        return 0
    m = st.open_mock()
    if m is None:
        raise TutorError("no mock is open (start one with `mock start`)")
    if args.score is None:
        raise TutorError("give --score (0-1 or percent)")
    score = args.score / 100 if args.score > 1 else args.score
    pred = None if args.predicted is None else (args.predicted / 100 if args.predicted > 1 else args.predicted)
    append_events(P, events, [{"type": "mock", "act": "result", "label": m["label"], "score": score,
                               "predicted": pred, "ts": stamp(now)}])
    st = replay(course, events)
    rd = readiness(st)
    cal = "" if pred is None else f" · you predicted {pct(pred)} ({'+' if pred >= score else ''}{rh(100 * (pred - score))} pts)"
    print(f"{m['label']}: {pct(score)}{cal} · readiness now {pct(rd['R'])}")
    return 0


def cmd_end(args):
    P, course, events = load_all(args)
    now = get_now(args)
    st = replay(course, events)
    s = st.open_session()
    if s is not None:
        append_events(P, events, [{"type": "session", "act": "end", "sess": s.id, "ts": stamp(now)}])
        st = replay(course, events)
        s = st.session(s.id)
    env = st.env
    today = s.day if s is not None else now.date()
    if s is not None and s.n:
        print(f"session {fmt_day(s.day)}: {s.n} items · {pct(s.correct / s.n)} unaided-correct · "
              f"{rh(mins(s.start, s.end))} min")
        if s.learned:
            print("learned: " + ", ".join(st.objs[i].title for i in s.learned if i in st.objs))
        if s.lapsed:
            print("slipped (back tomorrow): " + ", ".join(st.objs[i].title for i in s.lapsed if i in st.objs))
    rd = readiness(st)
    print(f"{counts(st)} · readiness {pct(rd['R'])}")
    nxt = env.next_study_day(today)
    if nxt is not None and env.days_left(today) > 0:
        due_n = sum(1 for o in st.active() if o.due is not None and o.due <= nxt)
        tl = len(to_learn(st))
        print(f"next session: {fmt_day(nxt)} ({env.days_left(nxt)} days before the exam) · ~{due_n} reviews"
              + (f" · {tl} objectives still to learn" if tl else ""))
    write_progress(P, course, st, now)
    if nxt is not None and env.days_left(today) > 1:
        write_plan(P, course, events, nxt)
        print(f"updated {P.tdir / 'progress.md'} and plan.md")
    else:
        print(f"updated {P.tdir / 'progress.md'}")
    return 0


def cmd_status(args):
    P, course, events = load_all(args)
    now = get_now(args)
    today = now.date()
    st = replay(course, events)
    env = st.env
    rd = readiness(st)
    print(f"{course.get('title', P.slug)} · exam {fmt_day(env.exam)} ({env.days_left(today)} days) · "
          f"readiness {pct(rd['R'])} · target {pct(env.target)} on mocks")
    print(f"objectives {len(st.active())}: {counts(st)}")
    print("ready: " + ("YES" if rd["ready"] else "not yet (" + "; ".join(rd["unmet_ready"]) + ")"))
    print("ace-ready: " + ("YES" if rd["ace"] else "not yet (" + "; ".join(rd["unmet_ace"][:3]) + ")"))
    weak = sorted(st.active(), key=lambda o: (-(o.weight * (1 - o.p())), o.order))[:5]
    print("weakest: " + ", ".join(f"{o.id} [{status_word(o)}]" for o in weak))
    fl = [f"{o.id}({','.join(sorted(o.flags))})" for o in st.active() if o.flags]
    if fl:
        print("flags: " + " ".join(fl))
    done = [m for m in st.mocks if m["score"] is not None]
    if done:
        print("mocks: " + " · ".join(f"{m['label']} {fmt_day(m['day'])} {pct(m['score'])}" +
                                      ("" if m["predicted"] is None else f" (pred {pct(m['predicted'])})")
                                      for m in done))
    if env.days_left(today) > 0:
        sp = session_plan(st, today, env.minutes)
        print(f"pace: {'BEHIND' if sp['behind'] else 'on track'} · teach-by {fmt_day(env.deadline)} · "
              f"today: {sp['due']} due, {sp['quota']} new" + (f", mock #{sp['mock']}" if sp["mock"] else ""))
    return 0


def cmd_plan(args):
    P, course, events = load_all(args)
    now = get_now(args)
    st = replay(course, events)
    s = st.open_session()
    today = now.date()
    env = st.env
    if env.days_left(today) < 1:
        print("the exam is today or over: nothing left to plan")
        return 0
    done_today = any(x.day == today and x.end for x in st.sessions)
    start = (env.next_study_day(today) or today) if (done_today and s is None) else today
    pr = write_plan(P, course, events, start)
    print(f"projection from {fmt_day(start)} ({env.minutes} min/day, ~80% accuracy):")
    if pr["taught"]:
        print(f"- all objectives first-taught by about {fmt_day(pr['taught'])} ({span(pr['taught_range'])}; "
              f"teach-by {fmt_day(env.deadline)})" + (" ✓" if pr["taught"] <= env.deadline else " (late)"))
    else:
        print(f"- NOT everything gets first-taught before the exam at {env.minutes} min/day")
    for d, _ in pr["mocks"]:
        print(f"- mock exam around {fmt_day(d)}")
    print(f"- at exam day: {pr['mastered']}/{len(st.active())} mastered, readiness ~{pct(pr['readiness']['R'])}")
    if is_behind(st, start) or not pr["taught"] or pr["taught"] > env.deadline:
        need = minutes_needed(course, events, start)
        print(f"- BEHIND: to finish on time you'd need ~{need} min/day" if need else
              "- BEHIND even at 3 h/day: triage the lowest-weight objectives")
    print(f"wrote {P.tdir / 'plan.md'}")
    return 0


def cmd_obj(args):
    P, course, events = load_all(args)
    st = replay(course, events)
    o = st.objs.get(args.id)
    if o is None:
        raise TutorError(f"unknown objective '{args.id}'" + suggest(args.id, st.objs))
    print(f"{o.id}: {o.title} · §{o.spec.get('sec', '?')} p.{o.spec.get('pages', '?')} · weight {o.weight}"
          f"{' · TRIAGED' if o.triaged else ''}")
    print(f"status {status_word(o)} · start {o.start} · tries {o.tries} · lapses {o.lapses} · "
          f"learned {iso(o.learned)} · spaced successes {[iso(x) for x in o.succ]} · mixed_ok {o.mixed_ok}")
    print(f"due {iso(o.due)} · flags {sorted(o.flags) or '—'} · prereqs {o.prereqs or '—'} · "
          f"confusable {o.confusable or '—'}")
    hist = [e for e in events if e.get("type") == "attempt" and e.get("obj") == o.id]
    for e in hist[-12:]:
        print(f"  {e['day']} {e.get('ctx')}: {e.get('res')}" + (f" h{e['hints']}" if e.get("hints") else "")
              + (f" c{e['conf']}" if e.get("conf") else "") + (f" [{e['err']}]" if e.get("err") else "")
              + (f" {e['item']}" if e.get("item") else "") + (f": {e['note']}" if e.get("note") else ""))
    return 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="project folder that holds courses/ and inbox/")
    common.add_argument("--course", help="course slug (default: the active course)")
    common.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
    ap = argparse.ArgumentParser(prog="tutor_state.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True

    def add(name, func, help_):
        p = sub.add_parser(name, parents=[common], help=help_)
        p.set_defaults(func=func)
        return p

    add("brief", cmd_brief, "≤10-line snapshot for the start of a session (never fails)")
    add("doctor", cmd_doctor, "check python, pypdf, folders, math mode")
    p = add("init", cmd_init, "create a course and adopt files from inbox/")
    p.add_argument("--slug", required=True)
    p.add_argument("--title")
    p.add_argument("--exam", required=True, help="exam date YYYY-MM-DD")
    p.add_argument("--exam-time")
    p.add_argument("--exam-minutes", type=int, default=50)
    p.add_argument("--questions", type=int)
    p.add_argument("--aids", help="e.g. 'no calculator, one formula sheet'")
    p.add_argument("--scope", help="e.g. 'Ch 1-3'")
    p.add_argument("--minutes", type=int, default=60, help="study minutes per day")
    p.add_argument("--off", help="weekly days off, e.g. sat,sun")
    p.add_argument("--start", help="first study day (default today)")
    p.add_argument("--no-adopt", action="store_true", help="leave inbox/ files where they are")
    p.add_argument("--force", action="store_true")
    add("adopt", cmd_adopt, "move new files from inbox/ into the active course's materials/")
    p = add("use", cmd_use, "list courses or switch the active one")
    p.add_argument("slug", nargs="?")
    p = add("import", cmd_import, "add/update objectives from a JSON file (validated)")
    p.add_argument("file")
    p.add_argument("--replace", action="store_true", help="the file is the complete list")
    p = add("set", cmd_set, "change exam/course settings")
    p.add_argument("--exam")
    p.add_argument("--exam-time")
    p.add_argument("--exam-minutes", type=int)
    p.add_argument("--questions", type=int)
    p.add_argument("--aids")
    p.add_argument("--scope")
    p.add_argument("--formats", help="exam format mix, e.g. free=0.6,short=0.3,mc=0.1")
    p.add_argument("--start")
    p.add_argument("--title")
    p.add_argument("--minutes", type=int)
    p.add_argument("--off")
    p.add_argument("--skip-date", action="append")
    p.add_argument("--unskip-date", action="append")
    p.add_argument("--math", choices=("auto", "latex", "unicode"))
    p.add_argument("--target", type=float, help="ace target for mocks, e.g. 95")
    p.add_argument("--triage", help="comma-separated objective ids to drop")
    p.add_argument("--untriage")
    p.add_argument("--actual", type=float, help="real exam score (0-1 or percent)")
    p.add_argument("--material", action="append", help="PATH=KIND (textbook|exam|homework|slides|syllabus|notes)")
    p.add_argument("--book", help="path of the textbook PDF")
    p.add_argument("--book-offset", type=int, help="pdf page = printed page + offset")
    p.add_argument("--book-answers", help="where the answer key is, e.g. 'pdf 1180-1219 (A-1..A-40)'")
    p.add_argument("--book-tables", help="where data tables are")
    p = add("next", cmd_next, "what to do now (opens today's session if needed) -> JSON")
    p.add_argument("--minutes", type=int, help="minutes the student has from now")
    p.add_argument("--focus", help="objective the student asked for")
    p = add("record", cmd_record, "log one graded attempt -> outcome JSON + next JSON")
    p.add_argument("--obj", required=True)
    p.add_argument("--ctx", required=True, choices=CTXS)
    p.add_argument("--res", required=True, choices=RESULTS)
    p.add_argument("--hints", type=int, default=0, help="hints used (a revealed step counts as wrong)")
    p.add_argument("--conf", type=int, choices=(1, 2, 3), help="1 guess · 2 fairly sure · 3 certain")
    p.add_argument("--err", choices=ERRS)
    p.add_argument("--item", help="short id/description of the item, to avoid repeats")
    p.add_argument("--key", help="verified correct answer")
    p.add_argument("--note", help="what went wrong, in a few words")
    p = add("void", cmd_void, "cancel the last attempt/mock event (or --id N), e.g. after a wrong key")
    p.add_argument("--id", type=int)
    p.add_argument("--reason", default="")
    p = add("note", cmd_note, "remember a learner habit, e.g. 'drops units'")
    p.add_argument("text", nargs="+")
    p.add_argument("--remove", action="store_true")
    p = add("mock", cmd_mock, "mock start | mock result")
    p.add_argument("action", choices=("start", "result"))
    p.add_argument("--n", type=int)
    p.add_argument("--minutes", type=int)
    p.add_argument("--label")
    p.add_argument("--score", type=float)
    p.add_argument("--predicted", type=float)
    add("end", cmd_end, "close the session; update progress.md and plan.md")
    add("status", cmd_status, "readiness report")
    add("plan", cmd_plan, "simulate the rest of the prep; write plan.md")
    p = add("obj", cmd_obj, "one objective's state and history")
    p.add_argument("id")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except TutorError as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
