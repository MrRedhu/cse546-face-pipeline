import os
import json
import base64
import io

import boto3
import numpy as np
import torch
from PIL import Image
from facenet_pytorch import InceptionResnetV1

# ---------- Global init (runs once per container cold start) ----------

sqs = boto3.client("sqs")

# You will set this env var in the Lambda console for face-recognition
RESPONSE_QUEUE_URL = os.environ.get("RESPONSE_QUEUE_URL")

# Path to the weights file (copied in Dockerfile)
WEIGHTS_PATH = os.environ.get("WEIGHTS_PATH", "/var/task/resnetV1_video_weights_1.pt")

# Load embeddings + labels
_saved = torch.load(WEIGHTS_PATH, map_location="cpu")
_embedding_list = _saved[0]   # list of tensors
_name_list = _saved[1]        # list of strings

# Load the FaceNet model
_resnet = InceptionResnetV1(pretrained="vggface2").eval()


def _preprocess_face_from_b64(face_b64: str) -> torch.Tensor:
    """
    Decode base64 JPEG, convert to tensor, normalize as expected by InceptionResnetV1.
    Output shape: (1, 3, 240, 240)
    """
    face_bytes = base64.b64decode(face_b64)
    img = Image.open(io.BytesIO(face_bytes)).convert("RGB")
    img = img.resize((240, 240))

    img_np = np.array(img).astype(np.float32) / 255.0  # [0,1]
    img_np = np.transpose(img_np, (2, 0, 1))           # HWC -> CHW

    # Normalize to [-1, 1] (standard for facenet-pytorch)
    img_np = (img_np - 0.5) / 0.5

    x = torch.from_numpy(img_np).unsqueeze(0)          # (1,3,240,240)
    return x


def _recognize_face(face_b64: str) -> str:
    """
    Compute embedding for input face and find nearest neighbor in _embedding_list.
    Returns the corresponding label from _name_list.
    """
    x = _preprocess_face_from_b64(face_b64)

    with torch.no_grad():
        emb = _resnet(x).squeeze(0)   # shape (512,)

    dist_list = []
    for emb_db in _embedding_list:
        db_vec = emb_db
        if db_vec.ndim > 1:
            db_vec = db_vec.squeeze(0)
        dist = torch.dist(emb, db_vec).item()
        dist_list.append(dist)

    min_idx = int(np.argmin(np.array(dist_list)))
    return _name_list[min_idx]


def lambda_handler(event, context):
    """
    SQS-triggered Lambda handler.

    - For each SQS record:
      - Get {request_id, face} from message body.
      - Run recognition.
      - Push {request_id, result} to RESPONSE_QUEUE_URL.
    """
    if not RESPONSE_QUEUE_URL:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "RESPONSE_QUEUE_URL not set in environment"})
        }

    try:
        records = event.get("Records", [])
        processed = 0

        for record in records:
            body = json.loads(record["body"])
            request_id = body["request_id"]
            face_b64 = body["face_image"]
            print(f"[FR] processing request_id={request_id}")


            label = _recognize_face(face_b64)
            print(f"[FR] recognized label={label} for request_id={request_id}")

            out_msg = {
                "request_id": request_id,
                "result": label,
            }

            sqs.send_message(
                QueueUrl=RESPONSE_QUEUE_URL,
                MessageBody=json.dumps(out_msg)
            )

            processed += 1

        return {
            "statusCode": 200,
            "body": json.dumps({"processed": processed})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

