# Recipes

Concrete workflows with **`agloom`** in direct mode (adjust `-m` / keys for your provider).

## 1. Git commit message from staged diff

**Setup:** staged changes, API key exported.

```bash
git diff --staged | agloom -q "write a concise conventional-commit title + body"
```

**What happens:** stdin carries the patch; the model proposes a message. If CLI tools are off, it never touches disk; if on, approve only reads you expect.

**Variation:** `git diff HEAD~1..HEAD | agloom -q "changelog bullet"`

## 2. PR review summary

**Setup:** [GitHub CLI](https://cli.github.com/) `gh`.

```bash
gh pr diff 123 | agloom -q "review this diff: bugs, suggestions, blocking concerns"
```

**What happens:** entire diff in context window limits — trim with `gh pr diff 123 --path src/` for huge PRs.

## 3. Generate tests for a function

```bash
agloom -q "read src/utils/parse.ts and add vitest tests in src/utils/parse.test.ts covering edge cases"
```

**What happens:** expect **write_file** / **edit_file** HITL prompts — use **`--hitl-tty`** or pre-approve in a safe sandbox.

## 4. Debug failing tests

```bash
npm test 2>&1 | agloom -q "explain the root cause and propose the minimal fix"
```

**What happens:** model sees stderr; may suggest shell commands — review before **`--auto-approve`**.

## 5. Rename across the codebase

```bash
agloom "rename function getCwd to getCurrentWorkingDirectory across the repo; keep behavior identical"
```

**What happens:** multi-step reads/edits; watch HITL closely or run from a clean git worktree.

## 6. Log triage (SRE-style)

```bash
kubectl logs deploy/api --tail=200 | agloom -q "summarize the dominant error pattern and likely cause"
```

**What happens:** stdin carries logs; no cluster access unless tools invoke kubectl afterward.

---

## Tips

- Add **`--json`** for structured pipelines ([Direct mode](direct-mode.md)).
- Use **`agloom --resolve-model "<spec>"`** before automation to verify keys + routing ([Models](models.md)).
