"""Клиент desktop-приложения: запросы к локальному серверу не должны уходить в системный прокси.

Разбор: при включённом прокси (VPN, v2ray) без исключения для localhost вместо ответа сервера
приходил «502 Bad Gateway» от самого прокси, а список сайтов в окне оставался пустым.
"""
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # тишина в выводе тестов
        pass


def test_local_server_is_reached_even_with_dead_system_proxy(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")  # порт, где никто не слушает
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(name, "")
        monkeypatch.setenv("COMPETITOR_API", f"http://127.0.0.1:{server.server_port}")

        import api_client
        importlib.reload(api_client)
        assert api_client.health() == {"status": "ok"}
    finally:
        server.shutdown()
        importlib.reload(api_client)
