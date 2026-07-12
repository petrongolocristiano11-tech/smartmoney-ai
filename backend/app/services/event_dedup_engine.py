from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_processed_events_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS processed_events (
                id SERIAL PRIMARY KEY,
                event_key VARCHAR(255) UNIQUE NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    db.commit()


def is_event_processed(
    db: Session,
    event_key: str,
) -> bool:
    ensure_processed_events_table(db)

    result = db.execute(
        text(
            """
            SELECT 1
            FROM processed_events
            WHERE event_key = :event_key
            LIMIT 1
            """
        ),
        {"event_key": event_key},
    ).first()

    return result is not None


def mark_event_processed(
    db: Session,
    event_key: str,
    event_type: str,
) -> None:
    ensure_processed_events_table(db)

    db.execute(
        text(
            """
            INSERT INTO processed_events (
                event_key,
                event_type
            )
            VALUES (
                :event_key,
                :event_type
            )
            ON CONFLICT (event_key) DO NOTHING
            """
        ),
        {
            "event_key": event_key,
            "event_type": event_type,
        },
    )

    db.commit() 