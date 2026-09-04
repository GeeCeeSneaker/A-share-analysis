# Contributing to A-share-analysis

This repository is public for transparency and collaboration, but `main` is a governed branch.

## Contribution model

### Authorized project developers

- May create and push project branches in this repository when they have GitHub Write permission.
- Must not push directly to `main`.
- Merge to `main` only through a pull request that satisfies protected-branch/ruleset requirements and CI.
- Changes to CODEOWNERS-controlled paths also require the designated Code Owner approval.

### External contributors

- Do not receive direct repository Write permission by virtue of the repository being public.
- Contribute by forking the repository and opening a pull request.
- External pull requests must be reviewed and approved by at least one authorized repository member with Write permission before merge.
- Changes to CODEOWNERS-controlled paths additionally require Code Owner approval.
- Maintainers may request design discussion before accepting changes that alter architecture, data semantics, migration contracts, governance, or provider truth.

## Pull request requirements

A mergeable pull request must:

1. target `main` from a non-`main` branch;
2. pass the repository's required CI status checks;
3. receive the required internal approval(s);
4. have all review conversations resolved;
5. receive fresh approval after review-invalidating changes when the repository rules require it;
6. satisfy project-specific DEVLOG / DEVELOPMENT_MANAGEMENT / ADR rules where applicable;
7. contain no credentials, tokens, account identifiers, private provider material, or other secrets.

## Security and credentials

Never commit or paste into public issues/PRs:

- passwords or access tokens;
- `.env` contents;
- real provider credentials or full account numbers;
- private SDK entitlement material that is not licensed for redistribution;
- private keys or signing material.

Provider identities committed for governance must be scrubbed stable identities only, as defined by the project contracts.

## Review authority

A public GitHub review from an unaffiliated user is useful feedback but does not constitute project approval. Required merge approval must come from an authorized repository member with the permissions required by the protected-branch/ruleset configuration.
