"""
SNMP Client
-----------
لایه‌ی ارتباط با دستگاه‌ها از طریق SNMP. این فایل "چطور پرسیدن" را مدیریت
می‌کند؛ اینکه "از چه دستگاهی چه چیزی بپرسیم" در device_profiles.py تعریف
شده است.

این فایل عمداً چیزی درباره‌ی "چه دستگاهی چه نوعی است" نمی‌داند - فقط توابع
عمومی برای خواندن CPU/Memory/Disk/Traffic بر اساس یک device_type ورودی
ارائه می‌دهد. اگر می‌خواهی نوع دستگاه جدیدی (مثلاً Juniper) اضافه کنی،
اینجا را دست نزن - فقط device_profiles.py را ویرایش کن.
"""

import logging
from easysnmp import Session, EasySNMPError

import device_profiles as profiles

log = logging.getLogger(__name__)


def _get_session(host: str, community: str, timeout: int = 3):
    return Session(hostname=host, community=community, version=2, timeout=timeout, retries=1)


def _safe_walk(session, oid):
    """اجرای snmpwalk با مدیریت خطا - اگر دستگاه آن OID را نداشته باشد، لیست خالی برمی‌گرداند."""
    try:
        return session.walk(oid)
    except EasySNMPError as e:
        log.debug("SNMP walk failed for oid=%s: %s", oid, e)
        return []


def _safe_get(session, oid):
    """اجرای snmpget با مدیریت خطا - اگر جواب نگرفت، None برمی‌گرداند."""
    try:
        return session.get(oid)
    except EasySNMPError as e:
        log.debug("SNMP get failed for oid=%s: %s", oid, e)
        return None


# =============================================================================
# CPU Load
# =============================================================================

def get_cpu_load(host: str, community: str, device_type: str):
    """
    درصد استفاده از CPU را برمی‌گرداند (عدد 0 تا 100)، یا None اگر
    این دستگاه CPU گزارش نمی‌دهد یا خطا رخ داد.

    روش خواندن بر اساس نوع دستگاه فرق می‌کند (به device_profiles.py نگاه کن):
    - میکروتیک: یک OID اسکالر اختصاصی که مستقیماً درصد را برمی‌گرداند
    - سیسکو: مشابه میکروتیک، یک OID اختصاصی دیگر
    - لینوکس/ویندوز/generic: جدول استاندارد HOST-RESOURCES-MIB که ممکن است
      چند ورودی (یک ورودی به‌ازای هر هسته‌ی CPU) داشته باشد؛ میانگین آن‌ها
      گرفته می‌شود تا یک عدد کلی به‌دست بیاید.
    """
    profile = profiles.get_profile(device_type)
    method = profile["cpu_method"]
    session = _get_session(host, community)

    if method is None:
        return None

    if method == "mikrotik":
        result = _safe_get(session, profiles.MIKROTIK_CPU_LOAD_OID)
        return int(result.value) if result else None

    if method == "cisco":
        result = _safe_get(session, profiles.CISCO_CPU_LOAD_OID)
        return int(result.value) if result else None

    if method == "host_resources":
        entries = _safe_walk(session, profiles.HR_CPU_LOAD_TABLE)
        values = [int(e.value) for e in entries if e.value.isdigit()]
        if not values:
            return None
        # میانگین همه‌ی هسته‌ها - یک تخمین ساده و معمول از بار کلی CPU
        return round(sum(values) / len(values))

    log.warning("Unknown cpu_method '%s' for device_type '%s'", method, device_type)
    return None


# =============================================================================
# Memory & Disk (فقط برای دستگاه‌هایی که HOST-RESOURCES-MIB دارند)
# =============================================================================

def _get_storage_entries(session):
    """
    جدول hrStorageTable را می‌خواند و به‌صورت لیستی از دیکشنری برمی‌گرداند:
    [{index, descr, type, size_bytes, used_bytes}, ...]
    این جدول شامل هم حافظه (RAM) و هم پارتیشن‌های دیسک است؛ فیلترش بر عهده
    تابع فراخواننده است.
    """
    descrs = _safe_walk(session, profiles.HR_STORAGE_DESCR)
    if not descrs:
        return []

    types = {e.oid_index: e.value for e in _safe_walk(session, profiles.HR_STORAGE_TYPE)}
    alloc_units = {e.oid_index: e.value for e in _safe_walk(session, profiles.HR_STORAGE_ALLOC_UNITS)}
    sizes = {e.oid_index: e.value for e in _safe_walk(session, profiles.HR_STORAGE_SIZE)}
    useds = {e.oid_index: e.value for e in _safe_walk(session, profiles.HR_STORAGE_USED)}

    entries = []
    for e in descrs:
        idx = e.oid_index
        try:
            unit_bytes = int(alloc_units.get(idx, 1))
            size_units = int(sizes.get(idx, 0))
            used_units = int(useds.get(idx, 0))
        except (ValueError, TypeError):
            continue
        entries.append({
            "index": idx,
            "descr": e.value,
            "type": types.get(idx, ""),
            "size_bytes": size_units * unit_bytes,
            "used_bytes": used_units * unit_bytes,
        })
    return entries


def get_memory_usage(host: str, community: str, device_type: str):
    """
    درصد استفاده از RAM را برمی‌گرداند، یا None اگر این نوع دستگاه پشتیبانی نمی‌کند
    یا مقداری پیدا نشد.
    """
    profile = profiles.get_profile(device_type)
    if not profile["supports_storage"]:
        return None

    session = _get_session(host, community)
    entries = _get_storage_entries(session)

    for e in entries:
        # hrStorageType برابر است با یک OID؛ ممکن است با یا بدون نقطه‌ی ابتدایی برگردد
        if e["type"].strip(".") == profiles.HR_STORAGE_TYPE_RAM.strip("."):
            if e["size_bytes"] <= 0:
                return None
            return round((e["used_bytes"] / e["size_bytes"]) * 100, 1)

    log.debug("No RAM entry found in hrStorageTable for host=%s", host)
    return None


def get_disk_usage(host: str, community: str, device_type: str, mount_point: str):
    """
    درصد استفاده از یک پارتیشن/مسیر دیسک مشخص را برمی‌گرداند.
    mount_point باید دقیقاً همان چیزی باشد که خود دستگاه در hrStorageDescr
    گزارش می‌دهد (مثلاً "/" روی لینوکس یا "C:\\" روی ویندوز) - اگر مطمئن
    نیستی، این تابع در صورت عدم تطبیق دقیق None برمی‌گرداند و در لاگ می‌توانی
    لیست کامل مسیرهای پیداشده را ببینی (از طریق debug logging).
    """
    profile = profiles.get_profile(device_type)
    if not profile["supports_storage"] or not mount_point:
        return None

    session = _get_session(host, community)
    entries = _get_storage_entries(session)

    fixed_disks = [e for e in entries if e["type"].strip(".") == profiles.HR_STORAGE_TYPE_FIXED_DISK.strip(".")]

    for e in fixed_disks:
        if e["descr"] == mount_point:
            if e["size_bytes"] <= 0:
                return None
            return round((e["used_bytes"] / e["size_bytes"]) * 100, 1)

    available = [e["descr"] for e in fixed_disks]
    log.warning(
        "Disk mount '%s' not found on host=%s. Available mount points: %s",
        mount_point, host, available
    )
    return None


# =============================================================================
# Interface Traffic (IF-MIB استاندارد - مشترک بین همه‌ی انواع دستگاه)
# =============================================================================

def list_interfaces(host: str, community: str):
    """لیست اینترفیس‌های دستگاه را به‌صورت {index: name} برمی‌گرداند."""
    session = _get_session(host, community)
    items = _safe_walk(session, profiles.IF_DESCR_OID)
    return {item.oid_index: item.value for item in items}


def get_interface_traffic(host: str, community: str, if_index: str):
    """
    مقدار لحظه‌ای شمارنده‌ی بایت‌های ورودی/خروجی یک اینترفیس خاص را برمی‌گرداند.
    این یک شمارنده‌ی تجمعی است (از زمان روشن شدن دستگاه)، نه نرخ لحظه‌ای؛
    محاسبه‌ی نرخ واقعی (bytes/sec) در collector.py با مقایسه‌ی دو خوانش
    متوالی انجام می‌شود.
    """
    session = _get_session(host, community)
    in_octets = _safe_get(session, f"{profiles.IF_IN_OCTETS_OID}.{if_index}")
    out_octets = _safe_get(session, f"{profiles.IF_OUT_OCTETS_OID}.{if_index}")
    if in_octets is None or out_octets is None:
        return None
    return {
        "in_octets": int(in_octets.value),
        "out_octets": int(out_octets.value),
    }
