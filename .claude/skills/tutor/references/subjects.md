# Subject guide

## Contents
1. Verifying answers (all subjects)
2. Math and statistics
3. Physics and engineering
4. Chemistry
5. Computer science

## 1. Verifying answers (all subjects)

Check every answer after the student responds and before you judge it. Model-written solutions go
wrong often enough that this matters. Everything below is standard-library Python, one line per call.

- **Exact arithmetic**:
  `python3 -c "from fractions import Fraction as F; print(F(2,3)*F(9,4) + F(1,6))"`
- **Are two expressions equal?** Evaluate both at random points (catches algebra slips in either one):
  `python3 -c "import math, random; f=lambda x: 2*x*math.cos(x**2); g=lambda x: math.cos(x*x)*x*2; print(all(abs(f(t)-g(t)) < 1e-9 for t in [random.uniform(-3, 3) for _ in range(6)]))"`
- **Derivative**: compare against a central difference of the original function; all values should be ~0:
  `python3 -c "import math; F=lambda x: math.sin(x**2); d=lambda x: 2*x*math.cos(x**2); h=1e-5; print([round((F(t+h)-F(t-h))/(2*h) - d(t), 6) for t in (0.3, 1.1, 2.0)])"`
- **Antiderivative**: differentiate their answer numerically and compare with the integrand, as above.
- **Definite integral** (Simpson's rule):
  `python3 -c "import math; f=lambda x: x**2*math.exp(x); a,b,n=0,1,1000; h=(b-a)/n; print(h/3*(f(a)+f(b)+4*sum(f(a+(2*i-1)*h) for i in range(1,n//2+1))+2*sum(f(a+2*i*h) for i in range(1,n//2))))"`
- **Limit**: evaluate close to the point from both sides:
  `python3 -c "f=lambda x: (x**2-4)/(x-2); print(f(2-1e-7), f(2+1e-7))"`
- **Equation**: substitute the student's solution back in, or find roots by bisection.
- **Statistics**: `statistics.mean`, `stdev` (sample, n−1), `pstdev` (population), and
  `statistics.NormalDist(mu, sigma).cdf(x)` / `.inv_cdf(p)`; binomial via `math.comb`. There's no
  t-distribution in the standard library: use the book's t-table, since exam answers use its rounding.
- **Units**: do the computation in SI, then check the final unit by dimensional analysis.
- **Symbolic checks**: if `python3 -c "import sympy"` works, sympy is fine to use. Never require it.
- **Code**: run it with `python3 -c`, or write a scratch file in `courses/SLUG/tutor/scratch/` and run
  that. For Java, C or C++, compile and run only if the compiler exists (`javac -version`, `gcc --version`);
  otherwise trace carefully by hand and tell the student it was traced by hand.

If a check disagrees with the key you had in mind, trust the check.

## 2. Math and statistics

**Item types**: compute; find (a derivative, integral, limit or extremum); solve; read a graph;
set up a word problem; short justification ("explain why f is continuous at 2"). If the exam wants
work shown, require the key steps.

**Convention checklist**:
- log means ln or log₁₀
- radians or degrees
- notation: f′(x), dy/dx or Df
- interval and set notation
- exact answers or decimals (how many places)
- sample SD (n−1) or population SD (n)
- z/t-table precision and interpolation rules
- default significance level
- the names used for theorems and tests

**Misconceptions to probe**:
- forgetting the inner derivative in the chain rule
- (a+b)² = a² + b²
- √(a+b) = √a + √b
- cancelling across a plus sign
- "plug in the value" when the limit is 0/0
- the derivative of a product is the product of the derivatives
- integrating a quotient term by term
- correlation implies causation
- the p-value is P(H₀ is true)
- confusing standard deviation with standard error

## 3. Physics and engineering

**Item types**: free-body diagram → Newton's laws; kinematics; energy and momentum conservation;
circuits; reading x–t, v–t and a–t graphs; units and estimation. Diagrams go on a printable page (inline SVG).

**Convention checklist**:
- g = 9.8, 9.81 or 10 m/s²
- which direction is positive
- significant-figure rules
- vector notation (bold, arrow, hat)
- which axis angles are measured from
- the sign of work and heat in thermodynamics (physics usually counts work done *by* the system)
- what the formula sheet contains

**Misconceptions to probe**:
- motion needs a force
- heavier objects fall faster
- the normal force always equals mg
- a = 0 at the top of a throw
- action–reaction pairs cancel on one object
- current is used up in a circuit
- confusing mass and weight
- confusing velocity and acceleration on graphs

## 4. Chemistry

**Item types**: stoichiometry and limiting reagent; gas laws; thermochemistry (ΔH, Hess's law);
equilibrium (ICE tables); acids and bases (pH, buffers); naming and formulas; Lewis structures and VSEPR.

**Convention checklist**. Always use the book's values, because numeric answers depend on them:
- molar masses, with the book's decimal places
- R = 8.314 J/(mol·K) or 0.08206 L·atm/(mol·K)
- standard conditions (0 °C and 1 atm vs 1 bar, or 25 °C for "standard state")
- the sign of work: chemistry books usually use w = −PΔV, so work done *on* the system is positive
- significant-figure rules, including decimal places for pH
- data-table values (Ka, Kb, Ksp, ΔHf°, E°): pull the exact entry from the book (course.json → book.tables)

**Misconceptions to probe**:
- mass vs moles
- coefficients vs subscripts
- "the limiting reagent is the one with less mass"
- equilibrium means equal concentrations
- strong vs concentrated
- "breaking bonds releases energy"
- pH of dilute strong acids below 1e-7 M

## 5. Computer science

**Item types**: trace code (output or final state); write a function; find and fix a bug;
Big-O of a snippet; explain a concept (recursion, references, scope); fill in missing code.

**Convention checklist**:
- language and version (Python 3.x, Java 17, …)
- 0- or 1-based indexing in pseudocode
- integer-division semantics
- which built-ins and libraries are allowed
- style requirements (docstrings, types)
- how exam code is presented (line numbers? handwritten answers?)

**Verification**: run it. For "write a function", test the student's code on your own cases,
including edge cases: empty input, 0 and 1, negatives, duplicates, very large values.

**Misconceptions to probe**:
- off-by-one errors in loops and ranges
- `=` vs `==`
- aliasing (two names for one list) and mutable default arguments
- integer vs float division
- recursion without a reachable base case
- return vs print
- variable shadowing and scope
- nested loops over different sizes
