# Building a frontend for VitalVault — in a separate repository

**Scope rule:** the submission package is the Intelligent Contract, its tests, and its docs. A
frontend is a *consumer* of the deployed contract and must live in its own repository; nothing in
this package depends on one existing. This file is the complete contract-side contract for
whoever builds it.

## What the UI needs to know

### Status model and strings

`get_vault(owner).status` is exactly one of `"ACTIVE"`, `"GRACE_PERIOD"`, `"RELEASED"`.

```
ACTIVE        → happy path; show countdown via seconds_until_triggerable(owner)
GRACE_PERIOD  → show countdown via seconds_until_releasable(owner), the vitality/death
                verdicts, and the "check in now" + "run scan/review" actions
RELEASED      → show get_claimable_amount(owner, viewer) and the claim action
```

### Reads (all `@gl.public.view`, free to poll)

| Method | Returns | UI use |
| --- | --- | --- |
| `get_vault(owner)` | full vault dict (see list below) | dashboard state |
| `get_beneficiaries(owner)` | `[{address, bps, claimed, claimed_at}]` | share table |
| `get_claimable_amount(owner, beneficiary)` | `{claimable_wei, claimed, is_beneficiary}` | claim button enablement |
| `seconds_until_triggerable(owner)` | int; negative = overdue | heartbeat countdown |
| `seconds_until_releasable(owner)` | int; negative = finalizable | grace countdown |
| `is_registered(owner)` | bool | "create vs. manage" routing |
| `list_vaults()` | `[owner_hex, …]` | explorer view |
| `get_protocol_constants()` | bounds and timings | client-side validation mirrors |

`get_vault` keys: `owner, has_standby_signer, standby_signer, heartbeat_interval_seconds,
last_check_in_at, created_at, identity_url, github_handle, x_handle, website_url,
beneficiary_count, status, grace_started_at, grace_deadline, released_at, balance,
distributable_balance, claimed_count, vitality_scan_count, last_vitality_scan_at,
vitality_verdict, vitality_rationale, death_review_count, last_death_review_at, death_verdict,
death_rationale, death_confirmed_at`.

⚠️ Wei-denominated fields (`balance`, `distributable_balance`, `claimable_wei`,
`get_protocol_constants().keeper_reward_wei`) are **strings** — parse with a bignum-aware helper.

### Writes (need a signed transaction)

`create_vault`, `update_beneficiaries`, `update_vitality_sources`, `update_identity_url`,
`update_heartbeat_interval`, `update_standby_signer`, `deposit` (attach value),
`owner_withdraw`, `check_in`, `trigger_inheritance`, `run_vitality_scan`,
`run_death_evidence_review(owner, url_list)`, `finalize_inheritance`, `claim_share` — full
signatures in the README method table.

Errors are prefixed: `[EXPECTED]` = a rule the caller violated (render the message to the user),
`[TRANSIENT]` = retryable infrastructure hiccup, `[LLM_ERROR]` = consensus/model-layer failure.

### Consensus-round calls behave differently

`run_vitality_scan` and `run_death_evidence_review` run validator consensus with live web access:
they take minutes, not seconds, and both are cooldown-bound (12 h / 24 h per vault). The UI
should expose the last verdict and rationale from `get_vault` and gate the buttons on
`last_vitality_scan_at` / `last_death_review_at` rather than letting users spam them.

## Suggested stack and snippets

`genlayer-js` against StudioNet, pointed at the reference deployment
([explorer](https://explorer-studio.genlayer.com/address/0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4)
— the canonical record lives in `deployments.json`):

```ts
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";

const CONTRACT_ADDRESS = "0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4";
const client = createClient({ chain: studionet, account: createAccount(privateKey) });

// read
const vault = await client.readContract({
  address: CONTRACT_ADDRESS,
  functionName: "get_vault",
  args: [ownerAddress],
});

// write (attaching value for a deposit)
const hash = await client.writeContract({
  address: CONTRACT_ADDRESS,
  functionName: "deposit",
  args: [ownerAddress],
  value: 2n * 10n ** 18n, // 2 GEN in wei
});
const receipt = await client.waitForTransactionReceipt({
  hash,
  status: TransactionStatus.FINALIZED, // always FINALIZED for consensus-round calls
});
```

## Screens that map 1:1 onto the state machine

1. **Create vault** — form fields mirror `create_vault` exactly; validate with
   `get_protocol_constants()` client-side before sending.
2. **Owner dashboard** — countdown ring from `seconds_until_triggerable`, one-tap `check_in`,
   withdraw, edit beneficiaries/sources, standby-signer management.
3. **Grace monitor** (public) — countdown from `seconds_until_releasable`, last scan/review
   verdicts and rationales, buttons for `run_vitality_scan`, `run_death_evidence_review`
   (URL list input), `finalize_inheritance`.
4. **Beneficiary claim** — `get_claimable_amount` → single `claim_share` button.
5. **Keeper view** — list vaults where `seconds_until_triggerable < 0` or
   `seconds_until_releasable < 0`; both transitions pay a small reward from the vault itself.

Keep the frontend dumb: every rule — intervals, bps sums, status transitions, aggregation — is
enforced on-chain. The UI's job is honest display of state and timely access to the
permissionless buttons, never enforcement.
