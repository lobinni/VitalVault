"""Deploy VitalVault to StudioNet, create a vault, and fund it — in one script.

Usage:
    cp samples/.env.example .env      # or export the variables another way
    python samples/deploy_and_create_vault.py

The script is deliberately small and readable rather than defensive: it is a reference for how
the SDK calls map onto the contract's methods, not production tooling. genlayer-py API surface
moves occasionally; if a call signature differs in your install, consult
https://docs.genlayer.com for the current form — the contract-side arguments documented here
(the method names, their order, and value-in-wei) are the stable part.
"""

import os
import sys
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "VitalVault.py"

HEARTBEAT_INTERVAL_SECONDS = 90 * 86400  # 90 days, inside the 14d..1095d protocol bounds
FUND_AMOUNT_WEI = 2 * 10**18             # 2 GEN


def load_env() -> dict:
    env = dict(os.environ)
    dotenv = Path(__file__).resolve().parents[1] / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env.setdefault(key.strip(), value.strip())
    return env


def main() -> None:
    env = load_env()
    private_key = env.get("PRIVATE_KEY", "")
    beneficiary = env.get("BENEFICIARY_ADDRESS", "")
    if not private_key or not beneficiary:
        sys.exit("Set PRIVATE_KEY and BENEFICIARY_ADDRESS in .env (see samples/.env.example)")

    # pip install genlayer-py
    from genlayer_py import create_account, create_client
    from genlayer_py.chains import studionet

    account = create_account(private_key)
    client = create_client(chain=studionet, account=account)
    owner = account.address
    print(f"owner: {owner}")

    # 1) Deploy -- or attach to the reference deployment when USE_EXISTING is set.
    #    The constructor takes no arguments and grants no roles.
    if env.get("USE_EXISTING") and env.get("CONTRACT_ADDRESS"):
        contract_address = env["CONTRACT_ADDRESS"]
        print(f"attaching to existing deployment: {contract_address}")
    else:
        contract_code = CONTRACT_PATH.read_bytes()
        deploy_hash = client.deploy_contract(code=contract_code, args=[])
        receipt = client.wait_for_transaction_receipt(hash=deploy_hash, status="finalized")
        contract_address = receipt["data"]["contract_address"]
        print(f"VitalVault deployed at: {contract_address}")

    # 2) Create the vault -- one per address. Optional sources are left empty here; see
    #    update_vitality_sources / update_identity_url to register them later.
    hash_ = client.write_contract(
        address=contract_address,
        function_name="create_vault",
        args=[HEARTBEAT_INTERVAL_SECONDS, [beneficiary], [10000], "", "", "", ""],
    )
    client.wait_for_transaction_receipt(hash=hash_, status="finalized")
    print("vault created")

    # 3) Fund it -- deposits are payable and permissionless; value is in wei.
    hash_ = client.write_contract(
        address=contract_address,
        function_name="deposit",
        args=[owner],
        value=FUND_AMOUNT_WEI,
    )
    client.wait_for_transaction_receipt(hash=hash_, status="finalized")
    print(f"funded with {FUND_AMOUNT_WEI / 10**18} GEN")

    # 4) Read it back.
    vault = client.read_contract(
        address=contract_address, function_name="get_vault", args=[owner]
    )
    print("vault state:")
    for key in ("status", "balance", "heartbeat_interval_seconds", "beneficiary_count"):
        print(f"  {key}: {vault.get(key)}")

    print("\nNext: python samples/lifecycle_walkthrough.py  (reads the walkthrough comments first)")


if __name__ == "__main__":
    main()
