# Copyright (c) 2026, hisham and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CafSettings(Document):
    def validate(self):
        self._validate_report_required_inputs()

    def _validate_report_required_inputs(self):
        """Block enabling a report when its required input or channel is missing."""

        # Missing Supplier report: enabled needs a 'missing' supplier selected.
        if self.get("supplier_enabled") and not self.get("supplier_missing_supplier"):
            frappe.throw(
                _("Missing Supplier report is enabled, but no supplier is selected. "
                  "Choose a 'Missing Supplier' (e.g. SUPPLIER MISSING) first.")
            )

        # Yield Drop report: enabled needs a threshold value.
        if self.get("yield_enabled") and not self.get("yield_limit"):
            frappe.throw(
                _("Yield Drop report is enabled, but no 'Yield Drop Threshold' is set. "
                  "Enter a threshold (e.g. 5) first.")
            )

        # A report with channels all disabled has no effect — require at least one channel.
        self._require_channel(supplier_enabled="supplier_enabled", wa="supplier_wa", tg="supplier_tg",
                              label="Missing Supplier")
        self._require_channel(yield_enabled="yield_enabled", wa="yield_wa", tg="yield_tg",
                              label="Yield Drop")

    def _require_channel(self, **kw):
        enabled = self.get(kw.get("enabled"))
        if enabled and not (self.get(kw.get("wa")) or self.get(kw.get("tg"))):
            frappe.throw(
                _("{0} report is enabled, but both WhatsApp and Telegram are off. "
                  "Turn on at least one channel.").format(kw.get("label"))
            )
