# Teaching one objective

`T` = `python3 "${CLAUDE_SKILL_DIR}/scripts/tutor_state.py"`.

## Contents
1. The sequence
2. Notes files
3. The hint ladder
4. Writing good items
5. Confusable pairs
6. Rescue
7. Fatigue and motivation
8. "Just tell me the answer"

## 1. The sequence

`next` tells you where to begin (`start`) and how many unaided correct answers in a row are still
needed (`need`).

1. **Probe** (mode `probe`): one exam-style question before any teaching. Trying first, even and
   especially when it fails, makes the explanation that follows stick better (the pretesting effect).
   Don't teach during a probe: one line of feedback, then the loop moves on.
2. **Explain** (start = `worked`): at most 5 sentences, in the course notation, citing § and pages.
   One idea: when this method applies, and what its first step is.
3. **Interactive worked example**: present the problem, then reveal the solution one step at a time.
   At each step ask "why this step?" or "what comes next?". Students who explain the steps to
   themselves learn much more (self-explanation, g ≈ 0.55).
4. **Faded example** (start = `faded` begins here): a similar problem with the early steps done; the
   student finishes it. Next time, leave more of the steps to them.
5. **Independent practice** until `need` is 0: vary numbers, context and representation, raise the
   difficulty, and include at least one item in the exam's own format. Record each with `--ctx learn`.
6. **Explain-back**: when `record` reports `"outcome": "learned"`, ask one question: "In a sentence,
   how do you recognize when to use this?" Don't grade it; fix any misconception in a line.

When the probe shows competence (start = `independent`), skip the examples and go straight to items.
Worked examples slow down students who already know the method (expertise reversal).

## 2. Notes files

`next` gives the path in `notes`. Write it the first time you teach an objective (≤30 lines), and
read it whenever the objective comes up again (`notes_exist: true`). It keeps explanations,
notation and examples consistent across sessions, since you start each session with no memory.

```
# <title> (§<sec>, p.<pages>)
Idea: <one sentence>
First-step cue: <how to recognize this problem type and what to do first>
Notation/conventions: <anything book-specific>
Worked example used: <problem>, key steps: <…>
Common errors: <general ones> | this student: <from their records>
Items used: <fingerprints, so they aren't repeated>
```

## 3. The hint ladder

Give one rung per request; each rung adds 1 to `--hints`.
1. **Goal**: restate what is being asked, in other words ("What exactly do we need to find?").
2. **Principle**: name the idea or the first step without doing it ("Which rule handles a function
   inside a function?").
3. **Narrowed step**: set the step up and ask for the specific move ("The outside is sin(u). What's
   its derivative?").
4. **One step shown**: do that one step completely, then hand the problem back.

If they needed rung 4 for the key step, record the attempt as **wrong**, not just aided. Then give
a fresh similar item for them to solve alone; that one is what counts.

## 4. Writing good items

- Exam-like first: match the blueprint's formats and difficulty. Change numbers and context each
  time; never reuse anything in `avoid`.
- Build each problem so that you know the answer, and verify it after they answer
  (references/subjects.md).
- When practice should mirror the course exactly, prefer the book's odd-numbered exercises. The
  answer key's location is in course.json → book.answers; pull only the page you need with
  `pdf_tools.py text`.
- One item per message. For multiple choice, use AskUserQuestion if available: the question with
  4 options, plus a second question for confidence. Otherwise use lettered options.
- Anything visual (a graph, a free-body diagram, a circuit) goes on a printable page
  (references/assessment.md, "Printables"). Use ASCII only for trivial sketches.

## 5. Confusable pairs

For objectives linked as `confusable` (product rule vs chain rule, permutations vs combinations,
momentum vs energy conservation), give items that force a choice. Ask "Which method applies here,
and why?" before they solve. In mixed and review items never label the topic.

## 6. Rescue (mode `rescue`)

The student has tried 10+ times without 3 unaided correct in a row. Don't repeat the same thing:
1. **Prerequisites**: one quick question on each prerequisite objective. If one fails,
   `T next --focus <prereq>` and teach that first.
2. **Change representation**: numbers → picture or graph, abstract → concrete example, or the reverse.
3. **Smaller steps**: a faded example with only the last step missing, then two steps, and so on.
4. **Park it**: after about 12 tries in one session, stop for today. Say "we'll come back tomorrow;
   sleep consolidates this." The scheduler moves on by itself.

## 7. Fatigue and motivation

- 3 misses in a row: an easier item, or back to a worked example.
- Late at night or visibly tired: offer to stop for today, and end on a success. (Judge by what
  they say and how they answer, never by the clock.)
- Treat errors as normal: mistakes in practice are how the exam gets easier. Praise strategies
  that worked, never "you're smart".
- Show progress when it's real: "that's 3 in a row, so this one is learned."

## 8. "Just tell me the answer"

Give the next hint rung and say briefly why working it out matters. Never give the full solution
before a genuine attempt. If they insist after a real attempt, show the worked solution, record
the attempt as wrong, and immediately give a similar item to solve alone. That item is the one
that counts.
