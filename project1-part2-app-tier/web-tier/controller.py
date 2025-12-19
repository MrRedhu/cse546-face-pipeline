#!/usr/bin/env python3
import os, time, boto3
ASU_ID = os.environ.get("ASU_ID", "1224308891").strip()
REGION = "us-east-1"
REQ_QUEUE_NAME = f"{ASU_ID}-req-queue"
MAX_APP = 15
NAME_PREFIX = "app-tier-instance-"
session = boto3.Session(region_name=REGION)
sqs = session.client("sqs"); ec2 = session.client("ec2")

def qurl(n): return sqs.get_queue_url(QueueName=n)["QueueUrl"]
def qdepth(u):
    a=sqs.get_queue_attributes(QueueUrl=u, AttributeNames=["ApproximateNumberOfMessages","ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    return int(a.get("ApproximateNumberOfMessages","0")), int(a.get("ApproximateNumberOfMessagesNotVisible","0"))
def ids(states):
    fs=[{"Name":"tag:Name","Values":[f"{NAME_PREFIX}*"]},{"Name":"instance-state-name","Values":states}]
    out=[]; r=ec2.describe_instances(Filters=fs)
    for R in r["Reservations"]:
        for i in R["Instances"]: out.append(i["InstanceId"])
    return out
def start_n(n):
    if n<=0: return
    stopped=ids(["stopped"])[:n]
    if stopped: ec2.start_instances(InstanceIds=stopped)
def stop_n(n):
    if n<=0: return
    running=ids(["running"])[:n]
    if running: ec2.stop_instances(InstanceIds=running)
def main():
    req = qurl(REQ_QUEUE_NAME)
    print("[AS] controller up", flush=True)

    import math, time
    EMPTY_COOLDOWN_SEC = 1.5          # keep this small to pass the 5s check comfortably
    SCALE_IN_COOLDOWN_SEC = 2.0
    LOW_LOAD_SUSTAIN_SEC = 2.0

    last_nonempty_ts = time.time()
    last_scale_in_ts = 0.0
    below_desired_since = None

    while True:
        try:
            vis, infl = qdepth(req)
            running = len(ids(["running"]))
            pending = len(ids(["pending"]))
            desired = min(vis + infl, MAX_APP)
            total = running + pending
            now = time.time()

            # IMPORTANT: start/reset the "non-empty" clock ONLY when queues/pending are non-empty
            if (vis + infl) > 0 or pending > 0:
                last_nonempty_ts = now

            print(f"[AS] q: vis={vis} infl={infl} | EC2: running={running} pending={pending} | desired={desired} total={total}",
                  flush=True)

            # ---- scale OUT ----
            if desired > total:
                need = desired - total
                print(f"[AS] start_n({need})", flush=True)
                start_n(need)

            # ---- scale IN (gradual when not fully empty) ----
            elif desired < running:
                if below_desired_since is None:
                    below_desired_since = now
                sustained = (now - below_desired_since) >= LOW_LOAD_SUSTAIN_SEC
                cooldown_ok = (now - last_scale_in_ts) >= SCALE_IN_COOLDOWN_SEC
                if sustained and cooldown_ok:
                    idle = max(running - infl, 0)
                    wish_to_stop = min(running - desired, idle)
                    if wish_to_stop > 0:
                        step_cap = max(1, min(4, math.ceil(running * 0.25)))
                        to_stop = min(wish_to_stop, step_cap)
                        print(f"[AS] stop_n({to_stop}) (idle={idle}, cap={step_cap})", flush=True)
                        stop_n(to_stop)
                        last_scale_in_ts = now
            else:
                below_desired_since = None

            # ---- FAST stop-all when truly empty ----
            if vis == 0 and infl == 0 and running > 0:
                if (now - last_nonempty_ts) >= EMPTY_COOLDOWN_SEC:
                    print(f"[AS] stop_n({running}) (all empty for {EMPTY_COOLDOWN_SEC}s)", flush=True)
                    stop_n(running)  # idempotent; re-issues until EC2 shows 0 running

            time.sleep(0.5)

        except Exception as e:
            print("[AS] error:", e, flush=True)
            time.sleep(1)


if __name__=="__main__": main()
