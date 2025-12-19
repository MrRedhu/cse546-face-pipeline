import os
import json
import base64
import io
import time
from collections import deque

import boto3
import numpy as np
from PIL import Image

# Greengrass IPC for Pubsub
import awsiot.greengrasscoreipc
from awsiot.greengrasscoreipc import client as gg_client
from awsiot.greengrasscoreipc.model import (
    SubscribeToTopicRequest,
    SubscriptionResponseMessage,
)

from facenet_pytorch import MTCNN

# ---------- CONFIG ----------

ASU_ID = "1224308891"

# The MQTT topic the workload generator publishes to
MQTT_TOPIC = f"clients/{ASU_ID}-IoTThing"

# SQS request queue URL (same as Part I)
REQUEST_QUEUE_URL = os.environ.get(
    "REQUEST_QUEUE_URL",
    "https://sqs.us-east-1.amazonaws.com/176087999560/1224308891-req-queue",
)

# NEW: SQS response queue URL for bonus (No-Face short-circuit)
RESPONSE_QUEUE_URL = os.environ.get(
    "RESPONSE_QUEUE_URL",
    "https://sqs.us-east-1.amazonaws.com/176087999560/1224308891-resp-queue",
)

# ---------- GLOBALS ----------

# Use Greengrass IAM credentials; just pin region
sqs = boto3.client("sqs", region_name="us-east-1")

# Same MTCNN config as Lambda
mtcnn = MTCNN(image_size=240, margin=0, min_face_size=20)

# One IPC client for the whole component
ipc_client = awsiot.greengrasscoreipc.connect()
TIMEOUT = 10

# ---------- REQUEST-ID DEDUP CACHE ----------

# We only need to deduplicate over a recent window to catch retries.
# Keep up to the last 1000 successfully-processed request_ids.
_SEEN_MAX = 1000
_seen_req_ids = set()
_seen_order = deque()


def _mark_request_id_seen(request_id: str) -> None:
    """
    Remember that we've successfully processed & forwarded this request_id.
    Bounded LRU-ish cache to avoid unbounded growth.
    """
    _seen_req_ids.add(request_id)
    _seen_order.append(request_id)
    # Evict oldest if we exceed the bound
    if len(_seen_order) > _SEEN_MAX:
        old = _seen_order.popleft()
        _seen_req_ids.discard(old)


def _already_seen_request_id(request_id: str) -> bool:
    return request_id in _seen_req_ids


def _send_no_face_response(request_id: str) -> None:
    """
    Bonus behavior: if no face is detected on the edge,
    send a direct 'No-Face' result to the RESPONSE queue
    instead of sending anything to the REQUEST queue / Lambda.
    """
    if not RESPONSE_QUEUE_URL:
        print(
            f"[FD] WARNING: RESPONSE_QUEUE_URL not set; cannot send No-Face for {request_id}",
            flush=True,
        )
        return

    out_msg = {
        "request_id": request_id,
        "result": "No-Face",
    }

    body = json.dumps(out_msg)
    print(
        f"[FD] request_id={request_id}: no face detected; sending No-Face to response SQS "
        f"(len={len(body)} bytes)",
        flush=True,
    )

    sqs.send_message(
        QueueUrl=RESPONSE_QUEUE_URL,
        MessageBody=body,
    )

    # Mark as seen so we don't reprocess duplicate retries
    _mark_request_id_seen(request_id)


def _process_frame_message(msg_str: str) -> None:
    """
    Handle one JSON message from MQTT topic:

    {
        "encoded": "<base64 frame>",
        "request_id": "...",
        "filename": "test_XX.jpg"
    }
    """
    try:
        body = json.loads(msg_str)

        # Part II spec: key is `encoded`, not `content`
        content_b64 = body["encoded"]
        request_id = body["request_id"]
        filename = body.get("filename", "frame.jpg")

        # --- Request-id dedup check BEFORE heavy work ---
        if _already_seen_request_id(request_id):
            print(
                f"[FD] duplicate request_id={request_id} - skipping re-processing",
                flush=True,
            )
            return

        # --- Decode image ---
        img_bytes = base64.b64decode(content_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img = Image.fromarray(np.array(img))

        # --- Run face detection ---
        face, prob = mtcnn(img, return_prob=True, save_path=None)

        # BONUS PATH: no face detected -> send No-Face to RESPONSE queue and return
        if face is None:
            _send_no_face_response(request_id)
            return

        # ---------- Existing path: face detected, send to REQUEST queue ----------

        # Normalize tensor -> uint8 RGB image
        face_img = face - face.min()
        if face_img.max() > 0:
            face_img = face_img / face_img.max()
        face_img = (face_img * 255).byte().permute(1, 2, 0).numpy()

        face_pil = Image.fromarray(face_img, mode="RGB")

        # Resize smaller (same as Part I)
        face_pil = face_pil.resize((160, 160))

        buf = io.BytesIO()
        face_pil.save(buf, format="JPEG", quality=70, optimize=True)
        face_bytes = buf.getvalue()
        face_b64 = base64.b64encode(face_bytes).decode("utf-8")

        msg = {
            "request_id": request_id,
            "filename": filename,
            "face_image": face_b64,
        }

        message_body = json.dumps(msg)
        print(
            f"[FD] request_id={request_id}: sending face to REQUEST SQS, size={len(message_body)} bytes",
            flush=True,
        )

        # Mark as seen only when we're about to send the job forward
        _mark_request_id_seen(request_id)

        sqs.send_message(
            QueueUrl=REQUEST_QUEUE_URL,
            MessageBody=message_body,
        )

    except Exception as e:
        print(f"[FD] ERROR processing message: {e}", flush=True)


class StreamHandler(gg_client.SubscribeToTopicStreamHandler):
    """
    Proper Greengrass stream handler for local Pubsub.
    Must subclass SubscribeToTopicStreamHandler so the
    IPC library can call ._model_name(), etc.
    """

    def __init__(self):
        super().__init__()

    def on_stream_event(self, event: SubscriptionResponseMessage) -> None:
        """
        Called for each Pubsub message on the subscribed topic.
        """
        try:
            # Prefer raw binary payload (bridge from IoT Core usually uses this)
            payload_str = None

            if event.binary_message is not None:
                payload_bytes = bytes(event.binary_message.message)
                payload_str = payload_bytes.decode("utf-8", errors="ignore")
            elif event.json_message is not None:
                # Some setups deliver JSON directly
                msg_obj = event.json_message.message
                # If it's already a dict, re-dump to string; otherwise cast
                if isinstance(msg_obj, (dict, list)):
                    payload_str = json.dumps(msg_obj)
                else:
                    payload_str = str(msg_obj)

            if payload_str is None:
                print("[FD] Received event without payload", flush=True)
                return

            print(
                f"[FD] Received MQTT message on {MQTT_TOPIC}: {payload_str[:200]}...",
                flush=True,
            )

            _process_frame_message(payload_str)

        except Exception as e:
            print(f"[FD] ERROR in on_stream_event: {e}", flush=True)

    def on_stream_error(self, error: Exception) -> bool:
        print(f"[FD] Stream error: {error}", flush=True)
        # Returning True closes the stream; False would keep it open
        return True

    def on_stream_closed(self) -> None:
        print("[FD] Stream closed.", flush=True)


def main():
    print(
        f"[FD] Starting FaceDetection component. Subscribing to topic: {MQTT_TOPIC}",
        flush=True,
    )

    # Build subscribe request
    request = SubscribeToTopicRequest()
    request.topic = MQTT_TOPIC

    handler = StreamHandler()
    operation = ipc_client.new_subscribe_to_topic(handler)
    future = operation.activate(request)
    future.result(TIMEOUT)

    print(f"[FD] Successfully subscribed to {MQTT_TOPIC}", flush=True)

    # Keep component alive
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
