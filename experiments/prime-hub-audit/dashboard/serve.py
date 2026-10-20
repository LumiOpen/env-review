"""Serve the env-audit dashboard snapshot. No dependencies.

  python3 serve.py [PORT]      then open http://127.0.0.1:8000

Answers /api/* from data/*.json (a snapshot of the live dashboard), serves static/, and returns
index.html for every page path so deep links and reloads work. Logs and env source code are not
included in this snapshot.
"""
import json, sys, urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA, STATIC = ROOT / "data", ROOT / "static"


class H(SimpleHTTPRequestHandler):
    def send_file(self, path, ctype):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, code, msg):
        body = json.dumps({"detail": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path.startswith("/api/"):
            parts = path[len("/api/"):].strip("/").split("/")
            if parts[0] == "env" and len(parts) == 2:
                f = DATA / "env" / f"{parts[1]}.json"
            elif len(parts) == 1:
                f = DATA / f"{parts[0]}.json"
            else:
                return self.send_json_error(404, "logs and source code are not included in this snapshot")
            if ".." in parts or not f.resolve().is_relative_to(DATA) or not f.is_file():
                return self.send_json_error(404, "not found")
            return self.send_file(f, "application/json")
        if path.startswith("/static/"):
            f = (STATIC / path[len("/static/"):]).resolve()
            if not f.is_relative_to(STATIC) or not f.is_file():
                return self.send_error(404)
            ctype = {".css": "text/css", ".js": "application/javascript", ".html": "text/html"}.get(f.suffix, "application/octet-stream")
            return self.send_file(f, ctype)
        return self.send_file(STATIC / "index.html", "text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"env audit dashboard (snapshot): http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
