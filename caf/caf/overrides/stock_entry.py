from erpnext.stock.get_item_details import Sum
import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from frappe.utils import flt
from frappe import _, bold
from erpnext.stock.serial_batch_bundle import SerialBatchCreation
import json
from erpnext.stock.serial_batch_bundle import SerialBatchCreation, get_serial_or_batch_items
from caf.caf.overrides.serial_and_batch_bundle import (
    get_se_link_id_and_item_type,
    is_item_in_delet_table,
    get_batch_for_linked_work_order,
)
import pdb

class CustomStockEntry(StockEntry):
    def validate(self):
        super().validate()
        # self.set_qi_items(self)
        self.table_get_link_id()

    def berfore_save(self):
        self.check_item()

    def check_item(self):
        if len(self.items) != 1:
            return  # Only validate if there's exactly 1 item
        item = self.items[0]

        print(f"self.items",item)
        
        if item.qty <= 1 and item.item_code in ("General Chicken", "Boild Chics", "CHIC C"):
            frappe.throw(f'QTY must be more than "1". Check the Batch QTY for \"<b>{item.item_code }<b>\".')

    def table_get_link_id(self):
        woPtr = frappe.get_value("Work Order", {"name": self.work_order}, "custom_link_id")

        if woPtr:  # Ensure the value is not None
            print("custom_link_id:", woPtr)
            return woPtr
        else:
            print("Work Order not found or 'custom_link_id' is empty.")
            return None

    def get_scrap_items_from_qi(self):
        # Check if 'custom_wrok_order' exists in Quality Inspection
        if not frappe.get_meta("Quality Inspection").has_field("custom_work_order"):
            frappe.throw("'custom_wrok_order' field not found in Quality Inspection")

        qi = frappe.qb.DocType("Quality Inspection")
        qi_scrap_item = frappe.qb.DocType("Job Card Scrap Item")

        qi_scrap_items = (
            frappe.qb.from_(qi)
            .join(qi_scrap_item)
            .on(qi_scrap_item.parent == qi.name)
            .select(
                Sum(qi_scrap_item.stock_qty).as_("stock_qty"),
                qi_scrap_item.item_code,
                qi_scrap_item.custom_warehouse,
                qi.name,
            )
            .where(
                (qi_scrap_item.item_code.isnotnull())
                & (qi.custom_work_order == self.work_order)
                & (qi.docstatus == 1)
                & (qi_scrap_item.custom_warehouse.isnotnull())
                & (qi_scrap_item.custom_warehouse != "")
            )
            .groupby(qi_scrap_item.item_code, qi_scrap_item.custom_warehouse)
        ).run(as_dict=True)

        print("qi_scrap_items", qi_scrap_items)

        return qi_scrap_items

    def get_existing_qi_items(self, work_order):
        """Fetch total qty per item from past QI Stock Entries to avoid duplication."""
        existing_entries = frappe.get_all(
            "Stock Entry",
            filters={
                "work_order": work_order,
                "docstatus": 1,  # Only consider submitted Stock Entries
                "stock_entry_type": "Manufacture",
            },
            fields=["name"],
        )

        existing_qi_qty = {}  # Dictionary to track total qty per (Item Code)

        for entry in existing_entries:
            stock_entry = frappe.get_doc("Stock Entry", entry["name"])
            for item in stock_entry.items:
                if item.custom_quality_inspection and item.item_code:
                    key = (item.item_code, item.t_warehouse)

                    # Sum up total quantity added
                    if key in existing_qi_qty:
                        existing_qi_qty[key] += item.qty
                    else:
                        existing_qi_qty[key] = item.qty

        return existing_qi_qty

    def get_previously_inserted_qty(self, work_order, item_code, warehouse):
        """Calculate the total quantity of a given item in previous Stock Entries."""
        existing_stock_entries = self.get_existing_qi_entries(work_order)

        if not existing_stock_entries:
            return 0  # No previous entries

        previous_qty = 0
        for se in existing_stock_entries:
            stock_entry = frappe.get_doc("Stock Entry", se["name"])

            for item in stock_entry.items:
                if (
                    item.item_code == item_code
                    and item.t_warehouse == warehouse
                    and item.custom_quality_inspection
                ):
                    previous_qty += item.qty  # Sum the previously inserted quantities

        return previous_qty

    def is_qi_already_added(self, stock_entry, qi_name):
        """
        Check if a given Quality Inspection (QI) reference already exists in the Stock Entry items.
        """
        existing_qi_names = {
            item.custom_quality_inspection
            for item in stock_entry.items
            if item.custom_quality_inspection
        }

        if qi_name in existing_qi_names:
            print(
                f"⚠️ QI {qi_name} already exists in Stock Entry {stock_entry.name}. Skipping duplicate entry."
            )
            return True

        print(
            f"✅ QI {qi_name} not found in Stock Entry {stock_entry.name}. Adding new entry."
        )
        return False  # Returns False if QI does not exist
    @frappe.whitelist()
    def set_qi_items(stock_entry):
        """Add QI and Scrap items to stock entry, ensuring no duplication by summing up past quantities."""
        try:
            if stock_entry.purpose not in ["Manufacture", "Repack"]:
                return

            scrap_items = stock_entry.get_scrap_items_from_qi()
            if not scrap_items:
                frappe.msgprint("No scrap items found from Quality Inspections.", alert=True)
                return

            existing_qi_qty = stock_entry.get_existing_qi_items(stock_entry.work_order)

            # ✅ Fetch existing items in Stock Entry for quick lookup
            existing_item_rates = {
                item.item_code: item.basic_rate for item in stock_entry.items
            }

            for scrap in scrap_items:
                qi_name = scrap.get("name")  # QI Name
                item_code = scrap.get("item_code")
                warehouse = scrap.get("custom_warehouse")
                total_qty = scrap.get("stock_qty", 0)

                if not (item_code and warehouse and total_qty):
                    frappe.msgprint(f"Skipping invalid scrap item: {scrap}", alert=True)
                    continue

                key = (item_code, warehouse)
                previously_inserted_qty = existing_qi_qty.get(key, 0)
                remaining_qty = total_qty - previously_inserted_qty

                if remaining_qty <= 0:
                    frappe.msgprint(
                        f"Skipping {item_code} as all {total_qty} qty has already been added.",
                        alert=True,
                    )
                    continue
                finished_items = [
                    i for i in stock_entry.items 
                    if getattr(i, "is_finished_item", 0)
                ]

                matched_finished = next(
                    (
                        i for i in finished_items 
                        if i.qty == remaining_qty 
                        and i.t_warehouse == "W Output - CAF"  # ✅ safety check
                    ),
                    None
                )

                if matched_finished:
                    # 🗑️ Remove the Finished Item safely
                    stock_entry.remove(matched_finished)
                    frappe.msgprint(
                        f"Removed Finished Item {matched_finished.item_code} "
                        f"(qty matched {remaining_qty}, warehouse {matched_finished.t_warehouse})",
                        alert=True
                    )

                # ✅ Determine the correct rate
                basic_rate = existing_item_rates.get(
                    item_code, frappe.get_value("Item", item_code, "valuation_rate")
                )

                # ✅ Append item to stock entry
                stock_entry.append(
                    "items",
                    {
                        "item_code": item_code,
                        "qty": remaining_qty,
                        "t_warehouse": warehouse,
                        "is_scrap_item": 1,
                        "uom": frappe.get_value("Item", item_code, "stock_uom"),
                        "basic_rate": basic_rate,
                        "stock_uom": frappe.get_value("Item", item_code, "stock_uom"),
                        "conversion_factor": 1,
                        "custom_table_link_id": stock_entry.table_get_link_id(),
                        "transfer_qty": remaining_qty,
                        "custom_quality_inspection": qi_name,  # Store QI reference
                    },
                )

            frappe.msgprint(
                f"QI and Scrap items added to Stock Entry {stock_entry.name}",
                alert=True,
            )

        except Exception as e:
            error_message = f"Error in set_qi_items: {str(e)}"
            frappe.msgprint(error_message, alert=True)


    def make_serial_and_batch_bundle_for_outward(self):
        if self.docstatus == 0:
            return
        #pdb.set_trace()
        print("custom code")
        serial_or_batch_items = get_serial_or_batch_items(self.items)
        if not serial_or_batch_items:
            return

        # fetch link_id and item_type from SE directly
        kwargs = frappe._dict({
            "posting_date": self.posting_date,
            "posting_time": self.posting_time,
            "name": self.name
        })
        print(f"kwargs: {kwargs}")
        custom_link_id, custom_item_type,name = get_se_link_id_and_item_type(kwargs)
        print(custom_link_id,custom_item_type)
        already_picked_serial_nos = []
        success_messages = []
        for row in self.items:
            if row.use_serial_batch_fields:
                continue

            if not row.s_warehouse:
                continue

            if row.item_code not in serial_or_batch_items:
                continue

            # check if custom logic should apply for this row
            has_bom = frappe.db.exists("BOM", {
                    "item": row.item_code,
                    "is_active": 1,
                    "docstatus": 1,
                })
            exists = frappe.db.exists(
                                "Stock Entry",
                                {
                                    "work_order": name,
                                    "purpose": "Material Transfer for Manufacture",
                                    "docstatus": 1
                                }
                            )
            
            is_excluded = is_item_in_delet_table(row.item_code)
            # print(f"has_bom: {has_bom}")
            r_bom = self.from_bom
            use_custom = (
                custom_item_type in ["Cook", "Pack"]
                and not exists
                and custom_link_id
                and has_bom
                and not row.serial_and_batch_bundle
                and not is_excluded
                and r_bom == 1

            )

            if use_custom and not row.serial_and_batch_bundle:

                batches = get_batch_for_linked_work_order(
                    item_code=row.item_code,
                    required_qty=row.transfer_qty,
                    custom_link_id=custom_link_id,
                    warehouse=row.s_warehouse,
                )

                # create ONE bundle with multiple entries
                bundle_doc = frappe.get_doc({
                    "doctype": "Serial and Batch Bundle",
                    "voucher_type": "Stock Entry",
                    "item_code": row.item_code,
                    "warehouse": row.s_warehouse,
                    "type_of_transaction": "Outward",
                    "posting_date": self.posting_date,
                    "posting_time": self.posting_time,
                    "has_batch_no": 1,
                    "company": self.company,
                })

                # append one entry per batch
                for b in batches:
                    bundle_doc.append("entries", {
                        "batch_no": b.batch_no,
                        "qty": b.qty * -1,
                        "warehouse": row.s_warehouse,
                    })

                bundle_doc.insert(ignore_permissions=True)
                bundle_doc.flags.ignore_voucher_validation = True
                #bundle_doc.submit()

                row.serial_and_batch_bundle = bundle_doc.name

                batch_names = ", ".join(b.batch_no for b in batches)
                success_messages.append(
                    _("✅ Batches {0} (Link ID {1}) assigned for item {2}.").format(
                        bold(batch_names),
                        bold(custom_link_id),
                        bold(row.item_code),
                    )
                )
            else:
                # fallback → original ERPNext logic
                bundle_doc = None
                if row.serial_and_batch_bundle and abs(row.transfer_qty) != abs(
                    frappe.get_cached_value(
                        "Serial and Batch Bundle", row.serial_and_batch_bundle, "total_qty"
                    )
                ):
                    bundle_doc = SerialBatchCreation({
                        "item_code": row.item_code,
                        "warehouse": row.s_warehouse,
                        "serial_and_batch_bundle": row.serial_and_batch_bundle,
                        "type_of_transaction": "Outward",
                        "ignore_serial_nos": already_picked_serial_nos,
                        "qty": row.transfer_qty * -1,
                    }).update_serial_and_batch_entries()
                elif not row.serial_and_batch_bundle:
                    bundle_doc = SerialBatchCreation({
                        "item_code": row.item_code,
                        "warehouse": row.s_warehouse,
                        "posting_date": self.posting_date,
                        "posting_time": self.posting_time,
                        "voucher_type": self.doctype,
                        "voucher_detail_no": row.name,
                        "qty": row.transfer_qty * -1,
                        "ignore_serial_nos": already_picked_serial_nos,
                        "type_of_transaction": "Outward",
                        "company": self.company,
                        "do_not_submit": True,
                    }).make_serial_and_batch_bundle()

                if not bundle_doc:
                    continue

                for entry in bundle_doc.entries:
                    if not entry.serial_no:
                        continue
                    already_picked_serial_nos.append(entry.serial_no)

                row.serial_and_batch_bundle = bundle_doc.name
        if success_messages:
            frappe.msgprint(
                "<br>".join(success_messages),
                title=_("Batch Assignment Summary"),
                indicator="green"
            )
            
@frappe.whitelist()
def get_first_item_stock_entry_table(stock_entry_name):
    se_item = frappe.get_doc("Stock Entry", stock_entry_name)
    if se_item.items:
        return se_item.items[0].item_code 
    else:
        return None








ALLOWED_ITEMS = ("General Chicken","CHIC C", "Boild Chics", "CHIC", "Cut Chic")


@frappe.whitelist()
def detect_batch_info(doc):

    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except Exception:
            frappe.throw("Invalid document data sent from frontend.")

    doc = frappe._dict(doc)

    # ✅ Must have exactly ONE item
    if not doc.get("items") or len(doc.get("items")) != 1:
        return None

    row = doc.get("items")[0]

    if not row.get("item_code"):
        return None

    # ✅ Only run for allowed items
    if row.get("item_code") not in ALLOWED_ITEMS:
        return None

    item_code = row.get("item_code")
    link_id = doc.get("custom_link_id")
    fallback_batch = doc.get("custom_batch_to_use")

    result = None

    # ==============================
    # 1️⃣ Try Link ID
    # ==============================
    if link_id:

        result = frappe.db.sql("""
            SELECT 
                sle.warehouse,
                sbi.batch_no,
                SUM(sle.actual_qty) as qty
            FROM `tabStock Ledger Entry` sle
            JOIN `tabSerial and Batch Entry` sbi
                ON sbi.parent = sle.serial_and_batch_bundle
            WHERE
                sle.item_code = %s
                AND sle.is_cancelled = 0
                AND sle.voucher_no IN (
                    SELECT name
                    FROM `tabStock Entry`
                    WHERE custom_link_id = %s
                )
            GROUP BY sle.warehouse, sbi.batch_no
            HAVING qty > 0
            ORDER BY qty DESC
            LIMIT 1
        """, (item_code, link_id), as_dict=True)

    # ==============================
    # 2️⃣ Fallback to Batch
    # ==============================
    if not result and fallback_batch:

        result = frappe.db.sql("""
            SELECT 
                sle.warehouse,
                sbi.batch_no,
                SUM(sle.actual_qty) as qty
            FROM `tabStock Ledger Entry` sle
            JOIN `tabSerial and Batch Entry` sbi
                ON sbi.parent = sle.serial_and_batch_bundle
            WHERE
                sle.item_code = %s
                AND sbi.batch_no = %s
                AND sle.is_cancelled = 0
            GROUP BY sle.warehouse, sbi.batch_no
            HAVING qty > 0
            ORDER BY qty DESC
            LIMIT 1
        """, (item_code, fallback_batch), as_dict=True)

    if not result:
        frappe.throw(
            _("No batch stock found for Item {0}.").format(item_code)
        )

    return {
        "warehouse": result[0]["warehouse"],
        "batch_no": result[0]["batch_no"],
        "qty": flt(result[0]["qty"])
    }

  # ==========================================================
# 🔥 SYNC BUNDLE WITH QTY (HOOK)
# Runs before_submit
# ==========================================================
def sync_bundle_with_qty(doc, method):

    # ✅ Must have exactly one row
    if not doc.items or len(doc.items) != 1:
        return

    row = doc.items[0]

    # ✅ Only allowed items
    if row.item_code not in ALLOWED_ITEMS:
        return

    if not row.qty:
        return

    old_bundle = row.serial_and_batch_bundle

    if old_bundle:
        try:
            frappe.delete_doc(
                "Serial and Batch Bundle",
                old_bundle,
                ignore_permissions=True,
                force=True
            )
        except Exception:
            pass

    batch_no = row.batch_no or doc.custom_batch_to_use

    if not batch_no:
        frappe.throw("Batch No missing — cannot create bundle")

    batch_dict = {
        batch_no: flt(row.qty)
    }

    bundle = SerialBatchCreation({
        "type_of_transaction": "Outward",
        "item_code": row.item_code,
        "warehouse": row.s_warehouse,
        "batches": batch_dict,
        "posting_date": doc.posting_date,
        "posting_time": doc.posting_time,
        "voucher_type": "Stock Entry",
        "voucher_no": doc.name,
        "voucher_detail_no": row.name,
        "qty": flt(row.qty),
        "company": doc.company,
        "do_not_submit": True,
    }).make_serial_and_batch_bundle()

    row.serial_and_batch_bundle = bundle.name
    row.batch_no = batch_no