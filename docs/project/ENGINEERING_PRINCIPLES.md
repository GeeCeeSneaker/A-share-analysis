# Engineering Principles

This file defines project-wide engineering principles. These rules apply to architecture, implementation, testing, data validation, automation, and future agent/Codex work.

## 1. Minimal solution first

The default choice is the **smallest design that satisfies the business purpose, correctness requirements, and basic operational safety**.

Do not add a module, abstraction, wrapper, state machine, receipt layer, hash/fingerprint, version field, policy engine, gate, or test merely because it can make the system more defensive. Every persistent mechanism must prevent a concrete failure that matters to this project and must be simpler than the failure it prevents.

Prefer, in this order:

1. an explicit project convention or documented rule;
2. a clear function/module boundary;
3. a small validation check at the real system boundary;
4. a new abstraction or safety mechanism only when the first three are insufficient.

A controlled internal caller is not treated as a hostile actor by default. Misuse by the Owner, maintainer, Codex, or project agents should normally be handled through APIs, naming, documentation, review, and tests—not through anti-forgery machinery inside ordinary Python objects.

## 2. Protect real risks, not hypothetical ones

Code-level safeguards are justified when they protect one of these concrete risks:

- credentials, secrets, private endpoints, or proprietary runtime material leaking;
- a request silently using the wrong date, universe, security, account, or environment;
- malformed, partial, missing, or out-of-scope provider data being promoted to complete data;
- point-in-time or temporal semantics being violated in a way that can contaminate research;
- durable artifacts being corrupted, partially published, or overwritten inconsistently;
- an irreversible or externally visible action executing with the wrong scope;
- a reproducibility-critical artifact no longer being traceable to its source inputs.

Do **not** build additional safety layers merely to prove that an Owner-approved source is trustworthy, to prevent an authorized in-process developer from constructing an internal object, or to defend against speculative future multi-source conflicts that do not yet exist.

## 3. One concern, one enforcement layer

Each invariant should have one primary enforcement point.

Avoid validating the same request identity, schema, hash, scope, and semantics independently in several nested objects. If raw persistence already verifies content integrity, higher layers should reference that result rather than recreate a parallel integrity protocol.

Avoid multiple wrappers around the same facts. Prefer one durable monthly acquisition result over chains such as `capture -> receipt -> sidecar -> adapter -> descriptor` unless each layer has an independent consumer and a distinct responsibility that cannot be expressed more simply.

## 4. No abstraction before demonstrated reuse

Do not generalize a one-off verification or remediation into a reusable framework unless a second real use case exists.

SPIKE/probe code is disposable by default. Once a probe answers its question:

- move the accepted rule into the production path;
- keep only the evidence necessary for the current contract;
- delete or archive obsolete probe code and probe-specific tests;
- rely on Git history, PR discussion, and issue records for superseded intermediate experiments.

Exploratory code must not become permanent architecture merely because it was useful during investigation.

## 5. Tests protect behavior, not implementation ceremony

Tests should focus on failures with meaningful consequences.

Keep tests for:

- core business/data semantics;
- request scope and identity at external boundaries;
- malformed/partial data fail-closed behavior;
- persistence/replay of a durable artifact;
- publication atomicity/idempotency where applicable;
- previously observed regressions that could recur.

Prefer deleting tests that only prove internal construction restrictions, duplicate serialization validators, private provenance markers, implementation-specific wrappers, or superseded SPIKE behavior when those mechanisms are removed.

A refactor should not preserve tests whose only purpose is to force retention of unnecessary architecture.

## 6. Version only durable contracts

Version a format or semantic rule when persisted artifacts may outlive the code that created them and replay compatibility matters.

Do not create separate version dimensions for every helper, fallback, wrapper, or internal type when one parent contract version is enough. Prefer one schema version plus one business-semantic version where that distinction is genuinely required.

## 7. Evidence should be sufficient, not maximal

For data acquisition, the minimum durable evidence normally consists of:

- source/provider identity chosen by Owner policy;
- exact request scope and parameters;
- retrieval time / required PIT metadata;
- raw artifact location plus integrity hash where replay matters;
- completeness-rule version;
- final completeness result and the small set of counts/hashes needed to reproduce or diagnose it.

Do not hash every intermediate subset or duplicate the same facts across several nested records without a concrete consumer.

## 8. Simplicity is an acceptance criterion

Every design/review must ask:

- Can this requirement be satisfied by convention instead of code?
- Can an existing module own this responsibility?
- Can a type/class be replaced by a plain function or data structure?
- Are we validating the same fact in more than one layer?
- Will this test still be valuable if the implementation is simplified?
- Does this change delete obsolete experimental code?

For refactoring work whose purpose is simplification, **net code/test deletion is expected**. A simplification task that adds a new framework without removing more complexity is not complete.

## 9. Project-specific trust rule

Data-source trust is an Owner governance decision. AmazingData is currently Owner-approved.

The system verifies that approved-source data was requested with the correct scope and semantics and was processed/persisted correctly. It does not attempt to cryptographically prove provider trust. If multiple Owner-approved sources later produce an actual material conflict, reconciliation will be designed for that observed conflict only.
