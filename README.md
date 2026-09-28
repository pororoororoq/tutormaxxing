# tutormaxxing

An exam-prep tutor for [Claude Code](https://claude.com/claude-code). Give it your course materials
(practice exams, homework, slides, a textbook PDF) and an exam date. It works out what you already
know, plans your prep up to the exam, and teaches, quizzes, spaces your reviews, mixes up practice
and runs printable mock exams until you're ready. You just answer, for as long as you want each day.

It's built as a Claude Code **skill** (`.claude/skills/tutor/`) plus a small state engine that
remembers your progress between sessions. Install it once and it works in every Claude Code
session, in any folder. The method comes from learning-science research; see
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

## Your pace, no timer

There's no clock. Go through new topics for as long as you like: after each new topic you get a
few mixed questions on older ones, then the next topic. Stop whenever you want ("I have to go");
reviews come back on their own days. A long break in the middle doesn't count against you.
Prefer a set number of new topics per day? Say "one day at a time", and "let's keep going"
switches back.

## Install once, use it in every Claude Code session

On your computer (Mac, Windows or Linux, with Python 3.9+):

```bash
git clone https://github.com/pororoororoq/tutormaxxing.git ~/tutormaxxing
python3 ~/tutormaxxing/install.py
```

Prefer not to type commands? Open the Code tab of the Claude desktop app on any folder and say:
*"Clone https://github.com/pororoororoq/tutormaxxing into my home folder and run `python3 install.py` in it."*

What the installer does:
- **Links the skill** into `~/.claude/skills/tutor`, the folder Claude Code reads in *every* session.
  It's a link back to this repo, so `git -C ~/tutormaxxing pull` updates the tutor everywhere.
- **Adds permission rules** to your user settings (`~/.claude/settings.json`, backed up first), so
  study sessions don't stop for approval prompts:
  - `Skill(tutor)`: Claude may load the tutor
  - `Edit(courses/**)`: it may write its files in your study folder
  - `Bash(python3 "…/skills/tutor/scripts/*)`: it may run its own scripts
- **Options**:
  - `--allow-python`: also approve the short `python3 -c` answer checks (any python3 command, in
    all projects). Without it, those checks ask first unless you use Auto mode.
  - `--copy`: copy the skill instead of linking it.
  - `--uninstall`: remove the skill and only the rules the installer added.

If you don't have Python yet, run `python3 --version` in Terminal on a Mac and it offers to
install it. On Windows, install it from python.org. The tutor offers to install `pypdf` (for PDFs)
the first time it needs it.

**Other ways to get it:**
- **Only in this repo**: open Claude Code in the `tutormaxxing` folder. It uses the project copy and
  `.claude/settings.json`, which applies after you accept the "trust this folder" prompt.
- **Through your Claude account**: package it as `tutor.skill` (ask Claude, or run the skill-creator's
  `package_skill.py`) and click **Save skill**, or upload it under Settings → Capabilities → Skills.
  It then also reaches Claude Code on the web and Cowork, but you must re-save it after every change.
  Use one install method, not both, or you'll see two tutors.

It does *not* work in a plain Chat conversation: chats don't keep files between conversations,
and the tutor's memory is its files.

## Daily use

Make one folder per course, for example `~/Study/Calc1`, and put your files in an `inbox/` folder
inside it. Practice exams matter most; the textbook is optional.

```
Calc1/
  inbox/      <- practice exams, homework, slides, syllabus, textbook PDF
  courses/    <- created by the tutor: your plan, progress, notes, mock exams
```

Open that folder in a **new** Claude Code session (desktop app Code tab, or `claude` in a terminal)
and type:

```
/tutor
```

- **The first time**, it asks one round of questions (exam date, chapters, roughly how long you
  study on a typical day, which only feeds the forecast), maps your materials, and starts with a few
  diagnostic questions.
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

Plain language works too: "I have to go", "exam moved to 10/20", "I don't get related rates",
"skip chapter 5", "the math looks broken".

Your dashboard is `courses/<course>/tutor/progress.md`. `plan.md` in the same folder lists the
topics in the order you'll learn them and the key dates (day by day, on the daily pace).

## Math display

- **Claude desktop app**: formulas render as real math (LaTeX).
- **Terminal**: formulas use plain-text math (x², √x, ∫₀¹).
- **Anywhere**: graphs, diagrams and mock exams open as a printable page in your browser, with full
  math rendering. It works offline.

If formulas ever look like raw code, say "plain math".

## Your data stays local

Everything about you lives in the `courses/` folder of your study folder: your materials, progress
log, notes and mock exams. Nothing is uploaded anywhere. If you study inside this repo, `courses/`
and `inbox/` are in `.gitignore`, so they're never committed: textbooks are copyrighted, and your
progress is yours.

## Permissions in this repo

`.claude/settings.json` in this repo is broader than the installer's rules: it lets Claude run any
`python3` command in this project without confirmation, which covers the answer checks too. If you'd
rather approve each one, delete the `Bash(python3 *)` and `Bash(python *)` lines. Expect a prompt on
most answers if you do.

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
install.py                  installs the skill for every Claude Code session on your computer
docs/research.md            the evidence and where every number comes from
tests/                      unit tests, simulations, PDF/render/installer tests, end-to-end harness
```
