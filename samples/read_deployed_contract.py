"""Zero-setup sanity check against the reference deployment on StudioNet.

Reads only -- no key, no funds, no transaction needed. Confirms the deployed code answers the
documented view surface:

    python samples/read_deployed_contract.py
    python samples/read_deployed_contract.py 0xOtherAddress   # read a different deployment

Set VAULT_OWNER in .env (or export it) to additionally probe a specific vault's state.
"""

import os
import sys
from pathlib import Path

REFERENCE_ADDRESS = "0xCdfB0533aE689AD2D7da6875f3F4454Ce8DF38e4"
EXPLORER = "https://explorer-studio.genlayer.com/address/"


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
    address = sys.argv[1] if len(sys.argv) > 1 else env.get("CONTRACT_ADDRESS", REFERENCE_ADDRESS)

    from genlayer_py import create_client
    from genlayer_py.chains import studionet

    client = create_client(chain=studionet)  # read-only client, no account required
    print(f"contract : {address}")
    print(f"explorer : {EXPLORER}{address}")

    constants = client.read_contract(
        address=address, function_name="get_protocol_constants", args=[]
    )
    print("\nprotocol constants (must match the documented bounds):")
    checks = [
        ("min_heartbeat_seconds", 14 * 86400),
        ("max_heartbeat_seconds", 1095 * 86400),
        ("grace_period_seconds", 45 * 86400),
        ("accelerated_grace_seconds", 7 * 86400),
        ("vitality_scan_cooldown_seconds", 12 * 3600),
        ("death_review_cooldown_seconds", 86400),
        ("max_beneficiaries", 12),
        ("bps_total", 10000),
    ]
    ok = True
    for key, expected in checks:
        actual = constants.get(key)
        mark = "ok " if actual == expected else "MISMATCH"
        if actual != expected:
            ok = False
        print(f"  [{mark}] {key}: {actual}")
    print(f"  keeper_reward_wei: {constants.get('keeper_reward_wei')}")

    owner = env.get("VAULT_OWNER", "")
    if owner:
        registered = client.read_contract(
            address=address, function_name="is_registered", args=[owner]
        )
        print(f"\nis_registered({owner}): {registered}")
        if registered:
            vault = client.read_contract(address=address, function_name="get_vault", args=[owner])
            for key in ("status", "balance", "last_check_in_at", "heartbeat_interval_seconds"):
                print(f"  {key}: {vault.get(key)}")
    else:
        print("\n(tip: set VAULT_OWNER in .env to probe a specific vault)")

    if not ok:
        sys.exit("constants mismatch -- the deployed code is not the documented build")
    print("\nOK: the deployment answers with the documented protocol constants.")


if __name__ == "__main__":
    main()
