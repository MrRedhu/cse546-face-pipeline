# Project 1 Part 2 — Multi-tier pipeline + autoscaling (EC2 + S3 + SQS)

## What it does
- Web tier receives uploads, stores image in S3 input bucket, sends metadata to SQS request queue,
  waits for result via SQS response queue, then returns `filename:prediction`.
- App tier pulls from request queue, fetches image from S3, runs inference, writes output to S3 output bucket,
  and pushes result to response queue.
- Controller scales app-tier instances up/down based on load.

## AWS resources (not currently deployed)
- S3: `<ASU_ID>-in-bucket`, `<ASU_ID>-out-bucket`
- SQS: `<ASU_ID>-req-queue`, `<ASU_ID>-resp-queue`

## How to run (high-level)
1) Provision buckets + queues in your account (and any required EC2 roles/security groups).
2) Set env vars (see `.env.example` at repo root).
3) Start web tier.
4) Start controller.
5) Start app-tier instances (controller may launch/terminate them depending on your implementation).

## Notes
This repo is sanitized; no credentials or key files are included.

## Architecture
<img src="../assets/diagrams/p1_part2.svg" width="900" alt="P1 Part 2 architecture">
