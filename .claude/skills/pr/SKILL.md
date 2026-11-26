---
name: pr
description: Open a pull request in bd78/py-md-view from a dev branch to main and see it through. Commits and pushes with the git-commit skill, has the pr-manager agent write and open the PR as the person, then loops - pr-manager reports failing checks, unresolved review findings and merge conflicts, python-devops fixes them, git-commit commits and pushes - until the PR is clean. Use when a change on a dev branch is committed and ready; one small change per pull request.
---

# Pull request

Each small, finished change gets its own pull request: one change, one branch, one PR. Open it without asking
once the change is committed and the local checks are green. Push first (step 1), so `origin/<branch>` equals
`HEAD`; then look for an open PR from that branch: `gh pr list -R bd78/py-md-view --head <branch> --state open`. If
there is one, the push already updated it: go to step 3 with its number instead of opening another.

Run it in the main conversation: it starts the `pr-manager` and `python-devops` agents, and agents cannot start
agents.

There is one remote, `origin` = `bd78/py-md-view`; head and base are in the same repository. `gh` acts as the person.

## 0. Preconditions

- `git branch --show-current` is not `main`. If it is, create a branch for the change (never commit to `main`).
- The PR covers one issue or one change. If the branch bundles unrelated work, split it into separate branches.
- The PR always opens as a **draft**; step 4 makes it ready.

## 1. Commit and push

- If there are uncommitted changes for this branch: run the `git-commit` skill in full (CodeRabbit loop with
  `python-devops`, local checks, commit). Pushing is part of this skill.
- Push: `git push -u origin <branch>`. Never `--force`.
- If there is nothing to commit, only make sure `origin/<branch>` equals `HEAD`.
- The local checks of `git-commit` step 4 must be green on the exact `HEAD` before opening the PR; cite them in the
  PR's "How it was checked".

## 2. Open the PR

Start `pr-manager` (`subagent_type: "pr-manager"`) with: mode **open**, the branch, draft, and a scratchpad
path for the body (`<scratchpad>/pr-<branch>.md`).

- **blocked** (duplicate, not pushed): report it and stop. An existing PR for the branch
  goes straight to step 3 with its number.
- Otherwise note the PR link and the title for the report.

## 3. Check rounds

A round is: start `pr-manager` with mode **check**, the PR number, and what the last round did (each finding fixed
with its commit SHA, or not changed with the reason). It answers those threads, records the head SHA, waits once for
the checks (CodeRabbit, SonarCloud) and reports `clean`, `needs fixes`, `again` or `blocked`.

- **Commits not from the skill** (CodeRabbit can push autofix commits): note `HEAD`, pull them (`git pull --ff-only`),
  read them, and review them as committed changes: `coderabbit review --agent --committed --base-commit <noted HEAD>`
  and the `ponytail:ponytail-review` skill on `git diff <noted HEAD>..HEAD`, plus the local checks. Keep, fix or
  revert with a new commit (through `git-commit`).
- **needs fixes** → start `python-devops` with every real item: failing checks that are ours, every finding with
  verdict "real defect" (major or minor), and conflicting files. It fixes each narrowly, adds a test for a bug, runs
  the local checks, and does **not** commit or push. For conflicts it merges `origin/main` (no rebase, no
  force-push) and reads the merged code. A finding judged "not a defect", "already fixed" or "pre-existing" gets a
  reply with the reason; decide "unsure" ones yourself and say why in the reply. Then review its diff (`git diff`),
  run the `git-commit` skill (the review loop, local checks, commit, push), and start the next round.
- **again** (head moved, or a review is still pending) → start the next round without a fix. It does not count
  toward the round limit; three `again` in a row is a guard.
- **blocked** → report the reason and stop (rate limit, rule 17).

## 4. The process, draft then ready

1. Open the PR as a draft (step 2).
2. Run check rounds (step 3) until one is `clean` on the current head.
3. Mark it ready, if it is still a draft: `gh pr ready <N> --repo bd78/py-md-view`. Marking it ready makes
   CodeRabbit review again.
4. Run check rounds again until one is `clean` on the current head. `pr-manager` counts only a review that started
   after the PR's latest ready-for-review event.
5. Merge (step 5).

**Stacked PRs** (base is another PR's branch): after the base changes, merge it into the stacked branch, check the
merged code as above, and push. Never merge a stacked PR itself: only a PR whose base is `main`.

**Guards** (stop and report when one trips):

- The same check or finding is still there after two different fixes (house rule 17).
- More than 5 fix rounds in total, or three `again` rounds in a row.
- A failure that also happens on `main`: not ours. Report it and leave it.
- A finding asks for a scope change, a CI or repository-settings change, a dependency outside the licence allowlist,
  or anything on house rule 10's list.

## 5. Merge

Only after a `clean` round on a ready PR. Read the base
(`gh pr view <N> --repo bd78/py-md-view --json baseRefName -q .baseRefName`); merge only when it is `main`. Merge
exactly the head that round checked:

```
gh pr merge <N> --repo bd78/py-md-view --merge --admin --match-head-commit <checked SHA>
```

If the head moved, run another round first. Then `git checkout main && git pull --ff-only origin main`, refresh the
graph (`/graphify . --update`), and report: the PR link, the merge SHA, the rounds run and what each fixed (commit
SHAs), what was answered without a change, and any check that failed and why it was not this PR's.

Never approve a PR, and never close one without the person's say-so.
