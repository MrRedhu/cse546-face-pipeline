# Project 1 Part 1 - EC2 Web Tier + S3 + SimpleDB

Single EC2 web service that accepts image uploads, writes to S3, looks up labels in SimpleDB, and returns a plaintext `filename:prediction`. This is a sanitized portfolio copy and is not deployed by default.

## Architecture
<img src="../assets/diagrams/p1_part1.svg" width="900" alt="P1 Part 1 architecture">

## How it works
- Client sends multipart POST to `/` with form key `inputFile`.
- Server uploads the file to the S3 input bucket.
- Server looks up the basename in a SimpleDB domain.
- Server returns `basename:label` as plain text.

## How to run (high-level, not deployed now)
- Create an S3 input bucket and SimpleDB domain in your AWS account.
- Set environment variables (see below or `.env.example` at repo root).
- Run `web-tier/server.py` on an EC2 instance (or locally with AWS creds configured).

## Config (env vars)
- `ASU_ID` (required if `INPUT_BUCKET` or `SDB_DOMAIN` are not set)
- `AWS_REGION` (default `us-east-1`)
- `INPUT_BUCKET` (S3 bucket name for uploads)
- `SDB_DOMAIN` (SimpleDB domain name)
- `PORT` (default `8000`)

## What I learned / skills demonstrated
- Building a minimal HTTP upload service with multipart parsing.
- Integrating S3 and SimpleDB for storage and lookup.
- Threaded HTTP serving and basic error handling.
