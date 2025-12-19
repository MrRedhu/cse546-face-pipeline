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

# Set via Lambda console (Environment variable)
RESPONSE_QUEUE_URL = os.environ.get("RESPONSE_QUEUE_URL")

# Path to the weights file (copied in Dockerfile / Lambda package)
WEIGHTS_PATH = os.environ.get("WEIGHTS_PATH", "/var/task/resnetV1_video_weights_1.pt")

# ------------------ Load embeddings + labels once ---------------------

_saved = torch.load(WEIGHTS_PATH, map_location="cpu")
_embedding_list_raw = _saved[0]   # list of tensors/arrays
_name_list = _saved[1]            # list of strings

_emb_matrix_list = []
for emb_db in _embedding_list_raw:
    t = emb_db
    # Handle numpy arrays as well as tensors
    if isinstance(t, np.ndarray):
        t = torch.from_numpy(t)
    # Flatten (e.g., (1, 512) -> (512,))
    if t.ndim > 1:
        t = t.view(-1)
    _emb_matrix_list.append(t.float())

# Final DB embedding matrix, shape: (N, 512)
_emb_matrix = torch.stack(_emb_matrix_list, dim=0)

# Use CPU (Lambda has no GPU by default)
device = torch.device("cpu")

_emb_matrix = _emb_matrix.to(device)

# Load FaceNet model once
_resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)

# Disable autograd globally (no training here)
torch.set_grad_enabled(False)


def _preprocess_face_from_b64(face_b64: str) -> torch.Tensor:
    """
    Decode base64 JPEG, convert to tensor, normalize as expected by InceptionResnetV1.
    Output shape: (1, 3, 240, 240) on the correct device.
    """
    face_bytes = base64.b64decode(face_b64)
    img = Image.open(io.BytesIO(face_bytes)).convert("RGB")
    img = img.resize((240, 240))

    img_np = np.array(img).astype(np.float32) / 255.0  # [0,1]
    img_np = np.transpose(img_np, (2, 0, 1))           # HWC -> CHW

    # Normalize to [-1, 1]
    img_np = (img_np - 0.5) / 0.5

    x = torch.from_numpy(img_np).unsqueeze(0)          # (1, 3, 240, 240)
    return x.to(device)


def _recognize_face(face_b64: str) -> str:
    """
    Compute embedding for input face and find nearest neighbor in _emb_matrix.
    Uses squared L2 distance (same nearest neighbor as plain L2).
    """
    x = _preprocess_face_from_b64(face_b64)

    with torch.no_grad():
        emb = _resnet(x)[0].float()   # shape (512,)

        # Vectorized squared L2: d^2 = sum_i (emb_i - db_i)^2 over dim=1
        emb_row = emb.unsqueeze(0)          # (1, 512)
        diff = _emb_matrix - emb_row        # (N, 512)
        dists = (diff * diff).sum(dim=1)    # (N,)

        min_idx = int(torch.argmin(dists).item())

    return _name_list[min_idx]


def lambda_handler(event, context):
    """
    SQS-triggered Lambda handler.

    For each record:
      - Message body must contain: { "request_id": ..., "face_image": "<b64>" }
      - Run recognition on face_image
      - Push {request_id, result} to RESPONSE_QUEUE_URL
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
        print(f"[FR] ERROR: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

