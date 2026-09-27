# tutormaxxing

An exam-prep tutor for [Claude Code](https://claude.com/claude-code). Give it your course materials
(practice exams, homework, slides, a textbook PDF) and an exam date. It works out what you already
know, builds a day-by-day plan, and teaches, quizzes, spaces your reviews, mixes up practice and runs
printable mock exams until you're ready. You just answer.

It's built as a Claude Code **skill** (`.claude/skills/tutor/`) plus a small state engine that
remembers your progress between sessions. The method comes from learning-science research; see
[docs/research.md](docs/research.md).

## How it teaches

1. **Diagnose**: a quick question on each topic before teaching it. Things you already know get skipped.
2. **Teach to mastery**: worked example → partly worked example → problems on your own, with
   step-by-step feedback and hints instead of answers, until you get 3 right in a row without help.
3. **Spaced reviews**: each topic comes back after a gap scaled to the time left before the exam.
   It only counts as mastered once you've recalled it on 3 separate later days.
4. **Mixed practice**: exam-style questions from different topics, without saying which topic it is,
   because recognizing the method is half of an exam.
5. **Mock exams**: printable and timed, taken on paper about a week and again 3–4 days before the exam,
   graded from a photo of your work.
6. **Final days**: no new material in the last 2 days, a formula sheet, sleep. On exam day, a
   5-question warm-up.

It never hands you the answer before you try. Research shows that AI tutors that give answers
raise homework scores but *lower* exam scores.

## Where the tutor shows up

The tutor is a Claude Code skill, so it appears in two places:

- **Claude Code sessions opened on this folder** (the Code tab of the desktop app, the terminal,
  or Claude Code on the web). Type `/` and it's listed as `tutor`. A session that was already open
  when the skill folder was created won't list it: start a new session.
- **Your account, from any folder**: install `tutor.skill` (built with
  `python3 scripts/package_skill.py` from the skill-creator skill, or ask Claude to package it) via
  the **Save skill** button, or upload it under Settings → Capabilities → Skills. It then syncs to
  every Claude Code session and to Cowork. Re-install after changing the skill here; this repo is
  the source of truth.

It does *not* work in a plain Chat conversation: chats don't keep files between conversations,
and the tutor's memory is its files. Use Claude Code, or Cowork with a folder selected.

## Setup (once)

You need Claude Code (terminal, or the Code tab of the Claude desktop app) and Python 3.9+.

```bash
git clone https://github.com/pororoororoq/tutormaxxing.git
cd tutormaxxing
python3 -m pip install --user pypdf   # for reading PDFs; the tutor offers to do this for you
```

Then put your course files in `inbox/`. Practice exams matter most; the textbook is optional.

```
tutormaxxing/
  inbox/                <- drop PDFs here: practice exams, homework, slides, syllabus, textbook
```

## Daily use

Open Claude Code in the `tutormaxxing` folder and type:

```
/tutor
```

- **The first time**, it asks one round of questions (exam date, chapters, minutes per day), maps your
  materials, and starts with a few diagnostic questions.
- **Every day after that**, `/tutor` gives a 2–3 line agenda and the first question. Answer with your
  final answer and key steps. Add `; 1`, `; 2` or `; 3` for how sure you are (guess / fairly sure /
  certain). You can also send a photo of your handwritten work.

Other commands:

| Command | What it does |
|---|---|
| `/tutor status` | Readiness report: what's mastered, what's weak, whether you're on track |
| `/tutor mock` | A timed, printable mock exam right now |
| `/tutor new` | Set up another course |
| `/tutor debrief` | After the real exam: record your score, note what surprised you |

Plain language works too: "only 20 min today", "exam moved to 10/20", "I don't get related rates",
"skip chapter 5", "the math looks broken".

Your dashboard is `courses/<course>/tutor/progress.md`, and the plan is in `plan.md` in the same folder.

## Math display

- **Claude desktop app**: formulas render as real math (LaTeX).
- **Terminal**: formulas use plain-text math (x², √x, ∫₀¹).
- **Anywhere**: graphs, diagrams and mock exams open as a printable page in your browser, with full
  math rendering. It works offline.

If formulas ever look like raw code, say "plain math".

## Your data stays local

Everything about you lives in `courses/` (your materials, progress log, notes, mocks). It's in
`.gitignore`, so it's never committed: textbooks are copyrighted, and your progress is yours.

## Permissions

`.claude/settings.json` lets the tutor load its skill, run Python and edit files under `courses/`
without asking, so quiz sessions aren't interrupted by permission prompts. Claude Code applies these
rules only after you **trust the folder**: the first time you open `tutormaxxing` in Claude Code,
accept the "trust this folder" prompt.

The trade-off: Claude can run any `python3` command in this project without confirmation. If you'd
rather approve each one, delete the `Bash(python3 *)` and `Bash(python *)` lines. Expect a prompt on
most answers if you do.

## Using it from another folder

To use the skill outside this repo, link it into your personal skills and copy the permissions:

```bash
ln -s "$(pwd)/.claude/skills/tutor" ~/.claude/skills/tutor
```

Then add the same `permissions.allow` entries to that project's `.claude/settings.json`. The tutor
keeps its data in `courses/` inside whichever folder you run it from.

## Improving it

It gets better from real use:
- After each exam, `/tutor debrief` writes `courses/<course>/tutor/lessons.md`: what the exam asked
  that the tutor didn't cover.
- Teaching behavior lives in `.claude/skills/tutor/SKILL.md` and `references/`.
- Scheduling rules and their parameters live in `.claude/skills/tutor/scripts/tutor_state.py`, with
  sources in [docs/research.md](docs/research.md).

Run the tests after changing anything:

```bash
python3 -m unittest discover tests        # engine + 21-day simulated students
```

`tests/test_simulation.py` runs strong, typical, weak and overloaded synthetic students through a
full prep. Use it to check that a scheduling change actually helps.

To test the tutor's actual *behavior* after changing SKILL.md or the references, run the
end-to-end check. The real skill tutors a simulated student (a second Claude with hidden
instructions to make mistakes, beg for answers and push back on grades) on a synthetic textbook
and practice exam, then an LLM judge audits the transcript:

```bash
python3 tests/e2e/sim_student.py --days 2     # ~20–40 min, a few dollars of API usage
```

The report and full transcript land in `tests/e2e/runs/<timestamp>/`. It checks that no answer is
revealed before an attempt, that every graded answer is recorded and graded correctly, that the
tutor holds its ground under pushback, math formatting, session wrap-up, permission prompts, and
how many PDF pages were read.

## Layout

```
.claude/skills/tutor/
  SKILL.md                  the tutor's instructions (rules, session loop, routing)
  references/               onboarding, teaching, assessment, per-subject guides
  scripts/tutor_state.py    state + scheduling engine (event log, spacing, mastery, mocks)
  scripts/pdf_tools.py      maps PDFs cheaply: outline, page labels, search, text, page chunks
  scripts/render.py         Markdown + LaTeX + plots → printable HTML (vendored KaTeX)
  assets/                   print template and vendored libraries
docs/research.md            the evidence and where every number comes from
tests/                      unit tests, simulations, PDF/render tests, end-to-end harness
```
