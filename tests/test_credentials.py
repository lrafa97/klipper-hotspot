import os
import stat

import pytest

from klipper_hotspot.credentials import (
    PASSWORD_ALPHABET,
    PASSWORD_LENGTH,
    Credentials,
    create_credentials,
    generate_credentials,
    load_credentials,
)
from klipper_hotspot.errors import CredentialsError


def test_generated_shape():
    creds = generate_credentials("Acme")
    assert creds.ssid.startswith("Acme-")
    assert len(creds.ssid) == len("Acme-") + 4
    assert len(creds.password) == PASSWORD_LENGTH
    assert set(creds.password) <= set(PASSWORD_ALPHABET)


def test_two_machines_do_not_share_credentials():
    seen = {generate_credentials("Acme").password for _ in range(50)}
    assert len(seen) == 50


def test_repr_never_contains_the_password():
    creds = Credentials(ssid="Klipper-ABCD", password="hunter2hunter2")
    assert "hunter2" not in repr(creds)
    assert "hunter2" not in str(creds)


def test_create_writes_0600_and_roundtrips(tmp_path):
    path = tmp_path / "etc" / "credentials"
    created = create_credentials(str(path), "Klipper")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_credentials(str(path)) == created
    assert not list(path.parent.glob("*.tmp"))


def test_create_refuses_to_overwrite(tmp_path):
    path = str(tmp_path / "credentials")
    create_credentials(path, "Klipper")
    with pytest.raises(CredentialsError, match="already exist"):
        create_credentials(path, "Klipper")


def test_load_rejects_group_or_world_readable_file(tmp_path):
    path = tmp_path / "credentials"
    create_credentials(str(path), "Klipper")
    os.chmod(path, 0o644)
    with pytest.raises(CredentialsError, match="chmod 600"):
        load_credentials(str(path))


def test_load_missing_file_points_to_init(tmp_path):
    with pytest.raises(CredentialsError, match="init"):
        load_credentials(str(tmp_path / "nope"))


@pytest.mark.parametrize("password", ["short", "x" * 64])
def test_load_rejects_invalid_wpa_password(tmp_path, password):
    path = tmp_path / "credentials"
    path.write_text(f"[hotspot]\nssid = Klipper-ABCD\npassword = {password}\n")
    os.chmod(path, 0o600)
    with pytest.raises(CredentialsError, match="8-63"):
        load_credentials(str(path))


def test_load_rejects_malformed_file(tmp_path):
    path = tmp_path / "credentials"
    path.write_text("garbage")
    os.chmod(path, 0o600)
    with pytest.raises(CredentialsError, match="malformed"):
        load_credentials(str(path))
