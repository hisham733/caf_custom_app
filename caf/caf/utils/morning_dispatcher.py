"""
Morning reports dispatcher.

Frappe scheduler cron is static in hooks.py, so per-report send times are
handled here: a periodic cron calls run_due_reports(), which reads each
report's enabled flag + send time from Caf Settings and runs the report only
when the current wall-clock matches the configured time.

Reports handled here:
  - missing supplier  (supplier_enabled / supplier_send_time)
  - yield drop        (yield_enabled / yield_send_time)
"""

import frappe

REPORT_RUNNERS = {
    "supplier": {
        "enabled_field": "supplier_enabled",
        "time_field": "supplier_send_time",
        "runner": "caf.caf.utils.missing_supplier_report.send_missing_supplier_warning",
    },
    "yield": {
        "enabled_field": "yield_enabled",
        "time_field": "yield_send_time",
        "runner": "caf.caf.utils.yield_report.send_yield_warning",
    },
}


def _current_hhmm():
    # Use Frappe site time so the dispatcher matches the site's configured timezone.
    return frappe.utils.now()[11:16]


def _render_time(value):
    """Normalize a Time value/string into 'HH:MM' (24h)."""
    if not value:
        return None
    s = str(value).strip()
    # Handle a full datetime string by keeping only the time part.
    if " " in s:
        s = s.split(" ")[-1]
    if len(s) >= 5:
        return s[:5]
    return None


def run_due_reports():
    """Run every enabled report whose configured send time matches now."""
    now = _current_hhmm()

    try:
        st = frappe.get_single("Caf Settings")
    except Exception:
        st = None

    for report_key, cfg in REPORT_RUNNERS.items():
        if st is None:
            continue
        try:
            enabled = st.get(cfg["enabled_field"])
            if enabled is not None and not enabled:
                continue
            send_time = _render_time(st.get(cfg["time_field"]))
            if send_time and now == send_time:
                frappe.enqueue(
                    cfg["runner"],
                    queue="long",
                    timeout=3600,
                )
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "Morning reports dispatcher: {0} failed".format(report_key),
            )
