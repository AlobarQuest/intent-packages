# ADR-0001: The approval chain, not git ancestry, is the audit trail

- **Status:** Accepted
- **Date:** 2026-09-28
- **Decided by:** Devon (Tier 3 item 30, 2026-09-28)

## Context

When a revision is approved, the CLI reads the commit at `HEAD` and `do_approve` records it. It writes that
sha into the package's `lineage.yaml` approval entry and into the `package.approved` event's
payload. Pull requests into this repository are squash-merged. Squashing rewrites a branch
into one new commit on `main`, so a commit that was `HEAD` on the branch never becomes an
ancestor of `main`.

On 2026-09-28, 5 of the 52 recorded approval commits were not ancestors of `main`:
`conformance-claim-helper` r1 (`8b5c929e`), `ws-p2.15-fail-closed-lifecycle-guards` r1
(`d978e516`), and revision 1 of the three standing `infraops-mcp-server-npm-*` packages
(`95f6e58c`, `de38100e`, `ee56a4c2`). The question was whether that breaks the audit trail,
and whether this repository should stop squash-merging so that it does not happen.

## Decision

**The approval chain is the audit trail. Squash-merge stays.**

An approval is proven by two things, and `verify_approval` checks both:

1. **The ledger.** `lineage.yaml` holds an approval entry whose `approved_hash` equals the
   hash of the package as it stands now, from a recognised approver.
2. **The chain.** The tamper-evident factory-events chain holds a `package.approved` event
   for that exact hash and revision, and the chain verifies.

Neither check reads git. The recorded `commit` is provenance: it says where the approver was
standing. `verify_approval` does not read it, and nothing else may treat it as proof. An
approval commit that is not an ancestor of `main` is therefore not a defect.

## Why not merge commits

- **The chain already proves more than ancestry could.** Ancestry would show that a commit
  exists on `main`. It would not show that the commit's package hash was approved, by whom,
  or that nobody edited the ledger afterwards. The chain shows all three, and a forged ledger
  entry fails it because only `do_approve` emits the event it looks for.
- **Squash is the estate's merge method.** The factory repositories squash-merge in practice,
  and the orchestrator's landing lanes call the merge API with the squash method. A different
  method in this one repository would be a special case, and it would prove nothing more.
- **The commit field keeps its value.** It still says what tree the approver saw. Where the
  object is still on GitHub (a squashed pull request's branch commits usually are), it can be
  read. It is just not the thing that proves the approval.

## Consequences

- Do not write a check that fails because an approval `commit` is not an ancestor of `main`.
  That would be keyed on git history, which squash-merging rewrites by design.
- To answer "was this revision approved?", run
  `PYTHONPATH=src python3 -m intent_packages verify-approval <path>`. Do not reason about git
  history.
- The factory-events chain of record is the Postgres database (orchestrator ADR-0055
  amendment 24), and it is the record that must be preserved and backed up. A lost chain cannot
  be rebuilt from git. `verify-approval` reads it under `FACTORY_EVENTS_READ_PASSWORD`, walking
  the chain and matching the approval in one read-only snapshot, and fails closed on any database
  error. Without the read password it fails closed too: it never reads a file. The emitter
  appends under `FACTORY_EVENTS_APPEND_PASSWORD`. Each password connects with the non-secret
  `FACTORY_EVENTS_DB_HOST`, `FACTORY_EVENTS_DB_PORT` and `FACTORY_EVENTS_DB_NAME` settings; the
  whole-DSN variables these replaced refuse by name (amendment 26). The sealed
  `~/.factory/events.sealed.jsonl` is the chain's pre-cut-over copy, imported at the FE-5
  cut-over; it is history, and nothing reads it as proof.
