import os
import sys

import pytest

_real_unlink = os.unlink


def _windows_safe_unlink(path, *args, **kwargs):
    try:
        return _real_unlink(path, *args, **kwargs)
    except PermissionError:
        return None


os.unlink = _windows_safe_unlink


def warp_to(direct_vm, iso: str) -> None:
    """Direct-VM time travel: sets the runner clock and mirrors the ISO datetime into the
    message metadata the contract reads from gl.message_raw."""
    direct_vm.warp(iso)
    gl = sys.modules.get("genlayer.gl")
    if gl is None:
        return
    raw = getattr(gl, "message_raw", None)
    if isinstance(raw, dict):
        raw["datetime"] = iso
    nested = getattr(getattr(gl, "message", None), "raw", None)
    if isinstance(nested, dict):
        nested["datetime"] = iso


@pytest.fixture
def contract(direct_deploy, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    deployed = direct_deploy("contracts/VitalVault.py")
    direct_vm.sender = direct_alice
    return deployed
