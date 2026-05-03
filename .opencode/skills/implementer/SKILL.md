---
name: implementer
description: Execute a single T{N.M} task from .opencode/tasks/ following task-guide.md with strict DI, no GOD-files, and mandatory test verification
compatibility: opencode
---

## Pre-flight rules

These rules apply to EVERY task. No exceptions.

### 1 — Full DI

Every dependency must be injectable through constructor or function argument.

```
# WRONG
class DataWriter:
    def __init__(self) -> None:
        self._path = Path("data/sessions")  # hardcoded
        self._lock = threading.Lock()        # hidden dependency

# CORRECT
class DataWriter:
    def __init__(self, path: Path, lock: threading.Lock) -> None:
        self._path = path
        self._lock = lock
```

If a class creates its own dependency inside __init__ or a method —
that is a DI violation. Fix it as part of the task.

### 2 — No GOD-files

No single file may own more than one responsibility.
If you touch a file and it clearly does 3+ unrelated things —
split it. But only split what you touched. Do not refactor the
entire codebase in one task.

Signs of a GOD-file:
- More than 3 classes in one file
- More than 300 lines that do unrelated work
- File name is generic: utils.py, helpers.py, common.py, tools.py

### 3 — Test verification

After ALL code changes are done:

1. Check: does this task's layer have test files?
   - Look in tests/ for files matching the changed module
2. If tests exist → run them:
   ```bash
   pytest tests/{matching_pattern} --tb=short -x
   ```
3. If tests fail → fix them in the same task. Do not stop.
4. If no tests exist → note in report: "no tests for this module"

After tests pass, also run:
```bash
ruff check {changed_files} --output-format=concise
mypy {changed_files} --strict --ignore-missing-imports
```

All three must be green before marking task done.

### 4 — Scope

Only change files listed in the task's Inputs or Steps.
If you discover a problem in an unrelated file —
note it in the report but do NOT fix it. That is a separate task.

### 5 — Layer direction

After all changes — verify import direction:
```
core → engine → bots → ui
```
No upward imports. No cross-layer shortcuts.

If your change introduced one — fix it immediately.

### 6 — Git branches

One task = one branch. No exceptions.

Branch naming:
```
task/T{N.M}-{kebab-slug}
```

Where:
- T{N.M} — exact task ID from the file name
- kebab-slug — 2-4 words from the title, lowercased, hyphenated

Examples:
```
[T1.1] Replace threading.Lock with multiprocessing in DataWriter.md
→ task/T1.1-replace-threading-lock

[T1.9] Eliminate module-level global _log_listener singleton.md
→ task/T1.9-remove-log-listener-singleton
```

---

## Execution flow

1. Read the task file. Extract T{N.M} and title.
2. Run `git branch --show-current` to detect current branch.
3. If on main or master:
   ```
   git checkout -b task/T{N.M}-{slug}
   ```
   If on another task branch — ask user:
   "Current branch is {branch}. Create new branch for this task?"
   If yes → `git checkout main && git checkout -b task/T{N.M}-{slug}`
4. CONFIRM branch is correct:
   ```
   git branch --show-current
   ```
   Print: "Branch: {result}". If not the expected branch — stop and ask user.
5. Phase A — Plan mode (do NOT write code)
   - Read all Inputs
   - List every file you will create or change
   - Verify plan does not violate layer rules
   - Print plan and wait for "approved"
6. Wait for "approved"
7. Phase B — Implementation
   - Execute Steps from the task file
   - Apply pre-flight rules during implementation
   - Commit after each logical step:
     ```
     [T{N.M}] {what changed}
     ```
8. After all checks green (tests, ruff, mypy):
   - Final commit if uncommitted changes remain:
     ```
     [T{N.M}] complete: {title}
     ```
   - Prepend to the top of the task file:
     ```
     ---
     status: DONE
     completed: {YYYY-MM-DD}
     ---
     ```
9. Push:
   ```
   git push -u origin task/T{N.M}-{slug}
   ```
10. Switch back:
    ```
    git checkout main
    git pull
    ```
11. STOP.

DO NOT add the task file to the branch. Keep it in local repo only.

Branch creation happens at step 3 — before any design, before any code.
If you skip step 3 — stop and ask user for permission to proceed.

Hard stop after checkout main. The implementer never:
- creates PR
- merges branches
- deletes branches
- pulls from origin

All of that is done manually by the user.

## Report

After all checks green, print:
- Files changed: list
- Tests: PASS / N/A
- ruff: 0 errors
- mypy: 0 errors
- New issues discovered (not fixed): list or "none"

## When to use me

Invoke when executing a task from .opencode/tasks/{layer}/.
Always pair with a specific task file.