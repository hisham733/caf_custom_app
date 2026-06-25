import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, MagicMock
from frappe.utils import today


class TestDailyOutputRecord(FrappeTestCase):
    """Tests for DailyOutputRecord controller methods."""

    def setUp(self):
        self.dor = frappe.get_doc({
            "doctype": "Daily Output Record",
            "date_of_output": today(),
        })
        self.dor.insert()

    def tearDown(self):
        frappe.db.rollback()

    # ── helpers ─────────────────────────────────────────────────────

    def _add_item(self, **kwargs):
        defaults = {
            "link_id": "LINK-001",
            "workstation": None,
            "round": 1,
            "size": 100,
            "number_of_pack": 0,
            "pack_name": None,
            "actual_qty": 0,
            "pack_workstation": None,
            "status": "Done",
        }
        defaults.update(kwargs)
        return self.dor.append("items", defaults)

    # ── _validate_row ───────────────────────────────────────────────

    @patch("frappe.get_all")
    def test_validate_row_match(self, mock_get_all):
        """actual_qty == produced_qty → silent pass, no warnings"""
        row = self._add_item(link_id="LINK-001", number_of_pack=1, pack_name="Item-A", actual_qty=100)
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 100.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            self.dor._validate_row(row)

        mock_msg.assert_not_called()

    @patch("frappe.get_all")
    def test_validate_row_mismatch(self, mock_get_all):
        """actual_qty != produced_qty → msgprint + add_comment with WO name and quantities"""
        row = self._add_item(link_id="LINK-001", number_of_pack=1, pack_name="Item-A", actual_qty=100)
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 95.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            with patch.object(self.dor, "add_comment") as mock_comment:
                self.dor._validate_row(row)

        mock_msg.assert_called_once()
        args, kwargs = mock_msg.call_args
        self.assertIn("WO-PACK-001", args[0])
        self.assertIn("95", args[0])
        self.assertIn("100", args[0])
        self.assertTrue(kwargs.get("alert"))
        mock_comment.assert_called_once()
        comment_text = mock_comment.call_args[1]["text"]
        self.assertIn("WO-PACK-001", comment_text)

    @patch("frappe.get_all")
    def test_validate_row_multi_slot_match(self, mock_get_all):
        """All 3 pack slots match → silent pass"""
        row = self._add_item(
            link_id="LINK-001", number_of_pack=3,
            pack_name="Item-A", actual_qty=100,
            pack_name_2="Item-B", actual_qty_2=50,
            pack_name_3="Item-C", actual_qty_3=25,
        )
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 100.0},
            {"name": "WO-PACK-002", "production_item": "Item-B", "produced_qty": 50.0},
            {"name": "WO-PACK-003", "production_item": "Item-C", "produced_qty": 25.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            self.dor._validate_row(row)

        mock_msg.assert_not_called()

    @patch("frappe.get_all")
    def test_validate_row_multi_slot_partial_mismatch(self, mock_get_all):
        """Slot 2 mismatches, slots 1 and 3 match → only slot 2 warns"""
        row = self._add_item(
            link_id="LINK-001", number_of_pack=3,
            pack_name="Item-A", actual_qty=100,
            pack_name_2="Item-B", actual_qty_2=50,
            pack_name_3="Item-C", actual_qty_3=25,
        )
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 100.0},
            {"name": "WO-PACK-002", "production_item": "Item-B", "produced_qty": 48.0},
            {"name": "WO-PACK-003", "production_item": "Item-C", "produced_qty": 25.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            with patch.object(self.dor, "add_comment") as mock_comment:
                self.dor._validate_row(row)

        mock_msg.assert_called_once()
        self.assertIn("WO-PACK-002", str(mock_msg.call_args))
        mock_comment.assert_called_once()

    @patch("frappe.get_all")
    def test_validate_row_legacy_single_match(self, mock_get_all):
        """number_of_pack=0 with pack_name + actual_qty → matches legacy field"""
        row = self._add_item(
            link_id="LINK-001", number_of_pack=0,
            pack_name="Item-A", actual_qty=100,
        )
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 100.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            self.dor._validate_row(row)

        mock_msg.assert_not_called()

    @patch("frappe.get_all")
    def test_validate_row_legacy_single_mismatch(self, mock_get_all):
        """number_of_pack=0 with mismatch → warns correctly"""
        row = self._add_item(
            link_id="LINK-001", number_of_pack=0,
            pack_name="Item-A", actual_qty=100,
        )
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 90.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            with patch.object(self.dor, "add_comment") as mock_comment:
                self.dor._validate_row(row)

        mock_msg.assert_called_once()

    @patch("frappe.get_all")
    def test_validate_row_no_pack_wos(self, mock_get_all):
        """No submitted Pack WOs for link_id → silent return"""
        row = self._add_item(link_id="LINK-001", number_of_pack=1, pack_name="Item-A", actual_qty=100)
        mock_get_all.return_value = []

        with patch("frappe.msgprint") as mock_msg:
            self.dor._validate_row(row)

        mock_msg.assert_not_called()

    @patch("frappe.get_all")
    def test_validate_row_no_actual_qty_entered(self, mock_get_all):
        """Slot has pack_name but actual_qty is 0 → skip that slot"""
        row = self._add_item(
            link_id="LINK-001", number_of_pack=2,
            pack_name="Item-A", actual_qty=0,
            pack_name_2="Item-B", actual_qty_2=50,
        )
        mock_get_all.return_value = [
            {"name": "WO-PACK-001", "production_item": "Item-A", "produced_qty": 100.0},
            {"name": "WO-PACK-002", "production_item": "Item-B", "produced_qty": 50.0},
        ]

        with patch("frappe.msgprint") as mock_msg:
            self.dor._validate_row(row)

        # Slot 1 skipped (actual_qty=0), Slot 2 matches → no warnings
        mock_msg.assert_not_called()

    # ── _set_workstation ────────────────────────────────────────────

    @patch("frappe.get_doc")
    def test_set_workstation_empty_op(self, mock_get_doc):
        """Operation with empty workstation → gets assigned and saved"""
        mock_wo = MagicMock()
        mock_wo.operations = [
            frappe._dict({"operation": "Op 1", "workstation": None}),
        ]
        mock_get_doc.return_value = mock_wo

        self.dor._set_workstation("WO-TEST", "Pack Station 1")

        mock_get_doc.assert_called_once_with("Work Order", "WO-TEST")
        self.assertEqual(mock_wo.operations[0].workstation, "Pack Station 1")
        mock_wo.save.assert_called_once()

    @patch("frappe.get_doc")
    def test_set_workstation_already_set(self, mock_get_doc):
        """Operation already has workstation → not overwritten, not saved"""
        mock_wo = MagicMock()
        mock_wo.operations = [
            frappe._dict({"operation": "Op 1", "workstation": "Existing Station"}),
        ]
        mock_get_doc.return_value = mock_wo

        self.dor._set_workstation("WO-TEST", "Pack Station 1")

        self.assertEqual(mock_wo.operations[0].workstation, "Existing Station")
        mock_wo.save.assert_not_called()

    @patch("frappe.get_doc")
    def test_set_workstation_no_operations(self, mock_get_doc):
        """WO has no operations → no error, no save"""
        mock_wo = MagicMock()
        mock_wo.operations = []
        mock_get_doc.return_value = mock_wo

        self.dor._set_workstation("WO-TEST", "Pack Station 1")

        mock_wo.save.assert_not_called()

    @patch("frappe.get_doc")
    def test_set_workstation_mixed_ops(self, mock_get_doc):
        """Multiple ops: only empty ones get assigned, save once"""
        mock_wo = MagicMock()
        op1 = frappe._dict({"operation": "Op 1", "workstation": None})
        op2 = frappe._dict({"operation": "Op 2", "workstation": "Fixed"})
        op3 = frappe._dict({"operation": "Op 3", "workstation": None})
        mock_wo.operations = [op1, op2, op3]
        mock_get_doc.return_value = mock_wo

        self.dor._set_workstation("WO-TEST", "Pack Station 1")

        self.assertEqual(op1.workstation, "Pack Station 1")
        self.assertEqual(op2.workstation, "Fixed")
        self.assertEqual(op3.workstation, "Pack Station 1")
        mock_wo.save.assert_called_once()

    # ── process_all integration ─────────────────────────────────────

    def test_process_all_no_wos_for_link_id(self):
        """Row with link_id that has no WOs → silently marked Done"""
        row = self._add_item(
            link_id="TEST-NO-WOS", status="Pending",
            number_of_pack=1, actual_qty=100,
        )
        self.dor.save()

        result = self.dor.process_all()

        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Daily Output Item", row.name, "status"), "Done")

    def test_process_all_already_done(self):
        """Row already Done → validates then skips (no error with no WOs)"""
        row = self._add_item(
            link_id="TEST-NO-WOS-DONE", status="Done",
            number_of_pack=1, actual_qty=100,
        )
        self.dor.save()

        result = self.dor.process_all()

        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Daily Output Item", row.name, "status"), "Done")

    def test_process_all_multiple_rows_mixed(self):
        """One row Done, one row Pending with no WOs → all processed OK"""
        done_row = self._add_item(
            link_id="TEST-MIX-DONE", status="Done",
            number_of_pack=1, actual_qty=100,
        )
        pending_row = self._add_item(
            link_id="TEST-MIX-PENDING", status="Pending",
            number_of_pack=1, actual_qty=50,
        )
        self.dor.save()

        result = self.dor.process_all()

        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Daily Output Item", done_row.name, "status"), "Done")
        self.assertEqual(frappe.db.get_value("Daily Output Item", pending_row.name, "status"), "Done")
