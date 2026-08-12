"""
Network Collector
------------------
جمع‌آوری دوره‌ای متریک‌های شبکه (ping latency/loss + SNMP اختیاری)
و ذخیره در InfluxDB.

این ماژول عمداً ساده نگه داشته شده تا بشه به راحتی گسترشش داد:
- افزودن NetFlow/sFlow
- افزودن جمع‌آوری از طریق netmiko برای دستگاه‌های Cisco/MikroTik
"""

import os
import time
import subprocess
import logging
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [collector] %(message)s")
log = logging.getLogger(__name__)

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "net-agent")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "network-metrics")

TARGETS = [t.strip() for t in os.getenv("SNMP_TARGETS", "8.8.8.8").split(",") if t.strip()]
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))


def ping_host(host: str, count: int = 4, timeout: int = 2):
    """
    اجرای ping و استخراج latency و packet loss.
    خروجی: dict با کلیدهای avg_latency_ms و packet_loss_pct
    """
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            capture_output=True, text=True, timeout=count * timeout + 5
        )
        output = result.stdout

        # استخراج درصد packet loss
        packet_loss = None
        for line in output.splitlines():
            if "packet loss" in line:
                try:
                    packet_loss = float(line.split("%")[0].split()[-1])
                except (ValueError, IndexError):
                    pass

        # استخراج میانگین latency
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


def write_metric(write_api, bucket, metric: dict):
    point = (
        Point("network_health")
        .tag("host", metric["host"])
        .field("reachable", int(metric["reachable"]))
        .field("packet_loss_pct", metric["packet_loss_pct"])
        .time(datetime.now(timezone.utc))
    )
    if metric["avg_latency_ms"] is not None:
        point = point.field("avg_latency_ms", metric["avg_latency_ms"])
    write_api.write(bucket=bucket, record=point)


def main():
    log.info("Starting collector for targets: %s", TARGETS)
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    while True:
        for target in TARGETS:
            metric = ping_host(target)
            log.info("target=%s reachable=%s loss=%.1f%% latency=%s",
                      metric["host"], metric["reachable"],
                      metric["packet_loss_pct"], metric["avg_latency_ms"])
            try:
                write_metric(write_api, INFLUXDB_BUCKET, metric)
            except Exception as e:
                log.error("Failed to write metric for %s: %s", target, e)

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
