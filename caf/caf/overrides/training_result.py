# Copyright (c) 2026, CAF Food Products Sdn Bhd and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, get_datetime, get_fullname, now_datetime

from hrms.hr.doctype.training_result.training_result import TrainingResult

SCALE_MARKER_START = "Very Poor: 1"
SCALE_MARKER_END = "Excellent: 5"


def _get_criteria_fieldnames():
    """Dynamically find the rating criteria in the child doctype metadata.

    Treats every Select field on Training Result Employee whose options match the
    1-5 rating scale (Very Poor: 1 ... Excellent: 5) as a criteria column.
    No hardcoded field list, so adding/renaming criteria needs no code change.
    """
    fields = frappe.get_meta("Training Result Employee").fields
    return [
        df.fieldname
        for df in fields
        if df.fieldtype == "Select"
        and df.options
        and SCALE_MARKER_START in df.options
        and SCALE_MARKER_END in df.options
    ]


def _score_from_option(value):
    if not value:
        return 0
    try:
        return int(str(value).split(":")[-1].strip())
    except (TypeError, ValueError):
        return 0


def _grade_from_total(total):
    if total >= 36:
        return "Very Good"
    if total >= 30:
        return "Good"
    if total >= 20:
        return "Ordinary"
    return "Bad"


class CustomTrainingResult(TrainingResult):
    def validate(self):
        super().validate()
        self.compute_employee_scores()
        self.set_duration()

    def compute_employee_scores(self):
        criteria = _get_criteria_fieldnames()
        for row in self.get("employees"):
            total = sum(_score_from_option(row.get(fieldname)) for fieldname in criteria)
            row.custom_total_marks = total
            row.custom_result = _grade_from_total(total)

    def set_duration(self):
        if not self.get("training_event"):
            return

        start_time, end_time = frappe.db.get_value(
            "Training Event", self.get("training_event"), ["start_time", "end_time"]
        )
        if start_time and end_time:
            self.custom_duration = flt(
                (get_datetime(end_time) - get_datetime(start_time)).total_seconds() / 3600.0, 2
            )

    def on_update(self):
        state = self.get("workflow_state")
        if state == "Submitted":
            if not self.get("custom_submitted_by"):
                self.db_set("custom_submitted_by", get_fullname(frappe.session.user))
            if not self.get("custom_submitted_date"):
                self.db_set("custom_submitted_date", now_datetime())
        elif state == "Approved":
            if not self.get("custom_reviewed_by_hr_head"):
                self.db_set("custom_reviewed_by_hr_head", get_fullname(frappe.session.user))
            if not self.get("custom_date"):
                self.db_set("custom_date", now_datetime())

    def on_update_after_submit(self):
        if self.get("workflow_state") == "Approved":
            if not self.get("custom_reviewed_by_hr_head"):
                self.db_set("custom_reviewed_by_hr_head", get_fullname(frappe.session.user))
            if not self.get("custom_date"):
                self.db_set("custom_date", now_datetime())