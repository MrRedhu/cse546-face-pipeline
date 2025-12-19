import os
import json
import base64
import io

import boto3
import numpy as np
from facenet_pytorch import MTCNN
from PIL import Image

# ---------- GLOBALS ----------

sqs = boto3.client("sqs")

# Get request queue URL from env with a fallback to your queue
REQUEST_QUEUE_URL = os.environ.get(
    "REQUEST_QUEUE_URL",
    "https://sqs.us-east-1.amazonaws.com/176087999560/1224308891-req-queue",
)

# One MTCNN instance reused across invocations
mtcnn = MTCNN(image_size=240, margin=0, min_face_size=20)


def _extract_body(event):
    """
    Support function URL payload v2.0 and direct test invocations.
    """
    if "body" in event and event["body"]:
        # Function URL / API Gateway: body is a JSON string
        return json.loads(event["body"])
    else:
        # Direct Lambda test invoke
        return event


def lambda_handler(event, context):
    try:
        body = _extract_body(event)

        content_b64 = body["content"]
        request_id = body["request_id"]
        filename = body.get("filename", "frame.jpg")

        # ------------ Decode image ------------
        img_bytes = base64.b64decode(content_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img = Image.fromarray(np.array(img))

        # ------------ Run face detection ------------
        face, prob = mtcnn(img, return_prob=True, save_path=None)

        if face is None:
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "request_id": request_id,
                        "message": "no face detected",
                    }
                ),
            }

        # Normalize tensor -> uint8 image
        face_img = face - face.min()
        face_img = face_img / face_img.max()
        face_img = (face_img * 255).byte().permute(1, 2, 0).numpy()

        face_pil = Image.fromarray(face_img, mode="RGB")

        # Resize smaller to keep message body well under SQS limits
        face_pil = face_pil.resize((160, 160))

        buf = io.BytesIO()
        # JPEG at moderate quality to keep it compact
        face_pil.save(buf, format="JPEG", quality=70, optimize=True)
        face_bytes = buf.getvalue()
        face_b64 = base64.b64encode(face_bytes).decode("utf-8")

        # Build *small* SQS message
        msg = {
            "request_id": request_id,
            "filename": filename,
            "face_image": face_b64,
        }

        message_body = json.dumps(msg)

        # Optional: log size in CloudWatch for debugging
        print(f"[FD] MessageBody length: {len(message_body)} bytes")

        sqs.send_message(
            QueueUrl=REQUEST_QUEUE_URL,
            MessageBody=message_body,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "request_id": request_id,
                    "message": "face queued for recognition",
                }
            ),
        }

    except Exception as e:
        print(f"[FD] ERROR: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }

