"""Answers for malformed requests: a clear 4xx instead of a 500 and a stack trace in the logs.

- Validation errors never echo the submitted values (a mistyped password would come back in the
  response, and a value the JSON encoder cannot write would turn the 422 into a 500).
- Text the database or UTF-8 cannot store (NUL characters, lone surrogates) is refused with 422.
- JSON nested deeper than Python can parse is refused with 400.
"""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError

INVALID_TEXT = "The request contains characters that cannot be stored."


def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


def _invalid_text(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": INVALID_TEXT})


def _too_deep(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": "The request is nested too deeply."})


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(UnicodeEncodeError, _invalid_text)
    app.add_exception_handler(DataError, _invalid_text)
    app.add_exception_handler(RecursionError, _too_deep)
