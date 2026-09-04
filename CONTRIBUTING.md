# Contributing to A-share-analysis

This repository is public, but project write/merge authority is intentionally centralized.

## Authorized project identity

The current and only authorized project developer / maintainer identity is:

```text
@GeeCeeSneaker
```

That account continues to use the repository in the same way as before for normal project development, review commits, branches, pull requests, and merges.

No other GitHub user should be granted Write / Maintain / Admin permission unless the project owner explicitly changes this policy in the future.

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
