"""Requisições hostis usam somente arquivos e serviços temporários."""

import asyncio
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from starlette import formparsers

from doclens import security
from doclens.api import create_app
from doclens.errors import DocumentError
from doclens.security import JSON_MAX_BYTES, MULTIPART_OVERHEAD
from tests.support import FakeModels, LocalTestClient, image_bytes


async def exchange(app, messages, *, path="/search", headers=(), receive=None):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 50000),
        "headers": [(b"host", b"127.0.0.1:8000"), *headers],
    }
    output = []
    iterator = iter(messages)
    reads = []

    async def next_message():
        reads.append(True)
        if receive is not None:
            return await receive()
        return next(iterator, {"type": "http.disconnect"})

    async def send(message):
        output.append(message)

    await app(scope, next_message, send)
    return output, reads


def status(output):
    return next(message["status"] for message in output if message["type"] == "http.response.start")


def body_message(data, more=False):
    return {"type": "http.request", "body": data, "more_body": more}


@pytest.mark.parametrize(
    "host", ["attacker.example:8000", "localhost.attacker.example", "127.0.0.2"]
)
def test_untrusted_host_is_rejected_before_processing(client, host):
    response = client.post(
        "/documents", headers={"Host": host}, files={"file": ("a.png", image_bytes())}
    )
    assert response.status_code == 400
    assert client.get("/documents").json() == []


@pytest.mark.parametrize("host,peer", [("localhost:8000", "127.0.0.1"), ("[::1]:8000", "::1")])
def test_loopback_hosts_and_clients_work(settings, host, peer):
    with LocalTestClient(
        create_app(settings, FakeModels()), base_url=f"http://{host}", client=(peer, 1)
    ) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/search", headers={"Origin": f"http://{host}"}, json={"query": "texto"}
        )
        assert response.status_code == 200


def test_non_loopback_peer_is_rejected_even_with_local_host(settings):
    with LocalTestClient(create_app(settings, FakeModels()), client=("192.0.2.10", 1)) as client:
        assert client.get("/documents").status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "https://attacker.example",
        "null",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8000.attacker.example",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/",
    ],
)
def test_external_or_invalid_origins_cannot_upload(client, origin):
    response = client.post(
        "/documents", headers={"Origin": origin}, files={"file": ("a.png", image_bytes())}
    )
    assert response.status_code == 403
    assert client.get("/documents").json() == []


@pytest.mark.parametrize("site", ["cross-site", "same-site", "none"])
def test_fetch_metadata_cannot_bypass_missing_origin(client, site):
    assert (
        client.post(
            "/search", headers={"Sec-Fetch-Site": site}, json={"query": "texto"}
        ).status_code
        == 403
    )


def test_legitimate_browser_and_local_cli_work(client):
    for headers in ({}, {"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"}):
        assert (
            client.post(
                "/documents", headers=headers, files={"file": ("a.png", image_bytes())}
            ).status_code
            == 201
        )
        assert (
            client.post("/search", headers=headers, json={"query": "computadores"}).status_code
            == 200
        )


@pytest.mark.parametrize("declared", [None, b"1", str(JSON_MAX_BYTES + 1).encode()])
def test_large_json_is_bounded_regardless_of_content_length(settings, declared):
    app = create_app(settings, FakeModels())
    headers = [(b"content-type", b"application/json")]
    if declared is not None:
        headers.append((b"content-length", declared))
    payload = json.dumps({"query": "texto", "ignored": "x" * JSON_MAX_BYTES}).encode()
    output, reads = asyncio.run(
        exchange(
            app, [body_message(payload[:10], True), body_message(payload[10:])], headers=headers
        )
    )
    assert status(output) == 413
    assert len(reads) == (0 if declared == str(JSON_MAX_BYTES + 1).encode() else 2)


def test_invalid_and_duplicate_lengths_and_hosts_are_rejected(settings):
    app = create_app(settings, FakeModels())
    for headers in [
        [(b"content-length", b"-1")],
        [(b"content-length", b"abc")],
        [(b"content-length", b"1"), (b"content-length", b"1")],
        [(b"host", b"attacker.example")],
    ]:
        output, reads = asyncio.run(exchange(app, [], headers=headers))
        assert status(output) == 400 and not reads
    output, reads = asyncio.run(exchange(app, [], headers=[(b"content-length", b"9" * 5000)]))
    assert status(output) == 413 and not reads


def test_upload_body_limit_closes_partially_written_temporary_files(settings, monkeypatch):
    settings.max_bytes = 1024
    app = create_app(settings, FakeModels())
    files = []
    original = formparsers.SpooledTemporaryFile

    def temporary(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", temporary)
    request = httpx.Request(
        "POST",
        "http://127.0.0.1/documents",
        files={"file": ("a.png", b"x" * (settings.max_bytes + MULTIPART_OVERHEAD))},
    )
    payload = request.read()
    messages = [body_message(payload[:2048], True), body_message(payload[2048:])]
    headers = [(b"content-type", request.headers["content-type"].encode())]
    output, _ = asyncio.run(exchange(app, messages, path="/documents", headers=headers))
    assert status(output) == 413
    assert files and all(file.closed for file in files)
    assert app.state.service.store.list_documents() == []


@pytest.mark.parametrize("extra", ["file", "field"])
def test_multipart_extra_parts_are_rejected_and_closed(client, monkeypatch, extra):
    opened = []
    original = formparsers.SpooledTemporaryFile

    def temporary(*args, **kwargs):
        file = original(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", temporary)
    parts = [("file", ("a.png", image_bytes()))]
    parts.append(("extra", ("b.png", image_bytes()) if extra == "file" else (None, "text")))
    assert client.post("/documents", files=parts).status_code == 400
    assert opened and all(file.closed for file in opened)
    assert client.get("/documents").json() == []


def test_exact_file_limit_is_allowed_and_one_more_byte_is_rejected(settings):
    image = image_bytes()
    settings.max_bytes = len(image)
    with LocalTestClient(create_app(settings, FakeModels())) as client:
        assert client.post("/documents", files={"file": ("a.png", image)}).status_code == 201
        assert client.post("/documents", files={"file": ("a.png", image + b"x")}).status_code == 413
        assert len(client.get("/documents").json()) == 1


def test_declared_oversize_upload_does_not_open_a_temporary_file(settings, monkeypatch):
    app = create_app(settings, FakeModels())

    def forbidden(*args, **kwargs):
        raise AssertionError("O corpo excessivo chegou ao parser")

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", forbidden)
    headers = [(b"content-length", str(settings.max_bytes + MULTIPART_OVERHEAD + 1).encode())]
    output, reads = asyncio.run(exchange(app, [], path="/documents", headers=headers))
    assert status(output) == 413 and not reads


def test_body_timeout_is_total_and_not_reset_per_chunk(settings, monkeypatch):
    app = create_app(settings, FakeModels())
    monkeypatch.setattr(security, "BODY_TIMEOUT_SECONDS", 0.03)

    async def trickle():
        await asyncio.sleep(0.02)
        return body_message(b" ", True)

    output, _ = asyncio.run(
        exchange(app, [], headers=[(b"content-type", b"application/json")], receive=trickle)
    )
    assert status(output) == 408
    with LocalTestClient(app) as client:
        assert client.post("/search", json={"query": "texto"}).status_code == 200


def test_canceling_body_receive_releases_capacity(settings):
    app = create_app(settings, FakeModels())

    async def cancel():
        entered = asyncio.Event()

        async def waiting():
            entered.set()
            await asyncio.Future()

        task = asyncio.create_task(exchange(app, [], receive=waiting))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    with LocalTestClient(app) as client:
        assert client.post("/search", json={"query": "texto"}).status_code == 200


def test_body_deadline_closes_upload_and_releases_capacity(settings, monkeypatch):
    app = create_app(settings, FakeModels())
    monkeypatch.setattr(security, "BODY_TIMEOUT_SECONDS", 0.02)
    opened = []
    original = formparsers.SpooledTemporaryFile

    def temporary(*args, **kwargs):
        file = original(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", temporary)
    request = httpx.Request(
        "POST", "http://127.0.0.1/documents", files={"file": ("a.png", image_bytes())}
    )
    prefix = request.read()[:200]
    calls = 0

    async def stalled():
        nonlocal calls
        calls += 1
        if calls == 1:
            return body_message(prefix, True)
        await asyncio.Future()

    output, _ = asyncio.run(
        exchange(
            app,
            [],
            path="/documents",
            headers=[(b"content-type", request.headers["content-type"].encode())],
            receive=stalled,
        )
    )
    assert status(output) == 408
    assert opened and all(file.closed for file in opened)
    with LocalTestClient(app) as client:
        assert (
            client.post("/documents", files={"file": ("a.png", image_bytes())}).status_code == 201
        )


def test_upload_busy_response_precedes_multipart_parsing(client, monkeypatch):
    service = client.app.state.service
    entered, release = threading.Event(), threading.Event()
    original = service.ingest

    def ingest(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(service, "ingest", ingest)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(client.post, "/documents", files={"file": ("a.png", image_bytes())})
        try:
            assert entered.wait(3)
            output, reads = asyncio.run(
                exchange(
                    client.app,
                    [],
                    path="/documents",
                    headers=[(b"content-type", b"multipart/form-data; boundary=x")],
                )
            )
            assert status(output) == 409 and not reads
            assert client.get("/health").status_code == 200
        finally:
            release.set()
        assert first.result(timeout=3).status_code == 201
    assert client.post("/documents", files={"file": ("b.png", image_bytes())}).status_code == 201


def test_only_two_searches_execute_and_errors_release_capacity(client, monkeypatch):
    service = client.app.state.service
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    active = 0

    def search(*args):
        nonlocal active
        with lock:
            active += 1
            if active == 2:
                entered.set()
        assert release.wait(3)
        raise DocumentError("Falha controlada.")

    monkeypatch.setattr(service, "search_response", search)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(client.post, "/search", json={"query": "texto"}) for _ in range(2)
        ]
        try:
            assert entered.wait(3)
            assert client.post("/search", json={"query": "texto"}).status_code == 409
        finally:
            release.set()
        assert [future.result(timeout=3).status_code for future in futures] == [422, 422]
    assert client.post("/search", json={"query": "texto"}).status_code == 422


def test_canceled_worker_keeps_capacity_until_it_finishes():
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(False)
    lease = security.RequestLease(slots)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lease.call, work)
        try:
            assert entered.wait(3)
            lease.release()
            assert not slots.acquire(False)
        finally:
            release.set()
        future.result(timeout=3)
    assert slots.acquire(False)
    lease.release()  # A limpeza duplicada não cria vagas extras.
    assert not slots.acquire(False)


def test_response_headers_docs_nonces_and_sensitive_cache(client, monkeypatch):
    for path in ["/", "/documents", "/search", "/static/app.js", "/missing"]:
        response = client.get(path)
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        if path in {"/", "/documents", "/search"}:
            assert response.headers["cache-control"] == "no-store"
    for path in ["/docs", "/redoc", "/docs/oauth2-redirect"]:
        response = client.get(path)
        nonce = re.search(r"'nonce-([^']+)'", response.headers["content-security-policy"])[1]
        scripts = re.findall(r"<script\b[^>]*>", response.text)
        assert scripts and all(f'nonce="{nonce}"' in script for script in scripts)
        assert all(
            'integrity="sha384-' in script and 'crossorigin="anonymous"' in script
            for script in scripts
            if "src=" in script
        )
        assert nonce not in client.get(path).headers["content-security-policy"]

    def fail():
        raise RuntimeError("private detail")

    monkeypatch.setattr(client.app.state.service.store, "list_documents", fail)
    with LocalTestClient(client.app, raise_server_exceptions=False) as error_client:
        response = error_client.get("/documents")
        assert response.status_code == 500 and "private detail" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
