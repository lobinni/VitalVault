# Deploying VitalVault

## Current reference deployment

The contract is already live on StudioNet — integrate against it directly, or deploy your own
copy below.

| | |
| --- | --- |
| Address | `0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4` |
| Network | GenLayer StudioNet |
| Explorer | <https://explorer-studio.genlayer.com/address/0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4> |
| Machine-readable record | `deployments.json` |

Verify the deployment answers with the documented protocol constants (reads only, no key):

```bash
python samples/read_deployed_contract.py
```

Attach to it from the SDK scripts instead of redeploying by setting `USE_EXISTING=1` in `.env`.
The same machine-readable record in `deployments.json` is the canonical pointer for CI and
frontends — read the address from there rather than hardcoding copies.

## Deploying your own copy

Three equivalent paths, depending on how much tooling you want. The contract's constructor takes
**no arguments** and grants **no privileged roles** — deployment itself confers no power.

## Option A — GenLayer Studio (fastest)

1. Open <https://studio.genlayer.com> and connect a funded Studio account.
2. Create a new contract file and paste the contents of `contracts/VitalVault.py`. Keep the
   `# { "Depends": "py-genlayer:…" }` pin on line 1 — it selects the exact runtime the tests ran
   against.
3. Deploy. The constructor runs with zero arguments.
4. Smoke-check from the Studio console:
   - call `get_protocol_constants()` — expect the 14-day / 45-day / 7-day constants;
   - call `create_vault` with `7776000` (90 days), one beneficiary at `10000` bps, and empty
     strings for the four URLs/handles;
   - attach value to a `deposit(your_address)` call and read `get_vault` back.

## Option B — GenLayer CLI

```bash
cd vitalvault
genlayer deploy --contract contracts/VitalVault.py --network studionet
```

Record the deployed address into `.env` (see `samples/.env.example`) so the SDK samples can pick
it up.

## Option C — Python SDK (scripted, repeatable)

`samples/deploy_and_create_vault.py` deploys the contract, creates a vault, and funds it in one
run:

```bash
cp samples/.env.example .env   # fill in your private key
python samples/deploy_and_create_vault.py
```

Values attached to write calls (deposits, keeper payouts) are denominated in wei; the sample uses
small amounts safe for testnets.

## After deployment

The contract never needs maintenance — there is no admin function to rotate and no parameter to
tune post-hoc. What you may want operationally instead:

- **A keeper habit, not a keeper service.** `trigger_inheritance` and `finalize_inheritance` are
  permissionless *by design*, and each pays a small reward from the vault's own balance to
  whoever performs it. Anyone watching `seconds_until_triggerable` / `seconds_until_releasable`
  can do it; no infra is required from the deployer.
- **Owner-side reminders.** The strongest protection the contract offers is the one it cannot
  force: the owner actually checking in. A calendar reminder well inside the heartbeat interval
  is worth more than any on-chain feature.
- **Configure the safety nets up front.** The vitality scan needs at least one registered source;
  the death-evidence review needs an identity anchor. Both are free to set at creation and
  worthless if skipped until after the owner goes quiet.

## Network notes

- The reference network is **StudioNet** (`networks.default: studionet` in `gltest.config.yaml`;
  `localnet` is provided for `--network localnet` runs).
- A first deployment against a local simulator is recommended before StudioNet: the direct-VM
  suite (`docs/TESTING.md`) covers logic, but only a live network exercises the real web-render
  and validator-consensus paths of the two rounds.
