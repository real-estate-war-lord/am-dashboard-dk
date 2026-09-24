#!/usr/bin/env python3
"""Automated UI check for the climate layer — the app driven headless, asserting on its own state.

Not a screenshot review. `tests/ui_check.html` loads `dist/index.html` in an iframe, drives it
through the hash exactly as a reader would, and reads the app's own live variables (`HZ`, `LF`,
`CZ`, `CMP`, the rendered DOM) back out. This script serves `dist/` on a random loopback port,
starts headless Chrome pointed at the harness, and waits for the harness to POST its results back.

The results come back over HTTP rather than through `--dump-dom` with a virtual-time budget on
purpose: under virtual time the page still does all of its real work (Leaflet redraws, the whole
5 MB app booting for every check), so the budget is either exhausted before the checks finish or
so large that the run takes longer than any sensible timeout. A callback needs neither.

Usage:  python3 scripts/ui_check.py [--timeout 300] [--show]
Exit code 1 if any check failed, so it can gate a release.
"""
import argparse
import http.server
import json
import pathlib
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
HARNESS = ROOT / "tests" / "ui_check.html"
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser",
]
RESULTS = queue.Queue()


def chrome_bin():
    for c in CHROME_CANDIDATES:
        p = shutil.which(c) if "/" not in c else (c if pathlib.Path(c).exists() else None)
        if p:
            return p
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    # HTTP/1.0: every response closes its connection, which keeps a headless browser's parallel
    # requests from queueing up behind a keep-alive socket nobody is going to use again.
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        RESULTS.put(body)
        self.send_response(204)
        self.end_headers()


def serve(directory):
    handler = lambda *a, **k: Handler(*a, directory=str(directory), **k)        # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for the harness")
    ap.add_argument("--show", action="store_true", help="run Chrome with a window, for debugging")
    ap.add_argument("--keep", action="store_true", help="keep the copied harness in dist/")
    args = ap.parse_args()

    if not (DIST / "index.html").exists():
        print("✗ dist/index.html missing — run `make build` first")
        return 1
    ch = chrome_bin()
    if not ch:
        print("✗ no Chrome or Chromium found — cannot run the UI check")
        return 1

    target = DIST / "ui_check.html"           # the harness must be same-origin with the page
    shutil.copy(HARNESS, target)
    srv, port = serve(DIST)
    profile = tempfile.mkdtemp(prefix="uicheck-")
    cmd = [ch, "--no-first-run", "--no-default-browser-check", "--disable-extensions",
           "--disable-background-networking", "--disable-gpu", "--no-sandbox",
           "--window-size=1400,900", f"--user-data-dir={profile}",
           # every external host fails fast: the basemap tiles and the web-font stylesheet are the
           # only ones the page asks for and neither is part of what is being checked
           "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--disable-remote-fonts",
           f"http://127.0.0.1:{port}/ui_check.html"]
    if not args.show:
        cmd.insert(1, "--headless=new")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        try:
            body = RESULTS.get(timeout=args.timeout)
        except queue.Empty:
            print(f"✗ the harness never reported back within {args.timeout}s")
            return 1
        results = json.loads(body)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(profile, ignore_errors=True)
        if not args.keep and target.exists():
            target.unlink()

    bad = [r for r in results if not r["pass"]]
    print(f"UI checks — {len(results) - len(bad)}/{len(results)} passed\n")
    for r in results:
        print(f"   {'✓' if r['pass'] else '✗'} {r['name']}")
        if r.get("detail"):
            print(f"        {r['detail']}")
    print("\n" + ("✗ UI CHECK FAILED" if bad else "✓ every UI check passed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
