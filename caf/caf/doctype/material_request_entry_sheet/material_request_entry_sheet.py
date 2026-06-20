# Copyright (c) 2025, hisham and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import datetime

class MaterialRequestEntrySheet(Document):
	@frappe.whitelist()
	def create_material_requests_from_entry_lines(self):
		# 🔍 Only fetch entry lines linked to this document
		entry_lines = frappe.get_all(
			"Material Request Entry Line",
			filters={"parent": self.name},
			fields=["*"]
		)

		transaction_date_original = self.transaction_date
		required_by_original = self.required_by


		if not entry_lines:
			frappe.throw("No Material Request Entry Lines found.")

		created_mrs = []

		for idx, raw in enumerate(entry_lines, start=1):
			mr = frappe.new_doc("Material Request")
			mr.material_request_type = raw.purpose or "Manufacture"
			mr.transaction_date = transaction_date_original
			mr.schedule_date = required_by_original

			# 🛠️ Adjust required_by if it's earlier than transaction date
            # this will be used for both item types
			# Ensure schedule_date is a date object
			schedule_date = raw.required_by
			if isinstance(schedule_date, str):
				schedule_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()

			if isinstance(transaction_date_original, str):
				transaction_date_original = datetime.strptime(transaction_date_original, "%Y-%m-%d").date()

			if schedule_date < transaction_date_original:
				frappe.msgprint(f"⚠️ Row #{idx}: Required date {schedule_date} is earlier than transaction date {transaction_date_original}. Adjusting.")
				schedule_date = transaction_date_original
			# ✅ Logging for debug
			if raw.pack_item_code:
				mr.append("items", {
					"item_code": raw.pack_item_code,
					"schedule_date": schedule_date,
					"custom_start_time": raw.pack_start_time,
					"custom_item_type": "Pack",
					"uom": raw.pack_uom,
					"qty": raw.quantity,
					"conversion_factor": 1,
					"custom_planner_qty": raw.quantity,
					"custom_workstation": raw.pack_workstation,
					"custom_round": raw.pack_round,
					"custom_note": raw.pack_note
				})
				mr.custom_batch_size = raw.batch_size
				mr.custom_operation_type = raw.operation_type

			if raw.recipe_item_code:
				mr.append("custom_recipe_table", {
					"item_code": raw.recipe_item_code,
					"schedule_date": schedule_date,
					"start_time": raw.cooking_start_time,
					"item_type": "Cook",
					"conversion_factor": 1,
					"uom": raw.recipe_uom,
					"workstation": raw.cooking_workstation,
					"round": raw.cooking_round,
					"custom_note": raw.cooking_note
				})

			if mr.get("items") or mr.get("custom_recipe_table"):
				try:
					mr.insert(ignore_permissions=True)
					frappe.db.commit()
					created_mrs.append(mr.name)
				except Exception as e:
					frappe.throw(f"❌ Error inserting MR at row #{idx}: {e}")
			else:
				frappe.msgprint(f"⚠️ Skipped creating MR due to missing item rows: {raw.name}")

		return created_mrs
