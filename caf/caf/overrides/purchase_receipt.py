import frappe
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
from frappe.model.mapper import get_mapped_doc
from frappe import _, throw

class CustomPurchaseReceipt(PurchaseReceipt):
      def before_save(self):

            self.set_has_exp_no()
      def on_submit(self):
            super().on_submit()   # keep standard ERPNext behavior
            self.set_manual_exp()
            self.make_auto_repack()
      def make_auto_repack(self):

            # 1️⃣ Get default settings
            settings_name = frappe.db.get_value(
                  "start and delete items",
                  {"custom_is_default": 1},
                  "name",
                  order_by="creation desc"
            )
            if not settings_name:
                  return

            settings = frappe.get_doc("start and delete items", settings_name)

            # 2️⃣ Build rule map
            rule_map = {
                  r.item: r for r in settings.repack_items_table
                  if r.enabled and r.item and r.target_item
            }
            if not rule_map:
                  return

            # 3️⃣ Filter PR rows
            repack_rows = [
                  row for row in self.items
                  if row.item_code in rule_map and row.qty > 0
            ]
            if not repack_rows:
                  return

            # 4️⃣ Prevent duplicate repack
            if frappe.db.sql("""
                  SELECT sed.name
                  FROM `tabStock Entry Detail` sed
                  JOIN `tabStock Entry` se ON se.name = sed.parent
                  WHERE sed.reference_purchase_receipt = %s
                  AND se.stock_entry_type = 'Repack'
                  LIMIT 1
            """, self.name):
                  return

            # 5️⃣ Create empty Stock Entry
            se = frappe.new_doc("Stock Entry")
            se.stock_entry_type = "Repack"
            se.reference_doctype = "Purchase Receipt"
            se.reference_name = self.name
            se.set_posting_time = 1
            se.posting_date = self.posting_date
            se.posting_time = self.posting_time

            alerts = []

            # 6️⃣ Process each PR row separately
            for row in repack_rows:

                  # 🔹 Get batch + expiry from PR-created batch
                  batch_data = frappe.db.get_value(
                        "Batch",
                        {
                        "item": row.item_code,
                        "reference_doctype": "Purchase Receipt",
                        "reference_name": self.name
                        },
                        ["name", "expiry_date"]
                  )

                  if not batch_data:
                        frappe.throw(f"No batch found for item {row.item_code} in PR {self.name}")

                  source_batch, expiry_date = batch_data

                  # 🔹 Add source (consume item)
                  se.append("items", {
                        "item_code": row.item_code,
                        "qty": row.qty,
                        "s_warehouse": row.warehouse,
                        "uom": row.uom,
                        "use_serial_batch_fields": 1,
                        "batch_no": source_batch,
                        "reference_purchase_receipt":self.name
                  })

                  # 🔹 Add target (FG item) — no batch_no
                  # ERPNext will auto-create batch
                  target_item = rule_map[row.item_code].target_item

                  se.append("items", {
                        "item_code": target_item,
                        "qty": row.qty,
                        "uom":row.uom,
                        "transfer_qty":row.stock_qty,
                        "t_warehouse": row.warehouse,
                        "is_finished_item": 1
                  })

                  alerts.append(
                        f"{row.item_code} → {target_item} ({row.qty} {row.uom})"
                  )

            # 7️⃣ Insert & Submit (auto-creates FG batches)
            se.insert(ignore_permissions=True)
            se.submit()

            # 8️⃣ Override expiry date for newly created FG batches
            # pdb.set_trace()
            for d in se.items:
                  if d.is_finished_item:

                        # find matching PR row
                        matching_row = next(
                        (r for r in repack_rows
                        if rule_map[r.item_code].target_item == d.item_code),
                        None
                        )

                        if matching_row:
                              source_expiry = frappe.db.get_value(
                                    "Batch",
                                    {
                                          "item": matching_row.item_code,
                                          "reference_doctype": "Purchase Receipt",
                                          "reference_name": self.name
                                    },
                                    "expiry_date"
                              )
                              frappe.log_error(
                                    title="Debug Repack Expiry",
                                    message=f"source_expiry: {source_expiry}, matching_row.item_code: {matching_row.item_code},self.name: {self.name}")
                        if source_expiry:
                              frappe.log_error(
                                    title="Debug Repack Expiry2",
                                    message=f"source_expiry: {source_expiry}"
                                    )
                              frappe.db.set_value(
                                    "Batch",
                                    {
                                          "item":d.item_code,
                                          "reference_doctype":"Stock Entry",
                                          "reference_name": se.name
                                    },
                                              "expiry_date",source_expiry
                              )
                              frappe.log_error(
                                    title="Debug Repack  target",
                                    message=f"source_expiry: {source_expiry}, matching_row.item_code: {d.item_code}"
                                    )

            # 9️⃣ Show alert
            frappe.msgprint(
                  _("The following sugars have been repacked:\n{0}".format(
                        "\n".join(alerts)
                  )),
                  alert=True
            )
      def set_manual_exp(self):
            item_codes= list(set(d.item_code for d in self.items if d.custom_expiry_date))
            if not item_codes:
                  return
            batch_enabled_items = frappe.get_all(
                  "Item", filters={"name":["in",item_codes],
                  "has_batch_no": 1
                  },
                  pluck="name"
            )
            batch_enabled_items = set(batch_enabled_items)

            if not batch_enabled_items:
                  return
            batches = frappe.get_all(
                  "Batch",
                  filters={"item": ["in",list(batch_enabled_items)],
                  "reference_name": self.name
                  },
                  fields=["name","item"]
            )

            batch_map = {d.item: d.name for d in batches}

            for item in self.items:
                  if not item.custom_expiry_date:
                        continue

                  if item.item_code not in batch_enabled_items:
                        continue

                  batch_name = batch_map.get(item.item_code)
                  if not batch_name:
                        continue
                  if batch_name and item.custom_expiry_date:
                        frappe.set_value(
                              "Batch",
                              batch_name,
                              "expiry_date",
                              item.custom_expiry_date
                        )


      def set_has_exp_no(self):
            # pdb.set_trace()
            item_codes_with_exp= list(set(d.item_code for d in self.items if d.custom_expiry_date))
            print(item_codes_with_exp)
            items = frappe.get_all(
                  "Item",
                  filters={
                        "name":["in",item_codes_with_exp],
                        "has_batch_no":1,
                        "disabled":0,
                        "has_expiry_date":0
                        },
                  pluck="name"
            )
            if not items:
                  return
            for item in items:
 
                  frappe.db.set_value("Item",item,{"has_expiry_date":1,"shelf_life_in_days":50})
            frappe.db.commit() 
     



