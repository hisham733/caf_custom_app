import json
from erpnext.manufacturing.doctype import production_plan
from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan
from erpnext.setup.doctype.item_group import item_group
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import cint
from erpnext.stock.doctype.warehouse.warehouse import ExistsCriterion
import frappe
# from frappe.apps import _
from frappe import _, msgprint
from frappe.monitor import datetime
from frappe.query_builder.terms import timedelta
import pytz
from frappe.utils import (
    add_days,
    ceil,
    flt,
    get_datetime,
    get_link_to_form,
    getdate,
    comma_and,
    nowtime,
    nowdate
    
)
from collections import defaultdict
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.get_item_details import IfNull, get_conversion_factor
from erpnext.manufacturing.doctype.production_plan.production_plan import (
    get_warehouse_list,get_raw_materials_of_sub_assembly_items,get_exploded_items,
    get_subitems,get_uom_conversion_factor,get_bin_details,get_materials_from_other_locations,
)
from erpnext.stock.doctype.material_request.material_request import create_pick_list,make_stock_entry

from erpnext.manufacturing.doctype.bom.bom import get_children as get_bom_children

class CustomProductionPlan(ProductionPlan):

    def _ensure_start_delete_cached(self):
        """Cache latest start/delete record once per PP instance."""
        if getattr(self, "_start_delete_cached", False):
            return

        # call existing method that sets flags.start_entries_data and delete_entries_data
        self.fetch_latest_record_with_child_tables()
        self._start_delete_cached = True

    def _get_cached_first_mr(self):
        if hasattr(self, "_first_mr_cache"):
            return self._first_mr_cache
        self._first_mr_cache = self.get_first_material_request()
        return self._first_mr_cache

    def before_save(self):
        # fetch the start and delete table here
        self.fetch_latest_record_with_child_tables()
        # "Fetch sub assembly items and optionally combine them."

    def before_submit(self):
        self.get_sub_assembly_items() 
        
        # """Fetch and set custom_link_id from the linked Material Requestl."""
        self.set_custom_link_id()


    @frappe.whitelist()
    def custom_make_material_request(self):
        """Create Material Requests grouped by Sales Order and Material Request Type"""
        material_request_list = []
        material_request_map = {}

        for item in self.mr_items:
            item_doc = frappe.get_cached_doc("Item", item.item_code)

            material_request_type = item.material_request_type or item_doc.default_material_request_type

            # key for Sales Order:Material Request Type:Customer
            key = "{}:{}:{}".format(item.sales_order, material_request_type, item_doc.customer or "")
            schedule_date = item.schedule_date or add_days(nowdate(), cint(item_doc.lead_time_days))

            if key not in material_request_map:
                # make a new MR for the combination
                material_request_map[key] = frappe.new_doc("Material Request")
                material_request = material_request_map[key]
                material_request.update(
                    {
                        "transaction_date": nowdate(),
                        "status": "Draft",
                        "company": self.company,
                        "material_request_type": material_request_type,
                        "customer": item_doc.customer or "",
                    }
                )
                # if self.get("custom_daily_production_id"):
                #     # Use set to avoid issues if the field is missing in some environments
                #     material_request.set("custom_daily_production_id", self.custom_daily_production_id)

                material_request_list.append(material_request)
            else:
                material_request = material_request_map[key]

            # add item
            material_request.append(
                "items",
                {
                    "item_code": item.item_code,
                    "from_warehouse": item.from_warehouse
                    if material_request_type == "Material Transfer"
                    else None,
                    "qty": item.quantity,
                    "schedule_date": schedule_date,
                    "warehouse": item.warehouse,
                    "sales_order": item.sales_order,
                    "production_plan": self.name,
                    "material_request_plan_item": item.name,
                    "project": frappe.db.get_value("Sales Order", item.sales_order, "project")
                    if item.sales_order
                    else None,
                },
            )

        for material_request in material_request_list:
            # if self.custom_daily_production_id:
            #     material_request.custom_daily_production_id = self.custom_daily_production_id
            # submit
            material_request.flags.ignore_permissions = 1
            material_request.run_method("set_missing_values")

            # if self.custom_daily_production_id:
            #     material_request.custom_daily_production_id = self.custom_daily_production_id

            material_request.save()
            material_request.submit()
            if material_request.material_request_type == "Material Transfer":
                doc = make_stock_entry(material_request.name)
                doc.insert(ignore_permissions=True)

        frappe.flags.mute_messages = False

        if material_request_list:
            material_request_list = [
                get_link_to_form("Material Request", m.name) for m in material_request_list
            ]
            msgprint(_("{0} created").format(comma_and(material_request_list)))
        else:
            msgprint(_("No material request created"))

        # self.submit()

    def set_custom_link_id(self):
        """Fetch and set custom_link_id from the linked Material Requestl."""
        mr_doc = self._get_cached_first_mr()
        if mr_doc and (mr_doc.get("custom_link_id") or mr_doc.get("custom_operation_type")):
            if not self.custom_link_id:
                try:
                    self.custom_link_id = mr_doc.get("custom_link_id")
                except Exception:
                    pass
            if not self.custom_operation_type:
                try:
                    self.custom_operation_type = mr_doc.get("custom_operation_type")
                except Exception:
                    pass

    def get_items_to_skip(self):

        delete_entries = getattr(self.flags, "delete_entries_data", None)

        # If not loaded yet, fetch it
        if delete_entries is None:
            self.fetch_latest_record_with_child_tables()
            delete_entries = getattr(self.flags, "delete_entries_data", None)

        # Still missing = real problem
        if delete_entries is None:
            frappe.throw("delete_entries_data could not be loaded")

        skip = {
            row.get("item_short_name"): cint(row.get("class"))
            for row in delete_entries
            if row.get("item_short_name")
        }

        return skip

    def make_work_order_for_subassembly_items(
        self, wo_list, subcontracted_po, default_warehouses,wip = False
    ):

        custom_item_group = frappe.db.get_value(
            "Production Plan Item",
            {"parent": self.name},
            "custom_item_group",
            order_by="idx asc",
        )
        # frappe.msgprint(f" If custom_item_group: {custom_item_group}")
        if custom_item_group == "CHIC WIP":
            items_to_skip = []
        if wip:
            items_to_skip = []
        else:
            items_to_skip = self.get_items_to_skip()
            # frappe.msgprint(f"Else items_to_skip: {items_to_skip}")


        for row in self.sub_assembly_items:

            if row.type_of_manufacturing == "Subcontract":
                subcontracted_po.setdefault(row.supplier, []).append(row)
                continue

            if row.type_of_manufacturing == "Material Request":
                continue
            if row.bom_level > 0 and row.parent_item_code in items_to_skip or row.production_item in items_to_skip:
                 continue
            # if row.production_item in items_to_skip:
            #     continue
            work_order_data = {
                "wip_warehouse": default_warehouses.get("wip_warehouse"),
                "fg_warehouse": default_warehouses.get("fg_warehouse"),
                "company": self.get("company"),
            }

            self.prepare_data_for_sub_assembly_items(row, work_order_data)
            work_order = self.create_work_order(work_order_data)
            if work_order:
                wo_list.append(work_order)
            


                # return wo_list

    def get_items_to_start(self):
        custom_start_item_table = []

        start_entries = getattr(self.flags, "start_entries_data", [])

        for row in start_entries:
            item_name = row.get("item_name")
            days_no = row.get("days_no")
            custom_start_item_table.append({"item_name": item_name, "days_no": days_no})

        return custom_start_item_table

    def get_holiday_list(self):
        company = frappe.get_cached_doc("Company", self.company)
        holiday_list_name = company.default_holiday_list

        if not holiday_list_name:
            return []

        holiday_list = frappe.get_cached_doc("Holiday List", holiday_list_name)
        return holiday_list.holidays or []


    def is_holiday(self, date):
        if not date:
            return False

        date = frappe.utils.getdate(date)

        return any(
            frappe.utils.getdate(h.holiday_date) == date
            for h in self.get_holiday_list()
        )


    def change_wo_plane_start_date(self, wo):
        """Calculate and return the planned start date for a Work Order (WO)."""

        schedule_date = self.custom_required_by

        if not schedule_date:
            frappe.throw("No Schedule Date found in Production Plan")

        # ✅ Get current time directly
        current_time = datetime.datetime.now().time()

        # ✅ Combine date + time
        planned_start_datetime = datetime.datetime.combine(
            getdate(schedule_date), current_time
        )

        planned_start_date = planned_start_datetime

        # ---- Adjustment logic ----
        start_earlier_items = self.get_items_to_start()

        item_code = wo.get("production_item")
        item_group = frappe.get_cached_value("Item", item_code, "item_group")

        days_delay = 0
        found = False

        for start_item in start_earlier_items:
            if item_code == start_item.get("item_name"):
                days_delay = start_item.get("days_no", 0)
                found = True
                break

        # enforce rule
        if item_group == "WIP TIM" and not found:
            frappe.throw(f"Please Add item: {item_code} in TIM Start Table")

        if days_delay and days_delay > 0:
            original_date = getdate(planned_start_date)
            original_time = planned_start_date.time()

            new_date = add_days(original_date, -days_delay)
            today_date = getdate()

            if new_date < today_date or self.is_holiday(new_date):
                new_date = today_date

            planned_start_date = datetime.datetime.combine(new_date, original_time)

        return planned_start_date

    def fetch_item_details_from_PP_tables_to_WO(self, wo):
        mr_data = self._get_cached_first_mr()
        if not mr_data:
            frappe.throw("❌ Error: No Material Request found for this Production Plan.")

        item_code = wo.get("production_item")
        if not item_code:
            frappe.throw("❌ Error: Missing item_code. Cannot fetch details.")

        # ── Unpack MR data ────────────────────────────────────────────────────────
        mr_recipe_items = mr_data.get("mr_recipe_items", [])
        mr_pack_items   = mr_data.get("mr_pack_items", [])

        if not mr_pack_items:
            frappe.throw("❌ Error: No items found in the linked Material Request.")

        # ── Apply top-level MR fields ──────────────────────────────────────────────
        wo.custom_operation_type = mr_data.get("custom_operation_type")
        wo.custom_link_id        = mr_data.get("custom_link_id")
        wo.custom_round          = mr_data.get("custom_round")
        wo.custom_batch_no_      = mr_data.get("custom_batch_id") or None

        # ── Resolve item type (fallback to item group if not set in MR) ───────────
        wo.custom_item_type = mr_data.get("custom_item_type") or self._resolve_item_type(wo.production_item)

        # ── Resolve note from recipe or pack items ────────────────────────────────
        wo.custom_note = self._find_field_in_items(item_code, "custom_note", mr_recipe_items, mr_pack_items)

        # ── Override with matched item fields (pack takes lower priority than recipe)
        for items in (mr_pack_items, mr_recipe_items):
            matched = next((i for i in items if i.get("item_code") == item_code), None)
            if matched:
                wo.custom_round      = matched.get("round")
                wo.custom_item_type  = matched.get("item_type")
                wo.custom_batch_size = mr_data.get("custom_batch_size")

        return wo, wo.custom_link_id, wo.custom_batch_size, wo.custom_item_type


    def _resolve_item_type(self, item_code):
        """Derive item type from the item's group when MR doesn't specify one."""
        GROUP_MAP = {
            "Products": "Pack",
            "Recipe":   "Cook",
        }
        item_group = frappe.get_cached_value("Item", item_code, "item_group")
        return GROUP_MAP.get(item_group, "WIP")


    def _find_field_in_items(self, item_code, field, *item_lists):
        """Return the first non-None value of `field` for `item_code` across multiple item lists."""
        for items in item_lists:
            value = next((i.get(field) for i in items if i.get("item_code") == item_code), None)
            if value is not None:
                return value
        return None

    def assign_workstation(self, wo):
        """Assign workstation from 'Material Request Item' or 'Material Request Cook Item' to Work Order operations."""

        item_code = wo.get("production_item")
        if not item_code:
            frappe.throw("Error: item_code is None or empty")
            return wo
        
        mr_data = self._get_cached_first_mr()
        workstation_to_use = None

        # First: Try to find workstation from Material Request Item
        for mr_item in mr_data.get("mr_pack_items", []):
            if (
                mr_item.get("item_code") == item_code
                and mr_item.get("custom_workstation")
            ):
                workstation_to_use = mr_item.get("custom_workstation")
                break

        # Second: fallback to recipe items
        if not workstation_to_use:
            for cook_item in mr_data.get("mr_recipe_items", []):
                if (
                    cook_item.get("item_code") == item_code
                    and cook_item.get("custom_workstation")
                ):
                    workstation_to_use = cook_item.get("custom_workstation")
                    break

        # Assign workstation to work order operations
        if workstation_to_use:
            for operation in wo.operations:
                # if not operation.workstation:
                original_ws = operation.workstation
                if original_ws != workstation_to_use:
                    operation.workstation = workstation_to_use
        return wo

    def fetch_warehouse_details_from_lookup_table(self, wo):
        """Fetch and assign WIP & FG warehouses for a Work Order (WO) based on Lookup table."""

        # Retrieve item_code from item dictionary
        item_code = wo.get("production_item")
        if not item_code:
            return None

        wip_warehouse = frappe.db.get_value(
            "lookup", {
                "production_item": item_code},
                  "wip_warehouse"
        )

        if not wip_warehouse:
            frappe.throw(f"No WIP Warehouse found for Item Code ({item_code})\nPlease add item in Lookup Item.")

        wo.wip_warehouse = wip_warehouse

        fg_warehouse = frappe.db.get_value(
            "lookup", {
                "production_item": item_code},
                  "fg_warehouse"
        )
        if not fg_warehouse:
            frappe.throw(f"No Target Warehouse found for Item Code ({item_code}).")

        wo.fg_warehouse = fg_warehouse 

        return wo

    def update_work_order_list(self,wo):

        self._ensure_start_delete_cached()
        wo.planned_start_date = self.change_wo_plane_start_date(wo)
        self.fetch_item_details_from_PP_tables_to_WO(wo)
        self.fetch_warehouse_details_from_lookup_table(wo)
        self.assign_workstation(wo)
        wo.use_multi_level_bom = 0
        try:
            wo.get_item_group_for_ig()
            wo.set_int_qty()    
            wo.save()
            wo.reload()
        except Exception:
            pass


# _________________________________________________________________________________________________________________



    def create_work_order(self, item):
        from erpnext.manufacturing.doctype.work_order.work_order import OverProductionError

        if flt(item.get("qty")) <= 0:
            return

        wo = frappe.new_doc("Work Order")
        wo.update(item)
        wo.set_work_order_operations()
        wo.set_required_items()
        wo.planned_start_date = item.get("planned_start_date") or item.get("schedule_date")

        if item.get("warehouse"):
            wo.fg_warehouse = item.get("warehouse")

        try:
            wo.flags.ignore_mandatory = True
            wo.flags.ignore_validate = True
            wo.insert()
            return wo.name
        except OverProductionError:
            pass


    # ----------------------------------------------------------------------------------------------------------------
    def get_first_material_request(self):
        """Fetch the first Material Request linked to a given Production Plan (PP)."""

        first_mr_entry = frappe.get_value(
            "Production Plan Material Request",
            {"parent": self.name},
            ["material_request"],
            order_by="idx ASC",
        )
        if not first_mr_entry:
            return None  # ✅ Ensure we return None instead of referencing a missing variable

        try:
            mr_doc = frappe.get_doc(
                "Material Request", first_mr_entry
            )  # ✅ Ensure this line always executes
            
        except frappe.DoesNotExistError:
            return None
        except Exception as e:
            return None

        # Extract child table (items)

        mr_items = []
        # mr_items_list = frappe.get_all("Material Request Item",filters={"parent":first_mr_entry},fields=["item_code","qty","warehouse","round"])
        if hasattr(mr_doc, "custom_recipe_table"):
            for item in mr_doc.get("custom_recipe_table", []):
                mr_items.append(
                    {
                        "item_code": item.item_code,
                        "qty": item.qty,
                        "warehouse": item.warehouse,
                        "item_type": item.item_type,
                        "round": item.round,
                        "custom_note": item.custom_note,
                        "custom_workstation": item.workstation,
                    }
                )
        mr_pack_items = []
        if hasattr(mr_doc, "items"):
            for pack_item in mr_doc.get("items", []):
                mr_pack_items.append(
                    {
                        "item_code": pack_item.item_code,
                        "round": pack_item.custom_round,
                        "item_type": pack_item.custom_item_type,
                        "custom_note": pack_item.custom_note,
                        "custom_workstation": pack_item.custom_workstation,
                    }
                )

        return {
            "name": mr_doc.name,
            "company": mr_doc.company,
            "schedule_date": getattr(mr_doc, "schedule_date", None),
            "custom_batch_size": getattr(mr_doc, "custom_batch_size", None),
            "custom_operation_type": getattr(mr_doc, "custom_operation_type", None),
            "custom_link_id": getattr(mr_doc, "custom_link_id", None),
            "mr_recipe_items": mr_items,  # Pass the extracted child table data
            "mr_pack_items": mr_pack_items,
            "custom_batch_id": getattr(mr_doc, "custom_batch_id", None),
        }

    def fetch_latest_record_with_child_tables(self):

        # Step 1: Fetch the latest record from 'start and delete items'
        latest_record = frappe.db.get_value(
            "start and delete items",
            filters={},
            fieldname=["name", "docstatus"],
            order_by="creation desc",
        )

        if not latest_record:
            frappe.throw("No records found in 'start and delete items'. Please create and submit one before proceeding.")
        

        record_name, record_docstatus = latest_record

        # Step 2: Ensure the record is submitted
        if record_docstatus != 1:
            frappe.throw(
                f"❌ The latest record '{record_name}' in 'start and delete items' is not submitted. "
                "Please submit it before proceeding."
            )

        # Step 3: Fetch the full document including child tables
        record_doc = frappe.get_doc("start and delete items", record_name)

        # Step 4: Extract child tables ('start' and 'delete') into arrays
        start_entries = []
        delete_entries = []

        for item in record_doc.get("start", []):  # Assuming 'start' is a child table
            start_entries.append(
                {
                    "item_name": item.item_name,
                    "description": item.description,
                    "days_no": item.days_no,
                }
            )

        for item in record_doc.get("delet", []):  # Assuming 'delete' is a child table
            delete_entries.append(
                {
                    "item_short_name": item.item_short_name,
                    "description": item.description,
                    "class": getattr(item, "class", None),
                }
            )


        # Step 5: Save values inside the document for later use
        self.latest_record_name = record_name
        self.latest_record_docstatus = record_docstatus
        self.flags.start_entries_data = start_entries
        self.flags.delete_entries_data = delete_entries

    # ______________________________________ this function is to add more MR filter in PP  ___________________

    @frappe.whitelist()
    def get_pending_material_requests(self):
        """Pull Material Requests that are pending based on criteria selected"""

        bom = frappe.qb.DocType("BOM")
        mr = frappe.qb.DocType("Material Request")
        mr_item = frappe.qb.DocType("Material Request Item")

        pending_mr_query = (
            frappe.qb.from_(mr)
            .from_(mr_item)
            .select(mr.name, mr.transaction_date)
            .distinct()
            .where(
                (mr_item.parent == mr.name)
                & (mr.material_request_type == "Manufacture")
                # & (mr.docstatus == 1)
                & (mr.status != "Stopped")
                & (mr.company == self.company)
                & (mr_item.qty > IfNull(mr_item.ordered_qty, 0))
                & (
                    ExistsCriterion(
                        frappe.qb.from_(bom)
                        .select(bom.name)
                        .where((bom.item == mr_item.item_code) & (bom.is_active == 1))
                    )
                )
            )
        )

        if self.from_date:
            pending_mr_query = pending_mr_query.where(
                mr.transaction_date >= self.from_date
            )

        if self.to_date:
            pending_mr_query = pending_mr_query.where(
                mr.transaction_date <= self.to_date
            )

        if self.warehouse:
            pending_mr_query = pending_mr_query.where(
                mr_item.warehouse == self.warehouse
            )

        if self.item_code:
            pending_mr_query = pending_mr_query.where(
                mr_item.item_code == self.item_code
            )
        if self.custom_status:
            pending_mr_query = pending_mr_query.where(mr.status == self.custom_status)
        pending_mr = pending_mr_query.run(as_dict=True)

        self.add_mr_in_table(pending_mr)

    # ______________________________________ this function is to let the PP Get the work orde items ___________________

    def get_mr_items(self):
        # Check for empty table or empty rows
        if not self.get("material_requests") or not self.get_so_mr_list(
            "material_request", "material_requests"
        ):
            frappe.throw(
                _("Please fill the Material Requests table"),
                title=_("Material Requests Required"),
            )

        mr_list = self.get_so_mr_list("material_request", "material_requests")

        bom = frappe.qb.DocType("BOM")
        mr_item = frappe.qb.DocType("Material Request Item")

        items_query = (
            frappe.qb.from_(mr_item)
            .select(
                mr_item.parent,
                mr_item.name,
                mr_item.item_code,
                mr_item.warehouse,
                mr_item.description,
                ((mr_item.qty - mr_item.ordered_qty) * mr_item.conversion_factor).as_(
                    "pending_qty"
                ),
            )
            .distinct()
            .where(
                (mr_item.parent.isin(mr_list))
                # & (mr_item.docstatus == 1)
                & (mr_item.qty > mr_item.ordered_qty)
                & (
                    ExistsCriterion(
                        frappe.qb.from_(bom)
                        .select(bom.name)
                        .where((bom.item == mr_item.item_code) & (bom.is_active == 1))
                    )
                )
            )
        )

        if self.item_code:
            items_query = items_query.where(mr_item.item_code == self.item_code)

        items = items_query.run(as_dict=True)

        self.add_items(items)
        self.calculate_total_planned_qty()
        return mr_list

    def combine_subassembly_items(self, sub_assembly_items_store):
            "Aggregate if same: Item, Warehouse, Inhouse/Outhouse Manu.g, BOM No."
            
            key_wise_data = {}

            # Read checkbox
            remove_deleted = cint(self.get("custom_remove_items_that_in_delete_table_custom_code"))

            # Prepare delete list only if checkbox is checked
            delte_item_from_sub_assembly = set()
            delete_entries = []
            if remove_deleted:
                # Get the item group passed from delta.py
                pd_group = self.get("custom_pd_group")
                
                if len(self.po_items) == 1:
                    row = self.po_items[0]

                    if not row.item_code:
                        return

                    item_group = frappe.db.get_value("Item", row.item_code, "item_group")
                    if not item_group:
                        frappe.throw(f"Item Group not found for Item {row.item_code}")

                    if item_group == "CHIC WIP":
                        delete_entries = []
                    else:
                        self.fetch_latest_record_with_child_tables()
                        delete_entries = getattr(self.flags, "delete_entries_data", [])

                else:
                    self.fetch_latest_record_with_child_tables()
                    delete_entries = getattr(self.flags, "delete_entries_data", [])

                if delete_entries:
                    # Logic: If pd_group exists (from delta.py), only remove items where class == 0
                    # If pd_group does NOT exist, remove items regardless of class
                    delte_item_from_sub_assembly = {
                        d.get("item_short_name")
                        for d in delete_entries
                        if d.get("item_short_name") and (cint(d.get("class")) == 0 if pd_group == "WIP" else True)
                    }
                    frappe.msgprint(_("Items in the Delete table will be removed from Sub Assembly table"), alert=True)

            for row in sub_assembly_items_store:

                # Skip rows if they are in delete list AND remove_deleted is checked
                if remove_deleted and (
                    row.get("parent_item_code") in delte_item_from_sub_assembly or
                    row.get("production_item") in delte_item_from_sub_assembly
                ):
                    continue

                # Build key conditionally: include parent_item_code only if remove_deleted is checked
                key_parts = [
                    row.get("production_item"),
                    row.get("fg_warehouse"),
                    row.get("bom_no"),
                    row.get("type_of_manufacturing"),
                ]
                if remove_deleted:
                    item_group = frappe.db.get_value("Item", {"item_code": row.get("parent_item_code")}, "item_group")
                    if item_group != "Products":
                        key_parts.append(row.get("parent_item_code"))

                key = tuple(key_parts)

                if key not in key_wise_data:
                    # Initialise first row for this key
                    key_wise_data[key] = row
                    continue

                # Merge with existing row
                existing_row = key_wise_data[key]
                existing_row.qty += flt(row.qty)
                existing_row.stock_qty += flt(row.stock_qty)
                existing_row.bom_level = max(existing_row.bom_level or 0, row.bom_level or 0)

            # Return merged list
            return list(key_wise_data.values())
        
    @frappe.whitelist()
    def make_work_order(self ,wip = False):
        from erpnext.manufacturing.doctype.work_order.work_order import get_default_warehouse
        wip = wip 
        wo_list, po_list = [], []
        subcontracted_po = {}
        default_warehouses = get_default_warehouse()

        self.make_work_order_for_finished_goods(wo_list, default_warehouses )
        self.make_work_order_for_subassembly_items(wo_list, subcontracted_po, default_warehouses, wip)
        self.make_subcontracted_purchase_order(subcontracted_po, po_list)
        self.show_list_created_message("Work Order", wo_list)
        self.show_list_created_message("Purchase Order", po_list)

        for wo in wo_list:
            wor = frappe.get_doc("Work Order", wo)
            self.update_work_order_list(wor)

        return wo_list
    


# ---------------------------to round the number in production plan--------------------------------------------
@frappe.whitelist()
def get_material_request_items(
    doc,
    row,
    sales_order,
    company,
    ignore_existing_ordered_qty,
    include_safety_stock,
    warehouse,
    bin_dict,
    custom_ignore_for_warehouses_qty=False,

):

    # frappe.msgprint("the override get_material_request_items")
    total_qty = row["qty"]

    required_qty = 0
    # custom_ignore_for_warehouses_qty: skip the projected_qty check for for_warehouse
	# but unlike ignore_existing_ordered_qty it does NOT affect the Transfer logic,
	# so get_materials_from_other_locations still runs and creates Material Transfers.
    if ignore_existing_ordered_qty or custom_ignore_for_warehouses_qty or bin_dict.get("projected_qty", 0) < 0:
        required_qty = total_qty
    elif total_qty > bin_dict.get("projected_qty", 0):
        required_qty = total_qty - bin_dict.get("projected_qty", 0)

    if (
        doc.get("consider_minimum_order_qty")
        and required_qty > 0
        and required_qty < row["min_order_qty"]
    ):
        required_qty = row["min_order_qty"]

    item_group_defaults = get_item_group_defaults(row.item_code, company)

    if not row["purchase_uom"]:
        row["purchase_uom"] = row["stock_uom"]    #
    custom_quantity = 0
    if row["purchase_uom"] != row["stock_uom"]:
        if not (
            (row["conversion_factor"] and row["conversion_factor"] != 0)
            or frappe.flags.show_qty_in_stock_uom
        ):
            frappe.throw(
                ("UOM Conversion factor ({0} -> {1}) not found for item: {2}").format(
                    row["purchase_uom"], row["stock_uom"], row.item_code
                )
            )
        required_qty = required_qty / row["conversion_factor"]

    if frappe.db.get_value("UOM", row["purchase_uom"], "must_be_whole_number"):
        custom_quantity = required_qty
        required_qty = ceil(required_qty)

    if include_safety_stock:
        required_qty += flt(row["safety_stock"])

    item_details = frappe.get_cached_value(
        "Item", row.item_code, ["purchase_uom", "stock_uom"], as_dict=1
    )

    conversion_factor = 1.0
    if (
        row.get("default_material_request_type") == "Purchase"
        and item_details.purchase_uom
        and item_details.purchase_uom != item_details.stock_uom
    ):
        conversion_factor = (
            get_conversion_factor(row.item_code, item_details.purchase_uom).get(
                "conversion_factor"
            )
            or 1.0
        )

    if required_qty > 0:
        # custom_quantity = required_qty / conversion_factor
        # if frappe.db.get_value("UOM", row["purchase_uom"], "must_be_whole_number"):
        #     custom_quantity = ceil(custom_quantity)
        # if custom_quantity:
        #     custom_quantity = custom_quantity / conversion_factor
        # else:
        #     custom_quantity = required_qty / conversion_factor
            
        return {
            "item_code": row.item_code,
            "item_name": row.item_name,
            "quantity": required_qty,
            "custom_round_quantity": custom_quantity,
            "conversion_factor": conversion_factor,
            "required_bom_qty": total_qty,
            "stock_uom": row.get("stock_uom"),
            "warehouse": warehouse
            or row.get("source_warehouse")
            or row.get("default_warehouse")
            or item_group_defaults.get("default_warehouse"),
            "safety_stock": row.safety_stock,
            "actual_qty": bin_dict.get("actual_qty", 0),
            "projected_qty": bin_dict.get("projected_qty", 0),
            "ordered_qty": bin_dict.get("ordered_qty", 0),
            "reserved_qty_for_production": bin_dict.get(
                "reserved_qty_for_production", 0
            ),
            "min_order_qty": row["min_order_qty"],
            "material_request_type": row.get("default_material_request_type"),
            "sales_order": sales_order,
            "description": row.get("description"),
            "uom": row.get("purchase_uom") or row.get("stock_uom"),
        }


@frappe.whitelist()
def get_items_for_material_requests(
    doc, warehouses=None, get_parent_warehouse_data=None
):
    if isinstance(doc, str):
        doc = frappe._dict(json.loads(doc))

    if warehouses:
        warehouses = list(set(get_warehouse_list(warehouses)))

        if (
            doc.get("for_warehouse")
            and not get_parent_warehouse_data
            and doc.get("for_warehouse") in warehouses
        ):
            warehouses.remove(doc.get("for_warehouse"))

    doc["mr_items"] = []

    po_items = doc.get("po_items") if doc.get("po_items") else doc.get("items")

    if doc.get("sub_assembly_items"):
        for sa_row in doc.sub_assembly_items:
            sa_row = frappe._dict(sa_row)
            if sa_row.type_of_manufacturing == "Material Request":
                po_items.append(
                    frappe._dict(
                        {
                            "item_code": sa_row.production_item,
                            "required_qty": sa_row.qty,
                            "include_exploded_items": 0,
                        }
                    )
                )

    # Check for empty table or empty rows
    if not po_items or not [
        row.get("item_code") for row in po_items if row.get("item_code")
    ]:
        frappe.throw(
            _(
                "Items to Manufacture are required to pull the Raw Materials associated with it."
            ),
            title=_("Items Required"),
        )

    company = doc.get("company")
    ignore_existing_ordered_qty = doc.get("ignore_existing_ordered_qty")
    custom_ignore_for_warehouses_qty = doc.get("custom_ignore_for_warehouses_qty")
    include_safety_stock = doc.get("include_safety_stock")

    so_item_details = frappe._dict()
    existing_sub_assembly_items = set()


    sub_assembly_items = defaultdict(int)
    if doc.get("skip_available_sub_assembly_item") and doc.get("sub_assembly_items"):
        for d in doc.get("sub_assembly_items"):
            sub_assembly_items[(d.get("production_item"), d.get("bom_no"))] += d.get("qty")

    for data in po_items:
        if not data.get("include_exploded_items") and doc.get("sub_assembly_items"):
            data["include_exploded_items"] = 1

        planned_qty = data.get("required_qty") or data.get("planned_qty")
        ignore_existing_ordered_qty = (
            data.get("ignore_existing_ordered_qty") or ignore_existing_ordered_qty
        )
        warehouse = doc.get("for_warehouse")

        item_details = {}
        if data.get("bom") or data.get("bom_no"):
            if data.get("required_qty"):
                bom_no = data.get("bom")
                include_non_stock_items = 1
                include_subcontracted_items = (
                    1 if data.get("include_exploded_items") else 0
                )
            else:
                bom_no = data.get("bom_no")
                include_subcontracted_items = doc.get("include_subcontracted_items")
                include_non_stock_items = doc.get("include_non_stock_items")

            if not planned_qty:
                frappe.throw(
                    _("For row {0}: Enter Planned Qty").format(data.get("idx"))
                )

            if bom_no:
                if data.get("include_exploded_items") and doc.get(
                    "skip_available_sub_assembly_item"
                ):
                    item_details = {}
                    if doc.get("sub_assembly_items"):
                        item_details = get_raw_materials_of_sub_assembly_items(
                            existing_sub_assembly_items,
                            item_details,
                            company,
                            bom_no,
                            include_non_stock_items,
                            sub_assembly_items,
                            planned_qty=planned_qty,
                        )

                elif data.get("include_exploded_items") and include_subcontracted_items:
                    # fetch exploded items from BOM
                    item_details = get_exploded_items(
                        item_details,
                        company,
                        bom_no,
                        include_non_stock_items,
                        planned_qty=planned_qty,
                        doc=doc,
                    )
                else:
                    item_details = get_subitems(
                        doc,
                        data,
                        item_details,
                        bom_no,
                        company,
                        include_non_stock_items,
                        include_subcontracted_items,
                        1,
                        planned_qty=planned_qty,
                    )
        elif data.get("item_code"):
            item_master = frappe.get_doc("Item", data["item_code"]).as_dict()
            purchase_uom = item_master.purchase_uom or item_master.stock_uom
            conversion_factor = (
                get_uom_conversion_factor(item_master.name, purchase_uom)
                if item_master.purchase_uom
                else 1.0
            )

            item_details[item_master.name] = frappe._dict(
                {
                    "item_name": item_master.item_name,
                    "default_bom": doc.bom,
                    "purchase_uom": purchase_uom,
                    "default_warehouse": item_master.default_warehouse,
                    "min_order_qty": item_master.min_order_qty,
                    "default_material_request_type": item_master.default_material_request_type,
                    "qty": planned_qty or 1,
                    "is_sub_contracted": item_master.is_subcontracted_item,
                    "item_code": item_master.name,
                    "description": item_master.description,
                    "stock_uom": item_master.stock_uom,
                    "conversion_factor": conversion_factor,
                    "safety_stock": item_master.safety_stock,
                }
            )

        sales_order = doc.get("sales_order")

        for item_code, details in item_details.items():
            so_item_details.setdefault(sales_order, frappe._dict())
            if item_code in so_item_details.get(sales_order, {}):
                so_item_details[sales_order][item_code]["qty"] = so_item_details[
                    sales_order
                ][item_code].get("qty", 0) + flt(details.qty)
            else:
                so_item_details[sales_order][item_code] = details

    mr_items = []
    for sales_order in so_item_details:
        item_dict = so_item_details[sales_order]
        for details in item_dict.values():
            bin_dict = get_bin_details(details, doc.company, warehouse)
            bin_dict = bin_dict[0] if bin_dict else {}
        
            if details.qty > 0:
                items = get_material_request_items(
                    
                    doc,
                    details,
                    sales_order,
                    company,
                    ignore_existing_ordered_qty,
                    include_safety_stock,
                    warehouse,
                    bin_dict,
                    custom_ignore_for_warehouses_qty=custom_ignore_for_warehouses_qty,
                )
                if items:
                    mr_items.append(items)

    if (not ignore_existing_ordered_qty or get_parent_warehouse_data) and warehouses:
        new_mr_items = []
        for item in mr_items:
            get_materials_from_other_locations(item, warehouses, new_mr_items, company)

        mr_items = new_mr_items

    if not mr_items:
        to_enable = frappe.bold(_("Ignore Existing Projected Quantity"))
        warehouse = frappe.bold(doc.get("for_warehouse"))
        message = (
            _(
                "As there are sufficient raw materials, Material Request is not required for Warehouse {0}."
            ).format(warehouse)
            + "<br><br>"
        )
        message += _("If you still want to proceed, please enable {0}.").format(
            to_enable
        )

    return mr_items




# def get_raw_materials_of_sub_assembly_items(
# 	existing_sub_assembly_items,
# 	item_details,
# 	company,
# 	bom_no,
# 	include_non_stock_items,
# 	sub_assembly_items,
# 	planned_qty=1,
# 	include_current_level_materials=True,
# ):
# 	bei = frappe.qb.DocType("BOM Item")
# 	bom = frappe.qb.DocType("BOM")
# 	item = frappe.qb.DocType("Item")
# 	item_default = frappe.qb.DocType("Item Default")
# 	item_uom = frappe.qb.DocType("UOM Conversion Detail")

# 	items = (
# 		frappe.qb.from_(bei)
# 		.join(bom)
# 		.on(bom.name == bei.parent)
# 		.join(item)
# 		.on(item.name == bei.item_code)
# 		.left_join(item_default)
# 		.on((item_default.parent == item.name) & (item_default.company == company))
# 		.left_join(item_uom)
# 		.on((item.name == item_uom.parent) & (item_uom.uom == item.purchase_uom))
# 		.select(
# 			(IfNull(Sum(bei.stock_qty / IfNull(bom.quantity, 1)), 0) * planned_qty).as_("qty"),
# 			item.item_name,
# 			item.name.as_("item_code"),
# 			bei.description,
# 			bei.stock_uom,
# 			bei.bom_no,
# 			item.min_order_qty,
# 			bei.source_warehouse,
# 			item.default_material_request_type,
# 			item.min_order_qty,
# 			item_default.default_warehouse,
# 			item.purchase_uom,
# 			item_uom.conversion_factor,
# 			item.safety_stock,
# 			bom.item.as_("main_bom_item"),
# 		)
# 		.where(
# 			(bei.docstatus == 1)
# 			& (bom.name == bom_no)
# 			& (item.is_stock_item.isin([0, 1]) if include_non_stock_items else item.is_stock_item == 1)
# 		)
# 		.groupby(bei.item_code, bei.stock_uom)
# 	).run(as_dict=True)

# 	for item in items:
#         # frappe.msgprint("custom function called")
# 		key = (item.item_code, item.bom_no)
# 		if item.item_code in existing_sub_assembly_items:
# 			continue

# 		if item.bom_no:
# 			frappe.msgprint(f"Fetching materials for {item.item_code} with bom no {item.bom_no}")
# 			next_planned_qty = item.qty
# 			shoild_fetch_materials_for_child = False
# 			if key in sub_assembly_items:
# 				next_planned_qty = flt(sub_assembly_items[key])
# 				should_fetch_materials_for_child = True
# 			else:
# 				should_fetch_materials_for_child = False
# 			planned_qty = flt(sub_assembly_items[key])
# 			get_raw_materials_of_sub_assembly_items(
# 				existing_sub_assembly_items,
# 				item_details,
# 				company,
# 				item.bom_no,
# 				include_non_stock_items,
# 				sub_assembly_items,
# 				planned_qty=planned_qty,
# 				include_current_level_materials=should_fetch_materials_for_child 
# 			)
# 		else:
# 			if include_current_level_materials:
# 				if not item.conversion_factor and item.purchase_uom:
# 					item.conversion_factor = get_uom_conversion_factor(item.item_code, item.purchase_uom)

# 				if details := item_details.get(item.get("item_code")):
# 					details.qty += item.get("qty")
# 				else:
# 					item_details.setdefault(item.get("item_code"), item)

# 	return item_details

def get_raw_materials_of_sub_assembly_items(
	existing_sub_assembly_items,
	item_details,
	company,
	bom_no,
	include_non_stock_items,
	sub_assembly_items,
	planned_qty=1,
	include_current_level_materials=True,
):
	bei = frappe.qb.DocType("BOM Item")
	bom = frappe.qb.DocType("BOM")
	item = frappe.qb.DocType("Item")
	item_default = frappe.qb.DocType("Item Default")
	item_uom = frappe.qb.DocType("UOM Conversion Detail")

	items = (
		frappe.qb.from_(bei)
		.join(bom)
		.on(bom.name == bei.parent)
		.join(item)
		.on(item.name == bei.item_code)
		.left_join(item_default)
		.on((item_default.parent == item.name) & (item_default.company == company))
		.left_join(item_uom)
		.on((item.name == item_uom.parent) & (item_uom.uom == item.purchase_uom))
		.select(
			(IfNull(Sum(bei.stock_qty / IfNull(bom.quantity, 1)), 0) * planned_qty).as_("qty"),
			item.item_name,
			item.name.as_("item_code"),
			bei.description,
			bei.stock_uom,
			bei.bom_no,
			item.min_order_qty,
			bei.source_warehouse,
			item.default_material_request_type,
			item.min_order_qty,
			item_default.default_warehouse,
			item.purchase_uom,
			item_uom.conversion_factor,
			item.safety_stock,
			bom.item.as_("main_bom_item"),
		)
		.where(
			(bei.docstatus == 1)
			& (bom.name == bom_no)
			& (item.is_stock_item.isin([0, 1]) if include_non_stock_items else item.is_stock_item == 1)
		)
		.groupby(bei.item_code, bei.stock_uom)
	).run(as_dict=True)

	for item in items:
		key = (item.item_code, item.bom_no)
		
		# 1. Skip if already processed
		if item.item_code in existing_sub_assembly_items:
			continue

		if item.bom_no:
			# frappe.msgprint(f"Fetching materials for {item.item_code} with bom no {item.bom_no}")
			
			# === FIXED LOGIC START ===
			if key in sub_assembly_items:
				# Case 1: Item IS in the table (WIP)
				# Use user's input quantity
				next_planned_qty = flt(sub_assembly_items[key])
				# Fetch its raw materials (Standard behavior)
				should_fetch_materials_for_child = True
				
				# FIX FOR DUPLICATES: Mark this WIP as processed so we don't do it again
				existing_sub_assembly_items.add(item.item_code)
			else:
				# Case 2: Item IS NOT in the table (Recipe)
				# Use calculated quantity (Pass through)
				next_planned_qty = item.qty
				# DO NOT fetch immediate raw materials (Ignore Recipe ingredients), 
				# BUT recurse to find BOMs inside (Find WIP).
				should_fetch_materials_for_child = False 
			
			# Recursive Call with the variables decided above
			get_raw_materials_of_sub_assembly_items(
				existing_sub_assembly_items,
				item_details,
				company,
				item.bom_no,
				include_non_stock_items,
				sub_assembly_items,
				planned_qty=next_planned_qty,
				include_current_level_materials=should_fetch_materials_for_child 
			)
			# === FIXED LOGIC END ===

		else:
			# Raw Materials Logic
			# If include_current_level_materials is False (because it's an unchecked Recipe),
			# this block is skipped, effectively ignoring the Recipe's raw materials.
			if include_current_level_materials:
				if not item.conversion_factor and item.purchase_uom:
					item.conversion_factor = get_uom_conversion_factor(item.item_code, item.purchase_uom)

				if details := item_details.get(item.get("item_code")):
					details.qty += item.get("qty")
				else:
					item_details.setdefault(item.get("item_code"), item)

	return item_details


from frappe import copy_doc

@frappe.whitelist()
def duplicate_production_plan(docname):

    original = frappe.get_doc("Production Plan", docname)
    new_doc = copy_doc(original)

    # ─── Core status reset ────────────────────────────────────
    new_doc.docstatus = 0
    new_doc.status = "Draft"
    new_doc.name = None

    # ─── These fields make ERPNext think the plan is completed ─
    # and hide the "Create Work Orders" button
    new_doc.total_produced_qty = 0
    new_doc.produced_qty = 0

    # ─── Reset work order creation tracking ───────────────────
    # Without this, ERPNext thinks work orders were already made
    new_doc.total_work_orders_created = 0

    # ─── Reset purchase order tracking ────────────────────────
    new_doc.total_purchase_orders_created = 0

    # ─── Reset all child row link/status fields ────────────────
    for row in new_doc.po_items:
        row.planned_qty = row.planned_qty or 0
        row.produced_qty = 0
        row.ordered_qty = 0
        row.work_order = None          # ← linked WO hides the button
        row.sales_order = row.sales_order  # keep reference if needed

    for row in new_doc.mr_items:
        row.ordered_qty = 0
        row.received_qty = 0
        row.purchase_order = None

    # ─── Optional title ───────────────────────────────────────
    new_doc.title = f"{original.title} (Copy)" if original.get("title") else None

    new_doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return new_doc.name




