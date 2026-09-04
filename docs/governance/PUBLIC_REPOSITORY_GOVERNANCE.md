# Public Repository Governance and Merge Protection

> Effective target: `GeeCeeSneaker/A-share-analysis`
> Repository visibility: PUBLIC
> Governance objective: public read/fork/PR participation without granting unaffiliated users authority to modify governed repository state.

## 1. Threat / permission model

Making the repository public grants read/fork access; it does **not** grant Write permission to outside users.

The required operating model is:

```text
Public user
  -> read / fork / open PR / comment
  -> NO direct repository push authority

Authorized project developer (GitHub Write)
  -> push feature/review branches
  -> NO direct push to main
  -> merge through protected PR flow

Repository Owner/Admin
  -> manages collaborators, rulesets, security settings
  -> should not bypass main protection during normal work
```

`main` is the authoritative integration branch and must be protected at the GitHub platform level. Repository documentation and CI are additional defenses; they are not substitutes for a ruleset/branch protection rule.

## 2. Required GitHub platform configuration — P0

At the time this document was created, `main` was reported by GitHub as `protected=false`, and the repository had no repository rulesets. This is an unsafe public-repository state and must be corrected in GitHub Settings.

### 2.1 Main branch ruleset

Preferred configuration: **Settings -> Rules -> Rulesets -> New branch ruleset**.

Create an ACTIVE ruleset named:

```text
protect-main
```

Target:

```text
refs/heads/main
```

Required rules:

1. Require a pull request before merging.
2. Required approvals: **1 minimum**.
   - A required approval must come from a user whose repository permission satisfies GitHub's protected-branch review rule (project collaborator / authorized reviewer).
3. Require review from Code Owners.
4. Dismiss stale approvals when new reviewable commits are pushed.
5. Require approval of the most recent reviewable push by someone other than the pusher when available in the repository UI.
6. Require all review conversations to be resolved.
7. Require status checks before merging.
8. Require the branch to be up to date before merging unless an explicit project exception is documented.
9. Block force pushes.
10. Block branch deletion.
11. Do not grant broad bypass permission to Write/Maintain users.
12. Normal repository administrators must follow the PR flow; any emergency bypass must be rare, documented in DEVLOG, and followed by retrospective review.

Required status check for the current workflow:

```text
Lint & Type Check (windows-latest / py3.14)
```

This is the project's reference production-runtime matrix leg. Other matrix legs continue to provide compatibility/cross-platform evidence and should remain green under project review policy even if they are not the platform-required check.

### 2.2 Classic branch protection fallback

If a ruleset is not used, create a classic protection rule for `main` with equivalent settings:

- Require a pull request before merging;
- require 1 approval;
- dismiss stale approvals;
- require Code Owner review;
- require the latest push to be reviewed by another person where supported;
- require status checks and up-to-date branch;
- require conversation resolution;
- do not allow force pushes;
- do not allow deletion;
- enable the option that prevents administrators from bypassing the protections during normal operation.

Use **one authoritative protection mechanism** with clearly understood behavior; do not create conflicting overlapping rules accidentally.

## 3. Collaborator permissions

### 3.1 Authorized developers

Normal project developers should receive **Write** permission, not Admin.

Write permission is sufficient to:

- create project branches;
- push commits to project branches;
- open and review pull requests;
- merge pull requests when all protected-main requirements are satisfied.

Admin access should be limited to the repository owner and explicitly designated maintainers who need to manage repository settings/rules.

### 3.2 External users

Do not add outside contributors as Write collaborators merely to accept a contribution.

External contribution path:

```text
fork -> branch -> pull request -> internal review -> CI -> merge/reject
```

A public review/approval from an unaffiliated user is feedback only. The protected-main required approval must be satisfied by an authorized reviewer under GitHub's permission rules.

### 3.3 If repository ownership later moves to an Organization

Use organization teams such as:

```text
@org/a-share-developers   -> Write
@org/a-share-maintainers  -> Maintain/Admin as needed
```

Then additionally enable branch push restrictions / ruleset bypass lists so only the developer/maintainer team and required GitHub Apps can update governed branches. Do not use an 'all members' team as a bypass actor.

## 4. CODEOWNERS policy

`.github/CODEOWNERS` protects security/governance-critical paths with explicit Owner review.

Current owner-controlled paths include:

```text
.github/
configs/production_account.yaml
configs/trading_rules/
data/golden/
migrations/
docs/adr/
docs/project/DEVELOPMENT_MANAGEMENT.md
```

Purpose:

- external contributors cannot change CI/governance contracts without Owner review;
- ordinary internal code changes can still be reviewed by authorized developers;
- CODEOWNERS itself is protected by ownership of `/.github/`.

Do not add `* @GeeCeeSneaker` unless the intended policy becomes 'Owner must personally approve every PR'. The current policy is deliberately less centralized: every PR needs internal approval, while sensitive paths additionally need Owner approval.

## 5. GitHub Actions protection — P0

Public repositories must treat fork PR workflow execution as untrusted input.

Configure **Settings -> Actions -> General** so that fork PR workflows from outside contributors require maintainer approval. Preferred policy:

```text
Require approval for all external contributors
```

Operational rules:

1. Never send repository secrets to fork pull-request workflows.
2. Keep `GITHUB_TOKEN` read-only unless a specific job proves write access is necessary.
3. Do not introduce `pull_request_target` for arbitrary external code execution without a separate security review.
4. Changes under `.github/workflows/` require CODEOWNER approval.
5. Review workflow changes before approving an external contributor's workflow run.
6. Do not install the proprietary AmazingData SDK or production credentials in public CI.

The current CI already intentionally runs without AmazingData SDK and without production credentials; preserve that boundary.

## 6. Public review moderation

Recommended repository setting:

```text
Settings -> Moderation options -> Code review limits
-> Limit to users explicitly granted read or higher access
```

This keeps public comments open while preventing arbitrary accounts from presenting an `Approve` / `Request changes` review as if it were project authority.

This setting is supplemental: required protected-branch approvals still need to be configured independently.

## 7. Secret / proprietary material protection — P0

Because the repository is public, enforce the following immediately:

- `.env` and real credentials remain gitignored;
- no passwords, Tokens, full provider account numbers, private keys, or production hosts in commits/issues/PR bodies;
- only scrubbed production account profile identity may be committed;
- enable GitHub Secret Scanning / Push Protection when available for the repository;
- if a real secret is ever committed, rotation is mandatory — deleting the later file does not make the public Git history safe;
- proprietary provider SDK binaries/manuals must only be committed if redistribution rights explicitly allow it.

## 8. Merge authority matrix

| Change source | Can push project branch? | Can push `main` directly? | Internal approval required? | CODEOWNER required? |
|---|---:|---:|---:|---:|
| Repository Owner/Admin | Yes | No during normal work | Yes under main rules | Yes for owned paths |
| Authorized developer (Write) | Yes | No | Yes | Yes for owned paths |
| External contributor | No (fork only) | No | Yes | Yes for owned paths |
| GitHub App / automation | Only as explicitly granted | No unless explicitly governed | Governed by ruleset/check design | As configured |

## 9. Merge checklist

Before merging any PR to `main`:

```text
[ ] PR is based on current main or satisfies up-to-date requirement
[ ] required Windows Python 3.14 CI check passed
[ ] project-required broader CI evidence is green
[ ] at least one authorized internal approval exists
[ ] CODEOWNER approval exists when applicable
[ ] stale approval was invalidated/reapproved after new commits
[ ] all conversations resolved
[ ] no secret/proprietary material exposure
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR requirements satisfied
[ ] no force-push/history rewrite used
```

## 10. Configuration verification

After the GitHub UI settings are applied, Reviewer must re-check:

```text
GET /branches/main
  protected == true

GET /rulesets
  contains active protect-main ruleset
```

and inspect a test PR to confirm:

1. direct push to `main` is rejected;
2. PR without approval cannot merge;
3. PR with failing required CI cannot merge;
4. stale approval is invalidated after new commit;
5. CODEOWNERS path change requests Owner review;
6. external fork PR cannot merge without internal approval;
7. external workflow run follows the configured approval policy.

Only after these checks should the public-repository protection milestone be marked VERIFIED / CLOSED.
