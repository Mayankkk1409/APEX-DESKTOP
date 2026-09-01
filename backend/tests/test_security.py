from app.security import hash_password, password_strength, verify_password


def test_password_hash_and_verify() -> None:
    hashed = hash_password("ApexDemo!23")
    assert hashed != "ApexDemo!23"
    assert verify_password("ApexDemo!23", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_strength_meter() -> None:
    weak = password_strength("abc")
    strong = password_strength("ApexDesk!2026")
    assert weak["score"] < strong["score"]
    assert strong["checks"]["symbol"]
    assert strong["checks"]["digit"]
