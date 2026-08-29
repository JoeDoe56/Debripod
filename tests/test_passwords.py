from debripod import auth
from debripod.passwords import check_password_hash, generate_password_hash, password_hash_supported, verify_password_hash


PASSWORD = "correct horse battery staple"
LEGACY_SCRYPT = "scrypt:32768:8:1$g0PonlXnaTYJpZCA$d4dd31b60e03c01e1410c259253186516b75f7e7a9b77e872982354fb326b43a52d1db985d90caecb4cd6d34172b7abd28ef800c5bca8f008c35e0d3dfb7c9f6"
LEGACY_PBKDF2 = "pbkdf2:sha256:260000$52jRzHf6XZsVEgaE$cacd5773b09d1118e326b496e9cb113f55dec679064fd4755b4e50565876be74"


def test_current_hash_round_trip_and_wrong_password():
    encoded = generate_password_hash(PASSWORD)
    assert encoded.startswith("scrypt:32768:8:1$")
    assert check_password_hash(encoded, PASSWORD)
    assert not check_password_hash(encoded, "wrong")
    assert verify_password_hash(encoded, PASSWORD) == (True, False)
    assert password_hash_supported(encoded)


def test_fixed_legacy_scrypt_vector_remains_valid():
    assert password_hash_supported(LEGACY_SCRYPT)
    assert verify_password_hash(LEGACY_SCRYPT, PASSWORD) == (True, False)
    assert not check_password_hash(LEGACY_SCRYPT, "wrong")


def test_fixed_legacy_pbkdf2_vector_requests_upgrade():
    assert password_hash_supported(LEGACY_PBKDF2)
    assert verify_password_hash(LEGACY_PBKDF2, PASSWORD) == (True, True)
    assert not check_password_hash(LEGACY_PBKDF2, "wrong")


def test_malformed_or_expensive_hashes_fail_closed():
    assert not check_password_hash("", PASSWORD)
    assert not check_password_hash("scrypt:1073741824:8:1$salt$00", PASSWORD)
    assert not check_password_hash("pbkdf2:sha256:999999999$salt$00", PASSWORD)
    assert not password_hash_supported("x")
    assert not password_hash_supported("scrypt:32768:8:1$salt$00")


def test_successful_legacy_login_persists_a_current_hash(monkeypatch):
    user = {"username": "alice", "password_hash": LEGACY_PBKDF2}
    saved: list[list[dict[str, str]]] = []
    monkeypatch.setattr(auth, "_valid_users", lambda: [dict(user)])
    monkeypatch.setattr(auth, "_save_users", lambda users: saved.append(users))

    assert auth._verify_user_password(user, PASSWORD)
    upgraded = saved[0][0]["password_hash"]
    assert upgraded != LEGACY_PBKDF2
    assert verify_password_hash(upgraded, PASSWORD) == (True, False)
