"""Run a parser in a child process with memory and CPU limits.

Documents come from customers and from the web: a crafted or broken file must fail on its own,
never exhaust the memory of the worker shared by every customer (and crash it again at each
retry). The child is forked (Linux) in a process group of its own, gets an address-space limit
(standard parsers only: Docling's ML runtime reserves large virtual areas) and a CPU-time limit,
parses, cuts the pages into chunks (also under those limits) and sends the result back. When it
ends, its whole process group is killed, so programs it started (Tesseract) never outlive it, also
when the job times out.

MENTIS_PARSE_MEMORY_MB (default 2048, 0 = no limit) and MENTIS_PARSE_CPU_SECONDS (default 1500)
tune the limits; MENTIS_PARSE_ISOLATION=0 parses in the worker process itself.
"""

import multiprocessing
import os
import pickle
import resource
import signal

from app.ingestion.types import ParseLimits, ParseResult


class ParseLimitExceeded(ValueError):
    """The file needed more memory or time than allowed to read (public message)."""


def _env_int(name: str, default: int) -> int:
    try:
        return max(int(os.getenv(name, str(default))), 0)
    except ValueError:
        return default


def _child(conn, data: bytes, file_type: str, limits: ParseLimits, parser: str, memory_mb: int, cpu_s: int) -> None:
    from app.ingestion import parse
    from app.ingestion.chunking import chunk_pages

    try:
        os.setsid()  # a process group of its own: the parent kills it whole (OCR programs included)
    except OSError:
        pass
    try:
        if memory_mb and parser != "docling":
            resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
        if cpu_s and parser != "docling":  # Docling's threads add up CPU time: the job timeout applies
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
        result = parse(data, file_type, limits, parser=parser)
        result.chunks = chunk_pages(result.pages)
        conn.send(("ok", result))
    except MemoryError:
        conn.send(("limit", None))
    except Exception as e:  # noqa: BLE001 - sent to the parent, which raises it there
        try:
            conn.send(("error", e))
        except Exception:  # noqa: BLE001 - an exception that cannot be pickled
            conn.send(("error", ValueError(str(e)[:300])))
    finally:
        conn.close()


def _kill_group(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def parse_isolated(data: bytes, file_type: str, limits: ParseLimits, parser: str = "standard") -> ParseResult:
    from app.ingestion import parse

    if os.getenv("MENTIS_PARSE_ISOLATION", "1") == "0":
        from app.ingestion.chunking import chunk_pages

        result = parse(data, file_type, limits, parser=parser)
        result.chunks = chunk_pages(result.pages)
        return result
    memory_mb = _env_int("MENTIS_PARSE_MEMORY_MB", 2048)
    cpu_s = _env_int("MENTIS_PARSE_CPU_SECONDS", 1500)
    ctx = multiprocessing.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(child, data, file_type, limits, parser, memory_mb, cpu_s),
                       daemon=parser != "docling")  # Docling may start processes of its own
    proc.start()
    child.close()
    try:
        status, payload = parent.recv()  # EOFError when the child was killed (memory, CPU)
    except EOFError:
        status, payload = "limit", None
    except (OSError, pickle.UnpicklingError, AttributeError, ImportError, TypeError):
        # A reply that cannot be read back (an odd exception type). Anything else, such as the job
        # timeout raised in this process, is not about the file: it goes up unchanged.
        status, payload = "error", ValueError("The file could not be read.")
    finally:
        parent.close()
        if proc.is_alive():
            _kill_group(proc.pid)
        proc.join(10)
        if proc.is_alive():
            proc.kill()
        _kill_group(proc.pid)  # what the child started and left running
    if status == "ok":
        return payload
    if status == "error":
        raise payload
    raise ParseLimitExceeded(
        "The file needs more memory or time to read than allowed: it may be damaged or built to overload "
        "the reader. Save it again (or export to PDF) and upload it again.")
