# Copyright (c) 2026, hisham and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document
from caf.caf.overrides.work_order import make_stock_entry, create_recook_stock_entry_backend
from datetime import datetime, timedelta


class DailyOutputRecord(Document):

    @frappe.whitelist()
    def process_all(self):
        for row in self.items:
            if row.status == "Done":
                self._validate_row(row)
                continue
            try:
                self._process_row(row)
                frappe.db.set_value("Daily Output Item", row.name, "status", "Done")
            except Exception as e:
                frappe.log_error(frappe.get_traceback(), "Daily Output Row {0} failed".format(row.idx))
                frappe.db.set_value("Daily Output Item", row.name, "status", "Failed")
                return {
                    "success": False,
                    "error": str(e),
                    "failed_row": row.idx,
                    "link_id": row.link_id,
                }
        return {"success": True, "message": "All rows processed successfully"}

    @frappe.whitelist()
    def enqueue_process_all(self):
        if self.processing_status == "In Progress":
            frappe.throw(_("Processing already in progress"))

        self.db_set("processing_status", "In Progress")
        self.db_set("processing_error", None)
        frappe.db.commit()

        frappe.enqueue(
            method="caf.caf.doctype.daily_output_record.daily_output_record.run_process_all_background",
            queue="default",
            timeout=600,
            name=self.name,
        )
        return {"queued": True}

    def _process_row(self, row):
        link_id = row.link_id

        all_wos = frappe.get_all("Work Order", filters={
            "custom_link_id": link_id,
            "docstatus": ["!=", 2],
        }, fields=["name", "custom_item_type", "status", "docstatus", "production_item"])

        if not all_wos:
            frappe.msgprint(_("No Work Orders found for link_id {0}").format(link_id))
            return

        type_order = {"WIP": 0, "Cook": 1, "Pack": 2}
        all_wos.sort(key=lambda w: type_order.get(w.get("custom_item_type", ""), 99))

        for wo in all_wos:
            item_type = wo.get("custom_item_type")
            wo_name = wo["name"]
            try:
                if item_type == "WIP":
                    self._complete_wip_wo(wo_name)
                elif item_type == "Cook":
                    self._process_single_wo(
                        wo_name,
                        do_recook=flt(row.recook) > 0,
                        recook_qty=flt(row.recook),
                    )
                elif item_type == "Pack":
                    num_packs = int(row.number_of_pack or 0)
                    if num_packs == 0:
                        if row.pack_name and wo.get("production_item") != row.pack_name:
                            continue
                        if row.pack_workstation:
                            self._set_workstation(wo_name, row.pack_workstation)
                        pack_qty = flt(row.actual_qty)
                    else:
                        matched = False
                        for idx in range(num_packs):
                            expected_item = row.pack_name if idx == 0 else row.get(f"pack_name_{idx + 1}")
                            if wo.get("production_item") != expected_item:
                                continue
                            workstation = row.pack_workstation if idx == 0 else row.get(f"pack_workstation_{idx + 1}")
                            if workstation:
                                self._set_workstation(wo_name, workstation)
                            pack_qty = flt(row.actual_qty if idx == 0 else row.get(f"actual_qty_{idx + 1}"))
                            matched = True
                            break
                        if not matched:
                            continue
                    self._process_single_wo(
                        wo_name,
                        total_balance=flt(row.balance),
                        total_pack_qty=pack_qty,
                    )
            except Exception as e:
                raise Exception(f"{wo_name}: {e}") from e

    def _validate_row(self, row):
        link_id = row.link_id
        pack_wos = frappe.get_all("Work Order", filters={
            "custom_link_id": link_id,
            "custom_item_type": "Pack",
            "docstatus": 1,
        }, fields=["name", "production_item", "produced_qty"])

        if not pack_wos:
            return

        num_packs = int(row.number_of_pack or 0)
        comments = []

        if num_packs == 0:
            if row.pack_name and flt(row.actual_qty):
                for pwo in pack_wos:
                    if pwo["production_item"] == row.pack_name:
                        if flt(row.actual_qty) != flt(pwo["produced_qty"]):
                            msg = _("{0}: expected produced_qty = {1}, actual_qty entered = {2}").format(
                                pwo["name"], pwo["produced_qty"], row.actual_qty
                            )
                            comments.append(msg)
                            frappe.msgprint(msg, alert=True)
                        break
        else:
            for idx in range(num_packs):
                expected_item = row.pack_name if idx == 0 else row.get(f"pack_name_{idx + 1}")
                actual_qty = flt(row.actual_qty if idx == 0 else row.get(f"actual_qty_{idx + 1}"))
                if not expected_item or not actual_qty:
                    continue
                for pwo in pack_wos:
                    if pwo["production_item"] == expected_item:
                        if actual_qty != flt(pwo["produced_qty"]):
                            msg = _("{0}: expected produced_qty = {1}, actual_qty entered = {2}").format(
                                pwo["name"], pwo["produced_qty"], actual_qty
                            )
                            comments.append(msg)
                            frappe.msgprint(msg, alert=True)
                        break

        if comments:
            self.add_comment(text="<br>".join(comments))

    def _process_single_wo(self, wo_name, total_balance=0, total_pack_qty=0, do_recook=False, recook_qty=0):
        wo = frappe.get_doc("Work Order", wo_name)

        if wo.docstatus == 0:
            wo.submit()
            wo.reload()

        if wo.status == "Completed":
            return

        if wo.status in ("Not Started", "Pending"):
            se_dict = make_stock_entry(
                work_order_id=wo_name,
                purpose="Material Transfer for Manufacture",
            )
            se = frappe.get_doc(se_dict)
            se.insert(ignore_permissions=True)
            se.submit()

        self._process_job_cards(wo_name)

        if do_recook:
            result = create_recook_stock_entry_backend(
                wo_name, recook_qty, "Prod Balance - CAF", auto_submit=1
            )
            if isinstance(result, dict) and not result.get("success"):
                frappe.msgprint(
                    _("Recook warning for {0}: {1}").format(wo_name, result.get("message", ""))
                )

        se_dict = make_stock_entry(
            work_order_id=wo_name,
            purpose="Manufacture",
            total_balance=total_balance,
            total_pack_qty=total_pack_qty,
        )
        se = frappe.get_doc(se_dict)
        se.insert(ignore_permissions=True)
        se.submit()


    def _complete_wip_wo(self, wo_name):
        wo = frappe.get_doc("Work Order", wo_name)
        if wo.docstatus == 0:
            wo.submit()
            wo.reload()
        if wo.status == "Completed":
            return

        if wo.status in ("Not Started", "Pending"):
            se_dict = make_stock_entry(
                work_order_id=wo_name,
                purpose="Material Transfer for Manufacture",
            )
            se = frappe.get_doc(se_dict)
            se.insert(ignore_permissions=True)
            se.submit()

        self._process_job_cards(wo_name)

        se_dict = make_stock_entry(
            work_order_id=wo_name,
            purpose="Manufacture",
        )
        se = frappe.get_doc(se_dict)
        se.insert(ignore_permissions=True)
        se.submit()

    def _set_workstation(self, wo_name, workstation):
        pack_wo = frappe.get_doc("Work Order", wo_name)
        changed = False
        for op in pack_wo.operations:
            if not op.workstation:
                op.workstation = workstation
                changed = True
        if changed:
            pack_wo.save()

    def _process_job_cards(self, wo_name):
        jcs = frappe.get_all("Job Card", filters={
            "work_order": wo_name,
            "docstatus": 0,
        }, fields=["name", "operation", "total_completed_qty", "for_quantity"])

        if not jcs:
            return

        base = datetime.now().replace(microsecond=0)

        for i, jc in enumerate(jcs):
            jc_doc = frappe.get_doc("Job Card", jc["name"])
            completed_qty = jc.get("total_completed_qty") or jc.get("for_quantity") or 0

            st = base + timedelta(seconds=i * 10)
            et = st + timedelta(seconds=5)

            jc_doc.append("time_logs", {
                "from_time": st,
                "status": "Work In Progress",
            })
            jc_doc.append("time_logs", {
                "from_time": st,
                "to_time": et,
                "completed_qty": completed_qty,
                "status": "Complete",
            })
            jc_doc.save()
            jc_doc.submit()


@frappe.whitelist()
def run_process_all_background(name):
    dor = frappe.get_doc("Daily Output Record", name)
    frappe.db.auto_commit_on_many_writes = 1
    try:
        result = dor.process_all()
        if result.get("success"):
            dor.db_set("processing_status", "Completed")
        else:
            error_msg = _("Row {0}: {1}").format(result.get("failed_row"), result.get("error"))
            dor.db_set("processing_status", "Failed")
            dor.db_set("processing_error", error_msg)
            dor.add_comment(text=error_msg)
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "DOR background failed: {0}".format(name))
        dor.db_set("processing_status", "Failed")
        dor.db_set("processing_error", str(e))
        dor.add_comment(text=str(e))
    finally:
        frappe.db.auto_commit_on_many_writes = 0
        frappe.db.commit()
