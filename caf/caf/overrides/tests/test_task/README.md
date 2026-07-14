# Task - Maintenance Items Tests

## How to Run

### Run All Tests

From the terminal:
```bash
cd /workspace/development/frappe-bench && bench console 2>&1 <<'EOF'
from caf.caf.overrides.tests.test_task.test_task import TestMaintenanceItems
import unittest
suite = unittest.TestLoader().loadTestsFromTestCase(TestMaintenanceItems)
unittest.TextTestRunner(verbosity=2).run(suite)
EOF
```

### Run a Single Test

```bash
cd /workspace/development/frappe-bench && bench console 2>&1 <<'EOF'
from caf.caf.overrides.tests.test_task.test_task import TestMaintenanceItems
import unittest
suite = unittest.TestLoader().loadTestsFromName('test_get_maintenance_items_with_real_workstation', TestMaintenanceItems)
unittest.TextTestRunner(verbosity=2).run(suite)
EOF
```

### Available Test Names

- `test_get_maintenance_items_returns_list`
- `test_get_maintenance_items_with_real_workstation`
- `test_get_maintenance_items_excludes_other_workstations`

Replace `test_get_maintenance_items_with_real_workstation` in the command above with any test name from the list.

## Expected Output

```
test_get_maintenance_items_excludes_other_workstations ... ok
test_get_maintenance_items_returns_list ... ok
test_get_maintenance_items_with_real_workstation ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.070s

OK
```

## Test Descriptions

| Test | What it checks |
|------|---------------|
| `test_get_maintenance_items_returns_list` | Non-existent workstation returns empty list `[]` |
| `test_get_maintenance_items_with_real_workstation` | Real workstation returns items with `name`, `item_name`, `image` keys |
| `test_get_maintenance_items_excludes_other_workstations` | Returned items are valid Items that exist in the system |
