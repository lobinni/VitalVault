# VitalVault

_A self-sovereign digital-inheritance vault for the GenLayer network — contract + tests. No admin, no operator, no third party ever holds a lever over any single vault._

An owner deposits funds and names beneficiaries with percentage shares (basis points). As long as they periodically prove they're still around — a plain `check_in()` transaction, the cheapest and strongest proof of life there is — the vault stays entirely theirs to withdraw from and reconfigure. If they go quiet past their own configured heartbeat interval, **anyone** may permissionlessly start a fixed **45-day grace period**; if no check-in arrives before it elapses, the vault is released and each beneficiary permissionlessly claims their share.

## Live deployment — StudioNet

| | |
| --- | --- |
| **Contract address** | `0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4` |
| **Network** | GenLayer StudioNet |
| **Explorer** | <https://explorer-studio.genlayer.com/address/0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4> |
| **Source** | `contracts/VitalVault.py` in this repository (constructor takes no arguments, grants no roles) |

One-command verification that the deployment answers with the documented protocol constants:

```bash
python samples/read_deployed_contract.py        # reads only — no key or funds needed
```

## Why this is a genuine Intelligent Contract, not just a timelock

A plain dead-man's switch — *release funds if nobody calls by deadline X* — is a timestamp comparison any smart contract can do. VitalVault uses GenLayer's consensus machinery in two optional, best-effort ways a pure timelock cannot replicate:

1. **`run_vitality_scan`** — the most common real failure mode of self-custody is an owner who is alive and digitally active, but has lost or forgotten the one specific wallet this vault listens to. While a vault is inside its grace period, anyone may ask a consensus round to inspect the owner's registered public pages (GitHub events feed, X profile, personal website) for activity dated *after* their last on-chain check-in. A single active source cancels the trigger exactly as if they'd checked in.

2. **`run_death_evidence_review`** — heirs of a genuinely deceased owner shouldn't wait longer than necessary. If the owner registered an *identity anchor URL* up front, anyone may submit 1–3 public evidence pages (obituaries, memorial notices) and a consensus round cross-checks the identity the anchor describes against what each evidence page credibly reports. A CONFIRMED review shortens the remaining grace period to a fixed 7-day minimum — never more.

Both rounds are strictly optional: a vault with no registered sources runs purely on its heartbeat, exactly like a conventional dead-man's switch.

## The asymmetric-risk design principle

The two mistakes this contract can make are wildly unequal in cost. Releasing a living person's savings is a severe, possibly irreversible harm; keeping a real inheritance in the grace state a while longer is an inconvenience. Every aggregation rule follows from that:

- **Vitality scan:** activity on **any single** source cancels the trigger. A confident `NO_VITALITY_DETECTED` requires **every** fetched source to agree nothing was found — one `UNDETERMINED` anywhere forces `INCONCLUSIVE`.
- **Death-evidence review:** the mirror image. Confirmation requires **every** fetched page to report the *same* person named by the identity anchor, with high confidence and an unambiguous identity match. One unclear page, failed fetch, or low-confidence verdict defeats the entire review.
- **A `check_in()` always wins, unconditionally.** No consensus verdict, in-flight scan, or even a confirmed death review can outrank a fresh signature from the owner's key. And on a `RELEASED` vault, `check_in()` raises loudly instead of silently no-op'ing.

## Architecture

```
vitalvault/
├── contracts/
│   └── VitalVault.py          # the single Intelligent Contract
├── tests/
│   └── direct/
│       ├── conftest.py        # direct-VM fixtures + time warp helper
│       └── test_vital_vault.py# 60+ direct-VM tests (see docs/TESTING.md)
├── samples/                   # genlayer-py SDK scripts (deploy/attach, lifecycle, read-back)
├── docs/
│   ├── TESTING.md             # how to run and extend the test suite
│   ├── DEPLOYMENT.md          # Studio / CLI / SDK deployment guide
│   └── FRONTEND.md            # build a frontend in a SEPARATE repo — not part of this package
├── deployments.json           # machine-readable record of the StudioNet deployment
├── gltest.config.yaml
├── requirements-dev.txt
└── DECISION.md                # the design record: what was decided, and why
```

**Submission scope: this package only — the Intelligent Contract, its tests, docs, and SDK samples.** A frontend (create a vault, watch the countdown, monitor a grace period, claim a share) is a natural companion but is deliberately *not* included here; `docs/FRONTEND.md` specifies the contract surface so one can be built in a separate repository without touching this package.

## Lifecycle

```
        check_in() any time ─────────────────────────┐
                                                    ▼
 ┌─────────┐   heartbeat missed    ┌──────────────┐  grace elapsed   ┌──────────┐
 │ ACTIVE  │ ────────────────────▶ │ GRACE_PERIOD │ ───────────────▶ │ RELEASED │
 └─────────┘  trigger_inheritance  └──────────────┘  finalize        └──────────┘
      ▲                                  │                                  │
      └─────────── check_in() ───────────┤                                  │
      └── vitality VITALITY_FOUND ───────┤                          claim_share()
      └── (death review CONFIRMED only   │                          per beneficiary,
          shortens the window to 7d) ────┘                          last claim sweeps dust
```

## Contract methods

| Method | Kind | Consensus round? | What it does |
| --- | --- | --- | --- |
| `create_vault(interval, addrs, bps, identity_url, github, x, website)` | write, self-only | No | Creates the caller's one vault: heartbeat interval, beneficiaries, optional identity anchor and vitality sources. |
| `update_beneficiaries(addrs, bps)` | write, owner-only, ACTIVE-only | No | Replaces the beneficiary set of a vault that hasn't been triggered. |
| `update_vitality_sources(github, x, website)` | write, owner-only, ACTIVE-only | No | Re-registers the public pages a vitality scan may consult. |
| `update_identity_url(identity_url)` | write, owner-only, ACTIVE-only | No | Re-registers the identity anchor used by death-evidence reviews. |
| `update_heartbeat_interval(seconds)` | write, owner-only, ACTIVE-only | No | Changes the heartbeat within protocol bounds (14 days – 3 years). |
| `update_standby_signer(addr, enabled)` | write, owner-only (any non-RELEASED state) | No | Names/clears a second key that may `check_in` — and nothing else. |
| `deposit(owner)` | payable write, permissionless | No | Adds funds to any vault — family can contribute too. Closed on RELEASED vaults. |
| `owner_withdraw(amount)` | write, owner-only, ACTIVE-only | No | Withdraws at will; this is not a one-way lock. |
| `check_in(owner)` | write, owner or standby signer | No | The primary proof of life. Instantly cancels any in-progress trigger. |
| `trigger_inheritance(owner)` | write, permissionless | No | Starts the fixed 45-day grace period once the heartbeat has elapsed. Pays a small keeper reward from the vault's own balance. |
| `run_vitality_scan(owner)` | write, permissionless | **Yes** | Optional safety net: consensus on post-check-in activity across registered sources. Cooldown: 12 h. |
| `run_death_evidence_review(owner, urls)` | write, permissionless | **Yes** | Optional accelerator: consensus on submitted death evidence vs. the identity anchor. Cooldown: 24 h. |
| `finalize_inheritance(owner)` | write, permissionless | No | Locks the distributable balance once the grace window elapses uncancelled. All state settles before the keeper payout. |
| `claim_share(owner)` | write, permissionless (beneficiary-gated by effect) | No | Deterministic per-beneficiary payout; the last claimant sweeps rounding dust so the vault always empties to exactly zero. |
| `get_vault` / `get_beneficiaries` / `get_claimable_amount` / `seconds_until_triggerable` / `seconds_until_releasable` / `list_vaults` / `is_registered` / `get_protocol_constants` | view | No | Reads, shaped for direct frontend consumption. |

## Why there is no admin

Contracts holding pooled assets or shared parameters justify an admin to bound risks that span *many* users. An inheritance vault has no equivalent shared surface: every parameter — the interval, the beneficiaries, the sources, whether to withdraw — belongs exclusively to one owner's own arrangement, and nothing about one vault's configuration ever touches another vault's economics. There is nothing an admin could responsibly be responsible for, so this contract has none. By the same logic, a `RELEASED` vault cannot be clawed back: undoing a release after beneficiaries have claimed would require a central arbitrator, which is precisely what the heartbeat interval, the fixed grace window, and the two consensus safety nets exist to make unnecessary.

## Fetch-target hardening (summary)

Every network fetch target is handled in code, in layers: deterministic shape validation before any round runs (https-only, hostname-only, IP literals refused outright, no user-info, no explicit ports) → live DNS-over-HTTPS re-resolution inside the round, refusing hosts without a public A record → redirect statuses refused → fetched text labelled UNTRUSTED EVIDENCE with an explicit no-instructions rule → the model only classifies per source, while the contract's own code forces any source it never actually fetched to `NOT_AVAILABLE` regardless of what the model claimed.

## Honest limitations

- **A released vault cannot be reclaimed.** Every protection is front-loaded into the heartbeat, the fixed 45-day window, and the two optional consensus nets. If all of those run their course with zero signal, release is final — as real-world inheritance is, once distributed.
- **A permanently lost key with no standby signer and no registered sources has no resolution short of the timeout.** Those features exist specifically to shrink that risk, but only if configured in advance.
- **The standby signer is intentionally narrow**: proof of life only — never funds, never configuration.
- **The vitality scan is best-effort, not proof.** Some platforms render little reliable date signal without authentication (which is exactly why one source's `UNDETERMINED` blocks the confident-negative verdict rather than being ignored).
- **Death-evidence acceleration is never mandatory and never final on its own**: it needs an identity anchor configured in advance, requires unanimous high-confidence confirmation, cannot extend a deadline, and loses instantly to a single `check_in()`.
- **No beneficiary identity verification and no legal-executor fast path.** Beneficiaries are trusted at face value; every vault runs on the same fixed timeline regardless of real-world circumstances.

## Quick start

```bash
cd vitalvault
pip install -r requirements-dev.txt
gltest --test-dir tests/direct        # runs the direct-VM suite
```

See `docs/TESTING.md` for the full guide and `docs/DEPLOYMENT.md` for putting the contract on StudioNet.
