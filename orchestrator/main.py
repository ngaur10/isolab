# orchestrator/main.py

import os
import re
import uuid
import time
import json
import asyncio
import secrets  # NEW: for generating secure random passwords

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, validator
from .cidr_pool import CIDRPool
from . import terraform as tf


app = FastAPI(title="Lab Orchestrator")
cidr_pool = CIDRPool()

# ── Session persistence ───────────────────────────────────────────────────────
SESSIONS_FILE = os.path.join(os.path.dirname(__file__), "sessions.json")

def load_sessions() -> dict:
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE) as f:
            return json.load(f)
    return {}

def save_sessions(sessions: dict):
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=2)

sessions = load_sessions()

# Restore CIDR pool state from persisted sessions
for sid, s in sessions.items():
    octet = int(s["cidr"].split(".")[1])
    cidr_pool.in_use[sid] = octet
    if octet in cidr_pool.available:
        cidr_pool.available.remove(octet)

# ── VPN IP ────────────────────────────────────────────────────────────────────
VPN_SERVER_IP = os.environ.get("VPN_SERVER_IP")
if not VPN_SERVER_IP:
    raise RuntimeError(
        "VPN_SERVER_IP environment variable is not set.\n"
        "Get the current IP from: AWS Console → EC2 → Instances → lab-vpn-server → Public IPv4\n"
        "Then run: $env:VPN_SERVER_IP = '<ip>' before starting uvicorn"
    )


# ── Startup: reschedule auto-destroy for sessions that survived a restart ─────
# Without this, labs running before a restart would never be auto-destroyed
@app.on_event("startup")
async def reschedule_auto_destroys():
    for sid, s in sessions.items():
        remaining = s["expires_at"] - time.time()
        delay = max(0, int(remaining))
        asyncio.create_task(auto_destroy(sid, delay=delay))
        print(f"[STARTUP] Rescheduled auto-destroy for session {sid} in {delay}s")


# ── Request model ─────────────────────────────────────────────────────────────
class StartLabRequest(BaseModel):
    user_id: str
    lab_name: str

    @validator("user_id", "lab_name")
    def alphanumeric_only(cls, v):
        if not re.match(r"^[a-z0-9\-]+$", v):
            raise ValueError("Only lowercase letters, numbers, and hyphens allowed")
        if len(v) > 32:
            raise ValueError("Maximum 32 characters")
        return v


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/start-lab")
async def start_lab(req: StartLabRequest):
    workspace = f"user-{req.user_id}-{req.lab_name}"

    # Prevent duplicate labs for the same user+lab combination
    for s in sessions.values():
        if s["workspace"] == workspace:
            raise HTTPException(409, f"Lab '{req.lab_name}' is already running for user '{req.user_id}'")

    session_id = str(uuid.uuid4())

    # NEW: Generate a secure random password for this lab session
    # Bob uses this to SSH into his lab VM — no .pem file needed
    lab_password = secrets.token_urlsafe(12)  # e.g. "xK9mP2nQrT4w"

    try:
        cidr = cidr_pool.acquire(session_id)
        outputs = tf.apply(req.user_id, cidr, req.lab_name, VPN_SERVER_IP, workspace, lab_password)
        lab_ip = outputs["lab_vm_ip"]["value"]

        sessions[session_id] = {
            "user_id":      req.user_id,
            "lab_name":     req.lab_name,
            "workspace":    workspace,
            "cidr":         cidr,
            "lab_password": lab_password,  # stored so destroy can pass it to terraform
            "expires_at":   time.time() + 3600,
        }
        save_sessions(sessions)

        asyncio.create_task(auto_destroy(session_id, delay=3600))

        # NEW: Return lab_ip, username and password to bob
        # Bob uses these to SSH in — no .pem file needed
        return {
            "session_id": session_id,
            "lab_ip":     lab_ip,
            "cidr":       cidr,
            "username":   "labuser",        # Linux user created on the VM
            "password":   lab_password,     # show this to bob ONCE
            "ssh_command": f"ssh labuser@{lab_ip}",  # ready-to-use command for bob
            "expires_in": "60 minutes",
        }

    except Exception as e:
        cidr_pool.release(session_id)
        raise HTTPException(500, str(e))


@app.delete("/stop-lab/{session_id}")
async def stop_lab(session_id: str):
    # Validate session_id format
    if not re.match(r"^[a-f0-9\-]{36}$", session_id):
        raise HTTPException(400, "Invalid session_id format — must be a UUID")

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    destroy_error = None
    try:
        tf.destroy(
            workspace=session["workspace"],
            user_id=session["user_id"],
            cidr=session["cidr"],
            lab_name=session["lab_name"],
            vpn_ip=VPN_SERVER_IP,
            lab_password=session["lab_password"],  # NEW: pass stored password to destroy
        )
    except Exception as e:
        destroy_error = e
    finally:
        cidr_pool.release(session_id)
        sessions.pop(session_id, None)
        save_sessions(sessions)

    if destroy_error:
        raise HTTPException(
            500,
            f"Terraform destroy failed (session cleaned up locally, AWS resources may still exist): {destroy_error}"
        )

    return {"status": "destroyed", "session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    return sessions


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_labs": cidr_pool.active_count(),
        "vpn_server_ip": VPN_SERVER_IP,
    }


# ── Auto-destroy expired sessions ─────────────────────────────────────────────
async def auto_destroy(session_id: str, delay: int):
    await asyncio.sleep(delay)
    if session_id in sessions:
        try:
            await stop_lab(session_id)
            print(f"[AUTO-DESTROY] Session {session_id} destroyed successfully")
        except Exception as e:
            print(f"[AUTO-DESTROY] ERROR: Failed to destroy session {session_id}: {e}")


# Run with:
#   $env:VPN_SERVER_IP = "YOUR_VPN_SERVER_IP"
#   uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000 --reload