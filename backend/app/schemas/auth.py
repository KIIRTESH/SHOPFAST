from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional


class RegisterRequest(BaseModel):
    username: str
    display_name: str
    pin: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) < 3 or len(v) > 32:
            raise ValueError("Username must be 3–32 characters.")
        if not v.replace("_", "").replace(".", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, underscores, and dots.")
        return v

    @field_validator("display_name")
    @classmethod
    def display_name_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2 or len(v) > 64:
            raise ValueError("Display name must be 2–64 characters.")
        return v

    @field_validator("pin")
    @classmethod
    def pin_valid(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) < 4 or len(v) > 8:
            raise ValueError("PIN must be 4–8 digits.")
        return v


class LoginRequest(BaseModel):
    username: str
    pin: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.strip().lower()


class AuthResponse(BaseModel):
    token: str
    user_id: int
    username: str
    display_name: str
    role: str
    counter_number: Optional[str] = None
    expires_at: str  # ISO datetime string


class UserProfile(BaseModel):
    user_id: int
    username: str
    display_name: str
    role: str
    counter_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
