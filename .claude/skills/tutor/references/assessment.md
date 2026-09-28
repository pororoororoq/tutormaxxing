# Assessment: mixed practice, mock exams, readiness

`T` = `python3 "${CLAUDE_SKILL_DIR}/scripts/tutor_state.py"`, `R` = `python3 "${CLAUDE_SKILL_DIR}/scripts/render.py"`.

## Contents
1. Mixed sets
2. Printables
3. Mock exams
4. Readiness
5. The final two days
6. Exam day
7. After the exam

## 1. Mixed sets (mode `mixed`)

- Exam-format items drawn across objectives, in the format given by `fmt` (free-response, short
  answer, multiple choice, …). Never name the topic; the student has to recognize the method.
  That recognition is a big part of what exams test (interleaving: math g ≈ 0.34; college physics
  homework gains of 50–125%).
- Ask for confidence on every item and record with `--ctx mixed`.
- `hard: true`: use a harder, multi-step or transfer variant. `extra: true`: today's essentials are
  done and this item is optional (SKILL.md, session loop).

## 2. Printables

`R FILE.md [--exam] [--title "…"]` turns Markdown into a standalone page with full LaTeX that works
offline, and opens it in the browser. Keep the source files in `courses/SLUG/tutor/print/` or `mocks/`.
- Math: `$…$` inline and `$$…$$` for display; any LaTeX works here, including matrices.
- Graphs: a fenced `plot` block, written with explicit `*` and functions such as sin cos tan exp ln
  log sqrt abs:

  ````
  ```plot
  title: f(x) = x^2 - 1 and its tangent at x = 1
  x: -3..3
  f(x) = x^2 - 1
  g(x) = 2*x - 2
  points: (1, 0)
  ```
  ````
- Diagrams (free-body diagrams, circuits, number lines): an inline `<svg>` in the Markdown.
- Use printables for: mock exams (`--exam` adds name and time fields and space to write), the formula
  sheet before the exam, questions that need a graph or diagram, and long derivations when math
  mode is `unicode`.

## 3. Mock exams (mode `mock`)

Mocks are scheduled automatically, about a week and 3–4 days before the exam, or run on request.
1. **Build** from the blueprint: `n` questions in `minutes` minutes (both from `next`: the real
   exam's length), in the exam's formats and point values. If they can't sit that long now, offer
   a shorter mock with proportionally less time (`--n`, `--minutes`) or doing it later today. Pick
   objectives by weight (heavier ones appear more), include at least one confusable pair, and use
   only items the student hasn't seen. Write the questions to `mocks/mock-N.md` and a separate
   key with a partial-credit rubric to `mocks/mock-N-key.md`. Verify every answer in the key.
   Never show the key before grading.
2. **Render**: `R courses/SLUG/tutor/mocks/mock-N.md --exam --title "Mock N"`. Ask them to work on
   paper, with only the aids the real exam allows.
3. **Predict**: ask "What score do you expect, in percent?" before they start.
4. **Start**: `T mock start --n N --minutes M`. State the time limit. Give no help during the mock.
5. **Collect**: photos of their work or typed answers, when time is up or when they finish.
6. **Grade** every question and part against the key, with partial credit for setup, execution,
   final answer and units. Record each part: `T record --obj ID --ctx mock --res … --conf … --err … --note "…"`.
7. **Result**: `T mock result --score S --predicted P`.
8. **Debrief** (≤10 lines):
   - the score, and their prediction vs the actual score
   - errors by type (concept / procedure / careless / misread / time)
   - the top 3 fixes, and what happens next (missed objectives are already re-queued)
   - for careless or misread errors, a checking routine: re-read the question, units, signs, plug
     the answer back in.

## 4. Readiness

Quote `T status`; never estimate readiness yourself.
- **Ready**: readiness ≥ 85%, last mock ≥ 80%, every high-weight objective solid.
- **Ace-ready** (the goal):
  - every objective mastered
  - the last two mocks both at or above the target (95%)
  - predicted scores within 10 points of actual
  - no open confident errors

Name the unmet criteria plainly, and never promise a grade.

## 5. The final two days

- **2 days before**: no new material (the scheduler enforces this). Fragile items and one mixed set.
- **1 day before**: fragile items first, then a quick sweep; `next` says `done` after it, so stop
  there. Make a one-page formula and methods sheet as a printable, built from what they struggled
  with. Making it is good retrieval practice even if notes aren't allowed in the exam.
- Recommend sleep over late cramming: sleep in the weeks before an exam predicts grades, and
  all-nighters backfire.

## 6. Exam day (mode `warmup`)

At most 5 easy items for confidence, with no teaching. Then logistics (calculator, ID, arrive early)
and a reminder of their personal traps from `progress.md` (units, re-reading the question). Close
with a short, encouraging send-off.

## 7. After the exam (mode `debrief`)

Ask how it went, and the score when they know it: `T set --actual SCORE`. Ask what surprised them:
topics, question styles or time pressure the tutor didn't prepare them for. Append those lessons to
`courses/SLUG/tutor/lessons.md`. They are the best source for improving this tutor before the next
exam.
