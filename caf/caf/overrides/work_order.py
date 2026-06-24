import math
import pdb
from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
import frappe
from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder
from frappe.utils import flt
from caf.caf.overrides.stock_entry import CustomStockEntry
from frappe import _
import requests
from frappe.utils import add_days, today, getdate

class CustomWorkOrder(WorkOrder):

    def set_required_items(self, reset_only_qty=False):
        # Step 1: Backup RECIPE qtys
        recipe_qty_backup = {}

        if reset_only_qty:
            for d in self.get("required_items"):
                if d.item_code and d.item_code.upper().startswith("RECIPE"):
                    recipe_qty_backup[d.item_code] = d.required_qty
        # frappe.msgprint("qty changed ")
        """set required_items for production to keep track of reserved qty"""
        if not reset_only_qty:
            self.required_items = []

        operation = None
        if self.get("operations") and len(self.operations) == 1:
            operation = self.operations[0].operation

        if self.bom_no and self.qty:
            item_dict = get_bom_items_as_dict(
                self.bom_no, self.company, qty=self.qty, fetch_exploded=self.use_multi_level_bom
            )

            if reset_only_qty:
                for d in self.get("required_items"):
                    if item_dict.get(d.item_code) :
                        d.required_qty = item_dict.get(d.item_code).get("qty")

                    if not d.operation:
                        d.operation = operation
            else:
                for item in sorted(item_dict.values(), key=lambda d: d["idx"] or float("inf")):
                    self.append(
                        "required_items",
                        {
                            "rate": item.rate,
                            "amount": item.rate * item.qty,
                            "operation": item.operation or operation,
                            "item_code": item.item_code,
                            "item_name": item.item_name,
                            "description": item.description,
                            "allow_alternative_item": item.allow_alternative_item,
                            "required_qty": item.qty,
                            "source_warehouse": item.source_warehouse or item.default_warehouse,
                            "include_item_in_manufacturing": item.include_item_in_manufacturing,
                        },
                    )

                    if not self.project:
                        self.project = item.get("project")

            self.set_available_qty()
        # Step 3: Restore RECIPE items' original qty
        if reset_only_qty and self.custom_item_type == "Pack":
            try:
                for d in self.get("required_items"):
                    if d.item_code in recipe_qty_backup:
                        d.required_qty = recipe_qty_backup[d.item_code]
            except ValueError:
                frappe.throw("Error")

    def validate(self):
        super().validate()
        for row in self.operations:
            if not row.workstation:
                frappe.throw(
                    _("Row #{0}: Workstation is required for operation {1}").format(
                        row.idx, row.operation
                    )
                )

    def before_submit(self):
        super().before_submit()
        # pdb.set_trace()
        # self.check_raw_mat_in_items_table()
    def on_cancel(self):
        return super().on_cancel()
        frappe.db.set_value("")

    def check_raw_mat_in_items_table(self):
        if self.custom_item_type in ["Cook", "WIP"]:
            print(f"item type{self.custom_item_type}")
            for mat in self.get("required_items"):
                print(f"mat.custom_rawmat_check{mat.custom_rawmat_check}")

        # i added this part to fast run the test then i will remov it 
                mat.custom_rawmat_check  = 1
                mat.custom_rawmat_in  = 1

                if mat.custom_rawmat_check != 1 or mat.custom_rawmat_in != 1:
                    frappe.throw(f"⚠️ <b>Error:</b> Item <b>{mat.item_name}</b> did not check Raw Mat or put in Machine.")

    def set_int_qty(self):
        if self.custom_item_type == "Pack":
            self.qty = math.floor(self.qty)
        self.set_required_items(reset_only_qty=len(self.get("required_items")))

    def before_save(self):
        self.validate_work_order()
        # frappe.msgprint("this msg from CAF app")
    def on_submit(self):
        super().on_submit()
        self.create_qi_reviw()

        if self.production_item.startswith("TIM"):
            automate_start_finish(self.name, total_balance=0, total_pack_qty = self.qty or 0)
            frappe.msgprint(title="TIM Automation", msg="For \"TIM\" Automate Start and Finish process completed." )

    def on_cancel(self):
        super().on_cancel()
        self.delete_linked_quality_reviews()

    def before_trash(self):
        super().before_trash()
        self.delete_linked_quality_reviews()

    def delete_linked_quality_reviews(self):
        try:
            reviews = frappe.get_all(
                "Quality Review",
                filters={"custom_work_order": self.name},
                fields=["name", "docstatus"]
            )

            if not reviews:
                return

            count = 0

            for review in reviews:
                doc = frappe.get_doc("Quality Review", review.name)

                # Step 1: Cancel if submitted
                if doc.docstatus == 1:
                    doc.cancel()

                # Step 2: Clear the link
                doc.db_set("custom_work_order", "")

                count += 1

            frappe.msgprint(
                f"Unlinked {count} Quality Review(s) from this Work Order.",
                alert=True
            )

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "Error unlinking Quality Reviews"
            )
            frappe.msgprint(
                "Could not unlink Quality Reviews. Check Error Log."
            )

    def create_qi_reviw(self):
            try:
                # 1. Retrieve all Job Cards for the current Work Order
                jblist = frappe.get_all(
                    "Job Card", 
                    filters={"work_order": self.name}, 
                    fields=["name", "workstation_type"]
                )
                
                # Use a set to keep track of goals we've already handled in this loop 
                # (to avoid duplicate checks if multiple job cards have the same workstation type)
                processed_goals = set()

                for jb in jblist:
                    if not jb.get("workstation_type"):
                        continue

                    # 2. Determine the Quality Goal Name
                    goal_name = frappe.db.get_value("Quality Goal", {"custom_workstation_type": jb.get("workstation_type")})

                    if goal_name and goal_name not in processed_goals:
                        # ── CHECK IF REVIEW ALREADY EXISTS ──
                        # Check if a Quality Review is already linked to this Work Order AND this Goal
                        if frappe.db.exists("Quality Review", {
                            "custom_work_order": self.name, 
                            "goal": goal_name,
                            "docstatus": ["<", 2] # Ignore cancelled ones
                        }):
                            # Skip if it already exists
                            processed_goals.add(goal_name)
                            continue

                        # 3. Fetch the FULL Quality Goal document
                        goal_doc = frappe.get_doc("Quality Goal", goal_name)

                        # 4. Create the new Review
                        qi_review = frappe.new_doc("Quality Review")
                        qi_review.goal = goal_name
                        qi_review.status = "Open"
                        qi_review.custom_work_order = self.name
                        
                        # 5. Populate the child table (objectives/items)
                        source_table = goal_doc.get("objectives") or goal_doc.get("items") 
                        
                        if source_table:
                            for item in source_table:
                                new_row = qi_review.append("reviews", {})
                                new_row.objective = item.objective 
                                new_row.target = item.target
                                new_row.status = "Open"
                        
                        # 6. Save the document
                        qi_review.insert(ignore_permissions=True)
                        processed_goals.add(goal_name)
                        
                        frappe.msgprint(_("✅ Quality Review created for Goal: <b>{0}</b>.").format(goal_name), alert=True)

            except Exception as e:
                frappe.log_error(message=frappe.get_traceback(), title="Error creating Quality Review")
                frappe.throw(_("Error creating Quality Review: {0}").format(str(e)))

    def validate_work_order(self):
        if self.production_plan and not self.material_request:
            # Retrieve the 'material_requests' child table entries
            material_requests = frappe.get_all(
                "Material Request",
                filters={"production_plan": self.production_plan},
                fields=["custom_link_id"],
                limit=1
            )

            if material_requests:
                self.custom_link_id = material_requests[0].get("custom_link_id")
                if not self.custom_link_id:
                    frappe.msgprint(
                        f"Production Plan [{self.production_plan}] does not have a Link ID.",
                        alert=True
                    )
            else:
                frappe.msgprint(
                    f"No Material Requests found for Production Plan [{self.production_plan}].",
                    alert=True
                )
    @frappe.whitelist()
    def get_item_group_for_ig(self):
        item_group = frappe.get_value("Item", self.production_item, "item_group")
        if item_group == "WIP TIM":
            return 1
        else:
            return 0
    @frappe.whitelist()
    def get_pack_qty(self):
        try:
            if self.material_transferred_for_manufacturing and self.custom_item_type == "Cook" and self.custom_link_id and self.custom_operation_type == "Recook":
                link_id = self.custom_link_id

                print("get_pack_qty is start")

                # Fetch all relevant work orders
                work_orders = frappe.get_all(
                    "Work Order",
                    filters={
                        "custom_link_id": link_id,
                        "status": ["not in", ["Cancelled", "Closed"]],
                        "custom_item_type": "Pack"
                    },
                    fields=["production_item", "qty"]
                )

                if not work_orders:
                    frappe.msgprint("No Pack-type Work Orders found.")
                    return 0

                # Get unique production items
                production_items = list(set([wo["production_item"] for wo in work_orders]))

                # Fetch weight_per_unit for all production items
                item_weights = frappe.get_all(
                    "Item",
                    filters={"name": ["in", production_items]},
                    fields=["name", "weight_per_unit"]
                )
                weight_map = {item["name"]: item.get("weight_per_unit", 0) or 0 for item in item_weights}

                total_weight = 0
                for wo in work_orders:
                    production_item = wo["production_item"]
                    qty = wo["qty"]
                    weight_per_unit = weight_map.get(production_item, 0)

                    if weight_per_unit == 0:
                        frappe.msgprint(f"Warning: Item '{production_item}' does not have a weight_per_unit.")

                    total_weight += weight_per_unit * qty
                    print(production_item)

                total_weight = round(total_weight, 9)
                print(f"Total Pack Qty: {total_weight}")

                # self.fg_completed_qty = total_weight

                return total_weight

            else:
                return 0

        except frappe.DoesNotExistError:
            frappe.msgprint("Error: Work Order not found.")
            return 0

        except Exception as e:
            frappe.msgprint(f"An error occurred: {str(e)}")
            return 0

@frappe.whitelist()
def make_stock_entry(
    work_order_id, purpose, qty=None, total_balance=0, total_pack_qty=0, warehouse=None, finish_mark=0
):
    work_order = frappe.get_doc("Work Order", work_order_id)
    total_balance = flt(total_balance)
    total_pack_qty = flt(total_pack_qty)
    finish_mark = int(finish_mark)

    wip_warehouse = (
        work_order.wip_warehouse
        if not frappe.db.get_value("Warehouse", work_order.wip_warehouse, "is_group")
        else None
    )

    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.purpose = purpose
    stock_entry.work_order = work_order_id
    stock_entry.company = work_order.company
    stock_entry.from_bom = 1
    stock_entry.bom_no = work_order.bom_no
    stock_entry.use_multi_level_bom = work_order.use_multi_level_bom
    stock_entry.custom_item_type = work_order.custom_item_type

    if work_order.custom_link_id:
        stock_entry.custom_link_id = work_order.custom_link_id
    if work_order.production_item == "CHIC C":
        stock_entry.custom_batch_to_use = work_order.custom_batch_no_

    # ✅ Resolve FINAL fg_completed_qty BEFORE get_items()
    # pdb.set_trace()
    if total_pack_qty and (total_pack_qty < flt(work_order.qty) and finish_mark == 0):
        resolved_qty = total_pack_qty
    elif total_pack_qty and (total_pack_qty < flt(work_order.qty) and finish_mark == 1):
        resolved_qty = total_pack_qty
    elif total_pack_qty >= flt(work_order.qty) - flt(work_order.produced_qty):
        resolved_qty = total_pack_qty
    elif qty is not None:
        resolved_qty = flt(qty)
    else:
        resolved_qty = flt(work_order.qty) - flt(work_order.produced_qty)

    stock_entry.fg_completed_qty = resolved_qty

    if work_order.bom_no:
        stock_entry.inspection_required = frappe.db.get_value(
            "BOM", work_order.bom_no, "inspection_required"
        )

    if purpose == "Material Transfer for Manufacture":
        stock_entry.to_warehouse = wip_warehouse
    else:
        stock_entry.from_warehouse = wip_warehouse
        stock_entry.to_warehouse = work_order.fg_warehouse

    stock_entry.set_stock_entry_type()
    stock_entry.get_items()  # ✅ Now uses correct qty from the start

    # ✅ Post-process items
    scrap_target_warehouse = frappe.db.get_single_value("Manufacturing Settings", "default_scrap_warehouse") or "Prod Balance - CAF"

    for item in stock_entry.items[:]:
        if item.is_scrap_item:
            if total_balance == 0:
                stock_entry.items.remove(item)
                frappe.msgprint(frappe._("Balance Item removed due to 0 balance"), alert=True)
            # elif total_balance > flt(work_order.qty) - flt(work_order.produced_qty) - flt(total_pack_qty):
            #     frappe.throw(frappe._("Balance Item is greater than the total quantity to produce"))
            else:
                item.qty = total_balance
                item.custom_table_link_id = work_order.custom_link_id
                item.t_warehouse = warehouse or (
                    scrap_target_warehouse
                    if frappe.db.exists("Warehouse", {"name": scrap_target_warehouse, "is_group": 0})
                    else item.s_warehouse
                )
        if item.item_code == work_order.production_item and item.is_finished_item == 1:
            if total_pack_qty != 0:
                item.qty = total_pack_qty

    if purpose != "Disassemble":
        stock_entry.set_serial_no_batch_for_finished_good()

    CustomStockEntry.set_qi_items(stock_entry)

    return stock_entry.as_dict()

def stock_entry_exists(work_order_id, purpose):
    """Checks if a submitted stock entry for a given purpose already exists."""
    return frappe.db.exists(
        "Stock Entry",
        {
            "work_order": work_order_id,
            "purpose": purpose,
            "docstatus": 1,  # 1 means Submitted
        },
    )
   
@frappe.whitelist()
def automate_start_finish(work_order_name, total_balance=0, total_pack_qty=0):
    """Auto-start and auto-finish a Work Order by creating the required Stock Entries."""
    print(f"📢 Starting automation for: {work_order_name}")

    try:
        work_order = frappe.get_doc("Work Order", work_order_name)

        # --- STEP 1: START / Material Transfer ---
        if work_order.status in ["Not Started", "Pending"]:
            if not frappe.db.exists(
                "Stock Entry",
                {"work_order": work_order.name, "purpose": "Material Transfer for Manufacture", "docstatus": 1}
            ):
                transfer_entry = frappe.get_doc(make_stock_entry(
                    work_order_id=work_order.name,
                    purpose="Material Transfer for Manufacture",
                    total_balance=total_balance,
                    total_pack_qty=total_pack_qty
                ))
                transfer_entry.insert(ignore_permissions=True)
                transfer_entry.submit()

                # ✅ Show success message directly from Python
                frappe.msgprint(
                    msg="✅ Material Transfer Stock Entry created.",
                    title="Automation Step 1 Complete",
                    indicator="green"
                )

                frappe.db.set_value("Work Order", work_order.name, "status", "In Process")
                frappe.db.commit()
                work_order.reload()

        # --- STEP 2: FINISH / Manufacture ---
        if not frappe.db.exists(
            "Stock Entry",
            {"work_order": work_order.name, "purpose": "Manufacture", "docstatus": 1}
        ):
            manufacture_entry = frappe.get_doc(make_stock_entry(
                work_order_id=work_order.name,
                purpose="Manufacture",
                total_balance=total_balance,
                total_pack_qty=total_pack_qty
            ))
            manufacture_entry.insert(ignore_permissions=True)
            manufacture_entry.submit()

            frappe.msgprint(
                msg="✅ Manufacture Stock Entry created.",
                title="Automation Step 2 Complete",
                indicator="green"
            )

            frappe.db.set_value("Work Order", work_order.name, "status", "Completed")
            frappe.db.commit()

        else:
            frappe.msgprint(
                msg="ℹ️ No new Stock Entries were needed. Process already complete.",
                title="Automation Info",
                indicator="blue"
            )

    # --- ERROR HANDLING ---
    except frappe.ValidationError as e:
        frappe.log_error(frappe.get_traceback(), f"Validation Failed for WO {work_order_name}")
        frappe.throw(
            title="Validation Error",
            msg=f"<b>Could not create the Stock Entry.</b><br><br>Reason: {e}"
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Unexpected Error for WO {work_order_name}")
        frappe.throw(
            title="System Error",
            msg=f"An unexpected error occurred while processing {work_order_name}. Please check the Error Log."
        )

@frappe.whitelist()
def check_for_job_cards(work_order_name):
    """
    Checks if any Job Card documents exist for a given Work Order.
    Returns True if Job Cards exist, False otherwise.
    """
    if not work_order_name:
        return False

    # frappe.db.exists() is the most efficient way to check for the existence of records.
    # It stops searching as soon as it finds one match.
    has_job_cards = frappe.db.exists("Job Card", {
        "work_order": work_order_name
    })
    print(f"has_job_cards: {has_job_cards}")
    if has_job_cards:

        return has_job_cards
    else:
        return False



@frappe.whitelist()
def fetch_bom_custom_procedures(bom_no):
    """Fetch the custom_procedure child table from a BOM."""
    if not bom_no:
        frappe.throw("BOM is required.")

    # Load the BOM document
    bom = frappe.get_doc("BOM", bom_no)

    # Return the child table data
    # return [{
    #     "procedure": row.procedure,
    #     # "description": row.description,
    #     # "sequence": row.sequence
    #     # Add more fields if your table has them
    # } for row in bom.custom_procedure]



@frappe.whitelist()
def create_weight_record(work_order):
    """Safely create Weight Record from Work Order"""
    try:
        # Ensure Work Order exists
        wo = frappe.get_doc("Work Order", work_order)

        # Check if Weight Record already exists
        existing = frappe.db.exists("Weight Record", {"custom_work_order": wo.name})
        if existing:
            return {"name": existing}

        # Create new Weight Record
        wr = frappe.new_doc("Weight Record")
        wr.custom_work_order = wo.name
        wr.item = wo.production_item
        wr.status = "Draft"  # Add required fields if any
        wr.posting_date = frappe.utils.nowdate()

        wr.insert(ignore_permissions=True)
        frappe.db.commit()
        wr.reload()

        return {"name": wr.name}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Weight Record Creation Failed")
        frappe.throw(f"Failed to create Weight Record: {str(e)}")



@frappe.whitelist()
def update_next_rawmat(work_order):
    wo = frappe.get_doc("Work Order", work_order)

    updated = False

    for row in wo.required_items:
        if not row.custom_rawmat_check:
            row.custom_rawmat_check = 1
            updated = True
            break

    if not updated:
        frappe.throw("All raw material items are already checked")

    # يسمح بالتحديث بعد Submit
    wo.flags.ignore_validate_update_after_submit = True
    wo.save(ignore_permissions=True)

    return True


@frappe.whitelist()
def update_next_rawmat_in(work_order):
    # 1. Fetch the Work Order document
    wo = frappe.get_doc("Work Order", work_order)

    # 2. CRITICAL VALIDATION: Check for submitted Material Receipt for Manufacturing (MRFM) Stock Entry
    # The Stock Entry should reference this Work Order and be Submitted (docstatus = 1)
    mr_entry_exists = frappe.db.exists(
        "Stock Entry",
        {
            "work_order": wo.name,
            "purpose": "Material Receipt for Manufacturing",
            "docstatus": 1
        }
    )
    
    # If no submitted MRFM Stock Entry is found, raise an error
    if not mr_entry_exists:
        frappe.throw(
            _("Please create and submit a Material Receipt for Manufacturing (MRFM) Stock Entry linked to Work Order {0} first.").format(wo.name)
        )

    # 3. Proceed with updating the custom field
    updated = False
    for row in wo.required_items:
        # Check if row.custom_rawmat_in is falsy (None, 0, or empty)
        if not row.custom_rawmat_in:
            row.custom_rawmat_in = 1
            updated = True
            break

    # 4. Handle case where all materials are already checked
    if not updated:
        frappe.throw(_("All raw material items are already checked."))

    # 5. Save the Work Order
    # Allows the update after the Work Order has been submitted (docstatus = 1)
    wo.flags.ignore_validate_update_after_submit = True
    wo.save(ignore_permissions=True)

    return True


    import frappe
from frappe import _
from frappe.utils import flt, nowdate, cint


@frappe.whitelist()
def get_item_warehouse_qty(item_code, warehouse):
    """Returns total available qty for an item in a given warehouse."""
    from erpnext.stock.utils import get_stock_balance
    try:
        qty = get_stock_balance(item_code, warehouse)
        return flt(qty)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "get_item_warehouse_qty Failed")
        return 0.0


@frappe.whitelist()
def create_recook_stock_entry_backend(work_order_name, qty, source_warehouse, auto_submit=1):
    try:
        # 1. Validate Work Order
        if not frappe.db.exists("Work Order", work_order_name):
            return {"success": False, "message": _("Work Order {0} not found.").format(work_order_name)}

        wo = frappe.get_doc("Work Order", work_order_name)

        # 2. NEW CHECK: Check if a Draft 'Manufacture' (FG Receipt) entry exists
        # Users often create the Manufacture entry but don't submit it. 
        # This prevents stock inconsistencies if they Recook while a receipt is pending.
        draft_manufacture = frappe.db.get_value("Stock Entry", {
            "work_order": work_order_name,
            "purpose": "Manufacture",
            "docstatus": 0
        }, "name")

        if draft_manufacture:
            return {
                "success": False,
                "message": _(
                    "❌ A draft <b>Manufacture</b> entry (<b>{0}</b>) already exists for this Work Order. "
                    "Please delete or submit it before creating a Recook."
                ).format(draft_manufacture)
            }

        # 3. Must have at least one submitted Material Transfer (Standard Raw Materials)
        if not frappe.db.exists("Stock Entry", {
            "work_order": work_order_name,
            "stock_entry_type": "Material Transfer for Manufacture",
            "docstatus": 1
        }):
            return {
                "success": False,
                "message": _("❌ This Work Order must have at least one submitted 'Material Transfer' before creating a Recook.")
            }

        # 4. Check if a Recook already exists (Draft or Submitted)
        existing_entries = frappe.get_all("Stock Entry", 
            filters={
                "work_order": work_order_name, 
                "stock_entry_type": "Material Transfer for Manufacture", 
                "docstatus": ["!=", 2]
            }, 
            fields=["name"]
        )

        for entry in existing_entries:
            se_items = frappe.get_all("Stock Entry Detail", 
                filters={"parent": entry.name}, 
                fields=["item_code"]
            )
            
            # Recook definition: Exactly 1 item row and that item matches the Production Item
            if len(se_items) == 1 and se_items[0].item_code == wo.production_item:
                return {
                    "success": False,
                    "message": _("❌ Recook already exists for this Work Order (See {0}).").format(entry.name)
                }
                
        if flt(qty) <= 0:
            return {"success": False, "message": _("Quantity must be greater than zero.")}

        # 5. Build Stock Entry
        item_uom = wo.get("stock_uom") or frappe.db.get_value("Item", wo.production_item, "stock_uom")

        se = frappe.new_doc("Stock Entry")
        se.stock_entry_type = "Material Transfer for Manufacture"
        se.work_order = work_order_name
        se.company = wo.company
        se.posting_date = nowdate()
        se.from_bom = 0

        se.append("items", {
            "item_code": wo.production_item,
            "qty": flt(qty),
            "uom": item_uom,
            "stock_uom": item_uom,
            "conversion_factor": 1,
            "s_warehouse": source_warehouse,
            "t_warehouse": wo.wip_warehouse,
        })

        se.insert(ignore_permissions=True)
        se_name = se.name

        # 6. Submit or return draft
        if cint(auto_submit):
            try:
                se.submit()
                return {
                    "success": True,
                    "se_name": se_name,
                    "submitted": True,
                    "message": _("✅ Stock Entry <b>{0}</b> submitted successfully.").format(se_name)
                }
            except Exception as submit_err:
                frappe.log_error(frappe.get_traceback(), "Recook SE Submission Failed")
                
                # Rollback/Cleanup
                current_docstatus = frappe.db.get_value("Stock Entry", se_name, "docstatus")
                try:
                    if current_docstatus == 1:
                        cancel_doc = frappe.get_doc("Stock Entry", se_name)
                        cancel_doc.cancel()
                    frappe.delete_doc("Stock Entry", se_name, ignore_permissions=True, force=True)
                except Exception as cleanup_err:
                    frappe.log_error(frappe.get_traceback(), "Recook SE Cleanup Failed")
                    return {
                        "success": False,
                        "message": _("❌ Submission failed and cleanup also failed for {0}.").format(se_name)
                    }

                return {
                    "success": False,
                    "message": _("❌ Submission failed. Stock Entry <b>{0}</b> was rolled back. <br> Error: {1}").format(se_name, str(submit_err))
                }
        else:
            return {
                "success": True,
                "se_name": se_name,
                "submitted": False,
                "message": _("📄 Stock Entry <b>{0}</b> created as Draft.").format(se_name)
            }

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Recook SE Creation Failed")
        return {"success": False, "message": _("Unexpected Error: {0}").format(str(e))}




@frappe.whitelist()
def update_workstation(work_order_name, changes):
    """
    Update workstation on:
      1. Work Order > Operations child table rows
      2. All linked Job Cards for each affected operation row
      3. Insert a Workstation Change Log entry per change

    Args:
        work_order_name (str): Name of the Work Order
        changes (list[dict]): Each dict has keys:
            - row_name        (str) child row name in tabWork Order Operation
            - operation       (str) operation name (label only, for logging)
            - old_workstation (str)
            - new_workstation (str)
    """
    import json

    if isinstance(changes, str):
        changes = json.loads(changes)

    if not changes:
        return {"success": False, "message": _("No changes provided.")}

    wo = frappe.get_doc("Work Order", work_order_name)
    updated_ops = 0
    updated_jcs = 0

    for change in changes:
        row_name    = change.get("row_name")
        operation   = change.get("operation", "")
        old_ws      = change.get("old_workstation", "")
        new_ws      = change.get("new_workstation", "")

        if not new_ws:
            continue

        # ── 1. Update the Operations child row ──────────────────────
        for op_row in wo.operations:
            if op_row.name == row_name:
                op_row.workstation = new_ws
                updated_ops += 1
                break

        # ── 2. Update linked Job Cards ───────────────────────────────
        job_cards = frappe.get_all(
            "Job Card",
            filters={
                "work_order": work_order_name,
                "operation":  operation,
                "docstatus":  ["!=", 2]          # exclude cancelled
            },
            fields=["name", "workstation"]
        )

        for jc in job_cards:
            frappe.db.set_value("Job Card", jc["name"], "workstation", new_ws)
            updated_jcs += 1

        # ── 3. Insert Workstation Change Log ─────────────────────────
        log = frappe.get_doc({
            "doctype":        "Log Change Workstation",
            "work_order":     work_order_name,
            "operation":      operation,
            "old_workstation": old_ws,
            "new_workstation": new_ws,
            "changed_by":     frappe.session.user,
            "change_date":    frappe.utils.now()
        })
        log.insert(ignore_permissions=True)

    # ── Save the Work Order (persists child-table changes) ───────────
    wo.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success":  True,
        "message":  _(
            "Workstation updated: {0} operation(s), {1} job card(s)."
        ).format(updated_ops, updated_jcs)
    }


def send_work_order_daly_report():
    report_date = add_days(today(), -1)

    # 1. Fetch data - Ensure field name is 'custom_item_type'
    work_orders = frappe.get_all("Work Order",
        filters={
            "creation": ["between", [f"{report_date} 00:00:00", f"{report_date} 23:59:59"]]
        },
        fields=["name", "status", "custom_item_type"]
    )

    if not work_orders:
        return

    # 2. Initialize with CORRECT spelling (WIP, not WOP / Pending, not Panding)
    report_data = {
        "WIP":  {"Completed": 0, "Pending": 0},
        "Pack": {"Completed": 0, "Pending": 0},
        "Cook": {"Completed": 0, "Pending": 0},
    } 

    for wo in work_orders:
        # Use .get to safely handle the field name
        tipe = wo.get("custom_item_type") or "Other"
        
        # If a new type appears (like 'Other'), initialize it
        if tipe not in report_data:
            report_data[tipe] = {"Completed": 0, "Pending": 0}
            
        # Count based on status
        if wo.status == "Completed":
            report_data[tipe]["Completed"] += 1
        else:
            report_data[tipe]["Pending"] += 1

    # 3. Format Message
    message = f"📊 *Daily Work Order Report*\n"
    message += f"📅 Date: {report_date}\n"
    message += "--------------------------\n\n"

    for tipe, counts in report_data.items():
        total = counts["Completed"] + counts["Pending"]
        if total > 0:
            message += f"*{tipe} Summary:*\n"
            message += f"✅ Completed: {counts['Completed']}\n"
            message += f"⏳ Not Finished: {counts['Pending']}\n"
            message += f"📈 Total: {total}\n\n"

    send_to_telegram(message)

def send_to_telegram(msg):
    # Fix: Ensure these keys exist in your site_config.json
    token = frappe.conf.get("telegram_bot_token")
    chat_id = frappe.conf.get("telegram_chat_id")
    
    if not token or not chat_id:
        frappe.log_error("Telegram token or chat_id missing in site_config.json", "Telegram Report Error")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        response = requests.post(url, data={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown" # Fix: changed "parse_made" to "parse_mode"
        })
        if response.status_code != 200:
            frappe.log_error(response.text, "Telegram Report Error")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Telegram Connection Error")