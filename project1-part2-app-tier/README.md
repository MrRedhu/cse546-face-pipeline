# Project 1 Part 2 - Multi-tier EC2 + S3 + SQS + Autoscaling Controller

Two-tier EC2 pipeline: a web tier accepts uploads and queues work, while an app tier pulls jobs for inference and returns results. A custom controller scales app-tier instances based on queue depth. This is a sanitized portfolio copy and is not deployed by default.

## Architecture
<img src="../assets/diagrams/p1_part2.svg" width="900" alt="P1 Part 2 architecture">

## How it works
- Web tier stores the image in the S3 input bucket.
- Web tier sends metadata to the SQS request queue (image not sent over SQS).
- App tier polls the request queue, fetches the image from S3, runs inference, and writes to the S3 output bucket.
- App tier sends `{request_id, prediction}` to the response queue; web tier returns `filename:prediction`.
- Controller scales EC2 app-tier instances up/down based on queue depth.

## How to run (high-level, not deployed now)
- Create S3 input/output buckets and SQS request/response queues.
- Set environment variables for buckets/queues and region (see below or `.env.example` at repo root).
- Start the web tier (`web-tier/server.py`), app tier (`app-tier/backend.py`), and controller (`web-tier/controller.py`).

## Config (env vars)
- `ASU_ID` (required if bucket/queue names are not set explicitly)
- `AWS_REGION` (default `us-east-1`)
- `INPUT_BUCKET`, `OUTPUT_BUCKET`
- `REQ_QUEUE_NAME`, `RESP_QUEUE_NAME`
- `REQ_QUEUE_URL`, `RESP_QUEUE_URL` (optional direct URLs)
- `CSE546_WEB_PORT` (default `8000`)
- `RECEIVE_WAIT_SECS`, `VISIBILITY_TIMEOUT`
- `SELF_STOP`, `IDLE_CHECKS_BEFORE_STOP`

## What I learned / skills demonstrated
- Coordinating multi-tier systems with SQS and S3.
- Implementing a custom autoscaling controller with EC2 APIs.
- Managing async request/response flows and timeouts.
