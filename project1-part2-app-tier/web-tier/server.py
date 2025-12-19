#!/usr/bin/env python3
import os, json, uuid, time, threading, queue
import boto3
from flask import Flask, request, Response
from werkzeug.utils import secure_filename
from botocore.exceptions import ClientError

ASU_ID = os.environ.get("ASU_ID", "").strip()
REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"
INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "").strip() or (
    f"{ASU_ID}-in-bucket" if ASU_ID else ""
)
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "").strip() or (
    f"{ASU_ID}-out-bucket" if ASU_ID else ""
)
REQ_QUEUE_NAME = os.environ.get("REQ_QUEUE_NAME", "").strip() or (
    f"{ASU_ID}-req-queue" if ASU_ID else ""
)
RESP_QUEUE_NAME = os.environ.get("RESP_QUEUE_NAME", "").strip() or (
    f"{ASU_ID}-resp-queue" if ASU_ID else ""
)
REQ_QUEUE_URL = os.environ.get("REQ_QUEUE_URL", "").strip() or None
RESP_QUEUE_URL = os.environ.get("RESP_QUEUE_URL", "").strip() or None
REQ_QUEUE_ATTRS = {"MaximumMessageSize": "1024", "ReceiveMessageWaitTimeSeconds": "20", "VisibilityTimeout": "60"}
RESP_QUEUE_ATTRS = {"ReceiveMessageWaitTimeSeconds": "20", "VisibilityTimeout": "60"}
RESPONSE_TIMEOUT_SEC = 300
PORT = int(os.environ.get("CSE546_WEB_PORT", "8000"))

session = boto3.Session(region_name=REGION)
s3 = session.client("s3")
sqs = session.client("sqs")
app = Flask(__name__)

def ensure_bucket(name):
    try: s3.head_bucket(Bucket=name)
    except ClientError as e:
        code = e.response.get("Error",{}).get("Code","")
        if code in ("404","NoSuchBucket","403"):
            kwargs = {"Bucket": name}
            if REGION != "us-east-1":
                kwargs["CreateBucketConfiguration"]={"LocationConstraint":REGION}
            s3.create_bucket(**kwargs)
        else: raise

def get_or_create_queue(name, attrs):
    try: url = sqs.create_queue(QueueName=name, Attributes=attrs)["QueueUrl"]
    except Exception: url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    sqs.set_queue_attributes(QueueUrl=url, Attributes=attrs)
    return url

def resolve_queue_url(name, attrs, override_url):
    if override_url:
        try:
            sqs.set_queue_attributes(QueueUrl=override_url, Attributes=attrs)
        except Exception:
            pass
        return override_url
    if not name:
        raise RuntimeError("Queue name or URL must be set in the environment")
    return get_or_create_queue(name, attrs)

def stem(p): import os; return os.path.splitext(os.path.basename(p))[0]

class Dispatcher(threading.Thread):
    daemon=True
    def __init__(self, resp_qurl): super().__init__(name="resp-dispatcher"); self.qurl=resp_qurl; self.waiters={}; self.lock=threading.Lock()
    def add_waiter(self, rid):
        q=queue.Queue(maxsize=1)
        with self.lock: self.waiters[rid]=q
        return q
    def deliver(self, rid, payload):
        with self.lock: q=self.waiters.pop(rid,None)
        if q:
            try: q.put_nowait(payload)
            except queue.Full: pass
    def run(self):
        while True:
            try:
                r=sqs.receive_message(QueueUrl=self.qurl, MaxNumberOfMessages=10, WaitTimeSeconds=20, MessageAttributeNames=["All"])
                for m in r.get("Messages",[]):
                    try: data=json.loads(m.get("Body","{}"))
                    except: data={}
                    rid=data.get("request_id")
                    if rid: self.deliver(rid, data)
                    sqs.delete_message(QueueUrl=self.qurl, ReceiptHandle=m["ReceiptHandle"])
            except Exception as e:
                print("[dispatcher] error:", e); time.sleep(0.5)

# Startup: ensure resources and dispatcher
if not INPUT_BUCKET or not OUTPUT_BUCKET:
    raise RuntimeError("INPUT_BUCKET and OUTPUT_BUCKET must be set (or ASU_ID)")
ensure_bucket(INPUT_BUCKET); ensure_bucket(OUTPUT_BUCKET)
REQ_URL = resolve_queue_url(REQ_QUEUE_NAME, REQ_QUEUE_ATTRS, REQ_QUEUE_URL)
RESP_URL = resolve_queue_url(RESP_QUEUE_NAME, RESP_QUEUE_ATTRS, RESP_QUEUE_URL)
DISP = Dispatcher(RESP_URL); DISP.start()

@app.route("/", methods=["POST"])
def root():
    if "inputFile" not in request.files:
        return Response("Missing 'inputFile'", status=400, mimetype="text/plain")
    f = request.files["inputFile"]; name = secure_filename(f.filename)
    if not name: return Response("Invalid filename", status=400, mimetype="text/plain")

    # 1) store input
    f.seek(0); s3.put_object(Bucket=INPUT_BUCKET, Key=name, Body=f.read())

    # 2) send small request (<= 1KB)
    rid=str(uuid.uuid4()); body=json.dumps({"request_id": rid, "s3_key": name})
    if len(body.encode())>1024: return Response("Message too large", status=500, mimetype="text/plain")
    sqs.send_message(QueueUrl=REQ_URL, MessageBody=body)

    # 3) wait for response
    waiter=DISP.add_waiter(rid)
    try: payload=waiter.get(timeout=RESPONSE_TIMEOUT_SEC)
    except queue.Empty: return Response("Timed out waiting for result", status=504, mimetype="text/plain")

    label=payload.get("prediction","Unknown")
    return Response(f"{stem(name)}:{label}", status=200, mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
