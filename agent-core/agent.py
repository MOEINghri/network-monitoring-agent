"""
Agent Core (Groq edition)
-------------------------
حلقه اصلی تصمیم‌گیری: هر چند وقت یک‌بار وضعیت شبکه را بررسی می‌کند،
با کمک یک مدل LLM روی Groq آن را تحلیل می‌کند، و در صورت لزوم از
ابزارهای مجاز (get_recent_metrics و execute_network_action) استفاده می‌کند.

از Groq به این دلیل استفاده شده که API آن سازگار با OpenAI است، پلن
رایگانش سخاوتمندانه و بدون محدودیت زمانی است، و از تمام مدل‌های آن
(از جمله llama-3.3-70b-versatile) پشتیبانی کامل از tool calling می‌شود.
"""

import os
import time
import json
import logging

from openai import OpenAI
from tools import TOOL_SCHEMAS, TOOL_IMPLEMENTATIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [agent] %(message)s")
log = logging.getLogger(__name__)

MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
POLL_INTERVAL_SECONDS = int(os.getenv("AGENT_POLL_INTERVAL_SECONDS", "60"))
TARGETS = [t.strip() for t in os.getenv("SNMP_TARGETS", "8.8.8.8").split(",") if t.strip()]

with open(os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt"), "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# Groq یک endpoint سازگار با OpenAI ارائه می‌دهد؛ فقط base_url و کلید عوض می‌شود
client = OpenAI(
    api_key=os.environ["GROQ_API_KEY"],
    base_url="https://api.groq.com/openai/v1",
)


def run_tool_loop(user_message: str, max_turns: int = 5):
    """
    یک حلقه ساده‌ی tool-use: پیام را به مدل می‌فرستد، اگر مدل درخواست
    استفاده از ابزار داد، ابزار را اجرا می‌کند و نتیجه را برمی‌گرداند، تا
    زمانی که مدل به پاسخ نهایی متنی برسد یا سقف max_turns برسد.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for turn in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls

        if not tool_calls:
            # پاسخ نهایی متنی
            return choice.message.content

        # پیام assistant را (همراه با درخواست‌های tool_call) به تاریخچه اضافه می‌کنیم
        messages.append(choice.message.model_dump(exclude_none=True))

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_input = {}

            log.info("Agent requested tool=%s input=%s", tool_name, tool_input)

            impl = TOOL_IMPLEMENTATIONS.get(tool_name)
            if impl is None:
                result = {"error": f"Unknown tool: {tool_name}"}
            else:
                result = impl(**tool_input)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "حداکثر تعداد مراحل تحلیل به پایان رسید بدون نتیجه‌گیری نهایی."


def monitor_cycle():
    """یک چرخه کامل بررسی وضعیت همه هدف‌های تعریف‌شده."""
    hosts_summary = ", ".join(TARGETS)
    prompt = (
        f"وضعیت فعلی شبکه را برای هاست‌های زیر بررسی کن: {hosts_summary}.\n"
        "برای هر هاست از ابزار get_recent_metrics استفاده کن (بازه 15 دقیقه اخیر).\n"
        "اگر مشکلی پیدا کردی که نیاز به اقدام دارد، از execute_network_action استفاده کن.\n"
        "در پایان یک خلاصه کوتاه فارسی از وضعیت کلی شبکه و هر اقدام انجام‌شده/پیشنهادی بده."
    )
    result = run_tool_loop(prompt)
    log.info("Monitor cycle result:\n%s", result)
    return result


def main():
    log.info("Agent started (model=%s). Monitoring targets: %s", MODEL, TARGETS)
    while True:
        try:
            monitor_cycle()
        except Exception as e:
            log.error("Error in monitor cycle: %s", e)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
