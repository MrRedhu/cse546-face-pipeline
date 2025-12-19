#!/usr/bin/env python3
import os, io, json, time
import boto3
from botocore.exceptions import ClientError

ASU_ID = os.environ.get("ASU_ID", "1224308891").strip()
REGION = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"

INPUT_BUCKET  = f"{ASU_ID}-in-bucket"
OUTPUT_BUCKET = f"{ASU_ID}-out-bucket"
REQ_QUEUE     = f"{ASU_ID}-req-queue"
RESP_QUEUE    = f"{ASU_ID}-resp-queue"

RECEIVE_WAIT_SECS   = int(os.environ.get("RECEIVE_WAIT_SECS", "20"))
VISIBILITY_TIMEOUT  = int(os.environ.get("VISIBILITY_TIMEOUT", "60"))
SELF_STOP = os.environ.get("SELF_STOP", "0") == "1"
IDLE_CHECKS_BEFORE_STOP = int(os.environ.get("IDLE_CHECKS_BEFORE_STOP", "2"))

session = boto3.Session(region_name=REGION)
s3  = session.client("s3")
sqs = session.client("sqs")
ec2 = session.client("ec2")

def qurl(name): return sqs.get_queue_url(QueueName=name)["QueueUrl"]
REQ_URL  = qurl(REQ_QUEUE)
RESP_URL = qurl(RESP_QUEUE)

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