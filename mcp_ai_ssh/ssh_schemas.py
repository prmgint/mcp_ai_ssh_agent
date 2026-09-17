from typing import Optional, Literal
from pydantic import BaseModel, SecretStr, Field

class ConnectParams(BaseModel):
    host: str
    username: str
    auth_type: Literal["password", "key"] = "password"
    password: Optional[SecretStr] = Field(default=None, repr=False)
    private_key_path: Optional[str] = None
    private_key_passphrase: Optional[SecretStr] = Field(default=None, repr=False)
    auth: Optional[SecretStr] = Field(default=None, repr=False, description="Legacy fallback for password. Use 'password' field instead.")
    port: int = 22
    timeout: int = 30

    def get_password(self) -> Optional[str]:
        if self.password:
            return self.password.get_secret_value()
        if self.auth:
            return self.auth.get_secret_value()
        return None

    def get_passphrase(self) -> Optional[str]:
        if self.private_key_passphrase:
            return self.private_key_passphrase.get_secret_value()
        return None
