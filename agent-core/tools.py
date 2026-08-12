"""
تعریف ابزارهایی که Agent مجاز به استفاده از آن‌هاست.
هر ابزار دقیقاً یک قابلیت محدود دارد - این طراحی عمدی است تا از
دسترسی آزاد Agent به سیستم جلوگیری شود.
"""

import os
import requests

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "net-agent")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "network-metrics")
GUARDRAIL_URL = os.getenv("GUARDRAIL_URL", "http://localhost:8000")
NOTIFIER_URL = os.getenv("NOTIFIER_URL", "http://localhost:8001")


# ---------------------------------------------------------------------------
# Tool schemas (به فرمت OpenAI function calling - مورد استفاده Groq)
# ---------------------------------------------------------------------------
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_recent_metrics",
            "description": "دریافت متریک‌های اخیر یک یا چند هاست شبکه (latency، packet loss، وضعیت reachability) برای بازه زمانی مشخص.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "آدرس IP یا نام هاست موردنظر"},
                    "minutes": {"type": "integer", "description": "بازه زمانی بر حسب دقیقه (پیش‌فرض 15)"},
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_network_action",
            "description": "درخواست اجرای یک اقدام کنترل‌شده روی شبکه. این درخواست از فیلتر Guardrail عبور می‌کند و ممکن است نیاز به تأیید انسانی داشته باشد یا رد شود.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_name": {
                        "type": "string",
                        "description": "نام اکشن، باید دقیقاً یکی از موارد whitelist شده باشد (مثل restart_service، block_ip، change_vlan_port)",
                    },
                    "params": {
                        "type": "object",
                        "description": "پارامترهای لازم برای آن اکشن خاص",
                    },
                    "reason": {
                        "type": "string",
                        "description": "توضیح کوتاه اینکه چرا این اکشن لازم است",
                    },
                },
                "required": ["action_name", "params", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_alert",
            "description": "ارسال یک هشدار به تکنسین شبکه (از طریق تلگرام). از این ابزار برای اطلاع‌رسانی هرگونه یافته مهم استفاده کن - چه یک مشکل بحرانی باشد، چه فقط یک نکته اطلاعاتی که تکنسین باید بداند.",
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["informational", "warning", "critical"],
                        "description": "شدت هشدار",
                    },
                    "title": {
                        "type": "string",
                        "description": "عنوان کوتاه هشدار (یک خط)",
                    },
                    "message": {
                        "type": "string",
                        "description": "توضیح کامل‌تر، شامل جزئیات فنی مرتبط",
                    },
                },
                "required": ["severity", "title", "message"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# پیاده‌سازی واقعی ابزارها
# ---------------------------------------------------------------------------
def get_recent_metrics(host: str, minutes: int = 15):
    """کوئری ساده از InfluxDB با Flux."""
    flux_query = f'''
    from(bucket: "{INFLUXDB_BUCKET}")
      |> range(start: -{minutes}m)
      |> filter(fn: (r) => r._measurement == "network_health" and r.host == "{host}")
    '''
    try:
        resp = requests.post(
            f"{INFLUXDB_URL}/api/v2/query?org={INFLUXDB_ORG}",
            headers={
                "Authorization": f"Token {INFLUXDB_TOKEN}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux_query,
            timeout=10,
        )
        resp.raise_for_status()
        return {"host": host, "raw_csv": resp.text[:4000]}  # محدود شده برای جلوگیری از پاسخ‌های خیلی بزرگ
    except Exception as e:
        return {"error": str(e), "host": host}


def execute_network_action(action_name: str, params: dict, reason: str):
    """ارسال درخواست به Guardrail Engine - Agent هرگز مستقیم به دستگاه وصل نمی‌شود."""
    try:
        resp = requests.post(
            f"{GUARDRAIL_URL}/execute",
            json={
                "action_name": action_name,
                "params": params,
                "reason": reason,
                "requested_by": "agent",
            },
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def send_alert(severity: str, title: str, message: str):
    """ارسال هشدار به Notifier Service - این تنها راه Agent برای اطلاع‌رسانی به انسان است."""
    try:
        resp = requests.post(
            f"{NOTIFIER_URL}/alert",
            json={"severity": severity, "title": title, "message": message},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"sent": False, "error": str(e)}


TOOL_IMPLEMENTATIONS = {
    "get_recent_metrics": get_recent_metrics,
    "execute_network_action": execute_network_action,
    "send_alert": send_alert,
}
