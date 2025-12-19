# Project 2 Part 1 — Serverless face pipeline (Lambda + ECR + SQS)

## What it does
Two-stage pipeline:
1) `face-detection` (Function URL) accepts base64 frames + request metadata, performs face detection, and enqueues work.
2) `face-recognition` is triggered by the SQS request queue, performs recognition, and writes results to SQS response queue.

## AWS resources (not currently deployed)
- ECR repo (container image for Lambda)
- SQS request queue + response queue
- Lambda functions: face-detection (Function URL), face-recognition (SQS trigger)

## How to run (high-level)
1) Build/push a Lambda container image to ECR (if using containers).
2) Create SQS queues and wire triggers.
3) Set env vars (see `.env.example` at repo root) and deploy.

## Notes
This repo is sanitized; no credentials are included.

## Architecture
<img src="../assets/diagrams/p2_part1.svg" width="900" alt="P2 Part 1 architecture">
