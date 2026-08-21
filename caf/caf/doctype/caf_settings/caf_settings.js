// Copyright (c) 2026, hisham and contributors
// For license information, please see license.txt

frappe.ui.form.on("Caf Settings", {
	test_waha: function (frm) {
		var chat_ids = (frm.doc.waha_chat_ids || "").split("\n").map(function (c) {
			return c.trim();
		}).filter(Boolean);

		if (!frm.doc.waha_base_url) {
			frappe.msgprint(__("Please enter a WhatsApp Base URL first."));
			return;
		}
		if (!chat_ids.length) {
			frappe.msgprint(__("Please enter at least one WhatsApp Chat ID first."));
			return;
		}

		frappe.call({
			method: "caf.caf.utils.notifications.send_test_whatsapp",
			args: {
				base_url: frm.doc.waha_base_url,
				chat_ids: frm.doc.waha_chat_ids || "",
				api_key: frm.doc.waha_api_key || "",
			},
			freeze: true,
			freeze_message: __("Sending test message…"),
			callback: function (r) {
				if (r.message && r.message.success) {
					frappe.show_alert({ message: r.message.message, indicator: "green" });
				} else {
					frappe.msgprint(r.message ? r.message.message : __("Test failed"));
				}
			},
			error: function () {
				frappe.msgprint(__("Test failed. Check the WAHA config and try again."));
			},
		});
	},

	test_telegram: function (frm) {
		var chat_ids = (frm.doc.telegram_chat_ids || "").split("\n").map(function (c) {
			return c.trim();
		}).filter(Boolean);

		if (!chat_ids.length) {
			frappe.msgprint(__("Please enter at least one Telegram Chat ID first."));
			return;
		}
		if (!frm.doc.telegram_bot_token) {
			frappe.msgprint(__("Please enter a Telegram Bot Token first."));
			return;
		}

		frappe.call({
			method: "caf.caf.utils.notifications.send_test_telegram",
			args: {
				bot_token: frm.doc.telegram_bot_token || "",
				chat_ids: frm.doc.telegram_chat_ids || "",
			},
			freeze: true,
			freeze_message: __("Sending test message…"),
			callback: function (r) {
				if (r.message && r.message.success) {
					frappe.show_alert({ message: r.message.message, indicator: "green" });
				} else {
					frappe.msgprint(r.message ? r.message.message : __("Test failed"));
				}
			},
			error: function () {
				frappe.msgprint(__("Test failed. Check the Telegram config and try again."));
			},
		});
	},
});
