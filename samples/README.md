# SDK samples

Runnable references for integrating with the deployed contract from Python (`genlayer-py`).
They are consumer code, like the frontend: they change no part of the contract package and are
not required to test it (for that, use the direct-VM suite in `../tests/direct`).

**Reference deployment (StudioNet):** `0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4` —
[explorer](https://explorer-studio.genlayer.com/address/0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4) —
also recorded in `../deployments.json`.

| Script | What it does |
| --- | --- |
| `read_deployed_contract.py` | zero-setup, read-only probe: verifies the live deployment answers with the documented protocol constants (no key or funds needed) |
| `deploy_and_create_vault.py` | deploys the contract (no constructor args), creates the caller's vault with one beneficiary at 10000 bps, and funds it with 2 GEN — set `USE_EXISTING=1` to attach to the reference deployment instead of redeploying |
| `lifecycle_walkthrough.py` | narrative script mapping every lifecycle step to its exact SDK call; live steps that require waiting 14+ days are commented out and annotated |

Setup:

```bash
pip install genlayer-py                  # the scripts read .env directly, no dotenv needed
cp .env.example ../.env                  # CONTRACT_ADDRESS already points at the live deployment
python read_deployed_contract.py         # sanity-check the chain with zero setup

# full write-path walkthrough (needs a funded key):
python deploy_and_create_vault.py        # or: USE_EXISTING=1 python deploy_and_create_vault.py
python lifecycle_walkthrough.py
```

Tips: set `VAULT_OWNER` in `.env` to have the read-back script probe a specific vault; keep
`CONTRACT_ADDRESS` in sync with `../deployments.json` if you deploy your own copy.

Conventions the scripts rely on: method argument **order** is positional and matches the README
method table; payable values are in **wei**; wei-denominated values read back from views are
**strings** (parse with `int(...)`, or a bignum helper in JS).
