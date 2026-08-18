app_name = "caf"
app_title = "Caf"
app_publisher = "hisham"
app_description = "custom app "
app_email = "hisham@gmail.com"
app_license = "mit"


override_doctype_class = {
    "Work Order": "caf.caf.overrides.work_order.CustomWorkOrder",
    "Production Plan": "caf.caf.overrides.production_plan.CustomProductionPlan",
    "Material Request": "caf.caf.overrides.material_request.CustomMaterialRequest",
    "Stock Entry": "caf.caf.overrides.stock_entry.CustomStockEntry",
    "Job Card": "caf.caf.overrides.job_card.CustomJobCard",
    "Quality Review": "caf.caf.overrides.quality_review.CustomQualityReview",
    "BOM": "caf.caf.overrides.bom.CustomBOM",
    "Purchase Receipt": "caf.caf.overrides.purchase_receipt.CustomPurchaseReceipt",
    # CAF appraisal (2026-08-05)
    "Appraisal": "caf.caf.overrides.appraisal.CustomAppraisal",
    "Employee Performance Feedback": "caf.caf.overrides.employee_performance_feedback.CustomEmployeePerformanceFeedback",
}
doctype_js = {
    "Job Card": "public/js/job_card.js",
    "Work Order": "public/js/work_order.js",
    "Production Plan": "public/js/production_plan.js",
    "Stock Entry": "public/js/stock_entry.js",
    "Quality Review": "public/js/quality_review.js",
    "Leave Application": "public/js/leave_application.js",
    # Chunk 7.3 — warn before half-cancelling a trade. The database can no longer
    # refuse it (see the before_cancel hook), so this warning is what stops a
    # silent half-cancel.
    "Shift Assignment": "public/js/shift_assignment.js",
    "BOM":"public/js/bom.js",
    "Purchase Receipt":"public/js/purchase_receipt.js",
    "Material Request":"public/js/material_request.js",
    "Task":"public/js/task.js",
    # CAF appraisal (2026-08-05)
    "Appraisal": "public/js/appraisal.js",
}
override_whitelisted_methods = {
    "erpnext.manufacturing.doctype.production_plan.production_plan.combine_subassembly_items": "caf.caf.overrides.production_plan.combine_subassembly_items",
    "erpnext.manufacturing.doctype.production_plan.production_plan.get_raw_materials_of_sub_assembly_items": "caf.caf.overrides.production_plan.get_raw_materials_of_sub_assembly_items",
    "erpnext.manufacturing.doctype.production_plan.production_plan.get_items_for_material_requests": "caf.caf.overrides.production_plan.get_items_for_material_requests",
    "erpnext.manufacturing.doctype.production_plan.production_plan.get_pending_material_requests": "caf.caf.overrides.production_plan.get_pending_material_requests",
    "erpnext.manufacturing.doctype.production_plan.production_plan.make_material_request": "caf.caf.overrides.production_plan.custom_make_material_request",
    "frappe.some_method": "caf.caf.overrides.job_card.create_qi_from_job_card",
    "erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry": "caf.caf.overrides.work_order.make_stock_entry",
    "erpnext.manufacturing.doctype.job_card.set_status":"caf.caf.overrides.job_card.custom_set_status",
    # "erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.get_auto_data":"caf.caf.overrides.serial_and_batch_bundle.get_auto_data"

}


# Override the method for get_material_request_items in production_plan

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = ["/assets/caf/css/ai_assistant.css"]
app_include_js = [
    "/assets/caf/js/ai_assistant_widget.js",
    # Chunk 7.5 — the "Trade a Saturday" dialog, shared by the Shift Assignment
    # list view (7.3) and the roster page (7.5). It has to be global because
    # `doctype_list_js` takes one file per doctype and `page_js` one per page,
    # so neither can serve both callers. Two copies of a dialog that FILES
    # DOCUMENTS drift apart silently, which is the worse trade.
    "/assets/caf/js/shift_trade.js",
    # MG, 2026-08-14 — department background colours on the stock organisational
    # chart (each card = one employee). MutationObserver decorates cards as they
    # render; employees without a department keep the default background.
    "/assets/caf/js/org_chart_dept_colors.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/caf/css/caf.css"
# web_include_js = "/assets/caf/js/caf.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "caf/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_list_js = {
    "Material Request" : "public/js/material_request_list.js",
    # Hosts the "Create Monthly Cycles for Year" button (D39). Creating 12
    # documents is an action, not a setting, and the list view is where HR
    # already goes to look at cycles.
    "Appraisal Cycle": "public/js/appraisal_cycle_list.js",
    # Q5 - workflow_state indicators + per-state sidebar counts. Under D54 both
    # Draft and Pending HR Review are docstatus 0, so the stock indicator cannot
    # distinguish them.
    "Appraisal": "public/js/appraisal_list.js",
    # Chunk 7.3 — hosts "Trade a Saturday" (OD-65). Filing a trade is an action,
    # and the list is where HR already goes to look at assignments.
    "Shift Assignment": "public/js/shift_assignment_list.js",
}
page_js = {"ai-assistant" : "public/js/ai_assistant.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "caf.utils.jinja_methods",
# 	"filters": "caf.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "caf.install.before_install"
# after_install = "caf.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "caf.uninstall.before_uninstall"
# after_uninstall = "caf.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "caf.utils.before_app_install"
# after_app_install = "caf.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "caf.utils.before_app_uninstall"
# after_app_uninstall = "caf.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "caf.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------
scheduler_events = {
      "cron": {
        "0 9 * * *": [
            "caf.caf.overrides.work_order.send_work_order_daly_report"
        ],
        # CAF N1 (2026-08-13) - plan §4378. 1 November, 08:00. Builds next
        # year's skeleton (the public-holiday list HR fills in, the Leave Period
        # and 12 Appraisal Cycles) and notifies every HR Manager that the gazette
        # dates are missing. Was specced, promised to HR in writing, and until
        # today `scheduler_events` held exactly one unrelated job.
        # ⚠️ The month is ALSO guarded in Python (`november_rollover_job`), because
        # a cron expression is easy to edit and hard to test.
        "0 8 1 11 *": [
            "caf.caf.scheduled.november_rollover_job"
        ],
        # CAF N2 (2026-08-13) - MG: "notify anyone with HR Manager role". Monday
        # 07:00. The three roster detectors already existed and the roster page
        # already shows them; what did not exist was anybody being TOLD. Silent
        # when nothing is found (SCHED-QUIET) - a weekly ping every week is one
        # HR learns to filter.
        "0 7 * * 1": [
            "caf.caf.scheduled.weekly_roster_check"
        ],
        # CAF (2026-08-18) - the safety net FBR44 leaves open. Import is a human
        # act, and its stated fallback is that employees notice the gap in their
        # Finger Log calendar and complain - a real feedback loop, but a slow one.
        # This asks one question at 16:00: is there a completed batch covering
        # yesterday? Silent when there is, which is most days.
        #
        # 🔴 It never touches the Ingress machine, deliberately. Natalie is a
        # desktop that sleeps on inactivity, so any check needing HER to answer
        # would be unreliable exactly when it matters most.
        #
        # 16:00 rather than the morning: the PC may only just have been switched
        # on at 09:00, and reminding somebody before they could plausibly have
        # done the job is how a reminder loses its meaning.
        "0 16 * * *": [
            "caf.caf.ingress.reminder.daily_import_check"
        ]
    }
}
# scheduler_events = {
# 	"all": [
# 		"caf.tasks.all"
# 	],
# 	"daily": [
# 		"caf.tasks.daily"
# 	],
# 	"hourly": [
# 		"caf.tasks.hourly"
# 	],
# 	"weekly": [
# 		"caf.tasks.weekly"
# 	],
# 	"monthly": [
# 		"caf.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "caf.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "caf.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "caf.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["caf.utils.before_request"]
# after_request = ["caf.utils.after_request"]

# Job Events
# ----------
# before_job = ["caf.utils.before_job"]
# after_job = ["caf.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"caf.auth.validate"
# ]
# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "caf",
# 		"logo": "/assets/caf/logo.png",
# 		"title": "Caf",
# 		"route": "/caf",
# 		"has_permission": "caf.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/caf/css/caf.css"
# app_include_js = "/assets/caf/js/caf.js"

# include js, css files in header of web template
# web_include_css = "/assets/caf/css/caf.css"
# web_include_js = "/assets/caf/js/caf.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "caf/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "caf/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "caf.utils.jinja_methods",
# 	"filters": "caf.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "caf.install.before_install"
# after_install = "caf.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "caf.uninstall.before_uninstall"
# after_uninstall = "caf.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "caf.utils.before_app_install"
# after_app_install = "caf.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "caf.utils.before_app_uninstall"
# after_app_uninstall = "caf.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "caf.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"caf.tasks.all"
# 	],
# 	"daily": [
# 		"caf.tasks.daily"
# 	],
# 	"hourly": [
# 		"caf.tasks.hourly"
# 	],
# 	"weekly": [
# 		"caf.tasks.weekly"
# 	],
# 	"monthly": [
# 		"caf.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "caf.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "caf.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "caf.task.get_dashboard_data"
# }

assistant_tools = []

override_doctype_dashboards = {
    "Purchase Receipt": "caf.caf.overrides.purchase_receipt_dashboard.get_data",
    "Stock Entry": "caf.caf.overrides.stock_entry_dashboard.get_data",
    "Job Card": "caf.caf.overrides.job_card_dashboard.get_data",
    "Work Order": "caf.caf.overrides.work_order_dashboard.get_data",
    "Task": "caf.caf.overrides.task_dashboard.get_data",
    "Item": "caf.caf.overrides.item_dashboard.get_data",
    "Material Request": "caf.caf.overrides.material_request_dashboard.get_data",
    # Chunk 7.5 (OD-72, placement a). hrms' own Shift Type dashboard links
    # Shift Assignment but not Employee, so the standing population — the
    # larger, more stable answer to "who is on this shift" — was invisible from
    # the shift itself.
    "Shift Type": "caf.caf.overrides.shift_type_dashboard.get_data",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["caf.utils.before_request"]
# after_request = ["caf.utils.after_request"]

# Job Events
# ----------
# before_job = ["caf.utils.before_job"]
# after_job = ["caf.utils.after_job"]
doc_events = {
    "Stock Entry": {
        "before_submit": "caf.caf.overrides.stock_entry.sync_bundle_with_qty"
    },
    # CAF appraisal (2026-08-05)
    "Employee": {
        # D15/D51 - reports_to is what decides who may appraise whom, so it is
        # mandatory except for the org roots
        "validate": "caf.caf.overrides.employee.ensure_reports_to"
    },
    "HR Settings": {
        # D69 - reject leave codes that do not exist in live Finger Log data
        "validate": "caf.caf.overrides.hr_settings.validate_leave_codes"
    },
    "Appraisal Template": {
        # D83 - a template omitting Attendance / Punctuality / OT Hours drops
        # that measurement silently, because auto-fill matches rows by KRA name
        "validate": "caf.caf.overrides.appraisal_template.warn_on_missing_auto_fill_kras"
    },
    # Fix session 2026-08-15, D-12 - a leave-owned Attendance row may only be
    # un-decided by cancelling the leave itself; a direct cancel silently drops
    # the day from the appraisal count while the leave stays Approved (FDR4 /
    # OD-60). Machine paths (FL cascade, re-resolve) set the skip flag.
    "Attendance": {
        "before_cancel": "caf.caf.attendance_verdict.block_cancel_of_leave_owned_day",
    },
    # CAF Chunk 5 (2026-08-10) - OD-44 / FBR39. A leave approved after the
    # appraisal was submitted has to reach the appraisal, or the two documents
    # disagree permanently.
    #   before_submit - REFUSE if the FBR39 window has closed. It must be
    #                   before_submit: Frappe writes docstatus=1 before on_submit
    #                   runs, so refusing there leaves the doc submitted AND
    #                   rejected (the Chunk 3 trap).
    #   on_submit     - refresh, and never throw: a throw here would roll back an
    #                   approved leave over a downstream display cell.
    #   on_cancel     - OD-60, the other direction. Stock's cancel_attendance()
    #                   db_sets docstatus=2, which ERASES the day rather than
    #                   reverting it: the Absent that stood there before the
    #                   leave does not come back. The day is restored from its
    #                   Finger Log first, THEN the appraisal reads it. No FBR39
    #                   gate here by decision - cancelling corrects the record,
    #                   it does not ask for something new.
    # 🔴 MG's requirement, 2026-08-13. Editing the public-holiday list has to move
    # the alternate-Saturday calendars with it, or the sequence "runs away" —
    # OD-71's hazard. Measured (§6.13a): only a SATURDAY holiday moves the
    # sequence, and it flips every Saturday after it to year end, reversibly.
    # ⚠️ The handler repoints Shift Types deliberately: a flip can swing the
    # list's own NAME between `1st-3rd` and `2nd-4th`, and a shift left on the old
    # name would silently receive its MIRROR's calendar.
    "Holiday List": {
        "on_update": "caf.caf.holiday_lists.on_public_holidays_changed",
    },
    # 🔴 MG's "make it costly" gate, OD-71. Ingress can still be downloaded and
    # the log can still be SAVED - only submit waits, so the draft is HR's queue,
    # the same shape as OD-58's Not Full Day.
    # ⚠️ OFF until `HR Settings.caf_roster_gate_from` is set. Every imported July
    # row and every test fixture predates the form, so an ungated version would
    # refuse the whole existing dataset. It is keyed on the WORK DATE's month,
    # never on today.
    "Finger Log": {
        "before_submit": "caf.caf.doctype.monthly_roster_confirmation"
                         ".monthly_roster_confirmation.require_confirmed_month",
        # Fix session 2026-08-15, D-15 - FL corrections reach the appraisal like
        # the leave / Shift Assignment triggers. doc_events run AFTER the
        # controller methods, so the Attendance is already created (on_submit,
        # finger_log.py:93-95) or cancelled (on_cancel, cancel_attendance) when
        # these read the day.
        "on_submit": "caf.caf.finger_log_scope.refresh_appraisal_on_submit",
        "on_cancel": "caf.caf.finger_log_scope.refresh_appraisal_on_cancel",
    },
    "Leave Application": {
        # CAF Chunk 6c (2026-08-13) - E7. Stock counts leave days against the
        # employee's STATIC Holiday List, which cannot know that a swap moved
        # which shift applies on a given date. This recounts the span through
        # resolve_day_type(). ⚠️ It MUST stay a `validate` hook: doc_events run
        # AFTER the controller's own validate, which is what lets it overwrite
        # the stock figure. The ledger derives from `total_leave_days`, so
        # correcting the document corrects the balance.
        "validate": "caf.caf.leave_days.recount_leave_days",
        "before_submit": "caf.caf.appraisal_refresh.check_leave_window",
        "on_submit": "caf.caf.appraisal_refresh.on_leave_application_submit",
        "on_cancel": "caf.caf.appraisal_refresh.on_leave_application_cancel",
    },
    # CAF Chunk 4 (2026-08-10) - OD-40. A swap filed AFTER the date has to reach
    # back and correct what that day meant: day_type, shift_type and the OT that
    # hangs off them. The punches are never touched (FDR10).
    "Shift Assignment": {
        # A list, and the order is the contract: re_resolve fixes Attendance
        # first, then the appraisal reads it. Reversed, the appraisal would
        # recompute from the stale verdict.
        # 🔴 MG's guard, 2026-08-13, simulated before it was written. A leave's
        # day count is fixed when it is approved and NOTHING recomputes it, so an
        # assignment filed over approved leave leaves a stale number standing.
        # before_submit, not on_submit: refusing in on_submit leaves the document
        # submitted AND rejected (the Chunk 3 trap, noted above).
        "before_submit": "caf.caf.shift_swap.block_swap_on_leave",
        "on_submit": [
            "caf.caf.re_resolve.on_shift_assignment_submit",
            "caf.caf.appraisal_refresh.on_shift_assignment_refresh",
        ],
        # before_cancel clears stock's validate_attendance() guard, which refuses
        # the cancel while any Attendance carries this shift - and does not even
        # filter on docstatus. Without it a swap could be filed but never unfiled.
        # 🔴 `unlink_pair` must run here too, and for a different reason:
        # `caf_swap_partner` is a real Link, and Frappe's link check fires on
        # CANCEL, not only on delete. Without it, one half of a swap can never be
        # cancelled alone — LinkExistsError, naming two document IDs and
        # explaining nothing — which makes MG's "inform HR, then let them cancel
        # one or both" impossible. The warning belongs in the dialog; the database
        # should not be the thing refusing.
        # ⚠️ `block_cancel_on_leave` runs FIRST, before anything mutates. The two
        # handlers after it clear links and references, and a refusal that fired
        # after them would leave the document uncancelled with its pairing
        # already broken - the half-configured state half_done_swaps() exists to
        # find.
        "before_cancel": [
            "caf.caf.shift_swap.block_cancel_on_leave",
            "caf.caf.re_resolve.before_shift_assignment_cancel",
            "caf.caf.shift_swap.unlink_pair",
        ],
        # Same ordering contract as on_submit: the day reverts, then the
        # appraisal reads it (OD-60).
        "on_cancel": [
            "caf.caf.re_resolve.on_shift_assignment_cancel",
            "caf.caf.appraisal_refresh.on_shift_assignment_refresh",
        ],
    },
}

# CAF appraisal permission layer (D18/D55/D56). Both are module-level functions,
# NOT methods on the controller class: frappe/model/db_query.py:867 and
# frappe/permissions.py:450 call them by dotted path.
#   permission_query_conditions -> read layer / list filtering (the subtree)
#   has_permission              -> write layer / per-document check
permission_query_conditions = {
    "Appraisal": "caf.caf.overrides.appraisal.get_permission_query_conditions",
    # CAF Chunk 6b (2026-08-13) - OD-82. The `Leave Approver` role is BLANKET:
    # measured, a Leave Approver who was NOT the employee's approver read, wrote
    # and SUBMITTED their leave. Role = the door, hook = the lock — the same
    # shape the Appraisal already uses, pointed at `leave_approver` instead of
    # `reports_to`. A Workflow Transition's "Allowed" column takes a ROLE and
    # never a person, so the workflow cannot do this by itself.
    "Leave Application":
        "caf.caf.overrides.leave_application.get_permission_query_conditions",
    # Fix session 2026-08-15, D-1/AC-1 - Employee read on Finger Log, scoped to
    # their own rows (OD-63 option d). Finger Log.employee is a Link since D-6,
    # but the User Permission mechanism is a data setup we cannot assume every
    # site has - this is the enforcement.
    "Finger Log": "caf.caf.finger_log_scope.get_permission_query_conditions",
}

has_permission = {
    "Appraisal": "caf.caf.overrides.appraisal.has_permission",
    "Leave Application": "caf.caf.overrides.leave_application.has_permission",
    # Fix session 2026-08-15, D-1/AC-1 - per-doc read check for Finger Log.
    "Finger Log": "caf.caf.finger_log_scope.has_permission",
}
# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"caf.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

after_migrate = ["caf.setup.add_manufacturing_fields"]

# Fixtures
# Custom DocPerm added 2026-08-05 for the CAF appraisal project (plan D33/D41/D40/D43/D66).
# Permission changes live in Custom DocPerm records, not code, so without this
# they exist on the dev site only and never reach production. The filter is
# deliberately narrow - only the doctypes this project touches. Note that
# touching one permission converts a doctype's WHOLE grid to Custom DocPerm,
# so the export captures the stock rows too, which is what makes the site's
# permission state reproducible.
# No Role fixture: D55 dropped the Appraisal Supervisor role, so this project
# creates no role at all.
fixtures = [
    {"dt": "Property Setter"},
    {"dt": "Custom Field"},
    {
        "dt": "Custom DocPerm",
        "filters": [
            [
                "parent",
                "in",
                [
                    "Appraisal",
                    "Appraisal Cycle",
                    "Employee Performance Feedback",
                    "Finger Log",
                    "HR Settings",
                    "KRA",
                    # Added 2026-08-12 with R3. Without it MG's "restrict write,
                    # keep read" rule lived ONLY in the site database — the exact
                    # drift D71 records, where CAF's Leave Application workflow
                    # existed nowhere else and no one knew until it was looked for.
                    # ⚠️ Custom DocPerm REPLACES DocPerm per doctype, so this
                    # fixture must stay complete: dropping a role here removes it.
                    "Shift Assignment",
                ],
            ]
        ],
    },
    # The Workflow and its supporting records (D58/D72, section 9.2). These are
    # DATABASE records, not code - `bench migrate` does not carry them, and a
    # missing Workflow raises NO error: Frappe simply applies none, so
    # appraisals submit straight through with no HR review and nobody is told.
    # Shipping them as fixtures means a fresh site gets the workflow
    # automatically; the deploy script still asserts it afterwards.
    #
    # ⚠️ DRIFT WARNING for the admin guide: editing the workflow live is
    # legitimate and is the whole point of the engine (e.g. adding an
    # accounts-review step). But whoever does it must re-export this fixture, or
    # git and reality diverge - which is exactly how CAF's existing Leave
    # Application workflow came to live only in the site database (D71).
    {
        "dt": "Workflow",
        "filters": [["name", "in", ["CAF Appraisal Workflow"]]],
    },
    {
        "dt": "Workflow State",
        "filters": [["name", "in", ["Draft", "Pending HR Review", "Completed"]]],
    },
    {
        "dt": "Workflow Action Master",
        "filters": [["name", "in", ["Submit for Review", "Approve", "Reject"]]],
    },
]
