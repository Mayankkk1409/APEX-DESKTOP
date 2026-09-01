import pytest
from pydantic import ValidationError

from app.schemas.auth import DEFAULT_PAPER_BALANCE, SignupRequest


def test_real_brokerage_rejects_starting_balance_field() -> None:
    with pytest.raises(ValidationError) as exc:
        SignupRequest(
            full_name="Ada Lovelace",
            username="ada",
            email="ada@example.com",
            password="ApexDesk!23",
            confirm_password="ApexDesk!23",
            account_mode="real_brokerage",
            starting_balance=25000,
        )
    assert "starting_balance" in str(exc.value)


def test_real_brokerage_rejects_null_starting_balance_key() -> None:
    with pytest.raises(ValidationError):
        SignupRequest.model_validate(
            {
                "full_name": "Ada Lovelace",
                "username": "ada",
                "email": "ada@example.com",
                "password": "ApexDesk!23",
                "confirm_password": "ApexDesk!23",
                "account_mode": "real_brokerage",
                "starting_balance": None,
            }
        )


def test_paper_funded_accepts_explicit_starting_balance() -> None:
    req = SignupRequest(
        full_name="Ada Lovelace",
        username="ada",
        email="ada@example.com",
        password="ApexDesk!23",
        confirm_password="ApexDesk!23",
        account_mode="paper_funded",
        starting_balance=25000,
    )
    assert req.starting_balance == 25000


def test_paper_funded_allows_omitted_starting_balance() -> None:
    req = SignupRequest(
        full_name="Ada Lovelace",
        username="ada",
        email="ada@example.com",
        password="ApexDesk!23",
        confirm_password="ApexDesk!23",
        account_mode="paper_funded",
    )
    assert req.starting_balance is None


def test_paper_funded_rejects_low_starting_balance() -> None:
    with pytest.raises(ValidationError, match="starting_balance must be at least 1000"):
        SignupRequest(
            full_name="Ada Lovelace",
            username="ada",
            email="ada@example.com",
            password="ApexDesk!23",
            confirm_password="ApexDesk!23",
            account_mode="paper_funded",
            starting_balance=500,
        )


def test_default_paper_balance_constant() -> None:
    assert DEFAULT_PAPER_BALANCE == 100_000.0
