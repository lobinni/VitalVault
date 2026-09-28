"""Direct-VM test suite for the VitalVault Intelligent Contract.

Run from the package root:

    gltest --test-dir tests/direct        # or: pytest tests/direct

The suite covers: vault creation and validation, funding and owner withdrawals, configuration
updates, check-in (owner + standby signer paths), the full trigger -> grace -> finalize -> claim
lifecycle, vitality-scan aggregation edge cases, death-evidence review gating, and fetch-target
hardening (literal-IP refusal and live DNS re-resolution).

Time handling: direct_vm.warp sets the VM clock; warp_to additionally mirrors the ISO timestamp
into the message metadata the contract reads. All timestamps below are chained from NOW so the
arithmetic stays auditable at a glance.
"""

import pytest

from conftest import warp_to

GEN = 10**18
KEEPER_REWARD = 15 * 10**13  # must match KEEPER_REWARD_WEI in the contract

NOW = "2099-01-01T00:00:00Z"
DEFAULT_INTERVAL = 90 * 86400  # 90 days -- inside the 14d..1095d bounds
AFTER_INTERVAL = "2099-04-01T00:00:05Z"  # 90 days + 5 s after NOW -> triggerable
JUST_BEFORE_INTERVAL = "2099-03-31T23:59:59Z"

# Grace period is a fixed 45-day protocol constant starting at the moment trigger_inheritance
# is actually called (AFTER_INTERVAL).
AFTER_GRACE = "2099-05-16T00:00:06Z"  # 45 days + 1 s after AFTER_INTERVAL
JUST_BEFORE_GRACE_END = "2099-05-16T00:00:00Z"

AFTER_SCAN_COOLDOWN = "2099-04-01T12:00:06Z"  # > 12 h after AFTER_INTERVAL

DEATH_REVIEW_TIME = "2099-04-02T00:00:00Z"
ACCELERATED_DEADLINE = "2099-04-09T00:00:00Z"  # DEATH_REVIEW_TIME + 7 days
AFTER_ACCELERATED_DEADLINE = "2099-04-09T00:00:05Z"
AFTER_DEATH_COOLDOWN = "2099-04-03T00:00:01Z"

PUBLIC_DNS_ANSWER = '{"Status":0,"Answer":[{"type":1,"data":"93.184.216.34"}]}'
PRIVATE_DNS_ANSWER = '{"Status":0,"Answer":[{"type":1,"data":"169.254.169.254"}]}'

VALID_GITHUB = "octocat"
VALID_X = "octocat"
VALID_WEBSITE = "https://example.com/octocat"
VALID_ANCHOR = "https://identity.example.com/about"
VALID_NEWS = "https://dailynews.example.com/obituaries/rowan-vale"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def create_vault(
    contract,
    direct_vm,
    owner,
    beneficiaries,
    interval=DEFAULT_INTERVAL,
    identity_url="",
    github="",
    x="",
    website="",
):
    direct_vm.sender = owner
    addrs = [b[0] for b in beneficiaries]
    bps = [b[1] for b in beneficiaries]
    contract.create_vault(interval, addrs, bps, identity_url, github, x, website)


def fund(contract, direct_vm, payer, owner, amount):
    direct_vm.sender = payer
    direct_vm.value = amount
    contract.deposit(owner)
    direct_vm.value = 0


def trigger(contract, direct_vm, keeper, owner):
    direct_vm.sender = keeper
    contract.trigger_inheritance(owner)


def mock_public_dns(direct_vm):
    direct_vm.mock_web(r".*dns\.google/resolve.*", {"status": 200, "body": PUBLIC_DNS_ANSWER})


def mock_vitality(direct_vm, github="UNDETERMINED", x="UNDETERMINED", website="UNDETERMINED",
                  reason="Evidence reviewed.", private_dns=False):
    direct_vm.clear_mocks()
    dns_body = PRIVATE_DNS_ANSWER if private_dns else PUBLIC_DNS_ANSWER
    direct_vm.mock_web(r".*dns\.google/resolve.*", {"status": 200, "body": dns_body})
    direct_vm.mock_web(
        r".*api\.github\.com/users/.*/events/public.*",
        {"status": 200, "body": '[{"type":"PushEvent","created_at":"2099-03-15T10:00:00Z"}]'},
    )
    direct_vm.mock_web(
        r"https://x\.com/.*", {"status": 200, "body": "profile page with a visible timeline of posts" * 3}
    )
    direct_vm.mock_web(
        r"https://example\.com/.*", {"status": 200, "body": "personal site body text, long enough to count" * 3}
    )
    direct_vm.mock_llm(
        r".*evaluating up to three registered public vitality sources.*",
        '{"github":"%s","x":"%s","website":"%s","rationale":"%s"}' % (github, x, website, reason),
    )


def mock_death_review(direct_vm, verdict="CONFIRMS_DEATH", match="true", confidence="high",
                      anchor_identity="Rowan Vale", reason="Notices cross-checked."):
    direct_vm.clear_mocks()
    mock_public_dns(direct_vm)
    direct_vm.mock_web(
        r"https://identity\.example\.com/about",
        {"status": 200, "body": "I am Rowan Vale, operator of this site and of the vault shared with heirs. " * 2},
    )
    direct_vm.mock_web(
        r"https://dailynews\.example\.com/.*",
        {"status": 200, "body": "Rowan Vale, software engineer, died on 2099-03-20 after an accident. " * 2},
    )
    direct_vm.mock_llm(
        r".*death evidence review for a registered identity anchor.*",
        '{"anchor_identity":"%s","evaluations":[{"verdict":"%s","identity_match":%s,"confidence":"%s"}],'
        '"rationale":"%s"}' % (anchor_identity, verdict, match, confidence, reason),
    )


# ---------------------------------------------------------------------------
# vault creation and validation
# ---------------------------------------------------------------------------


def test_create_vault(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    v = contract.get_vault(direct_bob)
    assert v["status"] == "ACTIVE"
    assert v["beneficiary_count"] == 1
    assert v["last_check_in_at"] == NOW
    assert v["balance"] == "0"
    assert v["has_standby_signer"] is False


def test_create_vault_twice_fails(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])


def test_create_vault_rejects_interval_too_short(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], interval=13 * 86400)


def test_create_vault_rejects_interval_too_long(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], interval=1100 * 86400)


def test_create_vault_accepts_interval_bounds(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], interval=14 * 86400)
    assert contract.get_vault(direct_bob)["heartbeat_interval_seconds"] == 14 * 86400


def test_create_vault_rejects_bps_sum_mismatch(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 5000), (direct_dave, 4000)])


def test_create_vault_rejects_duplicate_beneficiary(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 5000), (direct_carol, 5000)])


def test_create_vault_rejects_zero_bps(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 0), (direct_dave, 10000)])


def test_create_vault_rejects_owner_as_beneficiary(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_bob, 10000)])


def test_create_vault_rejects_too_many_beneficiaries(contract, direct_vm, direct_bob, direct_carol):
    beneficiaries = [(direct_carol, 0)] * 13
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, beneficiaries)


def test_create_vault_rejects_mismatched_lists(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.create_vault(DEFAULT_INTERVAL, [direct_carol, direct_dave], [10000], "", "", "", "")


def test_create_vault_rejects_bad_github_handle(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], github="bad handle!")


def test_create_vault_rejects_bad_x_handle(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], x="not@allowed")


def test_create_vault_rejects_non_https_website(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)],
                     website="http://example.com/octocat")


def test_create_vault_rejects_ip_literal_website(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)],
                     website="https://169.254.169.254/latest")


def test_create_vault_rejects_ip_literal_identity_url(contract, direct_vm, direct_bob, direct_carol):
    with pytest.raises(Exception):
        create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)],
                     identity_url="https://10.0.0.5/about")


def test_create_vault_accepts_empty_optional_fields(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    v = contract.get_vault(direct_bob)
    assert v["github_handle"] == ""
    assert v["identity_url"] == ""


def test_is_registered_and_list_vaults(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    assert contract.is_registered(direct_bob) is False
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    assert contract.is_registered(direct_bob) is True
    owners = contract.list_vaults()
    assert len(owners) == 1


def test_get_vault_unknown_address_raises(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        contract.get_vault(direct_bob)


def test_protocol_constants(contract):
    constants = contract.get_protocol_constants()
    assert constants["min_heartbeat_seconds"] == 14 * 86400
    assert constants["max_heartbeat_seconds"] == 1095 * 86400
    assert constants["grace_period_seconds"] == 45 * 86400
    assert constants["accelerated_grace_seconds"] == 7 * 86400
    assert constants["keeper_reward_wei"] == str(KEEPER_REWARD)
    assert constants["max_beneficiaries"] == 12
    assert constants["bps_total"] == 10000


# ---------------------------------------------------------------------------
# funding and withdrawals
# ---------------------------------------------------------------------------


def test_deposit_by_third_party(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_dave, direct_bob, 5 * GEN)
    assert contract.get_vault(direct_bob)["balance"] == str(5 * GEN)


def test_deposit_rejects_zero(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_dave
    direct_vm.value = 0
    with pytest.raises(Exception):
        contract.deposit(direct_bob)


def test_deposit_requires_existing_vault(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 1 * GEN
    with pytest.raises(Exception):
        contract.deposit(direct_bob)
    direct_vm.value = 0


def test_owner_withdraw(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_bob, direct_bob, 5 * GEN)
    direct_vm.sender = direct_bob
    contract.owner_withdraw(2 * GEN)
    assert contract.get_vault(direct_bob)["balance"] == str(3 * GEN)


def test_owner_withdraw_rejects_non_owner(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_bob, direct_bob, 5 * GEN)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.owner_withdraw(1 * GEN)


def test_owner_withdraw_rejects_over_balance(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.owner_withdraw(1 * GEN)


# ---------------------------------------------------------------------------
# configuration updates
# ---------------------------------------------------------------------------


def test_update_beneficiaries(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    contract.update_beneficiaries([direct_carol, direct_dave], [6000, 4000])
    listed = contract.get_beneficiaries(direct_bob)
    assert len(listed) == 2
    assert {x["address"].lower(): x["bps"] for x in listed} == {
        str(direct_carol).lower(): 6000,
        str(direct_dave).lower(): 4000,
    }


def test_update_beneficiaries_rejects_non_owner(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.update_beneficiaries([direct_dave], [10000])


def test_update_vitality_sources(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    contract.update_vitality_sources(VALID_GITHUB, VALID_X, VALID_WEBSITE)
    v = contract.get_vault(direct_bob)
    assert v["github_handle"] == VALID_GITHUB
    assert v["x_handle"] == VALID_X
    assert v["website_url"] == VALID_WEBSITE


def test_update_heartbeat_interval(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    contract.update_heartbeat_interval(30 * 86400)
    assert contract.get_vault(direct_bob)["heartbeat_interval_seconds"] == 30 * 86400
    with pytest.raises(Exception):
        contract.update_heartbeat_interval(86400)


def test_update_identity_url(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    contract.update_identity_url(VALID_ANCHOR)
    assert contract.get_vault(direct_bob)["identity_url"] == VALID_ANCHOR
    with pytest.raises(Exception):
        contract.update_identity_url("https://192.168.1.1/admin")


def test_configuration_locked_during_grace(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_dave, direct_bob)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.update_beneficiaries([direct_dave], [10000])
    with pytest.raises(Exception):
        contract.update_vitality_sources(VALID_GITHUB, "", "")
    with pytest.raises(Exception):
        contract.update_heartbeat_interval(30 * 86400)


# ---------------------------------------------------------------------------
# check-in and standby signer
# ---------------------------------------------------------------------------


def test_check_in_updates_timestamp(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, JUST_BEFORE_INTERVAL)
    direct_vm.sender = direct_bob
    contract.check_in(direct_bob)
    assert contract.get_vault(direct_bob)["last_check_in_at"] == JUST_BEFORE_INTERVAL


def test_check_in_rejects_strangers(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.check_in(direct_bob)


def test_standby_signer_can_check_in(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    contract.update_standby_signer(direct_dave, True)
    assert contract.get_vault(direct_bob)["has_standby_signer"] is True
    warp_to(direct_vm, JUST_BEFORE_INTERVAL)
    direct_vm.sender = direct_dave
    contract.check_in(direct_bob)
    assert contract.get_vault(direct_bob)["last_check_in_at"] == JUST_BEFORE_INTERVAL


def test_standby_signer_cannot_withdraw(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_bob, direct_bob, 2 * GEN)
    direct_vm.sender = direct_bob
    contract.update_standby_signer(direct_dave, True)
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.owner_withdraw(1 * GEN)
    with pytest.raises(Exception):
        contract.update_beneficiaries([direct_dave], [10000])


def test_disabled_standby_signer_loses_power(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    contract.update_standby_signer(direct_dave, True)
    contract.update_standby_signer(direct_dave, False)
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.check_in(direct_bob)


def test_standby_signer_nominable_during_grace(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    """An owner who notices the trigger late can still nominate help mid-grace -- the nomination
    itself moves nothing, and the standby signer's check-in then cancels the trigger."""
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_carol, direct_bob)
    direct_vm.sender = direct_bob
    contract.update_standby_signer(direct_dave, True)
    direct_vm.sender = direct_dave
    contract.check_in(direct_bob)
    assert contract.get_vault(direct_bob)["status"] == "ACTIVE"


def test_check_in_cancels_trigger(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_dave, direct_bob)
    assert contract.get_vault(direct_bob)["status"] == "GRACE_PERIOD"
    direct_vm.sender = direct_bob
    contract.check_in(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["status"] == "ACTIVE"
    assert v["grace_deadline"] == ""
    assert v["last_check_in_at"] == AFTER_INTERVAL


# ---------------------------------------------------------------------------
# lifecycle: trigger -> grace -> finalize -> claim
# ---------------------------------------------------------------------------


def test_trigger_too_early_fails(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, JUST_BEFORE_INTERVAL)
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.trigger_inheritance(direct_bob)


def test_trigger_is_permissionless_and_pays_keeper(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_bob, direct_bob, 3 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_dave, direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["status"] == "GRACE_PERIOD"
    assert v["grace_started_at"] == AFTER_INTERVAL
    assert v["grace_deadline"] == "2099-05-16T00:00:05Z"  # AFTER_INTERVAL + 45 days
    assert v["balance"] == str(3 * GEN - KEEPER_REWARD)


def test_trigger_skips_keeper_reward_when_broke(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_bob, direct_bob, 10)  # 10 wei, far below the keeper reward
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_dave, direct_bob)
    assert contract.get_vault(direct_bob)["balance"] == "10"


def test_trigger_twice_fails(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_dave, direct_bob)
    with pytest.raises(Exception):
        contract.trigger_inheritance(direct_bob)


def test_finalize_too_early_fails(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_dave, direct_bob)
    warp_to(direct_vm, JUST_BEFORE_GRACE_END)
    direct_vm.sender = direct_dave
    with pytest.raises(Exception):
        contract.finalize_inheritance(direct_bob)


def test_full_lifecycle_with_dust_sweep(contract, direct_vm, direct_alice, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 6000), (direct_dave, 4000)])
    fund(contract, direct_vm, direct_alice, direct_bob, 4 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    warp_to(direct_vm, AFTER_GRACE)
    direct_vm.sender = direct_alice
    contract.finalize_inheritance(direct_bob)
    distributable = 4 * GEN - 2 * KEEPER_REWARD
    v = contract.get_vault(direct_bob)
    assert v["status"] == "RELEASED"
    assert v["distributable_balance"] == str(distributable)
    assert v["released_at"] == AFTER_GRACE

    carol_share = distributable * 6000 // 10000
    claimable = contract.get_claimable_amount(direct_bob, direct_carol)
    assert claimable["claimable_wei"] == str(carol_share)

    direct_vm.sender = direct_carol
    contract.claim_share(direct_bob)
    # dave is the last beneficiary and sweeps the exact remainder (including any rounding dust)
    claimable = contract.get_claimable_amount(direct_bob, direct_dave)
    assert claimable["claimable_wei"] == str(distributable - carol_share)
    direct_vm.sender = direct_dave
    contract.claim_share(direct_bob)

    v = contract.get_vault(direct_bob)
    assert v["balance"] == "0"
    assert v["claimed_count"] == 2
    assert contract.get_claimable_amount(direct_bob, direct_carol)["claimable_wei"] == "0"


def test_claim_twice_fails(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_alice, direct_bob, 1 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    warp_to(direct_vm, AFTER_GRACE)
    direct_vm.sender = direct_alice
    contract.finalize_inheritance(direct_bob)
    direct_vm.sender = direct_carol
    contract.claim_share(direct_bob)
    with pytest.raises(Exception):
        contract.claim_share(direct_bob)


def test_claim_rejects_non_beneficiary(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_alice, direct_bob, 1 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    warp_to(direct_vm, AFTER_GRACE)
    contract.finalize_inheritance(direct_bob)
    direct_vm.sender = direct_alice  # alice kept the vault trigger/finalize, but is no beneficiary
    with pytest.raises(Exception):
        contract.claim_share(direct_bob)


def test_claim_rejects_before_release(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.claim_share(direct_bob)


def test_check_in_on_released_vault_fails_loudly(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_alice, direct_bob, 1 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    warp_to(direct_vm, AFTER_GRACE)
    contract.finalize_inheritance(direct_bob)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.check_in(direct_bob)


def test_deposit_after_release_fails(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    warp_to(direct_vm, AFTER_GRACE)
    contract.finalize_inheritance(direct_bob)
    direct_vm.sender = direct_alice
    direct_vm.value = 1 * GEN
    with pytest.raises(Exception):
        contract.deposit(direct_bob)
    direct_vm.value = 0


def test_withdraw_during_grace_fails(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    fund(contract, direct_vm, direct_alice, direct_bob, 1 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.owner_withdraw(1 * GEN)


def test_seconds_until_views(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    assert contract.seconds_until_triggerable(direct_bob) == DEFAULT_INTERVAL
    warp_to(direct_vm, JUST_BEFORE_INTERVAL)
    assert contract.seconds_until_triggerable(direct_bob) == 1
    warp_to(direct_vm, AFTER_INTERVAL)
    assert contract.seconds_until_triggerable(direct_bob) < 0
    trigger(contract, direct_vm, direct_dave, direct_bob)
    assert contract.seconds_until_triggerable(direct_bob) == 0
    assert contract.seconds_until_releasable(direct_bob) > 0
    warp_to(direct_vm, AFTER_GRACE)
    assert contract.seconds_until_releasable(direct_bob) < 0


# ---------------------------------------------------------------------------
# vitality scan (consensus round 1)
# ---------------------------------------------------------------------------


def _triggered_vault_with_sources(contract, direct_vm, owner, keeper, beneficiary, funds=1 * GEN):
    warp_to(direct_vm, NOW)
    create_vault(
        contract, direct_vm, owner, [(beneficiary, 10000)],
        github=VALID_GITHUB, x=VALID_X, website=VALID_WEBSITE,
    )
    fund(contract, direct_vm, owner, owner, funds)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, keeper, owner)


def test_vitality_scan_single_active_source_cancels(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_sources(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    mock_vitality(direct_vm, github="ACTIVE_AFTER_CHECKIN", x="UNDETERMINED", website="QUIET_AFTER_LAST_CHECKIN")
    contract.run_vitality_scan(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["status"] == "ACTIVE"  # auto-cancelled, exactly like a check-in
    assert v["vitality_verdict"] == "VITALITY_FOUND"
    assert v["last_check_in_at"] == AFTER_INTERVAL
    assert v["grace_deadline"] == ""
    assert v["vitality_scan_count"] == 1


def test_vitality_scan_all_quiet_keeps_grace(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_sources(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    mock_vitality(direct_vm, github="QUIET_AFTER_LAST_CHECKIN", x="QUIET_AFTER_LAST_CHECKIN",
                  website="QUIET_AFTER_LAST_CHECKIN")
    contract.run_vitality_scan(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["status"] == "GRACE_PERIOD"
    assert v["vitality_verdict"] == "NO_VITALITY_DETECTED"
    assert v["grace_deadline"] == "2099-05-16T00:00:05Z"  # standard timeline untouched


def test_vitality_scan_one_undetermined_forces_inconclusive(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_sources(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    mock_vitality(direct_vm, github="QUIET_AFTER_LAST_CHECKIN", x="UNDETERMINED",
                  website="QUIET_AFTER_LAST_CHECKIN")
    contract.run_vitality_scan(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["vitality_verdict"] == "INCONCLUSIVE"
    assert v["status"] == "GRACE_PERIOD"


def test_vitality_scan_needs_grace_status(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], github=VALID_GITHUB)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.run_vitality_scan(direct_bob)


def test_vitality_scan_needs_registered_sources(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    with pytest.raises(Exception):
        contract.run_vitality_scan(direct_bob)


def test_vitality_scan_cooldown(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_sources(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    mock_vitality(direct_vm, github="QUIET_AFTER_LAST_CHECKIN", x="QUIET_AFTER_LAST_CHECKIN",
                  website="QUIET_AFTER_LAST_CHECKIN")
    contract.run_vitality_scan(direct_bob)
    with pytest.raises(Exception):
        contract.run_vitality_scan(direct_bob)
    warp_to(direct_vm, AFTER_SCAN_COOLDOWN)
    contract.run_vitality_scan(direct_bob)  # allowed again once the cooldown elapsed
    assert contract.get_vault(direct_bob)["vitality_scan_count"] == 2


def test_vitality_scan_private_dns_overrides_model_claim(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    """Even when the model claims the website shows activity, the code-observed fetch facts win:
    a host resolving to a private/metadata address is NOT_AVAILABLE and cannot ground a
    VITALITY_FOUND verdict. Fetch-target hardening is a code boundary, not a prompt request."""
    _triggered_vault_with_sources(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    mock_vitality(direct_vm, github="QUIET_AFTER_LAST_CHECKIN", x="QUIET_AFTER_LAST_CHECKIN",
                  website="ACTIVE_AFTER_CHECKIN", private_dns=True)
    contract.run_vitality_scan(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["vitality_verdict"] == "NO_VITALITY_DETECTED"  # website forced NOT_AVAILABLE in code
    assert v["status"] == "GRACE_PERIOD"


# ---------------------------------------------------------------------------
# death-evidence review (consensus round 2)
# ---------------------------------------------------------------------------


def _triggered_vault_with_anchor(contract, direct_vm, owner, keeper, beneficiary):
    warp_to(direct_vm, NOW)
    create_vault(
        contract, direct_vm, owner, [(beneficiary, 10000)],
        identity_url=VALID_ANCHOR, github=VALID_GITHUB,
    )
    fund(contract, direct_vm, owner, owner, 1 * GEN)
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, keeper, owner)


def test_death_review_confirmed_accelerates(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm, verdict="CONFIRMS_DEATH", match="true", confidence="high")
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    v = contract.get_vault(direct_bob)
    assert v["death_verdict"] == "DEATH_EVIDENCE_CONFIRMED"
    assert v["death_confirmed_at"] == DEATH_REVIEW_TIME
    assert v["grace_deadline"] == ACCELERATED_DEADLINE  # shortened to the 7-day minimum
    assert v["status"] == "GRACE_PERIOD"


def test_death_review_accelerated_finalize(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm)
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    warp_to(direct_vm, AFTER_ACCELERATED_DEADLINE)
    contract.finalize_inheritance(direct_bob)
    assert contract.get_vault(direct_bob)["status"] == "RELEASED"


def test_death_review_ambiguous_page_defeats_review(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm, verdict="UNDETERMINED", match="false", confidence="low")
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    v = contract.get_vault(direct_bob)
    assert v["death_verdict"] == "DEATH_EVIDENCE_NOT_CONFIRMED"
    assert v["grace_deadline"] == "2099-05-16T00:00:05Z"  # standard 45-day deadline untouched
    assert v["death_confirmed_at"] == ""


def test_death_review_low_confidence_defeats_review(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm, verdict="CONFIRMS_DEATH", match="true", confidence="low")
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    assert contract.get_vault(direct_bob)["death_verdict"] == "DEATH_EVIDENCE_NOT_CONFIRMED"


def test_death_review_unknown_anchor_identity_defeats_review(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm, anchor_identity="unknown")
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    assert contract.get_vault(direct_bob)["death_verdict"] == "DEATH_EVIDENCE_NOT_CONFIRMED"


def test_check_in_still_wins_after_confirmed_review(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    """A fake obituary, however convincing to a consensus round, can never beat key control."""
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm)
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    assert contract.get_vault(direct_bob)["death_verdict"] == "DEATH_EVIDENCE_CONFIRMED"
    warp_to(direct_vm, AFTER_DEATH_COOLDOWN)
    direct_vm.sender = direct_bob
    contract.check_in(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["status"] == "ACTIVE"
    assert v["grace_deadline"] == ""
    assert v["death_confirmed_at"] == ""


def test_death_review_needs_identity_anchor(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)
    with pytest.raises(Exception):
        contract.run_death_evidence_review(direct_bob, [VALID_NEWS])


def test_death_review_needs_grace_status(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)], identity_url=VALID_ANCHOR)
    with pytest.raises(Exception):
        contract.run_death_evidence_review(direct_bob, [VALID_NEWS])


def test_death_review_rejects_ip_literal_evidence(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    with pytest.raises(Exception):
        contract.run_death_evidence_review(direct_bob, ["https://169.254.169.254/evidence"])
    with pytest.raises(Exception):
        contract.run_death_evidence_review(direct_bob, ["http://not-secure.example.com/obit"])


def test_death_review_rejects_empty_or_too_many_urls(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    with pytest.raises(Exception):
        contract.run_death_evidence_review(direct_bob, [])
    with pytest.raises(Exception):
        contract.run_death_evidence_review(
            direct_bob, [VALID_NEWS, VALID_NEWS, VALID_NEWS, VALID_NEWS]
        )


def test_death_review_cooldown(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    _triggered_vault_with_anchor(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    warp_to(direct_vm, DEATH_REVIEW_TIME)
    mock_death_review(direct_vm, verdict="UNDETERMINED", match="false", confidence="low")
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    with pytest.raises(Exception):
        contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    warp_to(direct_vm, AFTER_DEATH_COOLDOWN)
    contract.run_death_evidence_review(direct_bob, [VALID_NEWS])
    assert contract.get_vault(direct_bob)["death_review_count"] == 2


# ---------------------------------------------------------------------------
# edge cases and read-path guards
# ---------------------------------------------------------------------------


def test_update_vitality_sources_rejects_bad_url(contract, direct_vm, direct_bob, direct_carol):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.update_vitality_sources("", "", "ftp://example.com/octocat")


def test_get_claimable_for_unknown_caller(contract, direct_vm, direct_bob, direct_carol, direct_dave):
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    result = contract.get_claimable_amount(direct_bob, direct_dave)
    assert result["is_beneficiary"] is False
    assert result["claimable_wei"] == "0"


def test_empty_vault_full_lifecycle(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    """A vault with zero balance still transitions cleanly; claiming into emptiness fails loudly."""
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    warp_to(direct_vm, AFTER_INTERVAL)
    trigger(contract, direct_vm, direct_alice, direct_bob)  # no reward: balance is 0
    warp_to(direct_vm, AFTER_GRACE)
    contract.finalize_inheritance(direct_bob)
    v = contract.get_vault(direct_bob)
    assert v["status"] == "RELEASED"
    assert v["distributable_balance"] == "0"
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.claim_share(direct_bob)


def test_seconds_until_releasable_zero_outside_grace(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    create_vault(contract, direct_vm, direct_bob, [(direct_carol, 10000)])
    assert contract.seconds_until_releasable(direct_bob) == 0


def test_get_beneficiaries_unknown_owner_raises(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        contract.get_beneficiaries(direct_bob)


def test_trigger_unknown_vault_raises(contract, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        contract.trigger_inheritance(direct_bob)


def test_retrigger_blocked_after_vitality_cancel(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    """A VITALITY_FOUND cancel restarts the heartbeat from the scan time -- the vault cannot be
    re-triggered the same minute it was rescued."""
    _triggered_vault_with_sources(contract, direct_vm, direct_bob, direct_alice, direct_carol)
    mock_vitality(direct_vm, github="ACTIVE_AFTER_CHECKIN")
    contract.run_vitality_scan(direct_bob)
    assert contract.get_vault(direct_bob)["status"] == "ACTIVE"
    with pytest.raises(Exception):
        contract.trigger_inheritance(direct_bob)
