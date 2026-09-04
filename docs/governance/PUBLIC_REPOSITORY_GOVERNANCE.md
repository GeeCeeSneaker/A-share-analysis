# Public Repository Governance — Single Authorized Writer

> Repository: `GeeCeeSneaker/A-share-analysis`  
> Visibility: PUBLIC  
> Authorized project developer / maintainer: **`@GeeCeeSneaker` only**

## 1. Operating principle

The repository is public for reading, cloning, forking, and receiving external pull requests. Public visibility does **not** grant write authority.

The current project model is intentionally simple:

```text
@GeeCeeSneaker
  = project owner
  = only authorized developer
  = only authorized repository writer / merger
  = keeps the existing development workflow

Everyone else
  = external contributor
  = read / fork / issue / PR only
  = no direct push
  = no merge authority
  = no repository-setting authority
```

Do not introduce developer teams, additional maintainers, or multi-reviewer workflow while the project still uses one authorized GitHub identity.

## 2. Repository permission policy — P0

The collaborator allowlist for Write / Maintain / Admin must contain no project-development identity other than `@GeeCeeSneaker`.

Rules:

1. Do not grant Write / Maintain / Admin to outside contributors merely to accept a contribution.
2. External contributors work through forks and pull requests.
3. External approvals/reviews are feedback only; they never constitute project approval.
4. Only `@GeeCeeSneaker` may merge an external PR.
5. If another developer identity is needed in the future, update this governance contract first and then grant permission deliberately.

This is the primary protection boundary. A random public GitHub user cannot push to this repository without being explicitly added as a collaborator.

## 3. `main` protection — simple owner-bypass model

At the time this policy was introduced, GitHub reported:

```text
main.protected = false
repository rulesets = []
```

Because `@GeeCeeSneaker` is also the active developer and the project has historically used that account for direct reviewer/governance commits, protection must **not** break the existing owner workflow.

Preferred GitHub configuration:

### Ruleset

Create an ACTIVE branch ruleset targeting:

```text
refs/heads/main
```

Suggested name:

```text
protect-main-external
```

Configure the ruleset so that:

- force pushes are blocked;
- deletion of `main` is blocked;
- non-authorized actors cannot update `main`;
- normal external contribution reaches `main` only through a PR reviewed/merged by `@GeeCeeSneaker`;
- required CI remains enforced for PR merges where applicable;
- **repository Owner/Admin (`@GeeCeeSneaker`) is the explicit bypass actor**, so the existing project development/reviewer workflow can continue without mandatory self-approval or a second account.

Do **not** configure a rule that requires a second-person approval for every owner-authored PR: the project currently has no second authorized developer, so such a rule would only create fake process or deadlock normal development.

If GitHub UI makes a PR-review rule awkward for a single-owner personal repository, it is acceptable to rely on the stronger simple boundary:

```text
only @GeeCeeSneaker has repository write/admin permission
+ main force-push/delete blocked
+ external contributors have fork/PR only
+ owner alone decides merge
```

The objective is security, not ceremony.

## 4. CODEOWNERS

The repository uses a deliberately simple global ownership rule:

```text
* @GeeCeeSneaker
```

Meaning:

- every external pull request has a single authoritative owner;
- external users cannot establish approval authority by reviewing one another;
- there is no need to maintain a complex path-by-path ownership matrix while the project has only one developer identity.

## 5. External pull requests

External contribution path:

```text
fork
  -> branch
  -> PR
  -> inspect diff / CI / security impact
  -> @GeeCeeSneaker decides
       -> merge
       -> request changes
       -> close
```

External PRs are untrusted input. In particular, changes to the following require careful owner review before any workflow execution or merge:

```text
.github/workflows/
configs/
scripts/
migrations/
data/golden/
docs/adr/
provider / raw / canonical / feature / state correctness code
```

No external contributor should ever be added as a collaborator simply to make their PR easier to merge.

## 6. GitHub Actions for public forks

Configure **Settings -> Actions -> General** so external fork PR workflows require owner approval before execution when GitHub exposes that option.

Preferred setting:

```text
Require approval for all external contributors
```

Public/fork CI rules:

- no production credentials;
- no `.env` secrets;
- no AmazingData production account;
- no proprietary SDK binaries unless redistribution is explicitly allowed;
- avoid `pull_request_target` executing untrusted fork code;
- changes to workflow files are manually reviewed by `@GeeCeeSneaker` before approval.

The existing CI design — no AmazingData SDK and no production credentials — must remain frozen unless separately reviewed.

## 7. Secret protection — P0

Because the repository is public:

- enable GitHub Secret Scanning / Push Protection when available;
- never commit passwords, tokens, `.env`, private keys, full provider account data, or production credentials;
- only scrubbed production-account identity may enter Git;
- if a real secret is ever committed, rotate it immediately; deleting a later file does not remove exposure from public Git history.

## 8. Account security

Because one GitHub identity now carries all project write authority, protection of `@GeeCeeSneaker` is more important than adding procedural reviewers.

Strongly recommended:

- GitHub 2FA enabled;
- preferably passkey / hardware security key;
- review active sessions and authorized OAuth/GitHub Apps periodically;
- do not share the GitHub account password;
- use scoped tokens and revoke unused tokens;
- do not place personal access tokens in repository files or CI logs.

## 9. Effective authority matrix

| Actor | Read/fork | Submit PR | Push repository | Merge | Change settings |
|---|---:|---:|---:|---:|---:|
| `@GeeCeeSneaker` | Yes | Yes | Yes | Yes | Yes |
| Any other GitHub user | Yes | Yes | **No** | **No** | **No** |
| External GitHub App | As granted | As granted | **No unless owner explicitly grants it** | No by default | No by default |

## 10. Verification checklist

After GitHub Settings are applied, verify:

```text
[ ] repository remains public
[ ] @GeeCeeSneaker is the only intended write/admin developer identity
[ ] no unknown collaborator has Write/Maintain/Admin
[ ] main cannot be force-pushed
[ ] main cannot be deleted
[ ] external user cannot directly push repository branches
[ ] external PR cannot merge without @GeeCeeSneaker action
[ ] external fork Actions require owner approval when configured
[ ] public CI has no production credentials / AmazingData SDK
[ ] CODEOWNERS is `* @GeeCeeSneaker`
[ ] secret scanning / push protection enabled when available
```

## 11. Future expansion rule

If development later moves to multiple GitHub accounts, do **not** gradually add collaborators ad hoc. First revise this policy to define the new authorized-developer allowlist, branch protection, review requirements, and CODEOWNERS model; then grant permissions.

Until that explicit change, the authoritative rule is:

> **Only `@GeeCeeSneaker` may modify or merge the project repository. Everyone else is external and requires owner review.**
