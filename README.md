# CSE 546 Face Pipeline (Portfolio)

This repo is a sanitized, recruiter-ready snapshot of my CSE 546 cloud face-recognition pipelines across EC2, S3, SimpleDB, SQS, Lambda, and Greengrass. It is not deployed today; all resources and credentials are expected to be provided by the user.

## Architecture
<img src="assets/diagrams/p1_part1.svg" width="900" alt="Project 1 Part 1 architecture">
<img src="assets/diagrams/p1_part2.svg" width="900" alt="Project 1 Part 2 architecture">
<img src="assets/diagrams/p2_part1.svg" width="900" alt="Project 2 Part 1 architecture">
<img src="assets/diagrams/p2_part2.svg" width="900" alt="Project 2 Part 2 architecture">

## How it works
- P1 Part 1: HTTP upload -> S3 input -> SimpleDB lookup -> plaintext result.
- P1 Part 2: HTTP upload -> S3 input -> SQS request -> EC2 app tier inference -> S3 output + SQS response.
- P2 Part 1: Function URL -> face detection -> SQS request -> recognition Lambda -> SQS response.
- P2 Part 2: MQTT frames -> Greengrass face detection -> SQS request -> cloud recognition -> SQS response (optional No-Face fast path).

## How to run (high-level, not deployed now)
- Provision AWS resources in your account (S3 buckets, SimpleDB domain, SQS queues, EC2, Lambda, Greengrass).
- Configure environment variables from `.env.example` with your own resource names/URLs.
- Deploy each component (EC2 web/app tiers, Lambda functions, Greengrass component) and test end-to-end.

## What I learned / skills demonstrated
- Designing multi-tier pipelines across IaaS, serverless, and edge/IoT.
- Working with S3, SimpleDB, SQS, Lambda, and Greengrass.
- Managing async workflows, queue-based coordination, and autoscaling logic.
- Packaging ML inference code for constrained environments.
