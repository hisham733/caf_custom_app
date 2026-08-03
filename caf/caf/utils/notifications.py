"""
WAHA WhatsApp Notifications for Production Schedule.

Config in common_site_config.json:
{
    "waha": {
        "enabled": true,
        "base_url": "http://192.168.1.100:3000",
        "chat_ids": ["60123456789@c.us"]
    }
}
"""

import frappe


# ── Config ────────────────────────────────────────────────────────────────────

def _get_config():
    """Return WAHA config from site_config."""
    cfg = frappe.local.conf.get("waha") or {}
    return {
        "enabled": bool(cfg.get("enabled")),
        "base_url": cfg.get("base_url", "http://localhost:3000"),
        "chat_ids": cfg.get("chat_ids") or [],
    }


# ── Main entry point ─────────────────────────────────────────────────────────

def notify_dp_schedule(dp_name):
    """Send the DP schedule table to all configured WhatsApp chats.

    Call this after WO creation, submit week, or process_manual_updates.
    """
    config = _get_config()
    if not config["enabled"] or not config["chat_ids"]:
        return

    try:
        dp = frappe.get_doc("Daily Production", dp_name)
        text = _format_schedule_table(dp)
        for chat_id in config["chat_ids"]:
            _send_waha(chat_id, text, config)
    except Exception:
        frappe.log_error(
            title="DP WhatsApp notification failed",
            message=frappe.get_traceback(),
        )


def notify_simple(message):
    """Send a simple text message to all WhatsApp chats."""
    config = _get_config()
    if not config["enabled"] or not config["chat_ids"]:
        return

    try:
        for chat_id in config["chat_ids"]:
            _send_waha(chat_id, message, config)
    except Exception:
        frappe.log_error(
            title="WhatsApp notification failed",
            message=frappe.get_traceback(),
        )


# ── Schedule formatter ───────────────────────────────────────────────────────

def _format_schedule_table(dp):
    """Build a readable WhatsApp text table from DP rows."""
    # Group rows by workstation
    ws_rows = {}
    for row in dp.production_table:
        ws = row.recipe_cook_workstaion or "?"
        rnd = str(row.recipe_cook_round or "1")
        if ws not in ws_rows:
            ws_rows[ws] = {}
        ws_rows[ws][rnd] = row

    # Collect all round numbers in order
    all_rounds = sorted(
        {str(r.recipe_cook_round or "1") for r in dp.production_table},
        key=lambda x: int(x),
    )

    lines = []
    lines.append(f"📋 *{dp.name}*")
    lines.append(f"   {dp.required_by}")
    lines.append("")

    # Header
    header = "WS         "
    for rn in all_rounds:
        header += f"| R{rn}        "
    header += "|"
    lines.append(header)

    # Separator
    sep = "─" * len(header)
    lines.append(sep)

    # Rows
    for ws_name in sorted(ws_rows.keys()):
        row = ws_rows[ws_name]
        # Short name for WhatsApp
        short_name = ws_name[:9] if len(ws_name) > 9 else ws_name
        line = short_name.ljust(10) + " "
        for rn in all_rounds:
            cell = row.get(rn)
            if cell and cell.recipe_name and cell.recipe_name != "No Cooking":
                name = cell.recipe_name[:9]
                sz = str(int(cell.size or 0))
                line += f"| {name:<9}{sz:<2} "
            else:
                line += "|      —      "
        line += "|"
        lines.append(line)

    # Footer — total recipes
    cook_count = sum(
        1 for r in dp.production_table
        if r.recipe_name and r.recipe_name != "No Cooking"
    )
    lines.append("")
    lines.append(f"🍳 {cook_count} recipes for {dp.required_by}")

    return "\n".join(lines)


# ── WAHA sender ──────────────────────────────────────────────────────────────

def _send_waha(chat_id, text, config):
    """Send a text message via WAHA REST API."""
    import requests

    url = config["base_url"].rstrip("/") + "/api/sendText"
    payload = {
        "chatId": chat_id,
        "text": text,
        "session": "default",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            frappe.log_error(
                title="WAHA send failed",
                message=f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
    except requests.RequestException:
        frappe.log_error(
            title="WAHA connection failed",
            message=frappe.get_traceback(),
        )
