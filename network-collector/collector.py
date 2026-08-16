"""
Network Collector
------------------
جمع‌آوری دوره‌ای متریک‌های شبکه از دو منبع مجزا:

1. پینگ ساده (reachability/latency/packet loss) برای هر IP در SNMP_TARGETS
   (متغیر محیطی) - این یک چک سبک "آیا این هاست بالاست یا نه" است و به هیچ
   تنظیمات خاصی روی خود دستگاه نیاز ندارد.

2. متریک‌های عمیق SNMP (CPU/Memory/Disk/Traffic) برای دستگاه‌هایی که در
   devices.yaml تعریف شده‌اند. این نیازمند فعال بودن SNMP روی خود دستگاه است.

برای افزودن یک دستگاه جدید به بخش (2)، کافی است devices.yaml را ویرایش کنی -
نیازی به تغییر این فایل نیست، مگر اینکه بخواهی متریک کاملاً جدیدی
(غیر از CPU/Memory/Disk/Traffic) اضافه کنی.
"""

import os
import time
import subprocess
import logging
from datetime import datetime, timezone

import yaml
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

import snmp_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [collector] %(message)s")
log = logging.getLogger(__name__)

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "net-agent")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "network-metrics")

PING_TARGETS = [t.strip() for t in os.getenv("SNMP_TARGETS", "8.8.8.8").split(",") if t.strip()]
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
DEVICES_CONFIG_PATH = os.getenv("DEVICES_CONFIG_PATH", os.path.join(os.path.dirname(__file__), "devices.yaml"))
DEFAULT_SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "public")

# کش اینترفیس‌ها: به‌ازای هر (host) یک‌بار walk می‌کنیم و نتیجه را نگه می‌داریم
# تا هر ۱۵ ثانیه دوباره کل جدول اینترفیس‌ها را نخوانیم.
_interface_index_cache = {}  # {host: {interface_name: index}}

# آخرین خوانش شمارنده‌ی ترافیک هر (host, interface) برای محاسبه‌ی نرخ bytes/sec
_last_traffic_reading = {}  # {(host, interface): (timestamp, in_octets, out_octets)}


# =============================================================================
# بخش ۱: پینگ ساده (reachability)
# =============================================================================

def ping_host(host: str, count: int = 4, timeout: int = 2):
    """اجرای ping و استخراج latency و packet loss."""
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            capture_output=True, text=True, timeout=count * timeout + 5
        )
        output = result.stdout

        packet_loss = None
        for line in output.splitlines():
            if "packet loss" in line:
                try:
                    packet_loss = float(line.split("%")[0].split()[-1])
                except (ValueError, IndexError):
                    pass

        avg_latency = None
        for line in output.splitlines():
            if "min/avg/max" in line or "rtt" in line:
                try:
                    stats = line.split("=")[1].strip().split()[0]
                    avg_latency = float(stats.split("/")[1])
                except (IndexError, ValueError):
                    pass

        return {
            "host": host,
            "reachable": result.returncode == 0,
            "avg_latency_ms": avg_latency,
            "packet_loss_pct": packet_loss if packet_loss is not None else 100.0,
        }
    except subprocess.TimeoutExpired:
        return {"host": host, "reachable": False, "avg_latency_ms": None, "packet_loss_pct": 100.0}


def write_ping_metric(write_api, metric: dict):
    point = (
        Point("network_health")
        .tag("host", metric["host"])
        .field("reachable", int(metric["reachable"]))
        .field("packet_loss_pct", metric["packet_loss_pct"])
        .time(datetime.now(timezone.utc))
    )
    if metric["avg_latency_ms"] is not None:
        point = point.field("avg_latency_ms", metric["avg_latency_ms"])
    write_api.write(bucket=INFLUXDB_BUCKET, record=point)


def collect_ping_metrics(write_api):
    for target in PING_TARGETS:
        metric = ping_host(target)
        log.info("ping target=%s reachable=%s loss=%.1f%% latency=%s",
                  metric["host"], metric["reachable"],
                  metric["packet_loss_pct"], metric["avg_latency_ms"])
        try:
            write_ping_metric(write_api, metric)
        except Exception as e:
            log.error("Failed to write ping metric for %s: %s", target, e)


# =============================================================================
# بخش ۲: متریک‌های عمیق SNMP بر اساس devices.yaml
# =============================================================================

def load_devices_config(path: str):
    """
    خواندن و اعتبارسنجی سبک devices.yaml.
    اگر فایل وجود نداشت یا خالی بود، لیست خالی برمی‌گردانیم (یعنی این بخش
    از مانیتورینگ غیرفعال می‌ماند، بدون کرش کردن کل collector).
    """
    if not os.path.exists(path):
        log.warning("devices.yaml not found at %s - SNMP device monitoring is disabled.", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        log.error("Failed to parse devices.yaml: %s. SNMP device monitoring is disabled.", e)
        return []

    devices = data.get("devices", [])
    valid_devices = []
    for d in devices:
        # اعتبارسنجی حداقلی: هر دستگاه باید حداقل name، host، و type داشته باشد
        missing = [k for k in ("name", "host", "type") if k not in d]
        if missing:
            log.warning("Skipping device entry %s: missing required fields %s", d, missing)
            continue
        d.setdefault("community", DEFAULT_SNMP_COMMUNITY)
        d.setdefault("interfaces", [])
        d.setdefault("disk_mount", None)
        valid_devices.append(d)
    return valid_devices


def write_device_health(host: str, name: str, cpu_pct, mem_pct, disk_pct, write_api):
    """نوشتن متریک‌های سلامت دستگاه (CPU/Memory/Disk) در InfluxDB - فیلدهای None نوشته نمی‌شوند."""
    point = Point("device_health").tag("host", host).tag("device_name", name).time(datetime.now(timezone.utc))
    has_any_field = False

    if cpu_pct is not None:
        point = point.field("cpu_load_pct", cpu_pct)
        has_any_field = True
    if mem_pct is not None:
        point = point.field("memory_used_pct", mem_pct)
        has_any_field = True
    if disk_pct is not None:
        point = point.field("disk_used_pct", disk_pct)
        has_any_field = True

    if not has_any_field:
        return  # چیزی برای نوشتن نبود (مثلاً هیچ متریکی جواب نداد)

    write_api.write(bucket=INFLUXDB_BUCKET, record=point)


def write_interface_traffic(host: str, name: str, interface: str, in_bps: float, out_bps: float, write_api):
    point = (
        Point("interface_traffic")
        .tag("host", host)
        .tag("device_name", name)
        .tag("interface", interface)
        .field("in_bps", in_bps)
        .field("out_bps", out_bps)
        .time(datetime.now(timezone.utc))
    )
    write_api.write(bucket=INFLUXDB_BUCKET, record=point)


def collect_interface_traffic(device: dict, write_api):
    """جمع‌آوری ترافیک برای همه‌ی اینترفیس‌های تعریف‌شده‌ی یک دستگاه."""
    host = device["host"]
    community = device["community"]
    name = device["name"]

    if host not in _interface_index_cache:
        _interface_index_cache[host] = {}
        raw = snmp_client.list_interfaces(host, community)  # {index: name}
        for idx, if_name in raw.items():
            _interface_index_cache[host][if_name] = idx

    for interface_name in device["interfaces"]:
        if_index = _interface_index_cache[host].get(interface_name)
        if if_index is None:
            log.warning(
                "Interface '%s' not found on device '%s' (%s). Available interfaces: %s",
                interface_name, name, host, list(_interface_index_cache[host].keys())
            )
            continue

        traffic = snmp_client.get_interface_traffic(host, community, if_index)
        if traffic is None:
            continue

        key = (host, interface_name)
        now = time.time()
        if key in _last_traffic_reading:
            prev_time, prev_in, prev_out = _last_traffic_reading[key]
            elapsed = now - prev_time
            delta_in = traffic["in_octets"] - prev_in
            delta_out = traffic["out_octets"] - prev_out
            # شمارنده‌های SNMP معمولاً ۳۲ بیتی‌اند و ممکن است overflow شوند؛
            # اگر عدد جدید از قبلی کمتر بود (یعنی شمارنده ریست/overflow شده)،
            # این خوانش را نادیده می‌گیریم تا عدد منفی نادرست ثبت نشود.
            if elapsed > 0 and delta_in >= 0 and delta_out >= 0:
                in_bps = (delta_in * 8) / elapsed
                out_bps = (delta_out * 8) / elapsed
                log.info("snmp device=%s interface=%s in=%.0f bps out=%.0f bps",
                          name, interface_name, in_bps, out_bps)
                try:
                    write_interface_traffic(host, name, interface_name, in_bps, out_bps, write_api)
                except Exception as e:
                    log.error("Failed to write traffic metric for %s/%s: %s", name, interface_name, e)

        _last_traffic_reading[key] = (now, traffic["in_octets"], traffic["out_octets"])


def collect_device_snmp_metrics(device: dict, write_api):
    """جمع‌آوری کامل متریک‌های یک دستگاه: CPU، Memory، Disk، و ترافیک اینترفیس‌ها."""
    host = device["host"]
    community = device["community"]
    name = device["name"]
    device_type = device["type"]

    cpu = snmp_client.get_cpu_load(host, community, device_type)
    mem = snmp_client.get_memory_usage(host, community, device_type)
    disk = snmp_client.get_disk_usage(host, community, device_type, device.get("disk_mount"))

    log.info("snmp device=%s (%s) cpu=%s%% mem=%s%% disk=%s%%", name, host, cpu, mem, disk)

    try:
        write_device_health(host, name, cpu, mem, disk, write_api)
    except Exception as e:
        log.error("Failed to write device_health metric for %s: %s", name, e)

    collect_interface_traffic(device, write_api)


def main():
    log.info("Starting collector. Ping targets: %s", PING_TARGETS)

    devices = load_devices_config(DEVICES_CONFIG_PATH)
    if devices:
        log.info("Loaded %d SNMP device(s) from %s: %s",
                  len(devices), DEVICES_CONFIG_PATH, [d["name"] for d in devices])
    else:
        log.info("No SNMP devices configured (devices.yaml empty/missing) - only ping monitoring is active.")

    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    while True:
        collect_ping_metrics(write_api)

        for device in devices:
            try:
                collect_device_snmp_metrics(device, write_api)
            except Exception as e:
                # خطای یک دستگاه نباید بقیه‌ی دستگاه‌ها یا حلقه‌ی اصلی را متوقف کند
                log.error("Unexpected error collecting SNMP metrics for device '%s': %s", device.get("name"), e)

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
