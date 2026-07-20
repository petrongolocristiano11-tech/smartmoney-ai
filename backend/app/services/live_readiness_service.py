from datetime import timedelta

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.services.live_platform_config_service import (
    disarm_live_platform,
    get_or_create_platform_config,
    is_live_armed,
    utc_now,
)
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.live_trading_policy_service import (
    get_or_create_live_policy,
    record_live_event,
)
from backend.app.services.solana_rpc import SolanaRpcClient
from backend.app.services.solana_transaction_signer import SolanaTransactionSigner


def build_live_readiness(
    db: Session,
    *,
    rpc_client: SolanaRpcClient | None = None,
    signer: SolanaTransactionSigner | None = None,
) -> dict:
    policy = get_or_create_live_policy(db)
    config = get_or_create_platform_config(db)
    checks: list[dict] = []

    def add(code: str, label: str, passed: bool, message: str, *, blocking: bool = True):
        checks.append(
            {
                "code": code,
                "label": label,
                "passed": bool(passed),
                "blocking": blocking,
                "message": message,
            }
        )

    add(
        "MODE_LIVE",
        "Modalità LIVE",
        policy.mode == "LIVE",
        "La policy deve essere impostata su LIVE." if policy.mode != "LIVE" else "Modalità LIVE attiva.",
    )
    add(
        "KILL_SWITCH_RELEASED",
        "Kill switch",
        not policy.kill_switch,
        "Il kill switch deve essere rilasciato." if policy.kill_switch else "Kill switch libero.",
    )
    add(
        "SOURCE_WALLETS",
        "Wallet sorgente",
        bool(policy.source_wallets),
        "Configura almeno un wallet sorgente." if not policy.source_wallets else f"{len(policy.source_wallets)} wallet sorgente configurati.",
    )
    add(
        "LIVE_CONFIGURATION",
        "Credenziali LIVE",
        settings.is_live_trading_configured,
        "Configura wallet, chiave, Jupiter e LIVE_TRADING_API_KEY." if not settings.is_live_trading_configured else "Configurazione LIVE completa.",
    )
    add(
        "TOKEN_SAFETY",
        "Sicurezza token",
        config.token_safety_enabled and config.token_safety_fail_closed,
        "Abilita la sicurezza token in modalità fail-closed." if not (config.token_safety_enabled and config.token_safety_fail_closed) else "Sicurezza token fail-closed attiva.",
    )
    add(
        "SIMULATION_REQUIRED",
        "Simulazione transazione",
        settings.LIVE_TRADING_REQUIRE_SIMULATION,
        "Abilita LIVE_TRADING_REQUIRE_SIMULATION." if not settings.LIVE_TRADING_REQUIRE_SIMULATION else "Simulazione pre-invio obbligatoria.",
    )

    wallet_matches = False
    signer_message = "Signer non verificato."
    if settings.is_live_trading_configured:
        try:
            signer = signer or SolanaTransactionSigner()
            derived = signer.wallet_address
            wallet_matches = derived == settings.LIVE_TRADING_WALLET_ADDRESS
            signer_message = "Signer e wallet configurato corrispondono." if wallet_matches else "Il signer non corrisponde al wallet configurato."
        except Exception as exception:
            signer_message = f"Signer non valido: {type(exception).__name__}."
    add("SIGNER_MATCH", "Firma transazioni", wallet_matches, signer_message)

    balance_ok = False
    balance_message = "Saldo non verificato."
    if settings.LIVE_TRADING_WALLET_ADDRESS:
        try:
            rpc_client = rpc_client or SolanaRpcClient()
            balance = rpc_client.get_balance_sol(settings.LIVE_TRADING_WALLET_ADDRESS)
            minimum = policy.min_wallet_reserve_sol + min(policy.fixed_buy_size_sol, policy.max_order_size_sol)
            balance_ok = balance >= minimum
            balance_message = f"Saldo {balance:.6f} SOL; minimo operativo {minimum:.6f} SOL."
        except Exception as exception:
            balance_message = f"RPC non disponibile: {type(exception).__name__}."
    add("WALLET_BALANCE", "Saldo operativo", balance_ok, balance_message)

    armed = is_live_armed(config)
    ready = all(check["passed"] for check in checks if check["blocking"])

    return {
        "ready": ready,
        "armed": armed,
        "armed_until": config.live_armed_until if armed else None,
        "checks": checks,
    }


def arm_live_platform(
    db: Session,
    *,
    confirmation: str,
    rpc_client: SolanaRpcClient | None = None,
    signer: SolanaTransactionSigner | None = None,
) -> dict:
    if confirmation != "ARM LIVE FOR 15 MINUTES":
        raise LiveTradingError(
            "Conferma non valida. Usa esattamente ARM LIVE FOR 15 MINUTES.",
            code="LIVE_ARM_CONFIRMATION_REQUIRED",
            status_code=422,
        )

    readiness = build_live_readiness(db, rpc_client=rpc_client, signer=signer)
    if not readiness["ready"]:
        raise LiveTradingError(
            "I controlli di readiness LIVE non sono tutti superati.",
            code="LIVE_READINESS_FAILED",
            status_code=409,
            payload={"checks": readiness["checks"]},
        )

    config = get_or_create_platform_config(db)
    config.live_armed_until = utc_now() + timedelta(minutes=config.live_arm_ttl_minutes)
    record_live_event(
        db,
        event_type="LIVE_ARMED",
        severity="WARNING",
        message=f"Esecuzione LIVE armata per {config.live_arm_ttl_minutes} minuti.",
        payload={"armed_until": config.live_armed_until.isoformat()},
    )
    db.commit()
    db.refresh(config)

    readiness = build_live_readiness(db, rpc_client=rpc_client, signer=signer)
    return {
        "armed": True,
        "armed_until": config.live_armed_until,
        "readiness": readiness,
    }


def disarm_live(db: Session) -> dict:
    config = disarm_live_platform(
        db,
        reason="Esecuzione LIVE disarmata manualmente.",
    )
    return {
        "armed": False,
        "armed_until": None,
        "readiness": build_live_readiness(db),
    }
