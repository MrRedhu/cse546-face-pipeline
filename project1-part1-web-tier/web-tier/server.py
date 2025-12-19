#!/usr/bin/env python3

import os
import sys
import cgi
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# --------------------- CONFIG ---------------------
ASU_ID = os.environ.get("ASU_ID", "").strip()
REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"
PORT = int(os.environ.get("PORT", "8000"))
INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "").strip() or (
    f"{ASU_ID}-in-bucket" if ASU_ID else ""
)
SDB_DOMAIN = os.environ.get("SDB_DOMAIN", "").strip() or (
    f"{ASU_ID}-simpleDB" if ASU_ID else ""
)

# Boto3 clients (thread-safe)
_boto_cfg = Config(region_name=REGION, retries={"max_attempts": 5, "mode": "standard"})
_s3  = boto3.client("s3",  config=_boto_cfg)
_sdb = boto3.client("sdb", config=_boto_cfg)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("web-tier")

# ------------------ UTILITIES ---------------------
def _basename_no_ext(filename: str) -> str:
    base = os.path.basename(filename)
    if "." in base:
        return ".".join(base.split(".")[:-1])
    return base

def _find_label(attrs):
    """Find a label in SimpleDB attributes (prefer 'recognition')."""
    if not attrs:
        return None
    by_name = {a.get("Name", "").lower(): a.get("Value") for a in attrs}
    for key in ("recognition", "label", "prediction", "name"):
        if by_name.get(key):
            return by_name[key]
    # fallback to first attribute value if any
    for a in attrs:
        v = a.get("Value")
        if v:
            return v
    return None

def sdb_lookup(item_name: str) -> str:
    try:
        resp = _sdb.get_attributes(
            DomainName=SDB_DOMAIN,
            ItemName=item_name,
            ConsistentRead=True
        )
        return _find_label(resp.get("Attributes"))
    except (BotoCoreError, ClientError) as e:
        log.error("SimpleDB get_attributes failed: %s", e)
        return None

def s3_put_object(key: str, fileobj) -> None:
    try:
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)
        _s3.put_object(Bucket=INPUT_BUCKET, Key=key, Body=fileobj)
    except (BotoCoreError, ClientError) as e:
        log.error("S3 put_object failed: %s", e)
        raise

# --------------- THREADED SERVER ------------------
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_plain(self, code: int, text: str):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_POST(self):
        if self.path != "/":
            self._send_plain(404, "Not Found")
            return

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_plain(400, 'Bad Request: expected multipart/form-data with key "inputFile"')
            return

        try:
            fs = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype}
            )
        except Exception as e:
            log.error("multipart parse error: %s", e)
            self._send_plain(400, "Bad Request: cannot parse form")
            return

        if "inputFile" not in fs:
            self._send_plain(400, 'Bad Request: missing "inputFile" field')
            return

        fileitem = fs["inputFile"]
        if isinstance(fileitem, list):
            fileitem = fileitem[0]

        filename = getattr(fileitem, "filename", None)
        fileobj  = getattr(fileitem, "file", None)
        if not filename or fileobj is None:
            self._send_plain(400, 'Bad Request: "inputFile" must include a filename and content')
            return

        # 1) Store to S3 with key = original filename
        try:
            s3_put_object(filename, fileobj)
        except Exception:
            self._send_plain(500, "Internal Server Error: S3 upload failed")
            return

        # 2) Lookup SimpleDB by basename without extension
        item = _basename_no_ext(filename)
        label = sdb_lookup(item)
        if not label:
            label = "UNKNOWN"

        # 3) Return "<basename>:<label>" in plain text
        self._send_plain(200, f"{item}:{label}")

    # Quieter logs
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

def main():
    if not INPUT_BUCKET or not SDB_DOMAIN:
        log.error("Set INPUT_BUCKET and SDB_DOMAIN (or ASU_ID) in the environment before running.")
        sys.exit(2)

    addr = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(addr, Handler)
    log.info("Listening on %s:%d (region=%s, bucket=%s, sdb=%s)",
             addr[0], addr[1], REGION, INPUT_BUCKET, SDB_DOMAIN)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        log.info("Server stopped.")

if __name__ == "__main__":
    main()
