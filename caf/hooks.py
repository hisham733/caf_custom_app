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
}
doctype_js = {
    "Job Card": "public/js/job_card.js",
    "Work Order": "public/js/work_order.js",
    "Production Plan": "public/js/production_plan.js",
    "Stock Entry": "public/js/stock_entry.js",
    "Quality Review": "public/js/quality_review.js",
    "Leave Application": "public/js/leave_application.js",
    "BOM":"public/js/bom.js",
    "Purchase Receipt":"public/js/purchase_receipt.js",
    "Material Request":"public/js/material_request.js",
    "Task":"public/js/task.js"
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
app_include_css = ["/assets/caf/css/ai_assistant.css", "/assets/caf/css/settings_cards.css"]
app_include_js = ["/assets/caf/js/ai_assistant_widget.js"]

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
doctype_list_js = {"Material Request" : "public/js/material_request_list.js"}
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
        "0 8-18 * * *": [
            "caf.caf.utils.shortage_report.send_shortage_warning"
        ],
        "* 5-12 * * *": [
            "caf.caf.utils.morning_dispatcher.run_due_reports"
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
    "Material Request": "caf.caf.overrides.material_request_dashboard.get_data"
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
    }
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
fixtures = [
    {"dt": "Property Setter"},
    {"dt": "Custom Field"},
]
