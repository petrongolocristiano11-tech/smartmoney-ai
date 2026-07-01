from pydantic import BaseModel


class WalletCreate(BaseModel):
    address: str
    