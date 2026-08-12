# Network Monitoring & Control Agent

یک Agent هوشمند مبتنی بر LLM (Groq / Llama 3.3 70B) که وضعیت شبکه را مانیتور می‌کند، مشکلات را تحلیل می‌کند، به تکنسین شبکه هشدار می‌دهد (از طریق تلگرام) و در صورت لزوم می‌تواند مجموعه‌ای محدود و کنترل‌شده از اقدامات اصلاحی را (با یا بدون تأیید انسانی) درخواست کند.

![Status](https://img.shields.io/badge/status-active--development-yellow)
![License](https://img.shields.io/badge/license-MIT-blue)

## چرا این پروژه؟

بیشتر ابزارهای مانیتورینگ شبکه (Zabbix، Nagios، PRTG و...) فقط داده نشون می‌دن و تصمیم‌گیری رو به عهده انسان می‌ذارن. این پروژه یک لایه‌ی تصمیم‌گیری هوشمند روی این داده‌ها اضافه می‌کنه، اما با تمرکز جدی روی **ایمنی**: یک AI Agent هرگز نباید دسترسی آزاد به تغییر تنظیمات شبکه داشته باشه. طراحی این پروژه بر پایه‌ی جداسازی «تصمیم‌گیری» (Agent) از «اجرا» (Guardrail) است.

## دمو

| داشبورد Grafana | هشدار در تلگرام |
|---|---|
| ![dashboard](docs/screenshots/grafana-dashboard.png) | ![telegram](docs/screenshots/telegram-alert.png) |

## معماری

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Network Collector│────▶│   InfluxDB   │◀────│     Grafana      │
│   (ping/ICMP)    │     │ (متریک‌ها)    │     │   (داشبورد)      │
└─────────────────┘     └──────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌──────────────┐
                        │  Agent Core   │  (Groq API + Tool Calling
                        │  تحلیل و تصمیم │   llama-3.3-70b-versatile)
                        └──────────────┘
                          │           │
                          ▼           ▼
                 ┌──────────────┐  ┌──────────────┐
                 │   Guardrail   │  │   Notifier    │
                 │ (تنها مسیر    │  │  (Telegram)   │
                 │  اجرای اکشن)  │  │               │
                 └──────────────┘  └──────────────┘
                          │
                          ▼
                 تجهیزات شبکه واقعی/شبیه‌سازی‌شده
```

### اصل طراحی کلیدی: جداسازی «تصمیم‌گیری» از «اجرا»

`agent-core` **هرگز مستقیماً** به تجهیزات شبکه وصل نمی‌شود. هر درخواست اقدام باید از `guardrail-engine` عبور کند که:

1. بررسی می‌کند اکشن در لیست سفید (`whitelist.yaml`) هست یا نه
2. بر اساس سطح ریسک (`low` / `medium` / `critical`) تصمیم می‌گیرد که خودکار اجرا شود یا نیاز به تأیید صریح تکنسین دارد
3. در حالت `GUARDRAIL_MODE=observe`، هیچ اکشنی واقعاً روی شبکه اجرا نمی‌شود — فقط شبیه‌سازی و لاگ می‌شود (مناسب برای توسعه و دمو)
4. تمام درخواست‌ها را audit-log می‌کند

همچنین Agent برای اطلاع‌رسانی به انسان (چه هشدار بحرانی، چه فقط یک یافته‌ی اطلاعاتی) از ابزار `send_alert` استفاده می‌کند که مستقیماً به سرویس `notifier` وصل است و پیام را به تلگرام تکنسین ارسال می‌کند.

## اجزای پروژه

| ماژول | وظیفه | وضعیت |
|---|---|---|
| `network-collector` | جمع‌آوری متریک reachability/latency/packet-loss با ping و ذخیره در InfluxDB | ✅ فعال |
| `agent-core` | تحلیل داده با Groq API (رایگان)، تصمیم‌گیری، درخواست اقدام و هشدار | ✅ فعال |
| `guardrail-engine` | اعتبارسنجی و کنترل اجرای اقدامات بر اساس whitelist (FastAPI) | ✅ فعال |
| `notifier` | ارسال هشدار به تکنسین از طریق تلگرام (FastAPI) | ✅ فعال |
| `dashboard` (Grafana) | نمایش نمودار زنده latency / packet loss / reachability | ✅ فعال |

## اجرای سریع (Quick Start)

پیش‌نیاز: Docker و Docker Compose

```bash
git clone <this-repo>
cd network-agent-project
cp .env.example .env
# سپس GROQ_API_KEY (رایگان از console.groq.com/keys) و در صورت تمایل
# TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID را در .env تنظیم کنید

docker compose up --build
```

سرویس‌ها بعد از بالا آمدن:
- Grafana: http://localhost:3000 (کاربر/رمز اولیه: admin/admin)
- InfluxDB: http://localhost:8086
- Guardrail API: http://localhost:8000/docs
- Notifier API: http://localhost:8001/docs

راه‌اندازی داشبورد Grafana (وصل کردن به InfluxDB و ساخت پنل‌ها) در [docs/grafana-setup.md](docs/grafana-setup.md) توضیح داده شده است.

> برای شبیه‌سازی یک محیط شبکه واقعی‌تر (روتر/سوییچ) می‌توانید از GNS3 یا EVE-NG به‌صورت جداگانه استفاده کنید و آدرس‌های IP آن‌ها را در `SNMP_TARGETS` قرار دهید.

## چه چیزی الان مانیتور می‌شود؟

فعلاً پروژه فقط **reachability پایه** (ping-based) را برای فهرستی از IP‌های تعریف‌شده در `SNMP_TARGETS` (در `.env`) اندازه می‌گیرد: قابل‌دسترس بودن، تأخیر (latency)، و درصد از دست‌رفتن بسته (packet loss). پشتیبانی SNMP واقعی (CPU، ترافیک پورت، وضعیت اینترفیس) و اتصال واقعی به تجهیزات (از طریق netmiko/napalm) در `guardrail-engine` هنوز پیاده‌سازی نشده - نقشه راه پایین را ببینید.

## حالت‌های اجرا

پروژه دو حالت اصلی دارد که با متغیر `GUARDRAIL_MODE` کنترل می‌شود:

- **`observe`** (پیش‌فرض): Agent فقط مشاهده و تحلیل می‌کند، هیچ اقدامی واقعاً اجرا نمی‌شود. برای دمو و توسعه امن است.
- **`act`**: اقدامات کم‌ریسک (`risk_level: low`) به‌صورت خودکار اجرا می‌شوند؛ اقدامات پرریسک (`risk_level: critical`) همچنان نیاز به تأیید صریح از طریق `/approve/{id}` دارند.

## نقشه راه توسعه

- [x] جمع‌آوری متریک پایه (ping)
- [x] حلقه تصمیم‌گیری Agent با Tool Calling (Groq / Llama 3.3 70B)
- [x] لایه Guardrail با whitelist و سطح‌بندی ریسک
- [x] اطلاع‌رسانی هوشمند به تلگرام (Agent تصمیم می‌گیرد چه‌وقت هشدار بفرستد)
- [x] داشبورد Grafana با پنل‌های جدا برای latency / packet loss / reachability
- [ ] پشتیبانی کامل SNMP برای دستگاه‌های واقعی (CPU، ترافیک پورت، وضعیت اینترفیس)
- [ ] اتصال واقعی به تجهیزات با netmiko/napalm در Guardrail
- [ ] محیط شبیه‌سازی‌شده آماده با GNS3/EVE-NG
- [ ] تست‌های سناریوی خرابی (chaos scenarios)

## هشدار امنیتی

این پروژه یک نمونه آموزشی/پورتفولیو است. قبل از استفاده در هر محیط production واقعی:
- حتماً احراز هویت و کنترل دسترسی مناسب روی Guardrail API اضافه کنید
- کلیدهای API و توکن‌ها را هرگز commit نکنید (`.env` در `.gitignore` است)
- اکشن‌های پرریسک را همیشه با تأیید انسانی نگه دارید

## لایسنس

[MIT](LICENSE)
