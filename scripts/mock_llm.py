#!/usr/bin/env python3
"""Mock OpenAI endpoint: 503 twice, then a real response. For retry testing."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

calls = {"n": 0}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        calls["n"] += 1
        body = json.dumps({"calls": calls["n"]}).encode()
        if calls["n"] <= 2:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "upstream capacity limits"}}).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {"choices": [{"message": {"content": "MOCK DIGEST OK (attempt %d)" % calls["n"]}}]}
            self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *a):
        pass


def main():
    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    print(f"MOCK:{port}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import time
    time.sleep(60)


if __name__ == "__main__":
    main()
