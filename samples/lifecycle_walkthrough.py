"""Reference script: the VitalVault lifecycle end to end, with commentary.

READ THIS BEFORE RUNNING. Unlike the direct-VM suite (which warps the clock freely), a live
network waits in real time: the minimum heartbeat is 14 days and the grace period is 45 days, so
a full trigger -> finalize run is not a same-afternoon demo. This script exists primarily as
executable documentation — each step is the exact SDK call that step takes, in order. To see the
whole lifecycle in motion in seconds, run the direct-VM suite instead (docs/TESTING.md). To
rehearse it live, deploy a throwaway copy whose MIN_HEARTBEAT_SECONDS line you have temporarily
lowered for the experiment.

Usage after `deploy_and_create_vault.py`:
    export CONTRACT_ADDRESS=0x...   (or set it in .env)
    python samples/lifecycle_walkthrough.py
"""

import os
from pathlib import Path


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
    contract_address = env.get("CONTRACT_ADDRESS", "")
    if not private_key or not contract_address:
        raise SystemExit("Set PRIVATE_KEY and CONTRACT_ADDRESS in .env")

    from genlayer_py import create_account, create_client
    from genlayer_py.chains import studionet

    account = create_account(private_key)
    client = create_client(chain=studionet, account=account)
    owner = account.address

    def write(function_name, args, value=0, wait="finalized"):
        hash_ = client.write_contract(
            address=contract_address, function_name=function_name, args=args, value=value
        )
        return client.wait_for_transaction_receipt(hash=hash_, status=wait)

    def read(function_name, args):
        return client.read_contract(
            address=contract_address, function_name=function_name, args=args
        )

    # -- Step 0: where are we? ------------------------------------------------------------
    vault = read("get_vault", [owner])
    print("status:", vault["status"], "| balance:", vault["balance"])
    print("seconds until triggerable:", read("seconds_until_triggerable", [owner]))

    # -- Step 1: configure the safety nets BEFORE you need them ----------------------------
    # A standby signer can only ever prove life (check_in) -- never touch funds or config.
    if env.get("STANDBY_SIGNER"):
        write("update_standby_signer", [env["STANDBY_SIGNER"], True])
        print("standby signer registered")
    # Vitality sources let run_vitality_scan cancel a wrongful trigger later.
    if env.get("GITHUB_HANDLE"):
        write(
            "update_vitality_sources",
            [env["GITHUB_HANDLE"], env.get("X_HANDLE", ""), env.get("WEBSITE_URL", "")],
        )
        print("vitality sources registered")
    # An identity anchor enables run_death_evidence_review's acceleration.
    if env.get("IDENTITY_URL"):
        write("update_identity_url", [env["IDENTITY_URL"]])
        print("identity anchor registered")

    # -- Step 2: the everyday proof of life -------------------------------------------------
    write("check_in", [owner])
    print("checked in:", read("get_vault", [owner])["last_check_in_at"])

    # -- The steps below require real elapsed time. They are shown for completeness ---------
    #
    # -- Step 3 (permissionless, once seconds_until_triggerable goes negative):
    # write("trigger_inheritance", [owner])
    #
    # -- Step 4 (optional, permissionless, during the 45-day grace window):
    # write("run_vitality_scan", [owner])                 # consensus round, ~minutes
    # write("run_death_evidence_review", [owner, [obituary_url]])  # needs an identity anchor
    # ...but a plain check_in from the owner at any point cancels everything instantly.
    #
    # -- Step 5 (permissionless, once seconds_until_releasable goes negative):
    # write("finalize_inheritance", [owner])
    #
    # -- Step 6 (each beneficiary, from their own account):
    # print(read("get_claimable_amount", [owner, beneficiary]))
    # write("claim_share", [owner])


if __name__ == "__main__":
    main()
