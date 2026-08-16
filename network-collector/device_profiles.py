# =============================================================================
# device_profiles.py — تعریف OID های SNMP برای هر نوع دستگاه
# =============================================================================
#
# چرا این فایل جدا از snmp_client.py است؟
# چون OID ها بین برندهای مختلف فرق می‌کنند (هر شرکت MIB اختصاصی خودش را دارد)،
# منطقی است که "چه OID ای برای چه دستگاهی" را از "چطور SNMP query می‌زنیم" جدا کنیم.
# اگر خواستی یک نوع دستگاه جدید (مثلاً Juniper یا Fortinet) اضافه کنی، فقط باید
# یک پروفایل جدید اینجا تعریف کنی - نیازی به تغییر snmp_client.py یا collector.py نیست.
#
# پس‌زمینه‌ی فنی OID ها:
# - اکثر سیستم‌عامل‌های سرور (لینوکس با net-snmp، ویندوز با SNMP Service) از
#   HOST-RESOURCES-MIB استاندارد پشتیبانی می‌کنند، پس CPU/Memory/Disk آن‌ها با
#   OID یکسان قابل خواندن است.
# - دستگاه‌های شبکه‌ای (روتر/سوییچ) معمولاً HOST-RESOURCES-MIB ندارند و باید از
#   MIB اختصاصی شرکت سازنده (Enterprise MIB) استفاده کرد.
# - ترافیک اینترفیس (IF-MIB) تقریباً روی همه‌ی دستگاه‌ها یکسان است، برای همین
#   نیازی به تعریف جداگانه‌اش در هر پروفایل نیست (در snmp_client.py مشترک است).
# =============================================================================

# --- OID های عمومی HOST-RESOURCES-MIB (لینوکس، ویندوز، و اکثر دستگاه‌های generic) ---
HR_CPU_LOAD_TABLE = ".1.3.6.1.2.1.25.3.3.1.2"      # جدول hrProcessorLoad - باید walk و میانگین گرفته شود (چند هسته)
HR_STORAGE_DESCR = ".1.3.6.1.2.1.25.2.3.1.3"       # توضیح هر ورودی حافظه/دیسک (مثلاً "Physical memory" یا "/")
HR_STORAGE_TYPE = ".1.3.6.1.2.1.25.2.3.1.2"        # نوع ورودی (RAM یا Fixed Disk و ...)
HR_STORAGE_ALLOC_UNITS = ".1.3.6.1.2.1.25.2.3.1.4" # اندازه هر واحد شمارش، بر حسب بایت
HR_STORAGE_SIZE = ".1.3.6.1.2.1.25.2.3.1.5"        # گنجایش کل (بر حسب تعداد واحد)
HR_STORAGE_USED = ".1.3.6.1.2.1.25.2.3.1.6"        # مقدار استفاده‌شده (بر حسب تعداد واحد)

# مقادیر استاندارد hrStorageType برای تشخیص نوع ورودی (طبق HOST-RESOURCES-TYPES-MIB)
HR_STORAGE_TYPE_RAM = "1.3.6.1.2.1.25.2.1.2"
HR_STORAGE_TYPE_FIXED_DISK = "1.3.6.1.2.1.25.2.1.4"

# --- OID های IF-MIB (استاندارد، مشترک بین همه‌ی دستگاه‌ها) ---
IF_DESCR_OID = ".1.3.6.1.2.1.2.2.1.2"
IF_IN_OCTETS_OID = ".1.3.6.1.2.1.2.2.1.10"
IF_OUT_OCTETS_OID = ".1.3.6.1.2.1.2.2.1.16"

# --- OID اختصاصی MikroTik (MikroTik Enterprise MIB) ---
MIKROTIK_CPU_LOAD_OID = ".1.3.6.1.4.1.14988.1.1.3.14.0"  # اسکالر است (نه جدول)، مقدار مستقیم درصد

# --- OID اختصاصی Cisco (Cisco Process MIB) ---
# هشدار: این OID روی اکثر پلتفرم‌های IOS/IOS-XE کار می‌کند ولی تضمین‌شده نیست؛
# روی مدل‌های قدیمی‌تر ممکن است لازم باشد از cpmCPUTotal5sec به‌جایش استفاده شود.
# قبل از اعتماد کامل، حتماً با snmpwalk روی دستگاه واقعی تست کن.
CISCO_CPU_LOAD_OID = ".1.3.6.1.4.1.9.9.109.1.1.1.1.8.1"  # cpmCPUTotal5minRev، ایندکس 1


# =============================================================================
# پروفایل هر نوع دستگاه: مشخص می‌کند از کدام OID/روش برای هر متریک استفاده شود
# =============================================================================
#
# فیلد "cpu_method" یکی از این مقادیر است:
#   "host_resources" -> از جدول HR_CPU_LOAD_TABLE استفاده کن (walk + میانگین)
#   "mikrotik"        -> از MIKROTIK_CPU_LOAD_OID استفاده کن (مقدار مستقیم)
#   "cisco"           -> از CISCO_CPU_LOAD_OID استفاده کن (مقدار مستقیم)
#   None              -> این دستگاه اصلاً CPU گزارش نمی‌دهد، این متریک را نادیده بگیر
#
# فیلد "supports_storage" مشخص می‌کند آیا این نوع دستگاه HOST-RESOURCES-MIB
# (و در نتیجه Memory/Disk) را پشتیبانی می‌کند یا نه.

DEVICE_PROFILES = {
    "mikrotik": {
        "cpu_method": "mikrotik",
        "supports_storage": False,  # میکروتیک HOST-RESOURCES-MIB ندارد
    },
    "linux": {
        "cpu_method": "host_resources",
        "supports_storage": True,
    },
    "windows": {
        "cpu_method": "host_resources",
        "supports_storage": True,
    },
    "cisco": {
        "cpu_method": "cisco",
        "supports_storage": False,  # اکثر تجهیزات سیسکو HOST-RESOURCES-MIB ندارند
    },
    "generic": {
        # برای هر دستگاهی که مشخصاً نمی‌دانیم چیست ولی احتمالاً HOST-RESOURCES-MIB دارد
        "cpu_method": "host_resources",
        "supports_storage": True,
    },
}


def get_profile(device_type: str) -> dict:
    """
    پروفایل مربوط به یک نوع دستگاه را برمی‌گرداند.
    اگر نوع دستگاه ناشناخته بود (مثلاً تایپوی کاربر در devices.yaml)، به‌جای
    کرش کردن، از پروفایل "generic" استفاده می‌کند و هشدار می‌دهد - این باعث
    می‌شود یک تایپوی کوچک کل collector را از کار نیندازد.
    """
    if device_type not in DEVICE_PROFILES:
        import logging
        logging.getLogger(__name__).warning(
            "Unknown device type '%s' in devices.yaml, falling back to 'generic' profile. "
            "Valid types are: %s", device_type, list(DEVICE_PROFILES.keys())
        )
        return DEVICE_PROFILES["generic"]
    return DEVICE_PROFILES[device_type]
