import frappe
from frappe import _, bold
from frappe.utils import flt, cint

from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
    get_available_serial_nos,
    get_auto_batch_nos,
)


def get_se_link_id_and_item_type(kwargs):
    if not kwargs.get("posting_date") or not kwargs.get("posting_time"):
        return None, None

    # Submit path → use SE name directly
    if kwargs.get("name"):
        se = frappe.db.get_value(
            "Stock Entry",
            kwargs.get("name"),
            ["custom_link_id", "custom_item_type","work_order"],
            as_dict=True,
        )

    # Manual dialog path → use posting_date + posting_time
    else:
        se = frappe.db.get_value(
            "Stock Entry",
            {
                "posting_date": kwargs.get("posting_date"),
                "posting_time": kwargs.get("posting_time"),
                "docstatus": ["in", [0, 1]],
            },
            ["custom_link_id", "custom_item_type","work_order"],
            as_dict=True,
        )

    if not se:
        return None, None

    return se.get("custom_link_id"), se.get("custom_item_type"), se.get("work_order")

def is_item_in_delet_table(item_code):
    """
    Returns True if:
    1. Item exists in the 'delet' child table (Exclusion List).
    2. Item Group is NOT 'Recipe'.
    
    If True, the system skips custom batch logic and uses normal FIFO.
    """
    # 1. Check Item Group first (fastest check)
    item_group = frappe.db.get_value("Item", item_code, "item_group")
    # if item_group != "Recipe":
    parent_doc = frappe.get_all(
        "start and delete items",
        filters={"custom_is_default": 1},
        fields=["name"],
        order_by="creation desc",
        limit=1,
    )

    if not parent_doc:
        frappe.throw("Error: Could't find and Delete Table Record Or it's not submitted")

    # 3. Check the exclusion child table
    return frappe.db.exists(
        "delet",
        {
            "parent": parent_doc[0].name,
            "item_short_name": item_code,
        },
    )
    # else:
    #     return True

def get_batch_for_linked_work_order(item_code, required_qty, custom_link_id, warehouse):
    """
    Find batches produced for this item via Manufacture SEs
    with same custom_link_id. Consumes multiple batches if needed.
    Returns list of {batch_no, qty} dicts.
    """

    # Step 1: Find Manufacture SEs with same custom_link_id
    linked_ses = frappe.get_all(
        "Stock Entry",
        filters={
            "custom_link_id": custom_link_id,
            "purpose": "Manufacture",
            "docstatus": 1,
        },
        pluck="name",
    )

    if not linked_ses:
        frappe.throw(
            _(
                "No submitted Manufacture Stock Entry found "
                "for Link ID {0}. Cannot determine batch "
                "for item {1}."
            ).format(bold(custom_link_id), bold(item_code))
        )

    # Step 2: Find all batches referencing those SEs for this item
    matched_batches = frappe.get_all(
        "Batch",
        filters={
            "item": item_code,
            "reference_doctype": "Stock Entry",
            "reference_name": ("in", linked_ses),
            "disabled": 0,
        },
        fields=["name", "batch_qty", "reference_name"],
        order_by="creation asc",  # FIFO within the set
    )

    if not matched_batches:
        frappe.throw(
            _(
                "No batch found for Link ID {0} "
                "for item {1}. Please ensure the "
                "Manufacture Stock Entry is submitted."
            ).format(bold(custom_link_id), bold(item_code))
        )

    # Step 3: Check total available qty across all batches
    total_available = sum(flt(b.batch_qty) for b in matched_batches)

    if total_available <= 0:
        frappe.throw(
            _(
                "All batches for Link ID {0}, item {1} "
                "have no available quantity."
            ).format(bold(custom_link_id), bold(item_code))
        )

    if total_available < flt(required_qty):
        batch_details = ", ".join(
            f"{b.name} ({flt(b.batch_qty)})"
            for b in matched_batches
        )
        frappe.throw(
            _(
                "Batches for Link ID {0}, item {1} have "
                "insufficient total quantity. "
                "Available: {2} across [{3}], Required: {4}."
            ).format(
                bold(custom_link_id),
                bold(item_code),
                bold(total_available),
                batch_details,
                bold(flt(required_qty)),
            )
        )

    # Step 4: Split required qty across batches in order
    result = []
    remaining = flt(required_qty)

    for batch in matched_batches:
        if flt(remaining, 9) <= 0:
            break

        available = flt(batch.batch_qty)
        if available <= 0:
            continue

        take = min(available, remaining)
        result.append(frappe._dict({
            "batch_no": batch.name,
            "qty": flt(take, 9),
        }))
        remaining = flt(remaining - take, 9)

    return result  # ← now returns LIST not single batch_no
    
@frappe.whitelist()
def get_auto_data(**kwargs):
    kwargs = frappe._dict(kwargs)

    if cint(kwargs.has_serial_no):
        return get_available_serial_nos(kwargs)

    elif cint(kwargs.has_batch_no):
        # Step 1: Fetch custom_link_id and custom_item_type directly from SE
        custom_link_id, custom_item_type = get_se_link_id_and_item_type(kwargs)
        item_code = kwargs.get("item_code")

        # Step 2: Determine if we should use the custom linked logic
        # is_item_in_delet_table now returns True if:
        # - Item is in the exclusion table OR
        # - Item Group is NOT "Recipe"
        if is_item_in_delet_table(item_code):
            
            # Check the group specifically to show a clearer message
            item_group = frappe.db.get_value("Item", item_code, "item_group")
            
            if item_group != "Recipe":
                msg = _("ℹ️ Item {0} is not a Recipe. Using standard FIFO.").format(bold(item_code))
                indicator = "gray"
            else:
                msg = _("⚠️ Item {0} is in the exclusion list. Using standard FIFO.").format(bold(item_code))
                indicator = "orange"

            frappe.msgprint(msg, alert=True, indicator=indicator)
            return get_auto_batch_nos(kwargs)

        # Step 3: Only proceed if item type is Cook or Pack and link id exists
        if custom_item_type in ["Cook", "Pack"] and custom_link_id:
            
            # Step 4: Run linked batch logic
            frappe.msgprint(
                _(
                    "🔗 Link ID {0} detected for item {1} "
                    "(WO Type: {2}). Searching for linked batch..."
                ).format(
                    bold(custom_link_id),
                    bold(item_code),
                    bold(custom_item_type),
                ),
                alert=True,
                indicator="blue",
            )
            
            batches = get_batch_for_linked_work_order(
                  item_code=item_code,
                  required_qty=flt(kwargs.get("qty")),
                  custom_link_id=custom_link_id,
                  warehouse=kwargs.get("warehouse"),
            )

            if batches:
                batch_names = ", ".join(b.batch_no for b in batches)
                frappe.msgprint(
                      _("✅ Batches {0} selected from Link ID {1} for item {2}.").format(
                            bold(batch_names),
                            bold(custom_link_id),
                            bold(item_code),
                      ),
                      alert=True,
                      indicator="green",
                )

                return [
                      frappe._dict({
                            "batch_no": b.batch_no,
                            "qty": b.qty,
                            "warehouse": kwargs.get("warehouse"),
                      })
                      for b in batches
                ]

        # Fallback → normal FIFO if no Link ID or no batches found
        return get_auto_batch_nos(kwargs)