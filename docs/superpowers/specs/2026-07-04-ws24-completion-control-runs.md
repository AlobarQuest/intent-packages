# WS-2.4 Completion Control Runs

**Date:** 2026-07-04  
**Status:** Approved direction; execution packages start in Draft  
**Owner:** Devon

## Purpose

Close WS-2.4 without rewriting the historical result of the original software
pilot. Completion requires two new control runs:

1. a small software-delivery package whose literal CI acceptance criteria pass;
2. a non-software, offline listing-launch replay for the inactive historical
   property at 831 Riverwood Drive, Monroe, Georgia.

The original `ws-2.4-brain-approver-gate` package remains historical evidence.
Its AC-003 did not pass on its PR. Later foundation CI remediation removes the
underlying debt but does not retroactively change that result.

## Control run A: CI acceptance semantics

### Change

Add an operator-facing document to `intent-packages` defining how CI evidence is
adjudicated:

- only check results for the exact PR revision under verification count;
- every workflow named by an AC must conclude successfully;
- a non-gating check is not equivalent to a passing check;
- historical failures remain historical;
- later successful runs on another revision do not repair an earlier AC;
- an unmet AC blocks completion until the deliverable is corrected or the
  package is formally revised and reapproved;
- no silent waiver is permitted while the package format has no waiver record.

### Why this is real work

This is the durable operator rule missing during the original AC-003 decision.
It belongs in `intent-packages`, which owns intent acceptance semantics. The
change has no production runtime effect but traverses a real branch, PR, two CI
workflows, human merge approval, and the complete package lifecycle.

### Required checks

- `Quality / Lint, type-check, and test`
- `validate / validate`

Both must pass on the exact PR head revision before the package may leave
verification.

## Control run B: historical listing launch

### Candidate

- Address: 831 Riverwood Drive, Monroe, GA 30655
- Historical status: sold May 29, 2026
- Photo source:
  `/Users/devon/Downloads/831_riverwood_drive_lg_1777727659`
- Available photographs: 25
- Positioning: starter-family and empty-nester/recent-retiree audiences
- Renovation claims: prohibited; no `renovated`, `updated`, `remodeled`, or
  `refreshed` claims

### Isolation boundary

The replay produces local, reviewable documents only. It must not:

- modify `listing-prep`;
- write to MLS, Zillow, FUB, Calendar, n8n, or another external system;
- contact a client, vendor, or other third party;
- send email or text messages;
- spend money;
- delete data;
- read or write secrets;
- present the property as currently available.

### Outputs

- source and fact manifest;
- photo inventory and review;
- MLS headline and public remarks of at most 1,000 characters;
- extended listing/flyer copy;
- social copy;
- publication checklist;
- acceptance-criterion evidence index;
- cross-artifact consistency review;
- Devon approval record.

### Evidence handling

The current CLI has no command or lineage field for attaching realized evidence
to an AC. The pilot therefore records evidence in a separate index keyed by AC
ID. This is an explicitly temporary projection and does not close the Phase-3
evidence-storage gap.

### Failure handling

- Missing required facts or photographs: `blocked`.
- Requested external publication or production write: `not authorized`.
- Correctable deliverable defect: remain in execution and correct it.
- Material contract change: revise or supersede, then obtain fresh approval.
- Unmet AC: do not transition to completed.

## Lifecycle discipline

Each package follows:

```text
draft → ready_for_review → approved → executable → in_execution
      → verification → completed → closed
```

Transitions occur when the real work reaches each state. Approval binds the
exact pre-execution revision. No deliverable work starts before approval.

## Exit audit

After both control runs close:

1. validate every package;
2. verify both approvals;
3. reconcile every AC against realized evidence;
4. update the WS-2.4 friction notes;
5. update the Phase 2 exit checklist without erasing the original deviation;
6. run an independent adversarial review of all twelve Phase 2 criteria;
7. declare Phase 2 complete only if criteria 11 and 12 withstand that review.

