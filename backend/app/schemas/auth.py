from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

AccountMode = Literal["paper_funded", "real_brokerage"]
PAPER_PRESETS = {10000, 25000, 50000, 100000}
DEFAULT_PAPER_BALANCE = 100_000.0


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_\.\-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str
    account_mode: AccountMode
    starting_balance: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def reject_starting_balance_on_real(cls, data):
        if isinstance(data, dict):
            if data.get("account_mode") == "real_brokerage" and "starting_balance" in data:
                raise ValueError("starting_balance is not accepted for real_brokerage")
        return data

    @model_validator(mode="after")
    def validate_passwords_and_balance(self) -> "SignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        if self.account_mode == "paper_funded" and self.starting_balance is not None:
            if self.starting_balance < 1000:
                raise ValueError("starting_balance must be at least 1000")
        return self


class LoginRequest(BaseModel):
    username: str
    password: str


class OtpRequest(BaseModel):
    username: str


class OtpVerifyRequest(BaseModel):
    username: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str

    @model_validator(mode="after")
    def validate_passwords(self) -> "ForgotPasswordRequest":
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        return self


class ForgotPasswordVerifyRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    brokerage_connected: bool
    first_login: bool
    account_mode: AccountMode
    show_connect_modal: bool


class UserOut(BaseModel):
    id: str
    full_name: str
    username: str
    email: str
    account_mode: AccountMode
    brokerage_connected: bool
    connect_later_banner: bool
    first_login_completed: bool
    cash_balance: float
    buying_power: float
    portfolio_value: float
    starting_balance: Optional[float] = None

    model_config = {"from_attributes": True}


class ConnectBrokerageRequest(BaseModel):
    later: bool = False


class PasswordStrengthRequest(BaseModel):
    password: str
