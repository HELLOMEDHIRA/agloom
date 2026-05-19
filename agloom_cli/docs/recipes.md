# Recipes

Copy-paste workflows using **`agloom`** in **direct mode**. Swap **`-m`** and API keys for your provider ([Models](models.md)).

Each recipe follows the same shape: **you supply context** (stdin, repo, or a prompt) → **agloom classifies and runs tools** → **you review HITL** when writes or shell are involved.

---

## 1. Git commit message from staged diff

```bash
git diff --staged | agloom -q \
  -m groq:meta-llama/llama-3.3-70b-versatile \
  "write a concise conventional-commit title + body"
```

**What happens:** the patch is stdin; the model proposes a message. With CLI tools enabled, approve reads only — no disk writes unless you allow them.

**Variation:** `git diff HEAD~1..HEAD | agloom -q "changelog bullet"`

---

## 2. PR review summary

Requires [GitHub CLI](https://cli.github.com/) `gh`.

```bash
gh pr diff 123 | agloom -q \
  "review this diff: bugs, suggestions, blocking concerns"
```

**Tip:** trim huge PRs with `gh pr diff 123 --path src/`.

---

## 3. Generate tests for a module

```bash
agloom -q "read src/utils/parse.ts and add vitest tests covering edge cases"
```

Expect **write_file** / **edit_file** HITL prompts — use a clean git worktree or **`--hitl-tty`**.

---

## 4. Debug failing tests

```bash
npm test 2>&1 | agloom -q "explain the root cause and propose the minimal fix"
```

The model sees stderr; shell suggestions need explicit approval unless **`--auto-approve`** (use with care).

---

## 5. Rename across the codebase

```bash
agloom "rename getCwd to getCurrentWorkingDirectory across the repo; keep behavior identical"
```

Multi-step reads and edits — watch HITL closely.

---

## 6. Log triage (SRE-style)

```bash
kubectl logs deploy/api --tail=200 | agloom -q \
  "summarize the dominant error pattern and likely cause"
```

Logs via stdin only unless the agent later invokes kubectl through tools.

---

## Automation tips

| Flag | Use |
| ---- | --- |
| `--json` | NDJSON AGP on stdout for `jq` ([Direct mode](direct-mode.md)) |
| `agloom --resolve-model "<spec>"` | Verify keys before CI ([Models](models.md)) |
| `--no-cli-tools` | Answer from prompt/context only |

**Library embedding (no terminal):** [Python quick start](../agloom/getting-started/quickstart.md)
