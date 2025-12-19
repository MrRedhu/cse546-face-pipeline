# Demo (Portfolio)

This project is not currently deployed to AWS to avoid ongoing cloud costs.

If redeployed, the demo would show:
- Project 1 Part 1: upload image -> S3 store -> SimpleDB lookup -> `filename:prediction`
- Project 1 Part 2: upload -> S3 + SQS -> app-tier inference -> response queue -> result
- Project 2 Part 1: Function URL request -> detection -> SQS -> recognition -> SQS response
- Project 2 Part 2: MQTT frame publish -> Greengrass detection -> SQS -> Lambda recognition -> response

Suggested artifacts to add later:
- screenshots (CloudWatch logs, SQS queue metrics)
- short GIF/video of requests + outputs
