# Copyright (c) 2025, hisham and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, today, add_days
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from caf.caf.doctype.daily_production.cancellation import process_cancellations
from .wo_helpers import remove_all_wip_wo
from caf.caf.doctype.daily_production.rws import rws
from .rearrange_and_change_slot import process_slot_swaps , process_switch
from .change_size import process_recipe_change_or_size_change
from .change_pack import process_pack_change_or_add

import json
import datetime
# from caf.caf.overrides.production_plan import get_items_for_material_requests

import re
# ... (keep existing imports)
# ── Module-Level Constants ────────────────────────────────────────────────────
MR_DOCTYPE          = "Material Request"
CHILD_DOCTYPE       = "Create ProExl Items"
TEMPLATE_DOCTYPE    = "start and delete items"
TEMPLATE_CHILD      = "Machine Table"
NO_COOKING          = "No Cooking"
NEW_SCHEDULE        = "New Schedule"

NON_DATA_FIELDTYPES = {
    "Section Break", "Column Break", "Tab Break",
    "HTML", "Button", "Fold", "Heading","production_plane"
}


# ══════════════════════════════════════════════════════════════════════════════
#  Daily Production Document Class
# ══════════════════════════════════════════════════════════════════════════════
class DailyProduction(Document):
    def validate(self):
        """Validate rows before save/submit.

        Rules:
        1. Row with existing WOs cannot be set to "New Schedule"
        2. Row with "No Cooking" cannot have any status except "Change Slot"
        3. Non-cooking rows must have a size > 0
        4. On submit, at least one row must have a produ_status
        """
        if not self.workflow_state:
            self.workflow_state = "Draft"
        for item in self.production_table:
            # It CANNOT be set to "New Schedule" (preventing duplicate creation)
            if item.produ_status == NEW_SCHEDULE and item.wo_list and item.mr_reference:
                frappe.throw(
                    _("Row {0}: This row already has Work Orders. You cannot select <b>{1}</b>. Please clear the status.")
                    .format(item.idx, NEW_SCHEDULE)
                )
            if item.produ_status and item.produ_status != "Change Slot" and item.recipe_name == NO_COOKING:
                frappe.throw(
                    _("Row Number {0}: You cannot set a Production Status <strong>\"{2}\"</strong> if the Recipe is <b>{1}</b>. Please clear the status or select a valid recipe.")
                    .format(item.idx, NO_COOKING, item.produ_status)
                )
            if not item.size and item.recipe_name not in ("No Cooking", None, "") and item.produ_status != "New Schedule":
                frappe.throw(
                    _("Row {0}: Size can't be 0 or Empty for Recipe: <strong>{1}</strong>")
                    .format(item.idx, item.recipe_name)
                )
        self.validate_table_fields()

    def onload(self):
        """Ensure workflow_state is never falsy when form loads."""
        if not self.workflow_state:
            self.workflow_state = "Draft"

    def validate_table_fields(self):
        """Validate pack fields for each non-cooking row.

        - number_of_pack must be >= 1 for non-cooking recipes
        - Each pack must have a pack_name
        - Multi-pack rows require pack_qty for each pack
        """
        for row in self.production_table:

            if row.recipe_name == NO_COOKING:
                continue

            recipe_name = row.recipe_name
            pack_count = frappe.utils.cint(row.number_of_pack)

            # Validate pack selection first
            if recipe_name and pack_count <= 0:
                frappe.throw(
                    _(
                        "Row {0}: Please select a Pack Quantity before submitting "
                        "the recipe <strong>{1}</strong>."
                    ).format(row.idx, recipe_name)
                )
            if pack_count > 7:
                frappe.throw(
                    _("Row {0}: Number of packs cannot exceed 7 for recipe <strong>{1}</strong>.")
                    .format(row.idx, recipe_name)
                )
            # Validate against recipe BOM's actual pack count
            bom_pack_count = frappe.db.sql("""
                SELECT COUNT(DISTINCT bom.item)
                FROM `tabBOM` AS bom
                INNER JOIN `tabBOM Item` AS bom_item ON bom_item.parent = bom.name
                WHERE bom_item.item_code = %s
                  AND bom.is_active = 1 AND bom.docstatus = 1
                  AND bom.is_default = 1
            """, recipe_name)[0][0]
            if bom_pack_count and pack_count > bom_pack_count:
                frappe.throw(
                    _("Row {0}: Number of packs cannot exceed {1} for recipe <strong>{2}</strong>.")
                    .format(row.idx, bom_pack_count, recipe_name)
                )

            # Validate pack fields
            for i in range(1, pack_count + 1):
                suffix = "" if i == 1 else f"_{i}"

                pack_name = row.get(f"pack_name{suffix}")
                pack_qty = row.get(f"pack_qty{suffix}")

                # Pack name required
                if not pack_name:
                    frappe.throw(
                        _(
                            "Row {0}: Pack {1} Name is required "
                            "for recipe <strong>{2}</strong>."
                        ).format(row.idx, i, recipe_name)
                    )

                # Qty required for all packs except the last one
                if pack_count >= 2 and i < pack_count and not pack_qty:
                    frappe.throw(
                        _(
                            "Row {0}: Pack {1} Quantity is required "
                            "for recipe <strong>{2}</strong>."
                        ).format(row.idx, i, recipe_name)
                    )

            # Sequential pack qty: cannot fill pack N if pack N-1 is empty
            for i in range(2, pack_count + 1):
                suffix = f"_{i}"
                prev_suffix = "" if i == 2 else f"_{i - 1}"
                qty = row.get(f"pack_qty{suffix}") or 0
                prev_qty = row.get(f"pack_qty{prev_suffix}") or 0
                if qty and not prev_qty:
                    frappe.throw(
                        _(
                            "Row {0}: Please fill Pack {1} Quantity first before Pack {2} "
                            "for recipe <strong>{3}</strong>."
                        ).format(row.idx, i - 1, i, recipe_name)
                    )

            # Pack weight validation: skip if row already has WOs (historical data)
            # or if status doesn't involve pack changes
            _status_needs_pack_check = row.produ_status in ("New Schedule", "Recipe Change", "Pack Change", "")
            if pack_count > 1 and _status_needs_pack_check and not row.mr_reference and not row.wo_list:
                pack_names = []
                for i in range(1, pack_count + 1):
                    suffix = "" if i == 1 else f"_{i}"
                    name = row.get(f"pack_name{suffix}")
                    if name:
                        pack_names.append(name)

                bom_raw = frappe.db.get_value(
                    "BOM",
                    {"item": recipe_name, "docstatus": 1, "is_active": 1},
                    "custom_raw_materails",
                    order_by="modified desc",
                )
                if bom_raw:
                    raw_materials = frappe.utils.flt(bom_raw)
                    total_output = raw_materials * frappe.utils.flt(row.size)

                    # Batch fetch pack weights
                    weight_map = {}
                    iva_rows = frappe.get_all(
                        "Item Variant Attribute",
                        filters={"parent": ["in", pack_names], "attribute": "Weight"},
                        fields=["parent", "attribute_value"],
                    )
                    for iva in iva_rows:
                        weight_map[iva.parent] = frappe.utils.flt(iva.attribute_value)
                    missing = [n for n in pack_names if n not in weight_map]
                    if missing:
                        item_rows = frappe.get_all(
                            "Item",
                            filters={"name": ["in", missing]},
                            fields=["name", "weight_per_unit"],
                        )
                        for ir in item_rows:
                            weight_map[ir.name] = frappe.utils.flt(ir.weight_per_unit)

                    # Sum weighted qty of all packs except the last
                    weighted_sum = 0
                    for i in range(1, pack_count):
                        suffix = "" if i == 1 else f"_{i}"
                        name = row.get(f"pack_name{suffix}")
                        qty = frappe.utils.flt(row.get(f"pack_qty{suffix}"))
                        if name and qty:
                            weighted_sum += qty * weight_map.get(name, 0)

                    last_suffix = "" if pack_count == 1 else f"_{pack_count}"
                    last_name = row.get(f"pack_name{last_suffix}")
                    last_qty = frappe.utils.flt(row.get(f"pack_qty{last_suffix}"))
                    last_weight = weight_map.get(last_name, 0) if last_name else 0

                    if last_qty > 0:
                        weighted_sum += last_qty * last_weight
                        if weighted_sum > total_output:
                            min_size = int(weighted_sum / raw_materials) + 1
                            frappe.throw(_(
                                "Row {0}: Not enough output — total input is {1:.2f} kg but packs need {2:.2f} kg. "
                                "Increase size to at least {3}."
                            ).format(row.idx, total_output, weighted_sum, min_size))
                    elif last_weight > 0:
                        remaining = total_output - weighted_sum
                        if remaining < last_weight:
                            min_size = int((weighted_sum + last_weight) / raw_materials) + 1
                            frappe.throw(_(
                                "Row {0}: Not enough output — remaining {1:.2f} kg cannot pack '{2}' "
                                "(min weight: {3:.2f} kg). Increase size to at least {4}."
                            ).format(row.idx, remaining, last_name, last_weight, min_size))
    # ── Naming ────────────────────────────────────────────────────────────────
    def autoname(self):
        """DP-YYYY-MM-DD-#### based on creation date."""
        date_field = self.required_by
        if isinstance(date_field, str):
            from frappe.utils import get_datetime
            date_field = get_datetime(date_field)
        self.name = make_autoname(f"DP-.{date_field:%Y-%m-%d}-.####")
        return self.name

    def _assign_link_id(self):
        # Assign link_id to any non-No-Cooking row that's missing one
        for d in self.production_table:
            if not d.link_id:
                d.link_id = make_autoname("R-.YYYY.-.#####")

    def _fill_missing_slots(self):
        """Fill missing workstation+round combos with No Cooking placeholder rows.

        Reads distinct workstations from the Machine Table of the default template,
        then generates rounds 1..default_rounds for each workstation.
        """
        try:
            template = frappe.get_doc(TEMPLATE_DOCTYPE, _get_template_name())
        except Exception:
            return

        default_r = int(template.default_rounds or 3)
        ws_rows = frappe.get_all(
            TEMPLATE_CHILD,
            filters={"parent": template.name},
            fields=["workstation"],
            order_by="idx asc",
        )
        workstations = []
        seen_ws = set()
        for wr in ws_rows:
            if wr.workstation not in seen_ws:
                workstations.append(wr.workstation)
                seen_ws.add(wr.workstation)

        existing = set()
        for d in self.production_table:
            existing.add((str(d.recipe_cook_workstaion or ""), str(d.recipe_cook_round or "")))

        # Group workstations by type prefix (everything before the first digit)
        ws_groups = {}
        for ws in workstations:
            m = re.match(r"^(\D+)", ws)
            prefix = m.group(1).strip() if m else ws
            ws_groups.setdefault(prefix, []).append(ws)

        for prefix in sorted(ws_groups.keys(), key=lambda p: workstations.index(ws_groups[p][0])):
            group = ws_groups[prefix]
            for r in range(1, default_r + 1):
                for ws in group:
                    key = (str(ws), str(r))
                    if key in existing:
                        continue
                    row = self.append("production_table", {})
                    row.recipe_cook_workstaion = ws
                    row.recipe_cook_round = r
                    row.recipe_name = NO_COOKING
                    row.size = 0
                    if self.required_by:
                        row.required_date = str(self.required_by)

    def before_save(self):
        self._assign_link_id()
        self._fill_missing_slots()
        self._assign_link_id()  # re-assign to cover new placeholder rows

    # ── Submit Hook ───────────────────────────────────────────────────────────
    def before_submit(self):
        """Redirect to custom submit — just sets workflow_state, no docstatus change."""
        frappe.throw(_("Use 'Submit' button instead of document submission."))

    def on_submit(self):
        pass
                
    @frappe.whitelist()
    def process_manual_updates(self):
        """Orchestrate all post-submit production workflows.

        Called from on_submit (after DB commit). Runs each workflow step
        sequentially. If any step throws, the entire transaction is rolled back.

        Execution order:
        1. process_cancellations    – Cancel WOs for "Cancelled" rows
        2. process_recipe_change_or_size_change – Re-create WOs for size-changed rows
        3. process_slot_swaps       – Swap WOs between rearranged slots
        4. process_switch           – Migrate link_ids for "Change Slot" rows
        5. process_pack_change_or_add – Re-create WOs for changed packs
        6. rws                      – Sync row notes to WOs
        7. Pre-validate New Schedule rows (pack fields required)
        8. _process_new_schedules   – Create MRs + WOs for new schedule rows
        9. _obsolete_older_records  – Mark same-date DPs as Obsolete

        On success: sets custom_submit_ref, commits (if not in_submit).
        On failure: rolls back, logs error, throws user message.
        """
        try:
            # Guard: if custom_submit_ref is set but no MRs exist, clear it
            # (handles stuck state from failed process_manual_updates where
            # internal commits persisted the flag but rollback couldn't undo it)
            if self.custom_submit_ref:
                has_mr = any(row.mr_reference for row in self.production_table)
                if not has_mr:
                    self.db_set("custom_submit_ref", "")
                    frappe.db.commit()

            process_cancellations(self.name, self.doctype, CHILD_DOCTYPE)
            process_recipe_change_or_size_change(self, CHILD_DOCTYPE)
            process_slot_swaps(self, CHILD_DOCTYPE)
            process_switch(self, CHILD_DOCTYPE)
            process_pack_change_or_add(self, CHILD_DOCTYPE)
            
            rws(self, CHILD_DOCTYPE)

            # Pre-validate: "New Schedule" rows must have pack fields before creating MRs
            for row in self.production_table:
                if row.produ_status == NEW_SCHEDULE:
                    count = int(row.number_of_pack or 0)
                    if count == 0:
                        frappe.throw(
                            _("Row {0}: Recipe <b>{1}</b> must have a Pack assigned. "
                              "Set 'Number of Pack' and 'Pack Name' before creating Work Orders.")
                            .format(row.idx, row.recipe_name)
                        )
                    if not row.get("pack_name"):
                        frappe.throw(
                            _("Row {0}: Recipe <b>{1}</b> is missing Pack 1 Name. "
                              "Set 'Pack Name' before creating Work Orders.")
                            .format(row.idx, row.recipe_name)
                        )

            self._process_new_schedules()
            self._obsolete_older_records()

            # 2. Update the reference flag
            # We use db_set to update the value without triggering another save cycle
            if not self.custom_submit_ref:
                self.db_set("custom_submit_ref", self.name)
            
            # 3. Handle Commits
            # Only commit if NOT called during the submission process 
            # (Frappe handles the commit automatically during on_submit)
            if not frappe.flags.in_submit:
                frappe.db.commit()
                self.reload()

            # WhatsApp notification (async — don't block)
            try:
                from caf.caf.utils.notifications import notify_dp_schedule
                frappe.enqueue(notify_dp_schedule, dp_name=self.name, queue="short")
            except Exception:
                pass

            return True

        except Exception as e:
            # Undo everything if any part failed
            frappe.db.rollback()
            
            # Log the error for the developer
            frappe.log_error(frappe.get_traceback(), _("Production Update Failed"))
            
            # Message for the user
            frappe.throw(_("Update failed and changes were rolled back. Error: {0}").format(str(e)))

               
    # ── Production Table Flow ─────────────────────────────────────────────────
    def _on_submit_production_table(self) -> None:
        """Validate rows → group by recipe → create one MR per group."""
        _validate_production_rows(self.production_table)
        recipe_groups = _get_recipe_rows(self.production_table)
        if not recipe_groups:
            frappe.throw(_("❌ No valid recipes found in the production table."))
        for group in recipe_groups:
            self.create_material_request(group["recipe"], group["rows"])

    def get_full_group_for_row(self, row_doc):
        """Return a single-element group (row itself). Legacy compatibility."""
        return [row_doc]

    def _process_new_schedules(self):
        """Create Material Requests for 'New Schedule' rows.

        Collects recipe rows (one per non-No-Cooking row), creates one MR per row, then:
        - Sets produ_status → "New Schedule"
        - If row has link_id and Reheat type, removes all WIP WOs

        On failure: exception propagates to process_manual_updates which
        rolls back the entire transaction (no partial WOs created).
        """
        recipe_groups = _get_recipe_rows(self.production_table)
        for group in recipe_groups:
            if group["rows"][0].produ_status == NEW_SCHEDULE or (not group["rows"][0].mr_reference and not group["rows"][0].production_plane):
                self.create_material_request(group["recipe"], group["rows"])
                link_id = group["rows"][0].link_id
                reheat = group["rows"][0].production_type
                if link_id and reheat == "Reheat":
                    remove_all_wip_wo(link_id, work=True)

    # ── Obsolete Older Records ─────────────────────────────────────────────────
    def _obsolete_older_records(self) -> None:
        """No-op: versioning removed. Only one DP per date."""
        pass

    # ── Create Material Request ────────────────────────────────────────────────
    def create_material_request(self, recipe_name: str, rows: list) -> None:
        """Create and submit a Material Request for a recipe group.

        Steps:
        1. Skip if first row already has mr_reference
        2. Build MR header from Daily Production
        3. Append pack items + recipe row
        4. Insert + submit MR (submit triggers WO creation via on_submit)
        5. Write back mr_reference, wo_list, link_id to child rows
        6. Show success message with link

        Args:
            recipe_name: Recipe to create MR for
            rows: Child table rows for this recipe group
        """
        first = rows[0]
        if first.mr_reference:
            return
        
        mr = frappe.new_doc(MR_DOCTYPE)
        _build_mr_header(mr, self, first)
        _append_pack_items(mr, rows)
        _append_recipe_row(mr, recipe_name, first)
        mr.flags.ignore_permissions = True
        mr.insert()

        mr.submit()
        frappe.db.set_value(first.doctype, first.name, "mr_reference", mr.name)
        _write_back_to_row(first, mr.name, mr)
        if frappe.request:
            link = frappe.utils.get_link_to_form(MR_DOCTYPE, mr.name)
            frappe.msgprint(f"Material Request created for Recipe: {recipe_name}<br>{link}")

    def recreate_mr_after_update_slot(self, recipe_name: str, rows: list) -> list:
            """Force-update production after a size change while preserving the existing Link ID.

            Creates the new Material Request first, then detaches the old one
            only if the new one succeeds — keeping the old MR intact on failure.

            Args:
                recipe_name: Recipe to create the MR for
                rows: Child table rows for this recipe group

            Returns:
                List of newly created Work Orders (for WIP cleanup filtering)
            """
            first = rows[0]
            old_mr_name = first.get("mr_reference")
            existing_link_id = first.get("link_id")
            if not old_mr_name:
                self.create_material_request(recipe_name, rows)
                return []
            # 1. Create New MR
            new_mr = frappe.new_doc("Material Request")
            new_mr.custom_link_id = existing_link_id
            new_mr.custom_daily_production_id = self.name
            _build_mr_header(new_mr, self, first)
            _append_pack_items(new_mr, rows)
            _append_recipe_row(new_mr, recipe_name, first)
            # 2. Bypass Workflow & Submit
            new_mr.flags.ignore_permissions = True
            new_mr.flags.ignore_workflow = True
            if frappe.get_meta("Material Request").has_field("workflow_state"):
                new_mr.workflow_state = "Approved"
            new_mr.insert()
            new_mr.flags.ignore_workflow = True
            new_mr.submit()
            # 3. New MR created successfully — now detach old MR
            frappe.db.sql("UPDATE `tabCreate ProExl Items` SET mr_reference = NULL WHERE mr_reference = %s", (old_mr_name,))
            if frappe.db.exists("Material Request", old_mr_name):
                frappe.db.set_value("Material Request", old_mr_name, {"custom_link_id": "", "custom_daily_production_id": ""})
            # 4. Write back new MR reference
            newly_born_wos = getattr(new_mr, "wo_list", [])
            _write_back_to_row_additive(rows[0], new_mr.name, new_mr)
            return newly_born_wos

#  Material Request Helpers  (module-level, no self needed)
# ══════════════════════════════════════════════════════════════════════════════
def _build_mr_header(mr, daily_production, first_row) -> None:
    """Populate MR header fields from the Daily Production and first child row.

    Sets material_request_type, recipe/daily production references, batch
    size, schedule date, link_id, and operation type on the MR doc.

    Args:
        mr: Material Request document to populate
        daily_production: Parent Daily Production doc
        first_row: First child row in the recipe group
    """
    today_date                    = getdate(today())
    required_by  = getdate(daily_production.required_by) if daily_production.required_by else None
    mr.material_request_type      = "Manufacture"
    mr.custom_recipe_reference    = daily_production.name
    mr.custom_daily_production_id = daily_production.name
    mr.custom_batch_size          = first_row.size

    mr.schedule_date              = (
                                    today_date
                                    if not required_by or required_by < today_date
                                    else required_by
                                    )
    mr.custom_link_id             = first_row.link_id
    mr.custom_operation_type      = first_row.production_type


def _append_pack_items(mr, rows: list) -> None:
    """Append all pack items from child rows to the Material Request items table.

    Dynamically discovers pack_name, pack_name_2, pack_name_3, ... fields
    from the child doctype metadata and adds each as a separate MR item
    row with qty, schedule date, workstation, round, start time, and note.

    Args:
        mr: Material Request document to append items to
        rows: Child table rows (uses rows[0] for pack data)
    """
    row        = rows[0]
    today_date = getdate(today())
    required_date = getdate(row.required_date) if row.required_date else None  # ← normalize once

    # 1. Get all fieldnames from the child table's metadata
    all_fields = [f.fieldname for f in frappe.get_meta(row.doctype).fields]

    # 2. Identify all pack name fields and sort them correctly
    numbered_packs = [f for f in all_fields if f.startswith("pack_name_")]
    numbered_packs.sort(key=lambda x: int(x.split('_')[-1]))
    pack_name_fields = ["pack_name"] + numbered_packs

    for p_field in pack_name_fields:
        pack_item_code = row.get(p_field)
        if not pack_item_code:
            continue

        suffix = "" if p_field == "pack_name" else "_" + p_field.split('_')[-1]

        item                    = mr.append("items", {})
        item.item_code          = pack_item_code
        item.qty                = row.get(f"pack_qty{suffix}") or 1
        item.schedule_date      = today_date if not required_date or required_date < today_date else required_date
        item.custom_item_type   = "Pack"
        item.custom_workstation = row.pack_machine
        item.custom_round       = row.pack_round
        #item.custom_start_time  = row.pack_time 
        item.custom_note        = row.get(f"pack_remark{suffix}")

def _append_recipe_row(mr, recipe_name: str, first_row) -> None:
    """Append a recipe row to the MR's custom_recipe_table.

    Sets item_code, round, workstation, start time, schedule date,
    UOM (Kg), conversion factor, and note from the first child row.

    Args:
        mr: Material Request document
        recipe_name: Item code of the recipe
        first_row: First child row supplying cook parameters
    """
    today_date    = getdate(today())
    required_date = getdate(first_row.required_date) if first_row.required_date else None

    r                   = mr.append("custom_recipe_table", {})
    r.item_code         = recipe_name
    r.round             = first_row.recipe_cook_round
    r.workstation       = first_row.recipe_cook_workstaion
    r.start_time        = first_row.recipe_cook_time
    r.schedule_date     = today_date if not required_date or required_date < today_date else required_date
    r.uom               = "Kg"
    r.conversion_factor = "1"
    r.custom_note       = first_row.recipe_note



def _write_back_to_row(first_row, mr_name: str, mr) -> None:
    """Write back MR reference, production plan name, and link ID to the child row.

    Side effect: Updates the child table row in the database via frappe.db.set_value.

    Args:
        first_row: Child table row document
        mr_name: Name of the Material Request
        mr: Material Request document (used for p_name and custom_link_id)
    """
    frappe.db.set_value(first_row.doctype, first_row.name, {
        "mr_reference"      : mr_name,
        # "wo_list"           : wo_list_string,
        # "wo_list_with_type" : wo_with_type_string,  # ✅ All WOs with their type
        "production_plane"  : getattr(mr, "p_name", ""),
        "link_id"           : getattr(mr, "custom_link_id", ""),
    })

def _write_back_to_row_additive(first_row, mr_name: str, mr) -> list:
    """Merge new WOs with existing WOs in the row, purging cancelled ones.

    Reads current wo_list and wo_list_with_type from the DB, merges with
    fresh WOs from the MR, removes any with docstatus=2 (Cancelled), and
    writes the cleaned merged list back to the row.

    Side effect: Updates the child row in the database.

    Args:
        first_row: Child table row document
        mr_name: Name of the Material Request
        mr: Material Request document with wo_list and wo_list_with_type

    Returns:
        List of newly created WOs from this cycle
    """
    # Get current data from DB
    current = frappe.db.get_value(first_row.doctype, first_row.name, 
                                  ["wo_list", "wo_list_with_type"], as_dict=True) or {}
    
    existing_wos = [w.strip() for w in (current.get("wo_list") or "").splitlines() if w.strip()]
    existing_types = [t.strip() for t in (current.get("wo_list_with_type") or "").split(",") if t.strip()]

    # Get fresh WOs from the Material Request object
    new_wos = getattr(mr, "wo_list", []) or []
    new_types = [t.strip() for t in (getattr(mr, "wo_list_with_type", "")).split(",") if t.strip()]

    # Merge and Purge Cancelled
    final_wos = []
    final_types = []

    # Phase 4: Batch WO queries — single get_all instead of N+1
    all_wo_names = list(set(existing_wos + new_wos))
    wo_data = {}
    if all_wo_names:
        wo_records = frappe.get_all("Work Order",
            filters={"name": ["in", all_wo_names]},
            fields=["name", "docstatus", "custom_item_type"])
        wo_data = {w.name: w for w in wo_records}

    for wo in all_wo_names:
        res = wo_data.get(wo)
        if res and res.docstatus != 2:
            final_wos.append(wo)
            match = next((t for t in (existing_types + new_types) if wo in t), f"({wo},{res.custom_item_type})")
            final_types.append(match)

    # Save cleaned, merged list back to row
    frappe.db.set_value(first_row.doctype, first_row.name, {
        "mr_reference"      : mr_name,
        "wo_list"           : "\n".join(final_wos),
        "wo_list_with_type" : ",".join(final_types),
        "production_plane"  : getattr(mr, "p_name", ""),
    }, update_modified=False)

    return new_wos # Returns only the ones created in this cycle
# ══════════════════════════════════════════════════════════════════════════════
#  Validation & Grouping Helpers
# ══════════════════════════════════════════════════════════════════════════════
def _validate_production_rows(rows: list) -> None:
    """Validate every production row has at least one pack and positive pack qty.

    Args:
        rows: List of child table rows to validate

    Raises:
        frappe.throw if a row is missing pack_name or has qty <= 0
    """
    today = getdate(nowdate())

    for row in rows:
        if row.recipe_name and row.recipe_name != NO_COOKING:
            # Ensure at least the first pack is selected
            if not row.pack_name:
                frappe.throw(
                    _("Row {0}: Please select at least one Pack Name for recipe '{1}'.")
                    .format(row.idx, row.recipe_name)
                )
            
            # Check Qty for the primary pack
            if row.pack_name and (not row.pack_qty or row.pack_qty <= 0):
                 frappe.throw(_("Row {0}: Pack Qty must be > 0").format(row.idx))


def _get_recipe_rows(rows: list) -> list[dict]:
    """Collect non-'No Cooking' rows as standalone single-row groups.

    Each row with a recipe_name becomes its own group dict with
    {"recipe": recipe_name, "rows": [row]}.

    Args:
        rows: List of child table rows

    Returns:
        List of group dicts
    """
    groups = []
    for row in rows:
        if row.recipe_name and row.recipe_name != NO_COOKING:
            # Each row is now its own group containing itself
            groups.append({"recipe": row.recipe_name, "rows": [row]})
    return groups


# ══════════════════════════════════════════════════════════════════════════════
#  get_merged_production_items
# ══════════════════════════════════════════════════════════════════════════════
def _get_child_fields() -> list[str]:
    """Return data-bearing fieldnames from the Create ProExl Items child DocType.

    Excludes non-data fieldtypes (Section Break, Column Break, HTML, etc.)
    and always includes idx in the result.

    Returns:
        List of fieldname strings
    """
    meta   = frappe.get_meta(CHILD_DOCTYPE)
    fields = [
        df.fieldname for df in meta.fields
        if df.fieldtype not in NON_DATA_FIELDTYPES
    ]
    if "idx" not in fields:
        fields.append("idx")
    return fields


def _serialize_row(row: dict, date_str: str) -> dict:
    """Convert a DB row dict to a JSON-safe dict with required_date stamped.

    Converts datetime-like values to strings, forces number_of_pack=0 for
    No Cooking rows, and resets produ_status to empty string.

    Args:
        row: Row dict from frappe.get_all
        date_str: Date string to set as required_date

    Returns:
        Cleaned dict safe for JSON serialization
    """
    clean = {
        k: str(v) if hasattr(v, "isoformat") else v
        for k, v in row.items()
    }
    if row.get("recipe_name") == NO_COOKING:
        clean["number_of_pack"] = 0  # Force number_of_pack to 0 for No Cooking rows
    clean["required_date"] = date_str
    clean["produ_status"] = ""  # ✅ Reset status when loading from latest record
    return clean


def _get_template_name() -> str:
    """Return the default production template name, falling back to the latest created.

    Tries is_default=1 first, then creation desc order. Throws if
    no template record exists at all.

    Returns:
        Name of the production template DocType record
    """
    name = frappe.db.get_value(TEMPLATE_DOCTYPE, {"is_default": 1}, "name")
    if not name:
        name = frappe.db.get_value(TEMPLATE_DOCTYPE, {}, "name", order_by="creation desc")
    if not name:
        frappe.throw(
            _("No Production Template found. Please create a '{0}' record first.")
            .format(TEMPLATE_DOCTYPE)
        )
    return name


def _assert_submitted(doctype: str, record) -> None:
    """No-op: always allowed (non-submission workflow)."""
    pass

@frappe.whitelist()
def get_merged_production_items(date: str, doctype: str) -> dict:
    """Fetch and merge production items for a date from the latest non-obsolete DP.

    Retrieves all child rows from the latest submitted DP for the date,
    then back-fills missing workstation+round combos from the master
    production template. Cancelled rows are blanked (recipe set to
    No Cooking).

    Args:
        date: Target date string
        doctype: DocType name (typically "Daily Production")

    Returns:
        Dict with "rows" (list of merged items) and "custom_submit_ref" (str or falsy)
    """
    try:
        date_obj = getdate(date)
        date_str = str(date_obj)
        final    : list[dict]  = []
        seen     : set[tuple]  = set()
        fields   = _get_child_fields()

        latest = frappe.db.get_value(
            doctype,
            {
                "required_by"   : date_obj,
                "docstatus"     : ["<", 2],
                "workflow_state": ["!=", "Obsolete"],
            },
            ["name", "docstatus", "custom_submit_ref"],
            as_dict=True,
            order_by="creation desc",
        )

        submit_ref_status = latest.get("custom_submit_ref") if latest else ""

        if latest:
            _assert_submitted(doctype, latest)

            child_fields = fields + ["docstatus"] if "docstatus" not in fields else fields

            # ✅ Fetch ALL rows including Cancelled — no produ_status filter
            for row in frappe.get_all(
                CHILD_DOCTYPE,
                filters={"parent": latest.name},
                fields=child_fields,
                order_by="idx asc",
            ):
                # ✅ Blank out cancelled rows, keep only the 3 identity fields
                if row.get("produ_status") == "Cancelled":
                    final.append({
                        "recipe_cook_workstaion": row.get("recipe_cook_workstaion"),
                        "recipe_cook_round"     : row.get("recipe_cook_round"),
                        "link_id"               : row.get("link_id"),
                        "produ_status"          : "",   # preserve status so UI knows
                        "required_date"         : date_str,
                        "recipe_name"           : NO_COOKING,    # force recipe to No Cooking   
                        "size"                  : 0,              # force size to 0
                    })
                else:
                    final.append(_serialize_row(row, date_str))

                # ✅ Either way, mark this workstation+round as seen
                seen.add((
                    str(row.get("recipe_cook_workstaion")),
                    str(row.get("recipe_cook_round")),
                ))

        # ── Back-fill from Master Template ────────────────────────
        template = frappe.get_doc(TEMPLATE_DOCTYPE, _get_template_name())
        default_r = int(template.default_rounds or 3)
        ws_rows = frappe.get_all(
            TEMPLATE_CHILD,
            filters={"parent": template.name},
            fields=["workstation"],
            order_by="idx asc",
        )
        workstations = []
        seen_ws = set()
        for wr in ws_rows:
            if wr.workstation not in seen_ws:
                workstations.append(wr.workstation)
                seen_ws.add(wr.workstation)

        # Group workstations by type prefix (everything before the first digit)
        ws_groups = {}
        for ws in workstations:
            m = re.match(r"^(\D+)", ws)
            prefix = m.group(1).strip() if m else ws
            ws_groups.setdefault(prefix, []).append(ws)

        for prefix in sorted(ws_groups.keys(), key=lambda p: workstations.index(ws_groups[p][0])):
            group = ws_groups[prefix]
            for r in range(1, default_r + 1):
                for ws in group:
                    key = (str(ws), str(r))
                    if key in seen:
                        continue
                    final.append({
                        "recipe_cook_workstaion": ws,
                        "recipe_cook_round"     : r,
                        "recipe_name"           : NO_COOKING,
                        "size"                  : 0,
                        "required_date"         : date_str,
                    })

        # ── Re-index ──────────────────────────────────────────────
        for i, row in enumerate(final, start=1):
            row["idx"] = i

        return {
            "rows"      : final,
            "custom_submit_ref": submit_ref_status,
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), _("Production Merge Error"))
        frappe.throw(_("An error occurred while fetching production data."))
# Import your custom override




# ══════════════════════════════════════════════════════════════════════════════
#  Single WO Material Request
# ══════════════════════════════════════════════════════════════════════════════
def create_material_request_for_single_wo(doc) -> None:
    """Create and submit a Material Request for a single WO from the given doc.

    Iterates over doc.items, adds each as an MR item with WIP type, inserts
    and submits the MR.

    Side effect: Inserts and submits a Material Request; shows success message.

    Args:
        doc: Document with an items child table and required_by_1 date
    """
    mr                            = frappe.new_doc(MR_DOCTYPE)
    mr.material_request_type      = "Manufacture"
    mr.custom_recipe_reference    = doc.name
    mr.custom_daily_production_id = doc.name
    mr.schedule_date              = doc.required_by_1

    if doc.items:
        mr.custom_single_wo = doc.items[0].single_wo

    for row in doc.items:
        if not row.item_code:
            continue
        item                    = mr.append("items", {})
        item.item_code          = row.item_code
        item.qty                = row.qty or 0
        item.schedule_date      = row.schedule_date
        item.custom_item_type   = "WIP"
        item.custom_workstation = row.cook_machine
        item.custom_round       = row.cook_round
        item.custom_start_time  = row.cook_time
        item.custom_note        = row.note

    mr.flags.ignore_permissions = True
    mr.insert()
    mr.submit()

    link = frappe.utils.get_link_to_form(MR_DOCTYPE, mr.name)
    frappe.msgprint(f"✅ Material Request created<br>{link}")


# ══════════════════════════════════════════════════════════════════════════════
#  BOM Utilities
# ══════════════════════════════════════════════════════════════════════════════
@frappe.whitelist()
def get_bom_info(item_code: str) -> dict:
    """Return BOM total ingredient qty and yield for an item.

    Finds the default active BOM for item_code, sums BOM item qtys
    (converting grams to kg), and reads custom_yield.

    Args:
        item_code: Item code to look up

    Returns:
        Dict with "bom_total" and "bom_yield", or None for No Cooking
    """
    if item_code == NO_COOKING:
        return
    bom = frappe.db.get_value("BOM", {"item": item_code, "is_default": 1}, "name")
    if not bom:
        frappe.throw(_("No Default BOM found for item {0}").format(item_code))

    bom_items = frappe.get_all("BOM Item", filters={"parent": bom}, fields=["item_code", "qty"])
    bom_total = sum(
        bi["qty"] / 1000 if frappe.get_cached_value("Item", bi["item_code"], "stock_uom").lower() == "gram"
        else bi["qty"]
        for bi in bom_items
    )

    bom_yield = frappe.db.get_value("BOM", bom, "custom_yield")
    if not bom_yield:
        frappe.throw(_("No Yield value found or Yield = 0 in BOM for item {0}").format(item_code))

    return {"bom_total": bom_total, "bom_yield": bom_yield}


@frappe.whitelist()
def check_bom_recursion(bom_no: str, visited_boms: list = None, depth: int = 0) -> bool:
    """Recursively check for circular BOM references starting from bom_no.

    Follows child BOM items and their default BOMs, maintaining a visited
    list. If a BOM is revisited, logs an error and returns True.

    Args:
        bom_no: BOM name to start checking from
        visited_boms: Accumulator for BOMs already visited in this path
        depth: Current recursion depth (unused in logic, used for tracing)

    Returns:
        True if a circular reference is detected, False otherwise
    """
    if visited_boms is None:
        visited_boms = []

    if bom_no in visited_boms:
        frappe.log_error(
            f"Circular BOM: {' -> '.join(visited_boms)} -> {bom_no}",
            "BOM Recursion Detected"
        )
        return True

    current_path = visited_boms + [bom_no]

    if not frappe.db.get_value("BOM", bom_no, "item"):
        return False

    for row in frappe.db.get_all("BOM Item", filters={"parent": bom_no}, fields=["item_code", "bom_no"]):
        child_bom = row.bom_no or frappe.db.get_value("Item", row.item_code, "default_bom")
        if child_bom and check_bom_recursion(child_bom, current_path, depth + 1):
            return True

    return False


# ══════════════════════════════════════════════════════════════════════════════
#  Pack Search
# ══════════════════════════════════════════════════════════════════════════════
@frappe.whitelist()
def get_packs_for_recipe(doctype, txt, searchfield, start, page_len, filters):
    """Return pack items whose BOM contains the given recipe as an ingredient.

    Used as a Frappe LinkField search function. Excludes items already
    selected in the current row via filters.excluded_items.

    Args:
        doctype: DocType being searched
        txt: Search text
        searchfield: Field being searched
        start: Offset for pagination
        page_len: Page size limit
        filters: Dict with recipe_name and optionally excluded_items

    Returns:
        List of [item_code, item_name] lists
    """
    recipe_name = filters.get("recipe_name")
    excluded = filters.get("excluded_items")
    
    if not recipe_name:
        return []

    # Base Query
    query = """
        SELECT bom.item, item.item_name
        FROM `tabBOM` AS bom
        INNER JOIN `tabBOM Item` AS bom_item ON bom_item.parent = bom.name
        INNER JOIN `tabItem`     AS item     ON item.name = bom.item
        WHERE
            bom_item.item_code = %(recipe_name)s
            AND (item.name LIKE %(txt)s OR item.item_name LIKE %(txt)s)
            AND bom.is_active  = 1
            AND bom.docstatus  = 1
            AND item.disabled  = 0
            AND bom.is_default = 1
    """

    params = {
        "recipe_name": recipe_name,
        "txt"        : f"%{txt}%",
        "page_len"   : page_len,
        "start"      : start,
    }

    # 3. Apply the Exclusion Filter
    if excluded:
        # Frappe passes filters as strings/lists depending on version; ensure it's a list
        if isinstance(excluded, str):
            import json
            excluded = json.loads(excluded)
            
        if len(excluded) > 0:
            query += " AND bom.item NOT IN %(excluded)s"
            params["excluded"] = excluded

    query += " ORDER BY item.item_name LIMIT %(page_len)s OFFSET %(start)s"

    return frappe.db.sql(query, params, as_list=True)
# ══════════════════════════════════════════════════════════════════════════════
#  New Version Part
# ══════════════════════════════════════════════════════════════════════════════
from werkzeug.wrappers import Response
@frappe.whitelist(allow_guest=True)
def create_new_dp(docname, doctype=None):
    """No-op: versioning removed. Only one DP per date."""
    pass




# EXCEL SYNC ENDPOINT: Receives data from Excel, finds or creates the Daily Production doc for the given date, and updates the production table accordingly. It also handles the logic for determining the recipe based on the pack and BOM structure.
@frappe.whitelist()
def sync_excel_production(data, date=None):
    """Sync production plan data from an external Excel source.

    Finds or creates a Daily Production for the given date, clears the
    production table, and rebuilds it from the incoming data. Resolves
    each entry's recipe by looking up the pack's BOM for items in the
    'Recipe' or 'WIP Floss' item groups.

    Side effect: Creates/updates a Daily Production record and commits.

    Args:
        data: List of dicts with pack, workstation, round, size keys
        date: Target date string (defaults to today)

    Returns:
        Dict with status and message
    """
    # 0. Ensure 'data' is a list (handles potential decoding issues)
    if isinstance(data, str):
        import json
        data = json.loads(data)

    # 1. Logic: Default to today if date is missing or in the past
    target_date = date if (date and date != "") else today()
    if target_date < today():
        target_date = today()
    
    # 2. Find or Create the Daily Production document
    # Note: Using 'required_by' to match your latest field name
    doc_name = frappe.db.get_value("Daily Production", {"required_by": target_date}, "name")
    
    if not doc_name:
        doc = frappe.get_doc({
            "doctype": "Daily Production",
            "required_by": target_date,
        })
    else:
        doc = frappe.get_doc("Daily Production", doc_name)

    # 3. Clear existing table to overwrite with fresh Excel data
    doc.set("production_table", [])

    # 4. Process each row from Excel
    for entry in data:
        pack = entry.get('pack')
        recipe = "No Cooking"
        
        if pack and pack != "No Cooking":
            # Find the default active BOM for this Pack (Item Code)
            bom_name = frappe.db.get_value("BOM", {"item": pack, "is_active": 1, "is_default": 1}, "name")
            
            if bom_name:
                # Look for an item inside the BOM that belongs to the 'Recipe' Item Group
                bom_items = frappe.get_all("BOM Item", filters={"parent": bom_name}, fields=["item_code"])
                
                for item in bom_items:
                    item_group = frappe.db.get_value("Item", item.item_code, "item_group")
                    if item_group in ["Recipe","WIP Floss"]:
                        recipe = item.item_code
                        break # Found the recipe item, stop looking in this BOM
        
        # 5. Append to the child table
        # I used your field names (including 'workstaion' typo if that matches your doctype)
        doc.append("production_table", {
            "recipe_name": recipe,
            "recipe_cook_workstaion": entry.get('workstation'), 
            "recipe_cook_round": entry.get('round'),
            "pack_name": pack,
            "size": entry.get('size', 0)
        })

    doc.save()
    frappe.db.commit()
    
    return {"status": "success", "message": f"Successfully updated plan for {target_date}"}


@frappe.whitelist(allow_guest=True)
def say_hi():
    """Display a confirmation page and trigger a Metabase dashboard refresh.

    Renders a web page that sets trigger_metabase_refresh=1 cookie and
    auto-closes the browser tab after 500ms.
    """
    frappe.respond_as_web_page("Done", """<h2>hi there from erpnext</h2>
<p>Refreshing Metabase...</p>
<script>
    var now = new Date();
    var expires = new Date(now.getTime() + 30 * 1000);
    document.cookie = "trigger_metabase_refresh=1; path=/; expires=" + expires.toUTCString() + ";";
    setTimeout(function() {
        window.open('', '_self', '');
        window.close();
    }, 500);
</script>""")

@frappe.whitelist(allow_guest=True)
def create_empty_dp_week(week_no=None):
    """Create draft Daily Production documents for Monday-Saturday of a given week.

    Skips days before today and dates that already have a draft DP. For
    each day, merges production items from the latest non-obsolete DP.

    Side effect: Inserts multiple Daily Production records and commits.

    Args:
        week_no: Date string of the Monday of the target week (defaults to today)

    Renders a web page summary on completion.
    """
    try:
        start = getdate(week_no) if week_no else getdate(today())
        days_until_saturday = (5 - start.weekday()) % 7
        end_date = add_days(start, days_until_saturday)

        created = []
        skipped = []
        current_date = start

        while current_date <= end_date:
            if current_date < getdate(today()):
                current_date = add_days(current_date, 1)
                continue

            dp_name = frappe.db.get_value("Daily Production",
                {"required_by": str(current_date), "docstatus": 0}, "name")

            if dp_name:
                skipped.append(str(current_date))
            else:
                doc = frappe.new_doc("Daily Production")
                doc.required_by = str(current_date)

                data = get_merged_production_items(str(current_date), "Daily Production")
                if data and data.get("rows"):
                    # ── Validate link_id on source rows ──
                    rows_missing_link = [
                        r for r in data["rows"]
                        if r.get("recipe_name") and r.get("recipe_name") != NO_COOKING and not r.get("link_id")
                    ]
                    if rows_missing_link:
                        frappe.log_error(
                            title="Empty DP Week - Missing Link IDs",
                            message=f"Date: {str(current_date)}\n"
                                    f"Rows from source DP missing link_id (idx): {[r.get('idx') for r in rows_missing_link]}\n"
                                    f"Recipe names: {[r.get('recipe_name') for r in rows_missing_link]}"
                        )
                        frappe.throw(
                            _("Cannot create empty DP for {0}. {1} row(s) from the source are missing their Link ID. "
                              "Please contact the Administrator.")
                            .format(str(current_date), len(rows_missing_link))
                        )
                    doc.custom_submit_ref = data.get("custom_submit_ref", "")
                    excluded = ["name", "parent", "parentfield", "parenttype", "doctype", "idx"]
                    for item in data["rows"]:
                        child = doc.append("production_table", {})
                        for key, value in item.items():
                            if key not in excluded:
                                child.set(key, value)

                doc.insert(ignore_permissions=True)
                created.append(doc.name)

            current_date = add_days(current_date, 1)

        frappe.db.commit()
        body = f"<h2>Done</h2><p>Created: {len(created)} | Skipped (already draft): {len(skipped)}</p>"
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_empty_dp_week failed")
        frappe.respond_as_web_page("Error", f"<h2>Error</h2><p>{frappe.utils.cstr(e)}</p>")
        return

    frappe.respond_as_web_page("Done", body + """<script>
    var now = new Date();
    var expires = new Date(now.getTime() + 30 * 1000);
    document.cookie = "trigger_metabase_refresh=1; path=/; expires=" + expires.toUTCString() + ";";
    setTimeout(function() {
        window.open('', '_self', '');
        window.close();
    }, 5000);
</script>""")


@frappe.whitelist(allow_guest=True)
def create_empty_dp_week_by_number(week_number):
    """Create draft Daily Production documents for a given ISO week number.

    Converts the ISO week number to the Monday date of that week and
    delegates to create_empty_dp_week.

    Args:
        week_number: ISO week number (e.g. 21)
    """
    try:
        year = datetime.date.today().year
        week_number = int(week_number)
        jan4 = datetime.date(year, 1, 4)
        start = jan4 - datetime.timedelta(days=jan4.isocalendar()[2] - 1)
        monday = start + datetime.timedelta(weeks=week_number - 1)
        return create_empty_dp_week(week_no=str(monday))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_empty_dp_week_by_number failed")
        frappe.respond_as_web_page("Error", f"<h2>Error</h2><p>{frappe.utils.cstr(e)}</p>")


@frappe.whitelist(allow_guest=True)
def submit_dp_week(week_monday_str=None):
    """
    ============================================================================
    submit_dp_week  —  Bulk-submit all Daily Production records for a given week
    ============================================================================

    WHAT IT DOES
    ────────────
    Given a date (any day in the target week), it finds Monday–Saturday of that
    week, then for EACH day:

      1. Looks for a **draft** (docstatus=0) Daily Production for that date
      2. If found, checks that at least ONE child row has a `produ_status` set
      3. If yes → submits it.  If no → skips it.

    It collects all results and displays a web page report with 4 categories:
      ✅ Submitted      — successfully submitted
      ⏭️ Skipped (no draft)  — no DP exists for that date
      ⏭️ Skipped (no status) — DP exists but no rows have produ_status
      ❌ Failed         — DP exists but submit threw an error

    After the report, it sets a cookie to trigger a Metabase refresh and auto-
    closes the browser tab after 3 seconds.

    PARAMETERS
    ──────────
    week_monday_str : str or None
        Date string of the Monday of the target week, e.g. "2027-05-24".
        Passed automatically by submit_dp_week_by_number().
        If None (or omitted), defaults to TODAY.

    RETURNS
    ───────
    Nothing.  Renders a web page (frappe.respond_as_web_page).

    ============================================================================
    EXAMPLES
    ============================================================================

    1)  Submit all DPs for week 21 of the current year:
        ──────────────────────────────────────────────
        bench --site development.localhost execute \
            "caf.caf.doctype.daily_production.daily_production.submit_dp_week_by_number" \
            --kwargs "{'week_number': 21}"

    2)  Submit all DPs for the current week (if no argument given):
        ──────────────────────────────────────────────
        bench --site development.localhost execute \
            "caf.caf.doctype.daily_production.daily_production.submit_dp_week"

    3)  From a browser (whitelisted + guest access):
        ────────────────────────────────────────────
        http://your-site:8000/api/method/caf.caf.doctype.daily_production.daily_production.submit_dp_week_by_number?week_number=21

    ============================================================================
    ALGORITHM
    ============================================================================

    You call:  submit_dp_week_by_number(21)

        Step 1:  submit_dp_week_by_number converts week 21 → Monday date
                 (e.g. 2027-05-24)
        Step 2:  This Monday is passed to submit_dp_week as week_monday_str
        Step 3:  submit_dp_week calculates week_saturday = Mon + days_until_saturday
                 then loops day_date Mon → Tue → Wed → Thu → Fri → Sat
                 checking for draft DPs and submitting them

        Example: week 21 of 2027
                 Monday = 2027-05-24, Saturday = 2027-05-29

                 Loop:  Mon 24  →  Tue 25  →  Wed 26  →  Thu 27  →  Fri 28  →  Sat 29
                        │           │            │           │           │          │
                        check for draft DP →  if found + produ_status → submit()

    If you call submit_dp_week() directly with a date:
        bench execute "…submit_dp_week" --kwargs "{'week_monday_str': '2027-05-24'}"

        The date you pass is treated as the start of the week window, and the
        function walks FORWARD to Saturday.  Days before TODAY are always skipped.
        The week_start (Monday) is NOT explicitly calculated — the loop begins
        at the date you provided and walks forward to Saturday.

    NOTE on week boundaries:
      - Weekday numbers: Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
      - (5 - weekday) % 7  gives: Mon→4, Tue→3, Wed→2, Thu→1, Fri→0, Sat→6
        This means Saturday rolls over oddly — the calculation produces Sunday
        as the end date for Saturday inputs.  This is existing behaviour.
      - Days BEFORE today are ALWAYS skipped (line "if current_date < today: continue").
    ============================================================================
    """
    try:
        week_monday = getdate(week_monday_str) if week_monday_str else getdate(today())

        # ── Calculate the Saturday (end) of the week ──────────────────────────
        # weekday(): Monday=0 … Saturday=5, Sunday=6
        # (5 - weekday) % 7  yields days until Saturday:
        #   Mon(0)→4, Tue(1)→3, Wed(2)→2, Thu(3)→1, Fri(4)→0, Sat(5)→6
        days_until_saturday = (5 - week_monday.weekday()) % 7
        week_saturday = add_days(week_monday, days_until_saturday)

        submitted = []
        skipped_no_draft = []
        skipped_no_status = []
        failed = []
        day_date = week_monday

        # ── Walk each day from Monday → Saturday ──────────────────────────────
        while day_date <= week_saturday:
            # Never submit a day in the past
            if day_date < getdate(today()):
                day_date = add_days(day_date, 1)
                continue

            # Find the draft Daily Production for this date
            dp_name = frappe.db.get_value("Daily Production",
                {"required_by": str(day_date), "docstatus": 0}, "name")

            if not dp_name:
                skipped_no_draft.append(str(day_date))
            else:
                # Check that at least one row has a produ_status
                has_status = frappe.db.sql(
                    """SELECT 1 FROM `tabCreate ProExl Items`
                       WHERE parent = %s AND produ_status IS NOT NULL AND produ_status != ''
                       LIMIT 1""",
                    (dp_name,)
                )

                if not has_status:
                    skipped_no_status.append(dp_name)
                else:
                    try:
                        doc = frappe.get_doc("Daily Production", dp_name)
                        doc.submit()
                        submitted.append(dp_name)
                    except Exception as e:
                        frappe.log_error(frappe.get_traceback(), f"submit_dp_week failed for {dp_name}")
                        failed.append({"name": dp_name, "error": frappe.utils.cstr(e)})

            day_date = add_days(day_date, 1)

        # ── Commit before rendering (respond_as_web_page bypasses auto-commit) ──
        frappe.db.commit()

        # ── Build HTML report ─────────────────────────────────────────────────
        failed_html = ""
        if failed:
            failed_html = "<h3 style='color:red'>❌ Failed (fix and retry manually):</h3><ul>" + "".join(
                f"<li><b>{f['name']}</b>: {f['error']}</li>" for f in failed
            ) + "</ul>"

        no_status_html = ""
        if skipped_no_status:
            no_status_html = "<h3>Skipped — No Status Set:</h3><ul>" + "".join(
                f"<li>{dp}</li>" for dp in skipped_no_status
            ) + "</ul>"

        has_errors = bool(failed)
        body = f"<h2>Done</h2><p>Submitted: {len(submitted)} | Skipped (no draft): {len(skipped_no_draft)} | Skipped (no status): {len(skipped_no_status)} | Failed: {len(failed)}</p>{no_status_html}{failed_html}"
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "submit_dp_week failed")
        frappe.respond_as_web_page("Error", f"<h2>Error</h2><p>{frappe.utils.cstr(e)}</p>")
        return

    # ── Render the results page ────────────────────────────────────────────────
    # Auto-close only if no failures (let the user read errors otherwise)
    auto_close_js = """
    setTimeout(function() {
        window.open('', '_self', '');
        window.close();
    }, 3000);
""" if not has_errors else ""

    frappe.respond_as_web_page("Done", body + f"""<script>
    var now = new Date();
    var expires = new Date(now.getTime() + 30 * 1000);
    document.cookie = "trigger_metabase_refresh=1; path=/; expires=" + expires.toUTCString() + ";";
    {auto_close_js}
</script>""")

@frappe.whitelist(allow_guest=True)
def submit_dp_week_by_number(week_number):
    """
    Convenience wrapper around submit_dp_week.

    Instead of passing a date string, you pass an ISO week number and this
    function converts it to the Monday of that week before calling submit_dp_week.

    EXAMPLE
    ───────
    Submit week 14 of the current year:
        bench --site development.localhost execute \
            "caf.caf.doctype.daily_production.daily_production.submit_dp_week_by_number" \
            --kwargs "{'week_number': 14}"

    ALGORITHM
    ─────────
    1. Take ISO week_number (e.g. 14)
    2. Find January 4th of the current year (always in ISO week 1)
    3. Walk back to the Monday of that week
    4. Add (week_number - 1) * 7 days to get to the Monday of the requested week
    5. Call submit_dp_week(week_monday_str=that_monday)
    """
    try:
        
        year = datetime.date.today().year
        week_number = int(week_number)
        jan4 = datetime.date(year, 1, 4)
        start = jan4 - datetime.timedelta(days=jan4.isocalendar()[2] - 1)
        monday = start + datetime.timedelta(weeks=week_number - 1)
        return submit_dp_week(week_monday_str=str(monday))
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "submit_dp_week_by_number failed")
        frappe.respond_as_web_page("Error", f"<h2>Error</h2><p>{frappe.utils.cstr(e)}</p>")

@frappe.whitelist()
def add_extra_round(docname, workstation, total_rounds):
    """Add all extra round rows between default_rounds+1 and total_rounds
    for the given workstation, inserting each in the correct grouped position."""

    total_rounds = int(total_rounds)
    dp = frappe.get_doc("Daily Production", docname)
    template = frappe.get_doc(TEMPLATE_DOCTYPE, _get_template_name())
    default_rounds = template.default_rounds or 3
    max_rounds = template.max_rounds or 99

    if total_rounds <= default_rounds:
        frappe.throw(_("Total rounds ({0}) must be greater than default rounds ({1}).")
                     .format(total_rounds, default_rounds))

    if total_rounds > max_rounds:
        frappe.throw(_("Total rounds cannot exceed {0}.").format(max_rounds))

    # Build set of existing (workstation, round) pairs
    existing = set()
    for row in dp.get("production_table"):
        ws = str(row.recipe_cook_workstaion or "")
        rnd = int(row.recipe_cook_round or 0)
        existing.add((ws, rnd))

    # Determine group prefix
    m = re.match(r"^(\D+)", workstation)
    group_prefix = m.group(1).strip() if m else workstation

    # Find insert position: after the last row of the same group
    rows = dp.get("production_table")
    insert_idx = len(rows)
    for i in range(len(rows) - 1, -1, -1):
        row_ws = str(rows[i].recipe_cook_workstaion or "")
        row_m = re.match(r"^(\D+)", row_ws)
        row_prefix = row_m.group(1).strip() if row_m else row_ws
        if row_prefix == group_prefix:
            insert_idx = i + 1
            break

    # Add each missing round from default_rounds+1 to total_rounds
    added = []
    for rnd in range(default_rounds + 1, total_rounds + 1):
        if (workstation, rnd) in existing:
            continue
        row = dp.append("production_table", {
            "recipe_cook_workstaion": workstation,
            "recipe_cook_round": rnd,
            "recipe_name": NO_COOKING,
            "size": 0,
        })
        dp.get("production_table").remove(row)
        dp.get("production_table").insert(insert_idx, row)
        insert_idx += 1  # next row goes after this one
        added.append(rnd)

    if not added:
        frappe.throw(_("All rounds {0} to {1} for {2} already exist.")
                     .format(default_rounds + 1, total_rounds, workstation))

    # Re-index all rows
    for i, r in enumerate(dp.get("production_table"), 1):
        r.idx = i

    dp.save(ignore_permissions=True)

    # Log the change
    frappe.get_doc({
        "doctype": "Schedule Change Log",
        "change_datetime": frappe.utils.now_datetime(),
        "changed_by": frappe.session.user,
        "action_type": "Edit",
        "day": str(dp.required_by),
        "dp_name": dp.name,
        "workstation": workstation,
        "summary": _("Added rounds {0} for {1}").format(", ".join(str(r) for r in added), workstation),
        "changes_json": frappe.as_json({"added_rounds": added, "total_rounds": total_rounds}),
    }).insert(ignore_permissions=True)

    return {"workstation": workstation, "added_rounds": added}


@frappe.whitelist()
def get_machine_table_workstations(doctype, txt, searchfield, start, page_len, filters):
    """Return workstations from the default template's Machine Table for dropdown filtering."""
    template_name = _get_template_name()
    raw = frappe.db.sql("""
        SELECT DISTINCT mc.workstation
        FROM `tabMachine Table` mc
        WHERE mc.parent = %s
          AND mc.workstation LIKE %s
        ORDER BY mc.workstation
        LIMIT %s OFFSET %s
    """, (template_name, f"%{txt}%", page_len, start))
    return raw


@frappe.whitelist()
def get_template_round_config():
    """Return default_rounds and max_rounds from the default template."""
    template = frappe.get_doc(TEMPLATE_DOCTYPE, _get_template_name())
    return {
        "default_rounds": template.default_rounds or 3,
        "max_rounds": template.max_rounds or 99,
    }


@frappe.whitelist()
def submit_dp(docname):
    """Submit a Daily Production — sets workflow_state to 'Submitted', docstatus stays 0."""
    dp = frappe.get_doc("Daily Production", docname)

    if dp.docstatus != 0:
        frappe.throw(_("Only draft documents can be submitted."))

    if dp.workflow_state == "Submitted":
        frappe.throw(_("Daily Production is already submitted."))

    if all(d.recipe_name == NO_COOKING and not d.produ_status for d in dp.production_table):
        frappe.throw(_("All rows have recipe <strong>No Cooking</strong> — not allowed"))

    for row in dp.production_table:
        if not row.link_id:
            row.link_id = make_autoname("R-.YYYY.-.#####")

    dp.workflow_state = "Submitted"
    dp.save(ignore_permissions=True)
    return {"success": True}