#!/usr/bin/env python3
"""Serve the Daily Digest web UI and API."""
import json
import pathlib
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

DIGEST_DIR = pathlib.Path("digests")
WEB_DIR = pathlib.Path("web")
PORT = 8000


def latest_digest():
    files = sorted(DIGEST_DIR.glob("digest_*.json"), reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(WEB_DIR / "index.html", "text/html")
        elif self.path == "/api/digest":
            self._serve_digest()
        else:
            self.send_error(404)

    def _serve_file(self, path, content_type):
        path = pathlib.Path(path)
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _serve_digest(self):
        digest = latest_digest()
        if digest is None:
            self.send_error(404, "No digest found")
            return
        data = json.dumps(digest).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("", PORT), Handler)
    print(f"Daily Digest running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
