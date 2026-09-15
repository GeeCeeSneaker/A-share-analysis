# Contributing to A-share-analysis

This repository is public, but project write/merge authority is intentionally centralized.

## Authorized project identity

The current and only authorized project developer / maintainer identity is:

```text
@GeeCeeSneaker
```

That account continues to use the repository in the same way as before for normal project development, review commits, branches, pull requests, and merges.

No other GitHub user should be granted Write / Maintain / Admin permission unless the project owner explicitly changes this policy in the future.

## Core engineering principle: minimal solution first

All project development must follow [`docs/project/ENGINEERING_PRINCIPLES.md`](docs/project/ENGINEERING_PRINCIPLES.md).

The default is the **smallest design that satisfies the functional purpose, correctness requirements, and basic operational safety**. If a requirement can be enforced adequately through a documented convention, clear module boundary, code review, or a small boundary validation, do not add a new framework, anti-forgery mechanism, policy layer, wrapper type, version dimension, hash/fingerprint, or test suite for it.

In particular:

- Owner-approved internal developers/agents are not treated as hostile in-process callers by default;
- data-source trust is an Owner decision, not something code must cryptographically prove;
- one invariant should have one primary enforcement layer rather than several nested re-validations;
- exploratory SPIKE/probe code is disposable and should be removed after its conclusion is incorporated;
- tests protect meaningful behavior and real regressions, not unnecessary implementation ceremony;
- simplification refactors are expected to remove more code/test surface than they add.

A proposed abstraction or safety mechanism must identify the concrete project failure it prevents and why a simpler convention or existing boundary is insufficient.

## Repository operation principle: local Git first

For Codex, agents, automation, and normal maintainer work, the local clone / worktree is the **primary repository operation path and day-to-day code source of truth**.

- Prefer local `git` for repository reads, diff inspection, branch/worktree management, commits, history inspection, `fetch`, `pull`/rebase where appropriate, `push`, and exact-SHA verification.
- GitHub Connector / API is a **secondary and fallback path**. Use it when local Git access is unavailable or degraded, or for API-native operations such as PR/Issue metadata, review comments, and Actions/CI status that are not naturally represented by local Git.
- Do not use Connector availability as a reason to bypass a healthy local repository workflow or to treat Connector-returned repository content as more authoritative than the checked and synchronized Git refs.
- Before any remote write, review acceptance, or merge, reconcile the relevant local and remote refs and pin the exact base/head SHA. If local Git and Connector/API views disagree, **BLOCK the write/merge until the discrepancy is explained and the refs are synchronized**.
- A Connector outage or local-network problem does not by itself justify direct changes to `main`; normal branch, commit, review, and merge discipline remains in force unless the project owner explicitly authorizes an exception.
- When Connector fallback is used for a repository-content action, record or verify the resulting commit SHA and reconcile it back into the local Git view as soon as local access is restored.

The intent is reliability and recoverability: ordinary repository state should remain inspectable and reproducible with standard Git even when an external connector is slow, unavailable, or inconsistent.

## External contributors

Public users may:

- read and clone the repository;
- fork it;
- open issues and discussions where enabled;
- submit pull requests from forks;
- comment on public pull requests.

Public users may **not**:

- push directly to this repository;
- modify `main` or project branches;
- merge pull requests;
- change repository settings, Actions, rules, secrets, or collaborators;
- treat an external review/approval as project authorization.

Every external pull request is untrusted until reviewed by `@GeeCeeSneaker`. The owner may merge, request changes, or close it.

## CI and security

External pull requests must never receive production credentials, provider secrets, tokens, private keys, `.env` content, or proprietary SDK material. Public CI must remain credential-free and must not install or use the production AmazingData account.

Changes to `.github/workflows/`, production-account governance, migrations, trading rules, golden data, ADRs, or other correctness contracts require explicit owner review.

## Future change in developer model

If additional developer GitHub identities are introduced later, this document and repository protection rules must be updated deliberately before granting them write access. Until then, `@GeeCeeSneaker` is the complete authorized-writer allowlist.
