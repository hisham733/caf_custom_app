frappe.provide("caf.training_result");

const SCALE_MARKER_START = "Very Poor: 1";
const SCALE_MARKER_END = "Excellent: 5";

function get_scale_criteria() {
	const meta = frappe.get_meta("Training Result Employee");
	if (!meta || !meta.fields) return [];
	return meta.fields
		.filter(
			(df) =>
				df.fieldtype === "Select" &&
				df.options &&
				df.options.includes(SCALE_MARKER_START) &&
				df.options.includes(SCALE_MARKER_END)
		)
		.map((df) => df.fieldname);
}

function score_of_option(value) {
	if (!value) return 0;
	const parts = String(value).split(":");
	const num = parseInt(parts[parts.length - 1], 10);
	return isNaN(num) ? 0 : num;
}

function grade_of_total(total) {
	if (total >= 36) return "Very Good";
	if (total >= 30) return "Good";
	if (total >= 20) return "Ordinary";
	return "Bad";
}

function recalculate_employee_row(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const criteria = get_scale_criteria();
	let total = 0;
	criteria.forEach((fieldname) => {
		total += score_of_option(row[fieldname]);
	});
	row.custom_total_marks = total;
	row.custom_result = grade_of_total(total);
	frm.refresh_field("employees");
}

function esc(value) {
	return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function scale_parts(value) {
	const parts = String(value || "").split(":");
	const score = score_of_option(value);
	const rating = parts.length > 1 ? parts[0].trim() : parts[0];
	return { rating, score };
}

function get_criteria_meta() {
	return get_scale_criteria().map((fieldname) => {
		const df = frappe.meta.get_docfield("Training Result Employee", fieldname);
		return { fieldname, label: df && df.label ? df.label : fieldname };
	});
}

const GRADE_CLASS_MAP = {
	"Very Good": "grade-very-good",
	Good: "grade-good",
	Ordinary: "grade-ordinary",
	Bad: "grade-bad",
};

function build_evaluation_html(row, frm) {
	const criteria_rows = get_criteria_meta()
		.map((c, i) => {
			const p = scale_parts(row[c.fieldname]);
			const zebra = i % 2 === 1 ? " zebra" : "";
			return (
				`<tr class="crit-row${zebra}">` +
				`<td class="crit-idx">${i + 1}</td>` +
				`<td class="crit-label">${esc(c.label)}</td>` +
				`<td class="crit-rating"><span class="chip">${esc(p.rating)}</span></td>` +
				`<td class="crit-score">${p.score}</td>` +
				`</tr>`
			);
		})
		.join("");

	const overall = [
		["custom_exceeded_my_expectation", "Exceeded my expectation"],
		["custom_met_my_expectation", "Met my expectation"],
		["custom_failed_to_meet_my_expectation", "Failed to meet my expectation"],
	];
	const overall_rows = overall
		.map(
			([f, label]) =>
				`<div class="assessment-row ${row[f] ? "is-on" : ""}">` +
				`<span class="assess-dot">${row[f] ? "●" : "○"}</span>` +
				`<span class="assess-label">${esc(label)}</span>` +
				`<span class="badge ${row[f] ? "yes" : "no"}">${row[f] ? "Yes" : "No"}</span>` +
				`</div>`
		)
		.join("");

	const info_items = [
		["Employee", `${row.employee_name || ""}${row.employee ? " · " + row.employee : ""}`],
		["Department", row.department || "—"],
		["Training Event", frm.doc.training_event || "—"],
		["Training Attend", frm.doc.custom_training_attend || "—"],
		["Duration", frm.doc.custom_duration ? `${frm.doc.custom_duration} hrs` : "—"],
	];
	const info_html = info_items
		.map(
			([k, v]) =>
				`<div class="info-item"><div class="info-label">${esc(k)}</div><div class="info-value">${esc(v)}</div></div>`
		)
		.join("");

	const total = row.custom_total_marks || 0;
	const result = row.custom_result || "";
	const result_class = GRADE_CLASS_MAP[result] || "grade-neutral";

	return (
		`<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<title>Training Evaluation Report</title>
	<style>
		* { box-sizing: border-box; }
		body { margin: 0; padding: 0 0 24px; font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color: #0f172a; background: #fff; font-size: 13px; }
		.sheet { max-width: 820px; margin: 0 auto; }

		.topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 20px 24px; background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); color: #fff; border-radius: 0 0 14px 14px; }
		.topbar .brand { font-size: 16px; letter-spacing: .3px; opacity: .92; }
		.topbar .doctitle { font-size: 22px; font-weight: 700; margin-top: 2px; }
		.topbar .formno { flex: 0 0 auto; background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); padding: 6px 12px; border-radius: 999px; font-size: 11px; letter-spacing: .5px; white-space: nowrap; }

		.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 18px; margin: 14px 18px 0; box-shadow: 0 1px 2px rgba(15,23,42,.04); }
		.sect-title { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px; color: #0f766e; margin-bottom: 12px; }
		.sect-title::before { content: ""; width: 10px; height: 10px; border-radius: 3px; background: #0f766e; }

		.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 24px; }
		.info-item .info-label { font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #64748b; margin-bottom: 2px; }
		.info-item .info-value { font-size: 14px; font-weight: 600; }

		table.crit { width: 100%; border-collapse: collapse; }
		table.crit thead th { background: #f8fafc; color: #64748b; font-size: 10px; text-transform: uppercase; letter-spacing: .6px; text-align: left; padding: 8px 10px; border-bottom: 1px solid #e2e8f0; }
		table.crit thead th:first-child { text-align: center; width: 36px; }
		table.crit td { padding: 9px 10px; border-bottom: 1px solid #e2e8f0; }
		table.crit .crit-idx { color: #64748b; font-weight: 600; text-align: center; }
		table.crit .crit-label { font-weight: 600; }
		table.crit .crit-rating { text-align: center; }
		table.crit .crit-score { text-align: center; font-weight: 700; }
		table.crit .zebra td { background: #fcfdff; }

		.chip { display: inline-block; padding: 2px 10px; border-radius: 999px; background: #ccfbf1; color: #115e59; font-size: 12px; font-weight: 600; }

		.stat-row { display: flex; gap: 14px; margin-top: 14px; }
		.stat { flex: 1; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; text-align: center; }
		.stat .stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #64748b; margin-bottom: 4px; }
		.stat .num { font-size: 26px; font-weight: 800; }
		.stat.total .num { color: #0f766e; }
		.grade-very-good .num { color: #15803d; }
		.grade-good .num { color: #2563eb; }
		.grade-ordinary .num { color: #d97706; }
		.grade-bad .num { color: #dc2626; }
		.grade-neutral .num { color: #64748b; }

		.overall { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
		.assessment-row { display: flex; align-items: center; gap: 8px; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; background: #f8fafc; }
		.assess-dot { font-size: 14px; color: #cbd5e1; }
		.assessment-row.is-on { background: #f0fdf4; border-color: #bbf7d0; }
		.assessment-row.is-on .assess-dot { color: #22c55e; }
		.assess-label { flex: 1; font-size: 12px; font-weight: 600; }
		.badge { padding: 2px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; }
		.badge.yes { background: #dcfce7; color: #15803d; }
		.badge.no { background: #fee2e2; color: #b91c1c; }

		.comments { min-height: 70px; border: 1px dashed #cbd5e1; border-radius: 10px; padding: 12px; background: #f8fafc; white-space: pre-wrap; }

		.footer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; padding: 8px 18px 32px; }
		.sign-block .sign-label { font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #64748b; margin-bottom: 4px; }
		.sign-block .sign-value { font-size: 14px; font-weight: 700; padding-bottom: 6px; border-bottom: 1px solid #0f172a; min-height: 24px; }
		.sign-block.right { text-align: right; }

		@media print {
			body { background: #fff; }
			.topbar { border-radius: 0; }
			@page { size: A4; margin: 12mm; }
		}
	</style>
</head>
<body>
	<div class="sheet">
		<div class="topbar">
			<div>
				<div class="brand">CAF Food Products Sdn Bhd</div>
				<div class="doctitle">Training Evaluation Report</div>
			</div>
			<div class="formno">HR-PR-01-F &nbsp;·&nbsp; REV 00</div>
		</div>

		<div class="card">
			<div class="sect-title">Employee Details</div>
			<div class="info-grid">${info_html}</div>
		</div>

		<div class="card">
			<div class="sect-title">1 · Performance Evaluation</div>
			<table class="crit">
				<thead>
					<tr>
						<th>#</th>
						<th>Criteria</th>
						<th style="text-align:center;">Rating</th>
						<th style="text-align:center;">Marks</th>
					</tr>
				</thead>
				<tbody>${criteria_rows}</tbody>
			</table>
			<div class="stat-row">
				<div class="stat total">
					<div class="stat-label">Total Marks</div>
					<div class="num">${total}</div>
				</div>
				<div class="stat ${result_class}">
					<div class="stat-label">Result</div>
					<div class="num">${esc(result)}</div>
				</div>
			</div>
		</div>

		<div class="card">
			<div class="sect-title">2 · Overall Assessment</div>
			<div class="overall">${overall_rows}</div>
		</div>

		<div class="card">
			<div class="sect-title">3 · Comments</div>
			<div class="comments">${esc(row.comments)}</div>
		</div>

		<div class="footer-grid">
			<div class="sign-block">
				<div class="sign-label">Submitted by</div>
				<div class="sign-value">${esc(frm.doc.custom_submitted_by)}</div>
				<div class="sign-label" style="margin-top:10px;">Submitted Date</div>
				<div class="sign-value">${esc(frm.doc.custom_submitted_date)}</div>
			</div>
			<div class="sign-block right">
				<div class="sign-label">Reviewed by HR Head</div>
				<div class="sign-value">${esc(frm.doc.custom_reviewed_by_hr_head)}</div>
				<div class="sign-label" style="margin-top:10px;">Date</div>
				<div class="sign-value">${esc(frm.doc.custom_date)}</div>
			</div>
		</div>
	</div>
</body>
</html>`
	);
}

function print_html_evaluation(row, frm) {
	const w = window.open("", "_blank", "width=900,height=760");
	if (!w) {
		frappe.msgprint(__("Pop-up was blocked. Please allow pop-ups for this site and try again."));
		return;
	}
	w.document.write(build_evaluation_html(row, frm));
	w.document.close();
	setTimeout(() => {
		w.focus();
		w.print();
	}, 350);
}

function open_print_dialog(frm) {
	const employees = (frm.doc.employees || []).filter((r) => r.employee);
	if (!employees.length) {
		frappe.msgprint(__("No employees found in the Training Result."));
		return;
	}
	const options = employees.map((r, i) => ({
		label: `${r.employee_name || r.employee} (${r.employee})`,
		value: String(i),
	}));
	const dlg = new frappe.ui.Dialog({
		title: __("Select Employee"),
		fields: [
			{
				fieldname: "employee",
				fieldtype: "Select",
				label: __("Employee"),
				options: options,
				reqd: 1,
			},
		],
		primary_action_label: __("Print"),
		primary_action(values) {
			const row = employees[parseInt(values.employee, 10)];
			if (row) {
				dlg.hide();
				print_html_evaluation(row, frm);
			}
		},
	});
	dlg.show();
}

frappe.ui.form.on("Training Result", {
	refresh: function (frm) {
		frm.refresh_field("employees");
		frm.add_custom_button(__("Print Evaluation"), () => open_print_dialog(frm), __("Print"));
	},
});

const criteria_handlers = {};
get_scale_criteria().forEach((fieldname) => {
	criteria_handlers[fieldname] = function (frm, cdt, cdn) {
		recalculate_employee_row(frm, cdt, cdn);
	};
});

frappe.ui.form.on("Training Result Employee", criteria_handlers);