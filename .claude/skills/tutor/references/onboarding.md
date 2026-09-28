# Onboarding: from a pile of files to a running plan

Goal: the student answers **one** round of questions; you do everything else and start teaching in
the same sitting. Map the materials, don't read them: the whole setup should cost a few pages of
reading, not a textbook's worth. Claude already knows the subject. The materials only tell you
*this course's* scope, conventions and exam style.

`T` = `python3 "${CLAUDE_SKILL_DIR}/scripts/tutor_state.py"`, `P` = `python3 "${CLAUDE_SKILL_DIR}/scripts/pdf_tools.py"`.

## Contents
1. Intake
2. Setup check
3. Read the high-signal files
4. Map the textbook
5. Build the objectives
6. Conventions
7. Capacity check and kickoff
8. Missing materials
9. Adding materials later

## 1. Intake

- `T brief` lists the files in `inbox/`. Classify each with `P info FILE` (it guesses the kind):
  textbook, exam (practice or past), homework, slides, syllabus, notes.
- Extract before asking: a syllabus or practice exam often states the exam date, length, allowed
  aids and chapters. Anything the student typed with `/tutor` counts too.
- Ask **one** message covering only what is still missing. Use AskUserQuestion if available,
  otherwise a short numbered list:
  - course name and exam date (and time)
  - what the exam covers (chapters or topics)
  - roughly how long they study on a typical day (default 60 minutes; it only feeds the plan's
    forecast, since sessions have no timer) and weekly days off
  - calculator / formula sheet / notes allowed? (skip if a practice exam says)
- No files at all? Say they can drop practice exams, homework, slides or the textbook into
  `inbox/` anytime, and offer to start from the topic list alone (section 8).
- Create the course. It moves inbox files into `courses/SLUG/materials/` and creates every folder
  the tutor uses (`tutor/notes`, `mocks`, `print`, `scratch`):
  `T init --slug SLUG --title "…" --exam YYYY-MM-DD [--exam-time HH:MM] [--exam-minutes N] [--questions N] [--aids "…"] [--scope "…"] --minutes N [--off sat,sun]`
  Then for each file: `T set --material "materials/FILE=KIND"`. The pace is continuous (new topics
  for as long as they keep going); add `--pace daily` only if they asked for a set number per day.
- Write course files (blueprint, conventions, objectives, notes) with the Write tool, straight into
  `courses/SLUG/tutor/`. It creates missing folders itself, so never run `mkdir`.

## 2. Setup check

- `T doctor`. If pypdf is missing, ask once ("I need a small PDF library, pypdf. OK to install
  it?"), then `P setup`. It installs for the user, or into `courses/.venv` if the system Python
  refuses; `pdf_tools.py` finds that venv by itself.
- If it can't be installed: Read opens PDFs of ≤10 pages directly. For a big textbook, ask the
  student to export the table of contents and the chapter pages as a separate small PDF.

## 3. Read the high-signal files (fully)

Priority: practice/past exams > homework/problem sets > slides/syllabus. They define what the
professor actually tests, which matters more than anything in the textbook.
- PDFs ≤10 pages: Read them directly (you see equations and figures). Larger: `P text FILE --pages 1-10`,
  or `P split FILE --pages A-B --out courses/SLUG/tutor/scratch` and Read the chunks.
- Every problem type you see becomes (part of) an objective with weight 3.
- Write `courses/SLUG/tutor/blueprint.md`:

```
# Exam blueprint: <course>, <exam>
Sources: <files> · confidence: high (real practice exam) | medium (homework/syllabus) | low (topics only)
Format: <N> questions, <M> minutes · aids: <…>
Mix: free-response 60% · short answer 30% · multiple choice 10%
Points by topic: <…>
Recurring problem patterns:
- <pattern> → <objective ids>
Difficulty: <typical steps per problem; "show work" expectations; partial credit>
Mock recipe: <question count by kind; time>
```
  Then record the format numbers: `T set --formats free=0.6,short=0.3,mc=0.1 --questions N --exam-minutes M`.

## 4. Map the textbook (never bulk-read it)

- `P outline BOOK --match "Chapter 2|Chapter 3"` gives the in-scope sections with printed and PDF
  pages. Without bookmarks it parses the table-of-contents text. If that fails (a scanned book),
  `P split BOOK --pages 1-14 --out courses/SLUG/tutor/scratch` and Read the contents pages as images.
- Page offset: `P labels BOOK`, or `P find BOOK "2.4 The Chain Rule"` and compare with the printed
  number. Save it: `T set --book materials/BOOK.pdf --book-offset N`.
- Answer key: `P find BOOK "Answers to Odd"` → `T set --book-answers "pdf 1180-1219 (A-1..A-40)"`.
  For chemistry and statistics, also locate the data tables → `T set --book-tables "…"`.
- If section titles are too vague to name objectives, read the section's first page or its
  learning objectives (`P text BOOK --pages N`). Nothing more.

## 5. Build the objectives

An **objective** is one problem type that could appear on the exam, solved with one main idea or
procedure and testable in 1–5 minutes. Example: "Differentiate compositions with the chain rule".
- Sources: in-scope section titles × practice-exam problem types × your own knowledge of what those
  sections contain.
- Size: 4–8 per chapter, 15–30 per exam. Split when the first steps differ or two types are easy to
  confuse; link those with `confusable`. Merge sub-minute skills into their parent.
- Weights: 3 = on a practice exam or a headline topic of the syllabus; 2 = drilled in homework or
  boxed in the book; 1 = minor.
- `prereqs`: direct prerequisites inside the scope only. `order`: the book's teaching order.
  `kind`: procedure (most STEM problems) | concept (explain/why) | fact (definitions, constants).
- ids: lowercase letters, digits and hyphens, with a chapter prefix (`c2-chain-rule`).

Write `courses/SLUG/tutor/objectives.json`, then `T import courses/SLUG/tutor/objectives.json`. It
validates ids, prerequisites and cycles; fix what it reports and run it again.

```json
[{"id": "c2-chain-rule", "title": "Differentiate compositions with the chain rule", "sec": "2.4",
  "pages": "27-30", "weight": 3, "prereqs": ["c2-basic-rules"], "confusable": ["c2-product-rule"],
  "kind": "procedure", "order": 7}]
```

## 6. Conventions

Open references/subjects.md at the student's subject and walk its convention checklist. Answer
each item from the practice exam first, then with a targeted `P find BOOK "…"`. Write
`courses/SLUG/tutor/conventions.md` (≤20 lines): notation, units and significant figures, sign
conventions, constants and table values, language/version, calculator policy. Anything you can't
find: choose the most common convention and mark it "(assumed)".

## 7. Capacity check and kickoff

- `T plan`. It simulates five students through the prep. If it reports BEHIND, ask one question:
  study more on a typical day (`T set --minutes N` updates the forecast), drop the lowest-weight
  objectives (`T set --triage …`), or keep going (the tutor then teaches the highest-weight
  objectives first).
- Kickoff message (≤6 lines):
  - days until the exam and the number of objectives
  - the plan headline: first teaching done by …, mocks around …
  - how to answer: answer plus key steps, `; 1-3` for confidence, photos of paper welcome
  - pace: new topics keep coming for as long as they want to go on, and they can stop anytime
  - future sessions start with `/tutor`
  - if math mode is latex, add: "If formulas ever look like raw code, tell me 'plain math'."
- Then `T next` and ask the first diagnostic question in the same message.

## 8. Missing materials

- **No textbook**: build objectives from the syllabus, slides, homework and your knowledge of the
  standard course. Take conventions from the practice problems, or mark them "(assumed)".
- **No practice exam**: blueprint confidence is low. In intake, ask how long the exam is and whether
  it's mostly worked problems or multiple choice. Mocks then use typical first-year exam style.
- **Only a topic list**: that works. Echo the list back in one line so they can correct it.

## 9. Adding materials later

When the student adds files to `inbox/`, run `T adopt`, then:
- a practice exam or homework: read it, update `blueprint.md`, raise weights or add objectives by
  importing only the changed ones (`T import FILE` updates in place);
- lecture slides that reveal a different notation: update `conventions.md`.
Tell them in one line what changed in the plan.
