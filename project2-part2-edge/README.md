# Project 2 Part 2 - Edge/IoT Extension (Greengrass + MQTT + SQS + Lambda)

Greengrass runs face detection on the edge from MQTT frames, then forwards work to cloud recognition via SQS. This is a sanitized portfolio copy and is not deployed by default.

## Architecture
<img src="../assets/diagrams/p2_part2.svg" width="900" alt="P2 Part 2 architecture">

## How it works
- IoT client publishes base64 frames to an MQTT topic.
- Greengrass component performs MTCNN face detection on the edge.
- Detected faces are sent to the SQS request queue for cloud recognition.
- Recognition Lambda sends results to the SQS response queue.
- Optional fast path: if no face is detected, edge can send `"No-Face"` directly to the response queue.

## How to run (high-level, not deployed now)
- Provision IoT Core + Greengrass Core device.
- Create SQS request/response queues and deploy the recognition Lambda.
- Set environment variables (see below or `.env.example` at repo root).
- Deploy the Greengrass component and publish MQTT frames for testing.

## Config (env vars)
- `ASU_ID` (required if `MQTT_TOPIC` is not set)
- `AWS_REGION` (default `us-east-1`)
- `MQTT_TOPIC` (default `clients/<ASU_ID>-IoTThing`)
- `REQUEST_QUEUE_URL` (required)
- `RESPONSE_QUEUE_URL` (optional for No-Face fast path)

## What I learned / skills demonstrated
- Edge ML with Greengrass and MQTT integration.
- Hybrid pipelines that bridge IoT and cloud services.
