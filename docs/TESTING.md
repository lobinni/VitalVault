# Testing VitalVault

The contract ships with a direct-VM test suite: the GenVM executes the actual contract code
in-process, with web requests and LLM calls intercepted by mocks. No network, no accounts, no
validators needed — the suite runs in seconds and covers the full lifecycle plus both consensus
rounds.

## Prerequisites

```bash
cd vitalvault
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in `genlayer-test` (the gltest pytest plugin — it provides the
`direct_deploy`, `direct_vm`, `direct_alice`… fixtures) and `pytest`. If your environment
resolves a different distribution name for gltest, follow the install instructions at
<https://docs.genlayer.com> — the tests only depend on the direct-mode fixtures, not on a
particular package version.

## Running

From the package root (the directory containing `gltest.config.yaml`):

```bash
gltest --test-dir tests/direct        # preferred entry point
# or, if gltest delegates to pytest in your install:
pytest tests/direct -v
```

A successful run executes 60+ tests across these groups:

| Group | What it proves |
| --- | --- |
| creation & validation | one vault per owner; interval bounds (14 d – 1095 d); bps sum = 10000; no duplicates, zero shares, owner-as-beneficiary, >12 beneficiaries; handle charsets; https-only; IP-literal refusal for website and identity URLs |
| funding & withdrawals | permissionless deposits, zero-value rejection, owner-only withdrawals within balance |
| configuration | owner-only updates; everything except standby-signer nomination locked during grace |
| check-in | owner path, standby-signer path, stranger rejection, loud failure on RELEASED vaults, instant trigger cancellation |
| lifecycle | permissionless trigger with keeper reward (and the broke-vault skip), early/double trigger rejection, early finalize rejection, full claim flow with exact-balance dust sweep, double-claim and non-beneficiary rejection |
| vitality scan | single-active-source auto-cancel, unanimous-quiet keeps grace, one-UNDETERMINED forces INCONCLUSIVE, source/ status preconditions, cooldown, **private-DNS overrides the model's own claim** |
| death-evidence review | unanimous high-confidence confirmation accelerates to the 7-day floor; ambiguous/low-confidence/unknown-anchor defeats it; check-in still wins afterwards; URL validation; cooldown |

## How the mocks work

- `warp_to(direct_vm, iso)` sets the VM clock and mirrors the ISO timestamp into the message
  metadata the contract reads. All timestamps in the suite are chained from `NOW` so the
  arithmetic (90-day interval → `AFTER_INTERVAL`, +45-day grace → `AFTER_GRACE`, +7-day floor →
  `ACCELERATED_DEADLINE`) stays auditable.
- `direct_vm.mock_web(regex, {"status": …, "body": …})` answers any matching fetch (page render,
  GET request, or the `dns.google/resolve` DNS-over-HTTPS lookup used by the hardening layer).
- `direct_vm.mock_llm(regex, response)` answers the consensus prompt whose text matches the
  regex. The suite pins the *per-source classifications* and then varies what the contract's
  aggregation code must do with them — including the hostile case where the model claims activity
  on a source the code itself refused to fetch (see
  `test_vitality_scan_private_dns_overrides_model_claim`).

## Writing new tests

1. Reuse the helpers at the top of `test_vital_vault.py` (`create_vault`, `fund`, `trigger`,
   `mock_vitality`, `mock_death_review`). They exist so each test body reads as the scenario it
   verifies.
2. Any test touching time must `warp_to` first — an unwarped clock is a flake waiting to happen.
3. Views return wei-denominated values as **strings** (`balance`, `distributable_balance`,
   `claimable_wei`) and counts as ints; compare accordingly.
4. Reset `direct_vm.value` to `0` after payable calls, and `direct_vm.sender` before each
  actor's calls — fixtures are function-scoped, but state is not.

## Checking the live deployment

The direct-VM suite is authoritative for logic; a small read-only probe confirms the deployed
StudioNet build answers with the documented protocol constants:

```bash
python samples/read_deployed_contract.py
# expected tail: "OK: the deployment answers with the documented protocol constants."
```

Optionally set `VAULT_OWNER` in `.env` to additionally probe a specific vault's state. To
exercise real write paths (and eventually a consensus round) on StudioNet, use
`samples/lifecycle_walkthrough.py` — read its header comments first: the 14-day minimum
heartbeat means a full trigger cycle cannot be rehearsed in real time on the live build.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `no vault registered for this address` | wrong `direct_vm.sender` left over from the previous step |
| consensus round returns `INCONCLUSIVE` unexpectedly | the `mock_llm` regex no longer matches the prompt text — update the marker phrase |
| website/anchor source always `NOT_AVAILABLE` | missing `dns.google/resolve` mock — the DNS re-check needs its own `mock_web` entry |
| unexpected `[TRANSIENT]` clock error | test forgot `warp_to` before a time-dependent call |
| `read_deployed_contract.py` reports a mismatch | pointed at the wrong address or a stale build — check `deployments.json` first |
