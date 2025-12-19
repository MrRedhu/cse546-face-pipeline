# Runbook (High Level)

This is intentionally **high-level** for portfolio safety.
It outlines what the system components are and how they connect.

---

## Common prerequisites
- An AWS account you control
- Region: `us-east-1` (matches class conventions)
- Python 3.x, pip
- AWS CLI configured (profile or env vars)

---

## Project 1 — IaaS (EC2 + S3 + SimpleDB/SQS)

### Part 1: Web tier (S3 + SimpleDB emulated inference)
1) Create:
- S3 input bucket: `<ASU_ID>-in-bucket`
- SimpleDB domain: `<ASU_ID>-simpleDB` (populated with filename -> label mapping)

2) Launch an EC2 instance for the web tier and run:
- `web-tier/server.py` (HTTP POST `/` on port 8000)
- Ensure the instance security group allows inbound TCP 8000 (for your testing IPs)

3) Test (example):
- Send multipart form upload with key `inputFile`
- Expect plaintext response: `filename:prediction`

---

### Part 2: Multi-tier + autoscaling (SQS + S3 + EC2)
1) Create:
- S3 input bucket: `<ASU_ID>-in-bucket`
- S3 output bucket: `<ASU_ID>-out-bucket`
- SQS request queue: `<ASU_ID>-req-queue` (small max message size; do NOT send images through SQS)
- SQS response queue: `<ASU_ID>-resp-queue`

2) Web tier responsibilities:
- store image in S3 input bucket
- enqueue request metadata to request queue
- read result from response queue and return `filename:prediction`

3) App tier responsibilities:
- poll request queue
- fetch image from S3 input bucket
- run model inference
- write result to S3 output bucket
- send result to response queue

4) Autoscaling controller:
- start/stop app-tier instances based on queue depth/work in flight
- scale to 0 when idle

---

## Project 2 — Serverless + Edge (Lambda/ECR + Greengrass + MQTT)

### Part 1: Lambda pipeline (ECR + SQS)
1) Build a container image for Lambda (with deps like boto3, torch CPU, facenet_pytorch, opencv, Pillow)
2) Push image to ECR
3) Create SQS queues:
- `<ASU_ID>-req-queue`
- `<ASU_ID>-resp-queue`

4) Deploy Lambda functions:
- `face-detection` with a Function URL (client sends JSON: base64 `content`, `request_id`, `filename`)
- `face-recognition` triggered by the request queue (sends `{request_id, result}` to response queue)

---

### Part 2: Edge extension (Greengrass + MQTT + SQS + Lambda)
1) Provision a Greengrass Core device (EC2 used as an emulator)
2) Create and deploy a Greengrass component:
- `com.clientdevices.FaceDetection`
- subscribes to MQTT: `clients/<ASU_ID>-IoTThing`
- extracts JSON fields: `encoded`, `request_id`, `filename`
- runs MTCNN on edge
- pushes detected faces to SQS request queue

3) IoT client device:
- publishes frames to the MQTT topic
- polls SQS response queue for results

4) (Optional / class bonus idea):
- if no face is detected, edge can directly push `"No-Face"` to the response queue

