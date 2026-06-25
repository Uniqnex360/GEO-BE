from pydantic import BaseModel, EmailStr


class AccessToken(BaseModel):
    email: EmailStr
    password: str


class RefreshToken(BaseModel):
    refresh_token: str
