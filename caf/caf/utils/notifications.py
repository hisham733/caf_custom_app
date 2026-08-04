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

import re

import frappe


# ── Config ────────────────────────────────────────────────────────────────────

MAX_SEND_ATTEMPTS = 5
SEND_TIMEOUT = 15

def _get_config():
    """Return WAHA config from Caf Settings, falling back to site_config.

    If the Caf Settings record is populated (base_url / chat_ids / api_key),
    those values win. Otherwise the legacy "waha" key in site_config is used.
    """
    try:
        st = frappe.get_single("Caf Settings")
    except Exception:
        st = None

    if st and (st.get("waha_base_url") or st.get("waha_chat_ids") or st.get("waha_api_key")):
        raw_ids = (st.get("waha_chat_ids") or "").splitlines()
        chat_ids = [c.strip() for c in raw_ids if c.strip()]
        api_key = st.get_password("waha_api_key") if st.get("waha_api_key") else ""
        return {
            "enabled": bool(st.get("waha_enabled")),
            "base_url": st.get("waha_base_url") or "http://localhost:3000",
            "chat_ids": chat_ids,
            "api_key": api_key,
        }

    cfg = frappe.local.conf.get("waha") or {}
    raw_ids = cfg.get("chat_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    return {
        "enabled": bool(cfg.get("enabled")),
        "base_url": cfg.get("base_url", "http://localhost:3000"),
        "chat_ids": list(raw_ids),
        "api_key": cfg.get("api_key", ""),
    }


def _get_dp_whatsapp_template():
    """Return the DP WhatsApp image template from Caf Settings.

    Returns "New" (no Recipe column) or "Old" (Recipe | Size | Product).
    Defaults to "New".
    """
    try:
        return (frappe.db.get_single_value("Caf Settings", "dp_whatsapp_template") or "New")
    except Exception:
        return "New"


# ── Main entry point ─────────────────────────────────────────────────────────

def notify_dp_schedule(dp_name):
    """Send the DP schedule image to all configured WhatsApp chats.

    Call this after WO creation, submit week, or process_manual_updates.
    """
    config = _get_config()
    if not config["enabled"] or not config["chat_ids"]:
        return

    try:
        dp = frappe.get_doc("Daily Production", dp_name)
        if _get_dp_whatsapp_template() == "Old":
            image_b64 = _format_schedule_image_old(dp)
        else:
            image_b64 = _format_schedule_image(dp)
        caption = f"{dp.name} | {dp.required_by}"
        for chat_id in config["chat_ids"]:
            _send_waha_image(chat_id, image_b64, caption, config)
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


# ── Image formatter ──────────────────────────────────────────────────────────

def _classify_workstation(ws_name):
    """Return (group_type, short_label) for a workstation name.

    The index is captured right after the type keyword so names with a
    trailing suffix still get a number: "Cooker 2 Oil" -> ("Cooker", "C2"),
    "Cooker 1" -> ("Cooker", "C1"), "Fryer 3A" -> ("Fryer", "Fryer 3A").
    """
    import re

    lower = (ws_name or "").lower().strip()
    if "cooker" in lower:
        m = re.search(r"cooker\s*(\d+[A-Za-z]?)", ws_name or "", re.IGNORECASE)
        return "Cooker", f"C{m.group(1) if m else ''}"
    if "kettle" in lower:
        m = re.search(r"kettle\s*(\d+[A-Za-z]?)", ws_name or "", re.IGNORECASE)
        return "Kettle", f"K{m.group(1) if m else ''}"
    if "fryer" in lower:
        m = re.search(r"fryer\s*(\d+[A-Za-z]?)", ws_name or "", re.IGNORECASE)
        return "Fryer", f"Fryer {m.group(1) if m else ''}"
    return "Other", ws_name


def _extract_index(ws_name):
    """Return the leading numeric index from a workstation name."""
    import re

    m = re.search(r"(\d+)", ws_name or "")
    return int(m.group(1)) if m else 0


def _strip_recipe_word(name):
    """Return the recipe name without the leading 'Recipe' word.

    Example: "Recipe IBS" -> "IBS", "Recipe IB-LS" -> "IB-LS".
    """
    if not name:
        return ""
    return re.sub(r"^\s*Recipe\s+", "", str(name), flags=re.IGNORECASE)


def _format_schedule_image(dp):
    """Generate the WhatsApp DP schedule image (modified layout).

    No Recipe column — each round shows Production then Size, and the
    Production cell holds the recipe name without the 'Recipe' word.
    """
    return _render_schedule_image(dp, variant="new")


def _format_schedule_image_old(dp):
    """Generate the DP schedule image using the original layout.

    Original layout: Recipe | Size | Product (pack names) per round.
    """
    return _render_schedule_image(dp, variant="old")


def _render_schedule_image(dp, variant):
    """Render the DP schedule image for a given layout variant.

    variant="old": Recipe | Size | Product per round.
    variant="new": Production | Size per round (no Recipe column).
    """
    from PIL import Image, ImageDraw, ImageFont
    import io
    import base64
    import re
    import textwrap
    from datetime import datetime

    # Fonts
    font_root = "/usr/share/fonts/truetype/dejavu"
    try:
        title_font = ImageFont.truetype(f"{font_root}/DejaVuSans-Bold.ttf", 28)
        group_font = ImageFont.truetype(f"{font_root}/DejaVuSans-Bold.ttf", 20)
        header_font = ImageFont.truetype(f"{font_root}/DejaVuSans-Bold.ttf", 16)
        cell_font = ImageFont.truetype(f"{font_root}/DejaVuSans.ttf", 16)
        remark_font = ImageFont.truetype(f"{font_root}/DejaVuSans.ttf", 14)
    except Exception:
        title_font = ImageFont.load_default()
        group_font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        cell_font = ImageFont.load_default()
        remark_font = ImageFont.load_default()

    def _text_size(draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _draw_lines(draw, x0, y0, col_w, row_h, lines, font, line_h, x_pad, align_left=False):
        if not lines:
            return
        total_h = len(lines) * line_h
        ty = y0 + max((row_h - total_h) // 2, 2)
        for line in lines:
            if align_left:
                tx = x0 + x_pad
            else:
                tw = draw.textlength(line, font=font)
                tx = x0 + (col_w - tw) // 2
            draw.text((tx, ty), line, font=font, fill=text)
            ty += line_h

    # Group rows by workstation and round
    ws_rows = {}
    for row in dp.production_table:
        ws = row.recipe_cook_workstaion or "?"
        rnd = str(row.recipe_cook_round or "1")
        if ws not in ws_rows:
            ws_rows[ws] = {}
        ws_rows[ws][rnd] = row

    all_rounds = sorted(
        {str(r.recipe_cook_round or "1") for r in dp.production_table},
        key=lambda x: int(x),
    )

    # Classify and group workstations
    ws_groups = {}
    for ws in ws_rows.keys():
        ws_type, short_name = _classify_workstation(ws)
        ws_groups.setdefault(ws_type, []).append((ws, short_name))

    type_order = {"Cooker": 1, "Kettle": 2, "Fryer": 3}
    sorted_types = sorted(ws_groups.keys(), key=lambda t: type_order.get(t, 99))
    for t in sorted_types:
        ws_groups[t].sort(key=lambda x: _extract_index(x[0]))

    # Layout constants
    pad = 20
    header_h = 26
    group_h = 28
    title_h = 38
    ws_col_w = 70
    prod_col_w = 100
    size_col_w = 55
    recipe_col_w = 80 if variant == "old" else 0
    round_col_w = recipe_col_w + prod_col_w + size_col_w
    remark_col_w = 220
    cell_pad = 4
    remark_pad = 6

    # Font metrics
    cell_ascent, cell_descent = cell_font.getmetrics()
    remark_ascent, remark_descent = remark_font.getmetrics()
    cell_line_h = cell_ascent + cell_descent + 4
    remark_line_h = remark_ascent + remark_descent + 4

    min_row_h = 28

    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def _fit_prefix(draw, text, font, max_width):
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if draw.textlength(text[:mid], font=font) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return lo or 1

    def _wrap_lines(draw, text, font, max_width):
        if not text:
            return []
        lines = []
        for word in text.split():
            while word and draw.textlength(word, font=font) > max_width:
                cut = _fit_prefix(draw, word, font, max_width)
                lines.append(word[:cut])
                word = word[cut:]
            if not word:
                continue
            if not lines or draw.textlength(lines[-1] + " " + word, font=font) > max_width:
                lines.append(word)
            else:
                lines[-1] += " " + word
        return lines

    def _collect_round_cells(row_data, rn):
        cell = row_data.get(rn)
        if cell and cell.recipe_name and cell.recipe_name != "No Cooking":
            recipe = cell.recipe_name
            size = str(cell.size or 0)
            if variant == "old":
                packs = []
                for pf in ("pack_name", "pack_name_2", "pack_name_3",
                           "pack_name_4", "pack_name_5", "pack_name_6", "pack_name_7"):
                    val = cell.get(pf)
                    if val:
                        packs.append(str(val))
                product = " / ".join(packs) if packs else ""
            else:
                product = _strip_recipe_word(recipe)
        else:
            recipe = ""
            size = ""
            product = ""
        return {
            "recipe_lines": _wrap_lines(measurer, recipe, cell_font, recipe_col_w - cell_pad * 2)
                             if recipe_col_w else [],
            "size": size,
            "product_lines": _wrap_lines(measurer, product, cell_font, prod_col_w - cell_pad * 2),
        }

    def _collect_remarks(row_data):
        remarks = []
        for rn in all_rounds:
            cell = row_data.get(rn)
            if cell:
                if cell.get("recipe_note"):
                    remarks.append(cell.get("recipe_note"))
                for pf in ("pack_remark", "pack_remark_2", "pack_remark_3",
                           "pack_remark_4", "pack_remark_5", "pack_remark_6", "pack_remark_7"):
                    val = cell.get(pf)
                    if val:
                        remarks.append(val)
        return _wrap_lines(measurer, " / ".join(remarks), remark_font, remark_col_w - remark_pad * 2)

    # Precompute per-row layout (grows to fit content, min fixed size)
    row_layout = {}
    for ws_type in sorted_types:
        for ws_name, short_name in ws_groups[ws_type]:
            row_data = ws_rows[ws_name]
            rounds = {rn: _collect_round_cells(row_data, rn) for rn in all_rounds}
            remark_lines = _collect_remarks(row_data)
            n_lines = 1
            for rn in all_rounds:
                rc = rounds[rn]
                n_lines = max(n_lines, len(rc["recipe_lines"]), len(rc["product_lines"]))
            n_lines = max(n_lines, len(remark_lines))
            height = max(n_lines * cell_line_h + 6, min_row_h)
            row_layout[(ws_type, ws_name)] = {
                "short_name": short_name,
                "height": height,
                "rounds": rounds,
                "remark_lines": remark_lines,
            }

    img_w = pad + ws_col_w + (len(all_rounds) * round_col_w) + remark_col_w + pad
    img_h = pad + title_h + pad
    for ws_type in sorted_types:
        group_h_total = sum(
            row_layout[(ws_type, ws_name)]["height"] for ws_name, _ in ws_groups[ws_type]
        )
        img_h += group_h + (header_h * 2) + group_h_total + 4
    img_h += pad

    # Colors
    bg = (255, 255, 255)
    header_bg = (192, 192, 192)
    group_bg = (217, 217, 217)
    grid = (128, 128, 128)
    text = (0, 0, 0)
    alt_row = (242, 242, 242)

    # Distinct round colors (R1, R2, R3, ...)
    ROUND_COLORS = [
        (173, 216, 230),   # R1 - light blue
        (144, 238, 144),   # R2 - light green
        (255, 255, 224),   # R3 - light yellow
        (255, 182, 193),   # R4 - light pink
        (221, 160, 221),   # R5 - plum
        (255, 218, 185),   # R6 - peach
        (176, 196, 222),   # R7 - light steel blue
        (240, 230, 140),   # R8 - khaki
        (255, 160, 122),   # R9 - light salmon
    ]

    def _round_color(rn):
        return ROUND_COLORS[(int(rn) - 1) % len(ROUND_COLORS)]

    img = Image.new("RGB", (img_w, img_h), bg)
    draw = ImageDraw.Draw(img)

    # Title row
    try:
        date_obj = datetime.strptime(str(dp.required_by), "%Y-%m-%d")
        date_str = date_obj.strftime("%A, %B %d, %Y")
    except Exception:
        date_str = str(dp.required_by)

    y = pad
    draw.rectangle([pad, y, pad + 70, y + title_h], fill=header_bg, outline=grid)
    tw, th = _text_size(draw, "DATE", header_font)
    draw.text(
        (pad + (70 - tw) // 2, y + (title_h - th) // 2),
        "DATE",
        font=header_font,
        fill=text,
    )

    tw, th = _text_size(draw, date_str, title_font)
    draw.text(
        (pad + 70 + (img_w - 70 - pad * 2 - tw) // 2, y + (title_h - th) // 2),
        date_str,
        font=title_font,
        fill=text,
    )
    y += title_h + pad

    # Group sections
    for ws_type in sorted_types:
        group_rows = ws_groups[ws_type]

        # Group header
        draw.rectangle([pad, y, img_w - pad, y + group_h], fill=group_bg, outline=grid)
        tw, th = _text_size(draw, ws_type, group_font)
        draw.text((pad + 10, y + (group_h - th) // 2), ws_type, font=group_font, fill=text)
        y += group_h

        # Round headers
        x = pad + ws_col_w
        for rn in all_rounds:
            rn_color = _round_color(rn)
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(int(rn), f"{rn}th")
            label = f"{ordinal} Round"
            draw.rectangle([x, y, x + round_col_w, y + header_h], fill=rn_color, outline=grid)
            tw, th = _text_size(draw, label, header_font)
            draw.text(
                (x + (round_col_w - tw) // 2, y + (header_h - th) // 2),
                label,
                font=header_font,
                fill=text,
            )
            x += round_col_w

        # Remarks header
        draw.rectangle([x, y, x + remark_col_w, y + header_h], fill=header_bg, outline=grid)
        tw, th = _text_size(draw, "Remarks", header_font)
        draw.text(
            (x + (remark_col_w - tw) // 2, y + (header_h - th) // 2),
            "Remarks",
            font=header_font,
            fill=text,
        )
        y += header_h

        # Subheaders per round (variant determines order/content)
        if variant == "old":
            columns = [("recipe", recipe_col_w, "Recipe"),
                       ("size", size_col_w, "Size"),
                       ("product", prod_col_w, "Product")]
        else:
            columns = [("product", prod_col_w, "Product"),
                       ("size", size_col_w, "Size")]

        x = pad + ws_col_w
        for rn in all_rounds:
            rn_color = _round_color(rn)
            for kind, w, label in columns:
                draw.rectangle([x, y, x + w, y + header_h], fill=rn_color, outline=grid)
                tw, th = _text_size(draw, label, header_font)
                draw.text(
                    (x + (w - tw) // 2, y + (header_h - th) // 2),
                    label,
                    font=header_font,
                    fill=text,
                )
                x += w

        draw.rectangle([x, y, x + remark_col_w, y + header_h], fill=header_bg, outline=grid)
        x += remark_col_w
        y += header_h

        # Workstation rows
        for row_idx, (ws_name, short_name) in enumerate(group_rows):
            layout = row_layout[(ws_type, ws_name)]
            row_h = layout["height"]
            row_y = y
            y += row_h
            fill = alt_row if row_idx % 2 else bg

            # Workstation cell
            draw.rectangle([pad, row_y, pad + ws_col_w, row_y + row_h], fill=fill, outline=grid)
            tw, th = _text_size(draw, layout["short_name"], cell_font)
            draw.text(
                (pad + (ws_col_w - tw) // 2, row_y + (row_h - th) // 2),
                layout["short_name"],
                font=cell_font,
                fill=text,
            )

            x = pad + ws_col_w
            for rn in all_rounds:
                rc = layout["rounds"][rn]

                for kind, w, _label in columns:
                    if kind == "size":
                        draw.rectangle([x, row_y, x + w, row_y + row_h], fill=fill, outline=grid)
                        if rc["size"]:
                            tw, th = _text_size(draw, rc["size"], cell_font)
                            draw.text(
                                (x + (w - tw) // 2, row_y + (row_h - th) // 2),
                                rc["size"],
                                font=cell_font,
                                fill=text,
                            )
                    else:
                        lines = rc["recipe_lines"] if kind == "recipe" else rc["product_lines"]
                        draw.rectangle([x, row_y, x + w, row_y + row_h], fill=fill, outline=grid)
                        _draw_lines(draw, x, row_y, w, row_h,
                                    lines, cell_font, cell_line_h, cell_pad)
                    x += w

            # Remarks
            draw.rectangle([x, row_y, x + remark_col_w, row_y + row_h], fill=fill, outline=grid)
            _draw_lines(draw, x, row_y, remark_col_w, row_h,
                        layout["remark_lines"], remark_font, remark_line_h, remark_pad, align_left=True)

        y += 4

    # Export to base64
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def _text_size(draw, text, font):
    """Return (width, height) for a given text/font."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# ── WAHA senders ───────────────────────────────────────────────────────────────

def _send_waha(chat_id, text, config):
    """Send a text message via WAHA REST API. Max 5 attempts, then stop."""
    import requests
    from time import sleep

    url = config["base_url"].rstrip("/") + "/api/sendText"
    payload = {
        "chatId": chat_id,
        "text": text,
        "session": "default",
    }
    headers = {}
    if config.get("api_key"):
        headers["X-Api-Key"] = config["api_key"]

    last_error = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=SEND_TIMEOUT)
            if resp.ok:
                return
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as e:
            last_error = repr(e)
        if attempt < MAX_SEND_ATTEMPTS:
            sleep(2)

    frappe.log_error(
        title="WAHA connection failed",
        message=f"{last_error or 'unknown error'}\n\n{frappe.get_traceback()}",
    )


def _send_waha_image(chat_id, b64_image, caption, config):
    """Send an image message via WAHA REST API. Max 5 attempts, then stop."""
    import requests
    from time import sleep

    url = config["base_url"].rstrip("/") + "/api/sendImage"
    payload = {
        "chatId": chat_id,
        "file": {
            "mimetype": "image/png",
            "data": b64_image,
            "filename": "dp_schedule.png",
        },
        "caption": caption,
        "session": "default",
    }
    headers = {}
    if config.get("api_key"):
        headers["X-Api-Key"] = config["api_key"]

    last_error = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=SEND_TIMEOUT * 2)
            if resp.ok:
                return
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as e:
            last_error = repr(e)
        if attempt < MAX_SEND_ATTEMPTS:
            sleep(2)

    frappe.log_error(
        title="WAHA image connection failed",
        message=f"{last_error or 'unknown error'}\n\n{frappe.get_traceback()}",
    )
