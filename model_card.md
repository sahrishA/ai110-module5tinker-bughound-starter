# BugHound Mini Model Card (Reflection)

---

## 1) What is this system?

**Name:** BugHound  
**Purpose:** Analyze a Python snippet, propose a fix, and run reliability checks before deciding whether the fix should be auto-applied.

**Intended users:** Students learning agentic AI workflows, AI reliability concepts, and the risk-reward tradeoffs of automated code modification.

---

## 2) How does it work?

BugHound runs a five-step agentic loop:

1. **PLAN** — logs that a scan + fix workflow is starting.
2. **ANALYZE** — detects issues. In heuristic mode, regex rules check for `print(`, bare `except:`, and `TODO`. In Gemini mode, the LLM returns a JSON array of issues; if parsing fails the agent falls back to heuristics.
3. **ACT** — proposes a fix. In heuristic mode, regex substitutions replace `print(` with `logging.info(`, narrow bare `except:` to `except Exception as e:`. In Gemini mode, the LLM rewrites the full file; the agent strips code fences and falls back to heuristics on empty output.
4. **TEST** — `assess_risk` scores the proposed fix 0–100 based on issue severity, structural changes (line count, return statements, bare-except removal), and now the number of issues.
5. **REFLECT** — if `should_autofix` is True the agent logs that the fix is safe; otherwise it recommends human review.

Heuristics run offline with zero API calls. Gemini mode makes two API calls (analyze + fix) and can produce richer, context-aware output.

---

## 3) Inputs and outputs

**Inputs tested:**

| Snippet | Shape |
|---|---|
| `cleanish.py` | 5-line function with `logging.info` and `return` |
| `mixed_issues.py` | 10-line function with `TODO`, `print`, and bare `except:` |
| Two-print function | Short function with two `print()` calls and a `return` |
| Comments-only | Two comment lines, no executable code |
| Empty string | Zero bytes |

**Outputs observed:**

- *cleanish.py*: No issues, score 100, `should_autofix: True`.
- *mixed_issues.py* (heuristic): 3 issues (Low/High/Medium), score 20, `should_autofix: False`. Fix added `import logging`, replaced `print` with `logging.info`, narrowed `except:`.
- *comments-only*: No issues, score 100, `should_autofix: True` (fix = original code unchanged).
- *empty string*: No issues, `fixed_code` is empty → `assess_risk` immediately returns score 0, `level: high`, `should_autofix: False`.

---

## 4) Reliability and safety rules

**Rule 1 — High severity issue deducts 40 points**

Checks whether any detected issue carries severity "High". A bare `except:` is rated High because it silently swallows every exception including `KeyboardInterrupt` and `SystemExit`.

*Why it matters:* A fix that touches high-severity logic has a greater chance of altering error-handling behavior.

*False positive:* If Gemini labels an issue "High" that is stylistic (e.g., a long line), the score drops unfairly and the fix is blocked even if the change is trivial.

*False negative:* If Gemini labels a `bare except` as "Medium" (lower-confidence response), the rule misses the deduction entirely.

---

**Rule 2 — Return statements removed deducts 30 points**

Checks whether `return` appears in the original but not in the fixed code.

*Why it matters:* Removing a `return` changes a function's output from a value to `None`, which is a silent, hard-to-debug behavioral change.

*False positive:* If the original code contains `return` inside a string literal or comment (e.g., `# returns early`), the check fires incorrectly.

*False negative:* The rule only checks for the presence of the word `return`; if the fixed code returns `None` explicitly (`return None`) where the original returned a computed value, the rule passes with no penalty.

---

**Rule 3 (new) — Multiple issues deducts 10 points**

Added as a deliberate guardrail. If more than one issue is detected, the fix is likely touching multiple parts of the code simultaneously, increasing the risk of unintended interactions.

*Why it matters:* Two independent heuristic fixes (e.g., swapping `print` to `logging` AND narrowing `except`) interact in ways that compound the risk.

*False positive:* A file with two trivial low-severity issues (e.g., two stray print statements) is now blocked from auto-fix even though the fix is purely mechanical.

*False negative:* A single LLM fix that touches ten functions is not penalized by this rule because only one issue was detected.

---

## 5) Observed failure modes

**Failure 1 — Over-editing (heuristic mode): bare-except comment injection**

Input snippet from `mixed_issues.py`:
```python
    except:
        return 0
```
Heuristic fix produces:
```python
    except Exception as e:
        # [BugHound] log or handle the error
        return 0
```
The comment `# [BugHound] log or handle the error` is injected mid-function. While harmless, it is noise that real reviewers would need to remove. The fix changes more lines than necessary (2 lines become 3).

**Failure 2 — Unsafe confidence on "comments-only" input**

When the input is `# This file only has comments\n# No actual code here\n`, BugHound detects zero issues, returns the original code unchanged as the "fix", and scores it `level: low`, `should_autofix: True`. The system would auto-apply a no-op change and report it as a successful fix. This is semantically correct (nothing changed) but misleading — the agent should recognize it did nothing and say so explicitly.

---

## 6) Heuristic vs Gemini comparison

| Dimension | Heuristic mode | Gemini mode |
|---|---|---|
| Issue detection | Pattern-only (print, bare except, TODO) | Semantic: flags type mismatches, missing input validation, division-by-zero |
| Fix style | Mechanical substitution, can leave dead comments | Full rewrite respecting intent; can miss subtle behavior |
| False positives | Low (rules are very narrow) | Higher (LLM may flag style as "High" severity) |
| Output format | Always valid (Python strings) | Requires parsing; code fences must be stripped |
| Risk scorer agreement | Conservative — often blocks even when fix is safe | Often same score since risk is computed on the *output*, not the mode |

In heuristic mode the fixes are predictable but blunt. In Gemini mode the fixes can be more precise but require careful output parsing and are harder to verify automatically.

---

## 7) Human-in-the-loop decision

**Scenario:** The agent detects a bare `except:` inside a function that handles user authentication, and the LLM-generated fix changes both the exception type and the return value from `False` to `None`.

**Trigger:** If the fix removes or changes a `return` statement *and* a bare `except` was also modified, both high-risk structural changes occurred together. The combined deduction (30 + 5 + 40 = 75 points) already produces `level: high`. But even without the severity signals, this combination should always require review.

**Where to implement:** In `assess_risk` — add a rule: if both `"return" in original and "return" not in fixed` AND `"except:" in original and "except:" not in fixed`, force `should_autofix = False` unconditionally and add a reason like "Combined control-flow changes require human review."

**Message to user:** "BugHound detected changes to both return statements and exception handling. These changes may alter the function's behavior in error cases. Please review the diff before applying."

---

## 8) Improvement idea

**Guardrail: diff-size cap**

Currently the risk assessor only checks whether the fixed code is less than 50% of the original length. It does not check how many *lines* actually changed.

**Proposed change:** Compute a line-level diff using `difflib.ndiff` and count changed lines. If more than 40% of lines are modified, add a 15-point deduction with reason "Large proportion of lines changed." This catches cases where the LLM rewrites entire functions instead of making a targeted fix, without making the system dramatically more complex.

**Implementation:** Three lines in `assess_risk`:
```python
import difflib
changed = sum(1 for l in difflib.ndiff(original_lines, fixed_lines) if l.startswith(('+', '-')))
if original_lines and changed / max(len(original_lines), 1) > 0.4:
    score -= 15
    reasons.append("Large proportion of lines changed; verify the fix is minimal.")
```

**Measurable effect:** On `mixed_issues.py` (10 lines, 4 changed) the ratio is 40% — right at the boundary. Any LLM that rewrites more than 4 lines would now be penalized, making auto-fix harder to trigger for broad rewrites.
