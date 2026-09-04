# Security Policy

## Do not disclose secrets publicly

Do not open a public issue or pull request containing credentials, tokens, private keys, full provider account identifiers, `.env` contents, production connection details, or proprietary provider material that is not licensed for redistribution.

If you discover an exposed credential, treat it as compromised and notify the repository owner through a private channel. The credential must be rotated; removing it in a later commit is not sufficient because public Git history may retain it.

## Supported security scope

Security reports are especially important for:

- credential or token exposure;
- bypass of protected-branch / merge controls;
- GitHub Actions workflow injection or privilege escalation;
- ability for untrusted code to access secrets;
- Raw Evidence / trust-anchor tampering or provenance bypass;
- capability-approval bypass that could promote unverified provider data to production truth;
- path traversal, arbitrary file overwrite, or unsafe deserialization in data ingestion/replay paths.

## Public contribution boundary

Security fixes follow the same protected-main process as other changes. Do not bypass review or CI except for a documented emergency response authorized by the repository owner.
