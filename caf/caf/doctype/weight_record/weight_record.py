# Copyright (c) 2025, hisham and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
from datetime import datetime
from frappe.model.naming import getseries

class WeightRecord(Document):

    def autoname(self):
        if isinstance(self.work_date, datetime):
            date_start = self.work_date.strftime("%Y-%m-%d")
        else:
            date_start = self.work_date
            
        key = "WR-" + date_start
        self.name = key + "-" + getseries(key, 3)
      
            
