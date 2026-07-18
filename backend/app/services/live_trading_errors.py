class LiveTradingError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "LIVE_TRADING_ERROR",
        status_code: int = 409,
        payload: dict | None = None,
    ):
        super().__init__(message)

        self.message = message
        self.code = code
        self.status_code = status_code
        self.payload = payload or {}


class JupiterSwapError(LiveTradingError):
    pass


class SolanaSignerError(LiveTradingError):
    pass


class SolanaRpcError(LiveTradingError):
    pass 