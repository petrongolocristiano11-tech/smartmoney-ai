import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import (
    RequestValidationError,
)
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import (
    HTTPException as StarletteHTTPException,
)


logger = logging.getLogger("smartmoney.errors")


def get_request_id(
    request: Request,
) -> str | None:
    return getattr(
        request.state,
        "request_id",
        None,
    )


async def http_exception_handler(
    request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exception.status_code,
        content=jsonable_encoder(
            {
                "detail": exception.detail,
                "request_id": get_request_id(
                    request
                ),
            }
        ),
        headers=exception.headers,
    )


async def validation_exception_handler(
    request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            {
                "detail": exception.errors(),
                "request_id": get_request_id(
                    request
                ),
            }
        ),
    )


async def database_exception_handler(
    request: Request,
    exception: SQLAlchemyError,
) -> JSONResponse:
    request_id = get_request_id(request)

    logger.exception(
        "database_error request_id=%s path=%s",
        request_id,
        request.url.path,
    )

    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Database temporaneamente "
                "non disponibile."
            ),
            "request_id": request_id,
        },
    )


async def unhandled_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    request_id = get_request_id(request)

    logger.exception(
        "unhandled_error request_id=%s path=%s",
        request_id,
        request.url.path,
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "Errore interno del server."
            ),
            "request_id": request_id,
        },
    )


def register_exception_handlers(
    app: FastAPI,
) -> None:
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )

    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )

    app.add_exception_handler(
        SQLAlchemyError,
        database_exception_handler,
    )

    app.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    ) 