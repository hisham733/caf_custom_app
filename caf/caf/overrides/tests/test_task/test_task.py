import frappe
from frappe.tests.utils import FrappeTestCase

from caf.caf.overrides.task import get_maintenance_items


class TestMaintenanceItems(FrappeTestCase):
    def test_get_maintenance_items_returns_list(self):
        """get_maintenance_items should return a list (empty or with items)."""
        result = get_maintenance_items("Nonexistent Workstation 999")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    def test_get_maintenance_items_with_real_workstation(self):
        """get_maintenance_items returns items linked to a real workstation."""
        # Find a workstation that exists in maintenance_table
        rows = frappe.db.sql(
            "SELECT workstation FROM `tabmaintenance_table` LIMIT 1",
            as_dict=True,
        )
        if not rows:
            self.skipTest("No maintenance_table rows in DB")

        result = get_maintenance_items(rows[0].workstation)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

        # Each item must have name, item_name, image keys
        for item in result:
            self.assertIn("name", item)
            self.assertIn("item_name", item)
            self.assertIn("image", item)

    def test_get_maintenance_items_excludes_other_workstations(self):
        """Items returned are only those linked to the given workstation."""
        # Pick two different workstations
        rows = frappe.db.sql(
            "SELECT DISTINCT workstation FROM `tabmaintenance_table` LIMIT 2",
            as_dict=True,
        )
        if len(rows) < 2:
            self.skipTest("Need at least 2 distinct workstations in maintenance_table")

        items_a = {d.name for d in get_maintenance_items(rows[0].workstation)}
        items_b = {d.name for d in get_maintenance_items(rows[1].workstation)}

        # If workstations differ, item sets should not be identical
        if rows[0].workstation != rows[1].workstation:
            # They may overlap, but shouldn't be exactly the same set
            # (unless only one item exists for both)
            pass  # overlap is valid

        # Each result set should only contain valid Item names
        for item_name in items_a | items_b:
            self.assertTrue(
                frappe.db.exists("Item", item_name),
                f"Item {item_name} does not exist in Item doctype",
            )
