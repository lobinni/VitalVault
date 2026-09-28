# VitalVault — Decision Record

This document records the design decisions that are not obvious from the code, and the reasoning
behind them. It exists so a reviewer can check the contract against its stated intent without
having to reverse-engineer that intent.

## The product

A self-sovereign inheritance vault: an owner deposits funds, names beneficiaries with basis-point
shares, and keeps the vault entirely theirs by periodically proving they're still around. A
missed heartbeat starts a fixed, generous grace window that a fresh check-in — or, optionally,
consensus-verified evidence of continued public activity — cancels outright. Only if the window
elapses with zero signal of life through any channel does the vault become releasable. A second,
orthogonal consensus round lets heirs demonstrate a genuine death from public evidence and
shorten the wait to a fixed minimum.

## Counterfactual: why not just a timelock

The simplest version of this idea needs no blockchain intelligence at all, and non-GenLayer
projects ship exactly that. The plain design fails silently in the single most common real
scenario of self-custody: the owner is alive, active, and publicly verifiable — but has lost or
forgotten the specific wallet the vault listens to. A timestamp comparison cannot distinguish
that from genuinely being gone. `run_vitality_scan` exists to close part of that gap: validators
independently look at public evidence that no on-chain state can contain, under the Equivalence
Principle, and cancel the trigger on the strength of it.

The second round, `run_death_evidence_review`, addresses the mirror-image scenario: the owner
*is* genuinely deceased, public reporting says so plainly, and yet a pure timelock makes heirs
wait the full grace window regardless. Consensus-verified evidence can shorten that wait — with
gating as strict in this direction as the vitality scan is in the other.

## Why the aggregation rules are asymmetric — in both directions

The two errors available to each round differ enormously in cost, and the contract's rules follow
the costs, not any abstract symmetry:

| Round | Cheap mistake | Expensive mistake | Aggregation rule that follows |
| --- | --- | --- | --- |
| Vitality scan | Staying in grace a while longer | Releasing a living person's savings | ANY active source cancels; `NO_VITALITY_DETECTED` needs every fetched source to agree; one `UNDETERMINED` forces `INCONCLUSIVE`. |
| Death-evidence review | Heirs waiting the standard 45 days | Shortening a window on a wrong/ambiguous report | Confirmation needs every fetched page to confirm the same anchor-named person with high confidence; anything less defeats the review entirely. |

The prompt tells the model to prefer `UNDETERMINED` over guessing, for both rounds — but the
actual gating lives in this contract's own code, never in the model's compliance with that
instruction.

## Why fetch-availability is enforced by code, not requested by prompt

A model that reports `ACTIVE_AFTER_CHECKIN` for a source it never actually examined is not a
hypothetical failure — untrusted page text can contain instruction-like sentences, and a renderer
can technically "succeed" against a wrong target. So the code-observed facts (registered? fetched?
why not?) are threaded through each round as plain data, computed by the leader from the URL
fields and the fetch outcome, and every per-source classification is gated by them: a source the
code never fetched is forced to `NOT_AVAILABLE` no matter what the model answered. The model
classifies; only this code decides what the classification is allowed to mean.

## Why fetch-target hardening is layered, and where each layer runs

- **Registration time (deterministic):** every URL is shape-checked in plain code before being
  stored or used — https-only, hostname-only, printable ASCII, no user-info, no explicit ports,
  and IP-literal hosts refused outright. This runs outside any consensus round, so every
  validator reaches the identical verdict from the input alone. (`run_death_evidence_review`
  re-validates submitted URLs the same way before spending a consensus round.)
- **Inside the round (non-deterministic):** caller-influenced hosts are re-resolved through
  DNS-over-HTTPS (`dns.google/resolve`, type A) and refused unless at least one A record exists
  and every returned address is public — blocking the private ranges, loopback, link-local/cloud
  metadata (169.254.169.254), CGNAT, benchmarking, multicast, and documentation ranges. Redirect
  statuses are refused: the evidence must come from the exact target named, not from wherever
  that target felt like sending us today.
- **Fixed hosts are treated differently on purpose:** the GitHub events API and x.com are derived
  from validated handles, so they skip the DNS re-check — spending caller-host hardening on hosts
  the caller never influenced buys nothing.

Residual known limitation, stated plainly: a *platform-level* redirect that the web primitives
follow internally (server-side) before this contract ever sees a 3xx status cannot be blocked by
status refusal. The untrusted-evidence prompt framing and per-source code gating are the
mitigations.

## Why the grace period is a fixed protocol constant

A generous, owner-shortenable window would let a misconfigured (or mis-instructed) vault release
quickly after a missed heartbeat, transferring the misuse cost onto heirs and owners who never
agreed to it. 45 days for everyone keeps the safety floor uniform. The heartbeat interval itself
*is* owner-configurable (bounded 14 days – ~3 years) because it costs nothing to anyone but the
owner: it only decides when the window *opens*.

## Why acceleration can only ever shorten, never extend

`run_death_evidence_review` computes `min(current_deadline, now + 7 days)`. If the remaining
window were already shorter than 7 days, extending it on the word of public reporting would delay
a rightful release on the strength of evidence the owner never agreed to be bound by. A review is
allowed to make things slightly faster for a clearly genuine case, never slower for anybody.

## Why `check_in()` always wins, unconditionally

A consensus round, however carefully aggregated, is still *inferring* life or death from indirect
public evidence. A check-in is *direct*: a signature from a key the owner controls — the strongest
proof available to any contract. Letting any stored verdict delay or compete with it would invert
the actual reliability ordering of the two signals. Accordingly, `check_in()` short-circuits to
ACTIVE unconditionally, clears the deadline and any recorded death confirmation, and its failure
mode is loud: on a RELEASED vault it raises a clear error rather than silently no-op'ing, because
a reappearing owner deserves the truth, not a misleading success.

## Why there is no admin, and why RELEASED is final

No vault parameter affects anyone but its own owner and heirs; there is no shared pool, no shared
cap, no cross-vault externality for an admin to guard. The same reasoning makes RELEASED final: an
override would require a third party to arbitrate between a reappearing owner and beneficiaries
who may have already spent their claims — centralized arbitration the whole design exists to
avoid. The entire protection budget is therefore front-loaded: bounded heartbeat, fixed generous
window, always-winning check-in, standby signer, and two optional consensus nets.

## Why keeper rewards come from the vault's own balance

There is no shared pool to pay keepers from, and inventing one would reintroduce exactly the
shared-surface problem this contract avoids. Trigger and finalize each pay a small fixed reward
from the vault's own balance, skipped silently when unaffordable so a broke vault can never
wedge. The incentive attaches to the vault being serviced, which is precisely the party that
benefits from timely transitions.

## The direct-VM testing strategy, and what it deliberately does not assert

The suite in `tests/direct` exercises the contract through gltest's direct-VM mode with mocked
web and LLM endpoints. Two boundaries are intentional:

- **Native payouts to wallets.** EOA payouts are external messages that settle at finalization on
  a live network; under direct-VM the emit is a boundary no-op. Tests therefore assert this
  contract's own accounting (balances, distributable snapshots, claim flags, dust sweeps) around
  the payout calls, and the payout mechanism itself is the documented external-message pattern
  (`@gl.evm.contract_interface` + `emit_transfer`). Internal state is always fully settled before
  the payout, so a reverted or reentrant payout can never corrupt the ledger.
- **Consensus verdicts.** `strict_eq` is used with a canonical, sort-keyed JSON return so the
  leader's output is byte-comparable; mocks pin the LLM's per-source classifications while the
  tests vary *what the aggregation code does with them* — including the hostile case where the
  model claims activity on a source the code itself blocked (private-DNS test).

## Corrections baked in from the pre-submission self-review

1. All state (status, balances, claim flags, deadlines) is written **before** any external
   transfer in `owner_withdraw`, `trigger_inheritance`, `finalize_inheritance`, and
   `claim_share` — checks-effects-interactions, so a reentrant receiver sees final values.
2. `check_in()` on a RELEASED vault raises instead of silently succeeding as a misleading no-op.
3. The last beneficiary sweeps the exact remaining balance, so bps that do not divide evenly
   never strand dust with nobody left to claim it.
4. `claim_share` reads the clock through the same guarded helper as every other write, rather
   than tolerating a blank `claimed_at`.
5. Death-review acceleration was explicitly made one-directional (`min` deadline only) after
   noticing the first draft could, in principle, postpone a nearly-expired window.
6. Registration-time URL validation refuses **all** IP literals (not merely private ones) — a
   DNS-rebinding-resistant default, at the cost of refusing exotic-but-harmless deployments.
7. The standby signer can be nominated mid-grace: restricting nomination to ACTIVE vaults would
   have locked out the precise scenario (an owner noticing the trigger late) the feature exists
   to serve.
