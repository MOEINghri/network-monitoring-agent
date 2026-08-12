# راه‌اندازی داشبورد Grafana

بعد از بالا آمدن پروژه با `docker compose up --build`، این مراحل را برای وصل کردن Grafana به InfluxDB و ساخت داشبورد اولیه دنبال کنید.

## ۱. ورود به Grafana

مرورگر را باز کنید و به `http://localhost:3000` بروید. با `admin` / `admin` وارد شوید (بار اول رمز جدید می‌خواهد).

## ۲. افزودن دیتاسورس InfluxDB

از منوی کناری: `Connections` → `Data sources` → `Add data source` → `InfluxDB`

تنظیمات:

| فیلد | مقدار |
|---|---|
| Query Language | `Flux` |
| URL | `http://influxdb:8086` (نام سرویس داکر، نه `localhost`) |
| Auth → Token | مقدار `INFLUXDB_TOKEN` در `.env` (پیش‌فرض: `devtoken12345`) |
| Organization | مقدار `INFLUXDB_ORG` در `.env` (پیش‌فرض: `net-agent`) |
| Default Bucket | مقدار `INFLUXDB_BUCKET` در `.env` (پیش‌فرض: `network-metrics`) |

روی `Save & Test` بزنید؛ باید پیام موفقیت‌آمیز سبز ببینید.

## ۳. ساخت داشبورد با سه پنل جدا

از منو: `Dashboards` → `New` → `New Dashboard` → `Add visualization` → دیتاسورس InfluxDB را انتخاب کنید.

**پنل ۱ - Latency:**
```flux
from(bucket: "network-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "network_health")
  |> filter(fn: (r) => r._field == "avg_latency_ms")
```
عنوان: `Latency (ms)`

**پنل ۲ - Packet Loss:**
```flux
from(bucket: "network-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "network_health")
  |> filter(fn: (r) => r._field == "packet_loss_pct")
```
عنوان: `Packet Loss (%)`

**پنل ۳ - Reachable Status:**
```flux
from(bucket: "network-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "network_health")
  |> filter(fn: (r) => r._field == "reachable")
```
عنوان: `Reachable (1=Yes, 0=No)` — نوع نمودار را به `State timeline` یا `Bar chart` تغییر دهید.

هر پنل را با `Apply` تأیید کنید و در نهایت کل داشبورد را با `Save` ذخیره کنید.

## ۴. فعال کردن Auto-Refresh (اختیاری)

برای دیدن داده‌های زنده، بالای داشبورد کنار بازه‌ی زمانی، روی آیکون رفرش کلیک کنید و یک بازه (مثلاً `10s`) انتخاب کنید.
