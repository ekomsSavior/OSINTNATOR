"""Killable source workers with partial results and cancellation."""
import multiprocessing
import threading
import time
from dataclasses import dataclass, field

# Process.start() performs global child cleanup in multiprocessing. Serialize
# lifecycle operations across source threads so cleanup cannot race join/close.
_process_lifecycle=threading.Lock()

@dataclass
class Outcome:
    status: str
    hits: list = field(default_factory=list)
    error: str = ""


def scrape_worker(connection, site, query):
    if getattr(query, 'web_mode', False):
        from web_guard import restrict_worker
        restrict_worker()
    import scrapers
    import api_sources  # register API adapters in spawned workers
    import free_sources
    import public_web
    import web_search
    import identity_sources
    import linkedin_sources
    import property_sources
    import property_directory
    import obituary_sources
    import contact_sources
    try:
        with scrapers.get_session() as session:
            if site in ('Public Web Search','LinkedIn Name Search','Gravatar Email Profile','GitHub Email Commits','Official Property Records','US Address Geography','USPhoneBook'):
                from requests.adapters import HTTPAdapter
                session.mount('https://',HTTPAdapter(max_retries=0))
            session.emit_hit = lambda hit: connection.send(("hit", hit))
            hits = scrapers.run_scraper(session, site, query)
            connection.send(("done", list(hits)))
    except Exception as exc:
        connection.send(("error", str(exc)))
    finally:
        connection.close()


def run_bounded(site, query, timeout, cancel=None, worker=scrape_worker):
    if cancel is not None and cancel.is_set():
        return Outcome("cancelled")
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(writer, site, query), daemon=True)
    hits = []
    started = False
    try:
        with _process_lifecycle:process.start()
        started = True
        writer.close()
        deadline = time.monotonic() + timeout
        while True:
            if cancel is not None and cancel.is_set():
                return Outcome("cancelled", hits)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return Outcome("timeout", hits)
            if reader.poll(min(0.05, remaining)):
                try:
                    kind, value = reader.recv()
                except EOFError:
                    return Outcome("error", hits, "Source worker exited without a result")
                if kind == "hit":
                    hits.append(value)
                elif kind == "done":
                    return Outcome("complete", value)
                else:
                    return Outcome("error", hits, value)
            else:
                with _process_lifecycle:alive=process.is_alive()
                if not alive:return Outcome("error", hits, "Source worker exited without a result")
    finally:
        if started:
            with _process_lifecycle:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
        reader.close()
        writer.close()
