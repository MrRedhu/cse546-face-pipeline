#!/usr/bin/env python3
import os, io, json, time
import boto3
from botocore.exceptions import ClientError

ASU_ID = os.environ.get("ASU_ID", "").strip()
REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"

INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "").strip() or (
    f"{ASU_ID}-in-bucket" if ASU_ID else ""
)
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "").strip() or (
    f"{ASU_ID}-out-bucket" if ASU_ID else ""
)
REQ_QUEUE = os.environ.get("REQ_QUEUE_NAME", "").strip() or (
    f"{ASU_ID}-req-queue" if ASU_ID else ""
)
RESP_QUEUE = os.environ.get("RESP_QUEUE_NAME", "").strip() or (
    f"{ASU_ID}-resp-queue" if ASU_ID else ""
)
REQ_QUEUE_URL = os.environ.get("REQ_QUEUE_URL", "").strip() or None
RESP_QUEUE_URL = os.environ.get("RESP_QUEUE_URL", "").strip() or None

RECEIVE_WAIT_SECS   = int(os.environ.get("RECEIVE_WAIT_SECS", "20"))
VISIBILITY_TIMEOUT  = int(os.environ.get("VISIBILITY_TIMEOUT", "60"))
SELF_STOP = os.environ.get("SELF_STOP", "0") == "1"
IDLE_CHECKS_BEFORE_STOP = int(os.environ.get("IDLE_CHECKS_BEFORE_STOP", "2"))

session = boto3.Session(region_name=REGION)
s3  = session.client("s3")
sqs = session.client("sqs")
ec2 = session.client("ec2")

def qurl(name): return sqs.get_queue_url(QueueName=name)["QueueUrl"]
def resolve_queue_url(name, override_url):
    if override_url:
        return override_url
    if not name:
        raise RuntimeError("Queue name or URL must be set in the environment")
    return qurl(name)
REQ_URL  = resolve_queue_url(REQ_QUEUE, REQ_QUEUE_URL)
RESP_URL = resolve_queue_url(RESP_QUEUE, RESP_QUEUE_URL)

def get_queue_depth(q_url):
    a = sqs.get_queue_attributes(QueueUrl=q_url,
        AttributeNames=["ApproximateNumberOfMessages","ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    return int(a.get("ApproximateNumberOfMessages","0")), int(a.get("ApproximateNumberOfMessagesNotVisible","0"))

def send_response(request_id, label):
    body = json.dumps({"request_id": request_id, "prediction": label})
    sqs.send_message(QueueUrl=RESP_URL, MessageBody=body)

def stop_myself():
    try:
        import requests
        iid = requests.get("http://169.254.169.254/latest/meta-data/instance-id", timeout=1.0).text
        ec2.stop_instances(InstanceIds=[iid])
    except Exception as e:
        print("[backend] self-stop failed:", e)

def stem(key):
    import os
    return os.path.splitext(os.path.basename(key))[0]

# lazy import model to speed cold start
PREDICT = None
def ensure_model():
    global PREDICT
    if PREDICT is None:
        import sys
        sys.path.insert(0, "/opt/app")
        from model_infer import predict
        PREDICT = predict

def main():
    if not INPUT_BUCKET or not OUTPUT_BUCKET:
        raise RuntimeError("INPUT_BUCKET and OUTPUT_BUCKET must be set (or ASU_ID)")
    print("[backend] up; region=", REGION, "ASU_ID=", ASU_ID)
    idle_checks = 0
    while True:
        try:
            r = sqs.receive_message(QueueUrl=REQ_URL, MaxNumberOfMessages=1,
                                    WaitTimeSeconds=RECEIVE_WAIT_SECS,
                                    VisibilityTimeout=VISIBILITY_TIMEOUT)
            msgs = r.get("Messages", [])
            if not msgs:
                if SELF_STOP:
                    vis, infl = get_queue_depth(REQ_URL)
                    if vis == 0 and infl == 0:
                        idle_checks += 1
                        if idle_checks >= IDLE_CHECKS_BEFORE_STOP:
                            stop_myself(); time.sleep(2)
                    else:
                        idle_checks = 0
                continue

            idle_checks = 0
            m = msgs[0]; receipt = m["ReceiptHandle"]
            try:
                body = json.loads(m.get("Body","{}"))
            except: body = {}
            request_id = str(body.get("request_id","") or "").strip()
            s3_key     = str(body.get("s3_key","") or "").strip()
            if not request_id or not s3_key:
                print("[backend] invalid msg; deleting:", body)
                sqs.delete_message(QueueUrl=REQ_URL, ReceiptHandle=receipt)
                continue

            try:
                obj = s3.get_object(Bucket=INPUT_BUCKET, Key=s3_key)
                img_bytes = obj["Body"].read()
            except ClientError as e:
                print(f"[backend] S3 get_object failed for {s3_key}:", e)
                continue

            try:
                ensure_model()
                label = str(PREDICT(img_bytes))
            except Exception as e:
                print("[backend] inference failed:", e)
                continue

            out_key = stem(s3_key)
            try:
                s3.put_object(Bucket=OUTPUT_BUCKET, Key=out_key, Body=label.encode())
            except ClientError as e:
                print(f"[backend] S3 put_object failed for {out_key}:", e)
                continue

            send_response(request_id, label)
            sqs.delete_message(QueueUrl=REQ_URL, ReceiptHandle=receipt)

        except Exception as e:
            print("[backend] loop error:", e)
            time.sleep(0.5)

if __name__ == "__main__":
    main()
