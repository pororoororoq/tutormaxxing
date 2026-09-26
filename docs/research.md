# What the research says, and how the tutor uses it

This is the evidence behind the `tutor` skill: what works for preparing for a STEM exam in about
three weeks, what makes AI tutors help or hurt, and where each number in the scheduler comes from.
Effect sizes are standardized mean differences (d or g): 0.2 is small, 0.5 medium, 0.8 large.
Items marked **[unverified]** could not be confirmed against the primary source during research
(September 2026); everything else was checked against abstracts or primary summaries.

## Contents
1. The short answer
2. Learning techniques, ranked
3. AI tutors: what helps and what hurts
4. How the tutor implements it
5. Where each scheduler number comes from
6. What the tutor deliberately doesn't do
7. Caveats and open questions

## 1. The short answer

No single technique is "the best". The evidence converges on a **package**:

> **diagnose → mastery learning with step-level tutoring → successive relearning (spaced retrieval
> to a criterion) → interleaved, exam-format practice → timed mock exams**,
> run by a tutor that never does the student's work for them.

Three findings dominate:

- **Retrieval beats review.** Testing yourself (with feedback) beats rereading by about half a standard
  deviation, and far more when the test is delayed.
- **Spacing beats cramming**, and it works best combined with retrieval to a criterion
  ("successive relearning"): about a full letter grade in a real course.
- **An AI tutor's design decides whether it helps or hurts.** A well-designed AI tutor beat an
  active-learning class by 0.73–1.3 SD in less time. An unrestricted chatbot raised practice scores
  48% but *lowered* exam scores 17%.

## 2. Learning techniques, ranked

### Tier A: the core engine

**Retrieval practice (the testing effect).**
- Recall after one week: 56% after testing vs 42% after restudying. At 5 minutes, restudying looked
  better (83% vs 71%) and *felt* more effective ([Roediger & Karpicke 2006](https://journals.sagepub.com/doi/10.1111/j.1467-9280.2006.01693.x)).
- Meta-analyses:
  - [Rowland 2014](https://pubmed.ncbi.nlm.nih.gov/25150680/): g = 0.50; 0.73 with feedback vs 0.39 without.
  - [Adesope et al. 2017](https://journals.sagepub.com/doi/abs/10.3102/0034654316689306): g = 0.51 vs restudying, 0.67 in classrooms.
  - [Yang et al. 2021](https://pubmed.ncbi.nlm.nih.gov/33683913/): 222 classroom studies, g = 0.50.
- Transfer to *new* questions is weaker: d = 0.40, about 0.58 when practice and test formats match
  ([Pan & Rickard 2018](https://pubmed.ncbi.nlm.nih.gov/29733621/)).

**Spacing.**
- The best gap between sessions is a fraction of the time until the test: about 20–40% for a week-long
  retention interval, and smaller fractions for longer ones
  ([Cepeda et al. 2006](https://escholarship.org/uc/item/3rr6q10c), [2008](https://journals.sagepub.com/doi/10.1111/j.1467-9280.2008.02209.x)).
- Recall rises steeply as the gap grows toward the optimum and falls only slowly after it, so when
  unsure, err long.
- Expanding and equal gaps perform the same (g = 0.03, n.s.; [Latimier et al. 2021](https://link.springer.com/article/10.1007/s10648-020-09572-8)).

**Successive relearning** (retrieve to criterion, then relearn in later spaced sessions).
- Recommended protocol: 3 correct recalls in the first session, then about 3 spaced relearning
  sessions to 1 correct recall each ([Rawson & Dunlosky 2011](https://eric.ed.gov/?id=EJ934616)).
- In an intro course this added about 10 percentage points (a letter grade) on exams, and much better
  retention weeks later ([Rawson, Dunlosky & Sciartelli 2013](https://link.springer.com/article/10.1007/s10648-013-9240-4)).
  **[unverified: exact gaps and raw percentages]**
- Relearning sessions get fast: roughly 15 minutes for the first one, under 5 after that.

### Tier B: instructional moves

**Mastery learning and tutoring.**
- Bloom's "2 sigma" came from tutoring plus mastery thresholds of about 80–90%
  ([Bloom 1984](https://journals.sagepub.com/doi/10.3102/0013189X013006004)).
- Realistic estimates are smaller:
  - mastery learning: 0.52 SD ([Kulik et al. 1990](https://journals.sagepub.com/doi/10.3102/00346543060002265))
  - human tutoring: d = 0.79 ([VanLehn 2011](https://www.tandfonline.com/doi/abs/10.1080/00461520.2011.611369))

**Worked examples, then faded examples, then independent problems.**
- Worked examples in math: g = 0.48 ([Barbieri et al. 2023](https://link.springer.com/article/10.1007/s10648-023-09745-1)).
- Fade from the end ([Renkl & Atkinson 2003](https://www.tandfonline.com/doi/abs/10.1207/S15326985EP3801_3)).
- Examples *hurt* students who already know the method (expertise reversal; [Kalyuga 2007](https://link.springer.com/article/10.1007/s10648-007-9054-3)).
  A quick "what's the first step?" probe detects this.

**Self-explanation.** Explaining steps to yourself: g = 0.55
([Bisra et al. 2018](https://link.springer.com/article/10.1007/s10648-018-9434-x); [Chi 1994](https://onlinelibrary.wiley.com/doi/10.1207/s15516709cog1803_3)).

**Feedback.**
- Overall d = 0.48 ([Wisniewski et al. 2020](https://www.frontiersin.org/articles/10.3389/fpsyg.2019.03087/pdf)).
- Explanations beat bare right/wrong (0.49 vs 0.05 in computer-based settings;
  [Van der Kleij et al. 2015](https://journals.sagepub.com/doi/abs/10.3102/0034654314564881)).
- Praise of the person doesn't help ([Hattie & Timperley 2007](https://journals.sagepub.com/doi/abs/10.3102/003465430298487)).
- **Hypercorrection**: errors made with *high confidence* are corrected most readily after feedback
  ([Butterfield & Metcalfe 2001](https://pubmed.ncbi.nlm.nih.gov/11713883/)).

**Interleaving.**
- 63% vs 20% a week later for mixed vs blocked math practice, despite *lower* practice accuracy
  (60% vs 89%) ([Rohrer & Taylor 2007](https://link.springer.com/article/10.1007/s11251-007-9015-8)).
- A randomized trial across 54 classes: d = 0.83 ([Rohrer et al. 2020](https://eric.ed.gov/?id=EJ1237752)).
- College physics homework: median gains of 50% and 125% ([Samani & Pan 2021](https://www.nature.com/articles/s41539-021-00110-x)).
- Meta-analysis ([Brunmair & Richter 2019](https://psycnet.apa.org/record/2019-57442-001)): g = 0.42
  overall, 0.34 for math. It works best for similar, confusable problem types; it hurts for word lists.

### Tier C: supporting moves

- **Pretesting**: even failed attempts before instruction improve learning of that content
  ([Richland et al. 2009](https://pubmed.ncbi.nlm.nih.gov/19751074/); [Pan & Carpenter 2023](https://link.springer.com/article/10.1007/s10648-023-09814-5)).
- **Exam-format practice**: memory works best when practice matches the test's demands
  (transfer-appropriate processing). Taking a practice exam beats reviewing its key ([Balch 1998](https://journals.sagepub.com/doi/10.1207/s15328023top2503_3)).
- **Sleep, not cramming**:
  - Sleep between learning and relearning halved the practice needed ([Mazza et al. 2016](https://journals.sagepub.com/doi/abs/10.1177/0956797616659930)).
  - Sleep in the month and week before an exam predicted grades; the night before didn't
    ([Okano et al. 2019](https://www.nature.com/articles/s41539-019-0055-z)).
- **Don't trust "I understand."**
  - Judgments made with the answer in view inflate confidence ([Koriat & Bjork 2005](https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Koriat_RBjork_2005.pdf)).
  - Students in active-learning classes learned more but *felt* they learned less
    ([Deslauriers et al. 2019](https://www.pnas.org/doi/abs/10.1073/pnas.1821936116)).

**Consensus reviews.** [Dunlosky et al. 2013](https://journals.sagepub.com/doi/abs/10.1177/1529100612453266)
rates practice testing and distributed practice as *high* utility, and rereading, highlighting and
summarizing as *low*. The [IES practice guide (Pashler et al. 2007)](https://ies.ed.gov/ncee/wwc/Docs/PracticeGuide/20072004.pdf)
recommends spacing, alternating worked examples with problems, quizzing, and deep "why/how" questions.

**A caveat for math.** For math *procedures*, spacing (g ≈ 0.28) and testing effects are smaller than
for facts ([Murray et al. 2025](https://link.springer.com/article/10.1007/s10648-025-10035-1)). Worked
examples, independent practice and interleaving carry more of the weight there; the tutor still spaces reviews.

## 3. AI tutors: what helps and what hurts

| Study | Finding | What the tutor does about it |
|---|---|---|
| [Kestin et al. 2025](https://www.nature.com/articles/s41598-025-97652-6), Harvard physics RCT (N=194) | AI tutor beat an active-learning class by 0.73–1.3 SD in a median 49 vs 60 minutes. Its prompt said: be brief, one step at a time, never give the full solution, expert solutions embedded for accuracy. | Short turns, one step, one question; grounded answer keys |
| [Bastani et al. 2025](https://www.pnas.org/doi/10.1073/pnas.2422633122), PNAS (~1,000 students) | Unrestricted GPT: +48% practice, **−17%** on the exam without AI. Hint-giving "GPT Tutor" with teacher solutions: +127% practice, no exam harm. GPT alone was correct only 51% of the time. | No solutions before attempts; hint ladder; verify every answer; mastery counts only unaided answers |
| [VanLehn 2011](https://www.tandfonline.com/doi/abs/10.1080/00461520.2011.611369) | Answer-level tutoring d = 0.31; step-level 0.76; human 0.79 | Feedback targets the first wrong step |
| [Kulik & Fletcher 2016](https://journals.sagepub.com/doi/abs/10.3102/0034654315581420) | Tutoring systems: +0.66 on local tests but +0.13 on standardized ones | Practice matched to *this* exam's blueprint; mocks mirror its format |
| [Khanmigo, NBER 2026](https://www.nber.org/papers/w35620) | ~0.06–0.08 SD/yr; students rarely engaged. The bottleneck was engagement, not tutor quality. | The tutor drives every session and always names the next one |
| [Lehmann et al.](https://arxiv.org/abs/2409.09047), [Kumar et al.](https://link.springer.com/chapter/10.1007/978-3-031-98459-4_5), [Anthropic 2026](https://www.anthropic.com/research/AI-assistance-coding-skills) | Having AI *generate* solutions lowered understanding; asking it for *explanations* raised it. Students overestimate what they learned with AI. | Explanations yes, answers no; calibration through confidence ratings and predicted vs actual mock scores |
| [Check My Work?](https://arxiv.org/abs/2506.10297) | LLM accuracy drops up to 15 points when the student states a wrong answer (sycophancy) | Re-verify under pushback; never flip without evidence |
| [LearnLM](https://arxiv.org/abs/2412.16429), [ChatGPT study mode](https://openai.com/index/chatgpt-study-mode/) | Shared principles: active learning, managing cognitive load, adapting, metacognition, don't do the student's work | Built into the rules and teaching sequence |

## 4. How the tutor implements it

| Evidence | Tutor behavior (where) |
|---|---|
| Pretesting; diagnosis first | First contact with every objective is a probe; 8 diagnostic probes in session 1, spread across chapters (`decide`, `pick_probe`) |
| Expertise reversal | The probe result sets the teaching entry point: worked / faded / independent |
| Worked → faded examples; self-explanation | Teaching sequence with "why this step?" prompts (teaching.md) |
| Mastery learning; successive relearning | Learned = 3 unaided correct in a row; mastered = first-try unaided successes on ≥3 later days (`apply_attempt`) |
| Spacing ∝ time left | Review gap ≈ 35% of the days left, clamped to 2–7 days (`due_after_success`) |
| Hypercorrection | Confident errors are flagged and reviewed first next session (`review_order`) |
| Interleaving, discrimination | Mixed sets with the topic hidden, favoring confusable pairs (`pick_mixed`) |
| Exam-format practice | Blueprint from practice exams; mixed-item formats in blueprint proportions; printable timed mocks |
| Feedback with explanation, at the first wrong step | SKILL.md rules 4–5 |
| Engagement bottleneck | `/tutor` → agenda → first question in the same message; every session ends with the next date |
| LLM errors, sycophancy | Verify after every answer; `void` to correct past grading; hold verdicts under pushback |
| Sleep, no cramming | No new material in the last 2 days; short final day; exam-day warm-up only |
| Grounding in the course, not the whole book | "Map, don't read": practice exams read fully, textbook only mapped and looked up on demand |

## 5. Where each scheduler number comes from

| Constant (tutor_state.py) | Value | Source / rationale |
|---|---|---|
| `LEARN_STREAK` | 3 | Rawson & Dunlosky's initial criterion of 3 correct recalls; ASSISTments and ALEKS mastery rules also use 3 in a row |
| `MASTERY_DAYS` | 3 | 3 spaced relearning sessions to 1 correct each (Rawson & Dunlosky 2011) |
| `GAP_RATIO`, `GAP_MIN/MAX` | 0.35, 2–7 days | Optimal gap ≈ 20–40% of the retention interval (Cepeda 2008); err long; ≥1 night of sleep |
| `DUR_RATIO` | 0.15 → 2–3 days | Durable = succeeded after a real gap, not just on consecutive days |
| `TEACH_BY` | 55% of the window | Simulation: with 35% gaps, an objective first learned by day ~12 of 21 can still reach mastery |
| `REVIEW_SHARE` | 60% | Due reviews first, but new learning must keep moving |
| `STUCK_TRIES` | 10 | "Wheel-spinning" definition: 10 attempts without mastery ([Beck & Gong 2013](https://link.springer.com/chapter/10.1007/978-3-642-39112-5_44)) |
| Mixed sets | 3 items/session, then 5 in the last 45% of the window | Interleaving after initial blocked practice; more exam-format work closer to the exam |
| Mocks | ~7 days out (if ≥70% learned; forced at 5), again at 3–4 days out; never in the last 2 days | Time to act on the first mock; second confirms; last days are for consolidation |
| Readiness p-values | .05 / .30 / .55–.85 / .92 | Heuristic; each (readiness, mock) pair is logged so these can be calibrated against real results |
| Ready / ace-ready | R ≥ 85%, last mock ≥ 80% / all mastered, last 2 mocks ≥ 95%, predictions within 10 points | Mastery thresholds of 80–90% (Bloom); calibration research (Koriat & Bjork) |

The parameter *package* is a synthesis; no single study tested it end to end. The simulations in
`tests/test_simulation.py` check that it behaves sensibly across strong, typical, weak and
overloaded students, missed days, a moved exam date, and a one-week window.

## 6. What the tutor deliberately doesn't do

- **Rereading, highlighting, summarizing**: low utility (Dunlosky et al. 2013).
- **Learning styles**: no adequate evidence that matching instruction to a "style" helps
  ([Pashler et al. 2008](https://journals.sagepub.com/doi/full/10.1111/j.1539-6053.2009.01038.x)).
- **Overlearning in one sitting**: its benefit disappeared after 4 weeks ([Rohrer et al. 2005](https://onlinelibrary.wiley.com/doi/abs/10.1002/acp.1083)).
  The scheduler only gives extra practice on objectives that have rested for a few days. Drilling
  everything daily left no spacing gap and, in simulation, *prevented* mastery.
- **All-nighters**: trading sleep for study backfires ([Gillen-O'Neel et al. 2013](https://pubmed.ncbi.nlm.nih.gov/22906052/)).
- **Reading the whole textbook**: Claude already knows first-year STEM content. The successful AI
  tutors were grounded in *course problems and solutions*, not whole books, so the tutor reads
  practice exams fully and only maps the textbook.

## 7. Caveats and open questions

- Effect sizes come from specific populations and tests. Gains on a particular midterm will vary.
- The readiness formula is a heuristic until it's calibrated with real exam scores. Record them with
  `set --actual` and the lessons in `lessons.md`.
- Spacing and testing effects are smaller for math procedures (Murray et al. 2025); the right mix of
  worked examples, practice and spacing for calculus specifically is still an open question.
- The Khanmigo results show the hardest problem is showing up. Future improvements could add
  reminders (calendar invites).
