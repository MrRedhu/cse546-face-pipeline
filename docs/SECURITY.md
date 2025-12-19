# Security Notes (Portfolio Copy)

This repository is a **sanitized portfolio copy** of coursework.

## Not included (intentionally removed)
- Any AWS keys (ACCESS KEY ID / SECRET ACCESS KEY)
- `credentials/credentials.txt`
- Private key material (e.g., `*.pem`, `*.key`, `*.crt`)
- Local environment files (e.g., `.env`)

## Safe ways to run this code
Use one of these approaches (never commit secrets):

### Option A: AWS CLI profile (recommended)
- Configure locally with `aws configure --profile <name>`
- Run code using that profile in your environment

### Option B: Environment variables
Export credentials only in your terminal/session:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN` (if using temporary creds)
- `AWS_REGION`

## IAM guidance (high level)
- Use least privilege for any IAM users/roles.
- Prefer temporary credentials when possible.
- Keep any key files outside the repo (or use AWS Systems Manager / Secrets Manager in real projects).
