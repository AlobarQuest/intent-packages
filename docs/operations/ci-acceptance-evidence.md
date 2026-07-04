# CI Acceptance Evidence

Use this rule whenever an intent-package acceptance criterion requires one or
more CI checks to pass.

## Pass rule

A CI-backed acceptance criterion passes only when every check named by the
criterion concludes successfully on the exact pull-request revision being
verified.

Record at least:

- pull-request URL;
- head commit SHA;
- required workflow and job names;
- conclusion for each named check;
- check-run URL or another stable provider reference.

Do not substitute a check from the base branch, an earlier commit, a later
commit, another pull request, or a rerun against different source content.

## Non-gating checks

Whether a repository configures a check as merge-blocking is separate from
whether an intent package requires that check to pass.

If an acceptance criterion names a non-gating check, that check must still
conclude successfully. “Non-gating” does not mean “passed,” “optional,” or
“safe to ignore.” If the check was not intended to be required, correct the
package through its revision and approval process before relying on different
evidence.

## Historical results

Historical failures remain failures for the revision on which they occurred.
A later remediation or successful run demonstrates the later state; it does
not retroactively satisfy an acceptance criterion attached to the earlier
revision.

Preserve the original result and record the remediation separately.

## Failed, missing, or ambiguous checks

Treat the acceptance criterion as unmet when a named check:

- fails;
- is cancelled;
- is skipped when the criterion requires execution;
- is missing;
- is still pending;
- ran against a different revision; or
- cannot be unambiguously matched to the criterion.

An unmet criterion blocks package completion. Correct the deliverable and
obtain valid evidence, or formally revise or supersede the package and obtain
fresh approval. The current package format has no structured waiver record, so
operators must not silently treat an unmet criterion as passed.

