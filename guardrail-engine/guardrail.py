"""
Guardrail Engine
----------------
تنها نقطه‌ای در کل سیستم که مجاز است اکشن‌ها روی تجهیزات شبکه اجرا شود.
Agent هیچ‌وقت مستقیماً به دستگاه‌ها متصل نمی‌شود؛ همیشه از این سرویس عبور می‌کند.

مسئولیت‌ها:
1. بررسی اینکه اکشن درخواستی در whitelist وجود دارد.
2. بررسی سطح ریسک و اینکه آیا نیاز به تأیید انسانی دارد یا نه.
3. اگر GUARDRAIL_MODE=observe باشد، هیچ اکشنی واقعاً اجرا نمی‌شود (فقط شبیه‌سازی/لاگ).
4. ثبت کامل هر درخواست (audit log) برای شفافیت و بررسی بعدی.
"""

import os
import time
import logging
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [guardrail] %(message)s")
log = logging.getLogger(__name__)

GUARDRAIL_MODE = os.getenv("GUARDRAIL_MODE", "observe")  # observe | act

with open(os.path.join(os.path.dirname(__file__), "whitelist.yaml"), "r", encoding="utf-8") as f:
    WHITELIST = yaml.safe_load(f)["actions"]

# صف ساده در حافظه برای اکشن‌هایی که منتظر تأیید انسانی هستند
PENDING_APPROVALS = {}

app = FastAPI(title="Network Agent Guardrail")


class ActionRequest(BaseModel):
    action_name: str
    params: dict
    requested_by: str = "agent"
    reason: Optional[str] = None


@app.post("/execute")
def execute_action(req: ActionRequest):
    action = WHITELIST.get(req.action_name)
    if action is None:
        log.warning("REJECTED unknown action: %s", req.action_name)
        raise HTTPException(status_code=400, detail=f"Action '{req.action_name}' is not in the whitelist.")

    missing = [p for p in action["params"] if p not in req.params]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required params: {missing}")

    audit_entry = {
        "action": req.action_name,
        "params": req.params,
        "risk_level": action["risk_level"],
        "reason": req.reason,
        "requested_by": req.requested_by,
        "timestamp": time.time(),
    }
    log.info("AUDIT %s", audit_entry)

    # اکشن‌های پرریسک همیشه نیاز به تأیید انسانی دارند، صرف‌نظر از mode
    if action["requires_approval"]:
        approval_id = f"{req.action_name}-{int(time.time())}"
        PENDING_APPROVALS[approval_id] = audit_entry
        log.info("PENDING approval required for %s (id=%s)", req.action_name, approval_id)
        return {
            "status": "pending_approval",
            "approval_id": approval_id,
            "message": "این اکشن ریسک بالایی دارد و نیاز به تأیید تکنسین دارد.",
        }

    if GUARDRAIL_MODE == "observe":
        log.info("OBSERVE MODE - action simulated, not executed: %s", req.action_name)
        return {"status": "simulated", "message": "سیستم در حالت observe است؛ اکشن واقعاً اجرا نشد."}

    # اینجا نقطه‌ای است که در نسخه واقعی، اتصال به دستگاه (netmiko/napalm) انجام می‌شود
    log.info("EXECUTING action=%s params=%s", req.action_name, req.params)
    # TODO: پیاده‌سازی واقعی اجرای اکشن روی دستگاه
    return {"status": "executed", "action": req.action_name, "params": req.params}


@app.post("/approve/{approval_id}")
def approve_action(approval_id: str):
    entry = PENDING_APPROVALS.pop(approval_id, None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Approval ID not found or already handled.")
    log.info("APPROVED by technician: %s", entry)
    # اینجا اکشن واقعاً اجرا می‌شود (در نسخه واقعی)
    return {"status": "approved_and_executed", "action": entry["action"], "params": entry["params"]}


@app.post("/reject/{approval_id}")
def reject_action(approval_id: str):
    entry = PENDING_APPROVALS.pop(approval_id, None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Approval ID not found or already handled.")
    log.info("REJECTED by technician: %s", entry)
    return {"status": "rejected", "action": entry["action"]}


@app.get("/pending")
def list_pending():
    return PENDING_APPROVALS


@app.get("/whitelist")
def get_whitelist():
    return WHITELIST


@app.get("/health")
def health():
    return {"status": "ok", "mode": GUARDRAIL_MODE}
