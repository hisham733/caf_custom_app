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

function date_only(value) {
	const s = String(value || "").replace("T", " ").trim();
	return s.split(" ")[0];
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
	const scale_scores = [1, 2, 3, 4, 5];
	const criteria_rows = get_criteria_meta()
		.map((c, i) => {
			const p = scale_parts(row[c.fieldname]);
			const cells = scale_scores
				.map(
					(n) =>
						`<td class="num"><span class="rate-num ${p.score === n ? "circled" : ""}">${n}</span></td>`
				)
				.join("");
			return (
				`<tr>` +
				`<td class="crit-no">${i + 1}</td>` +
				`<td class="crit-label"><span class="head">${esc(c.label)}</span></td>` +
				cells +
				`</tr>`
			);
		})
		.join("");

	const overall_rows = [
		["custom_exceeded_my_expectation", "Exceeded my expectation"],
		["custom_met_my_expectation", "Met my expectation"],
		["custom_failed_to_meet_my_expectation", "Failed to meet my expectation"],
	]
		.map(
			([f, label]) =>
				`<div class="tick-item"><span class="tick-box">${row[f] ? "✓" : ""}</span>${esc(label)}</div>`
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
	const RESULT_BANDS = [
		{ grade: "Very Good", marks: "36-40 Marks", label: "Very good" },
		{ grade: "Good", marks: "30-35 Marks", label: "Good" },
		{ grade: "Ordinary", marks: "20-29 Marks", label: "Ordinary" },
		{ grade: "Bad", marks: "0 - 20 Marks", label: "Bad" },
	];
	const result_rows = RESULT_BANDS.filter((b) => b.grade === result)
		.map(
			(b) =>
				`<div class="result-row"><span class="band">${b.marks}</span><span>${b.label}</span></div>`
		)
		.join("");

	return (
		`<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<title>Training Evaluation Report</title>
	<style>
		* { box-sizing: border-box; }
		html, body { margin: 0; padding: 0; }
		body {
			font-family: "Times New Roman", Times, serif;
			color: #000;
			font-size: 11.5px;
			line-height: 1.3;
			background: #d9d9d9;
			padding: 18px 12px;
		}

		.sheet {
			max-width: 760px;
			width: 100%;
			margin: 0 auto;
			background: #fff;
			box-shadow: 0 1px 3px rgba(0,0,0,.15), 0 8px 20px rgba(0,0,0,.12);
			padding: 20px 28px 16px;
		}

		.doc-header { display: flex; justify-content: space-between; font-size: 10.5px; margin-bottom: 8px; }

		.company { text-align: center; font-size: 20px; margin: 0 0 4px; }
		.report-title { text-align: center; font-size: 14px; font-weight: 700; text-decoration: underline; letter-spacing: .5px; margin-bottom: 6px; }
		.instruction { font-style: italic; font-size: 11.5px; margin-bottom: 6px; }

		.outer-box { border: 1.5px solid #000; }

		.emp-box { padding: 6px 12px; }
		.info-grid { display: flex; flex-direction: column; gap: 4px; }
		.info-item .info-label { font-weight: 700; }
		.info-item .info-value { font-weight: 400; }

		.section-band { border-top: 1.5px solid #000; border-bottom: 1px solid #000; text-align: center; font-weight: 700; font-size: 11.5px; padding: 3px 0; }

		table.crit { width: calc(100% - 16px); border-collapse: collapse; font-size: 11px; }
		table.crit td, table.crit th { padding: 2px 4px; vertical-align: middle; }
		table.crit tr { page-break-inside: avoid; break-inside: avoid; }
		table.crit thead .circle-hdr { text-align: center; font-weight: 400; border-bottom: 1px solid #000; padding-bottom: 1px; }
		table.crit thead .col-label { text-align: center; font-weight: 400; padding-top: 1px; font-size: 10px; }
		table.crit .crit-no { width: 30px; text-align: center; }
		table.crit .crit-label .head { font-weight: 700; font-style: italic; }
		table.crit td.num { text-align: center; width: 44px; }

		.rate-num { display: inline-block; width: 18px; text-align: center; }
		.rate-num.circled {
			border: 1.5px solid #000;
			border-radius: 50%;
			width: 20px; height: 20px;
			line-height: 17px;
			background: #000; color: #fff;
			font-weight: 700;
		}

		.total-row { display: flex; justify-content: flex-end; gap: 30px; padding: 4px 16px 1px 0; font-weight: 700; font-size: 11.5px; }

		.result-block { padding: 2px 16px 6px 0; font-size: 11.5px; text-align: right; }
		.result-title { font-weight: 700; text-decoration: underline; margin-bottom: 1px; }
		.result-row { display: flex; gap: 10px; justify-content: flex-end; }
		.result-row .band { width: 88px; }
		.result-row.is-active { font-weight: 700; }

		.section2 { padding: 6px 16px 2px 12px; font-size: 11.5px; }
		.section2 .q { font-weight: 700; font-style: italic; }
		.tick-row { display: flex; gap: 24px; margin-top: 4px; flex-wrap: wrap; }
		.tick-item { display: flex; align-items: center; gap: 5px; }
		.tick-box { width: 14px; height: 14px; border: 1.2px solid #000; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }

		.section3 { padding: 8px 16px 2px 12px; font-size: 11.5px; }
		.section3 .q { font-weight: 700; font-style: italic; margin-bottom: 4px; }
		.dotted-line { border-bottom: 1px dotted #000; min-height: 16px; margin-bottom: 2px; }

		.sign-area { padding: 10px 16px 2px 12px; font-size: 11.5px; }
		.sign-area > div:first-child { font-weight: 700; }
		.sign-line { display: flex; gap: 40px; align-items: flex-end; margin-top: 14px; }
		.sign-line .field { flex: 1; border-bottom: 1px dotted #000; min-height: 12px; }
		.sign-line .field.short { flex: 0 0 200px; }
		.sign-caption { display: flex; gap: 40px; margin-top: 2px; font-size: 11.5px; }
		.sign-caption .cap { flex: 1; }
		.sign-caption .cap.short { flex: 0 0 200px; }

		.hr-band { border-top: 1.5px solid #000; border-bottom: 1px solid #000; font-weight: 700; font-size: 11.5px; padding: 3px 12px; }
		.hr-box { border-bottom: 1.5px solid #000; padding: 8px 12px 4px; min-height: 36px; white-space: pre-wrap; }
		.hr-sign { padding: 2px 12px 8px; }

		@media print {
			html, body { background: #fff !important; }
			body { padding: 0; }
			.sheet { box-shadow: none; max-width: none; padding: 6px 8px; }
			.outer-box { page-break-inside: avoid; break-inside: avoid; }
			@page { size: A4; margin: 9mm 12mm; }
		}
	</style>
</head>
<body>
	<div class="sheet">
		<div class="doc-header">
			<div>FORM NO: HR-PR-01-F</div>
			<div>REV:00 (1/12/2003)</div>
		</div>

		<div class="company">CAF Food Products Sdn Bhd</div>
		<div class="report-title">TRAINING EVALUATION REPORT</div>
		<div class="instruction">This report should be filled by the HOD in order to evaluate their sub-ordinate's competency after attend the training.</div>

		<div class="outer-box">
			<div class="emp-box">
				<div class="info-grid">${info_html}</div>
			</div>

			<div class="section-band">EVALUATION ON THE EMPLOYEE PERFORMANCE AFTER THE TRAINING</div>

			<table class="crit">
				<colgroup>
					<col style="width:34px">
					<col>
					<col style="width:44px"><col style="width:44px"><col style="width:44px"><col style="width:44px"><col style="width:44px">
				</colgroup>
				<thead>
					<tr>
						<td></td>
						<td></td>
						<td colspan="5" class="circle-hdr">Please Circle</td>
					</tr>
					<tr>
						<td></td>
						<td></td>
						<td class="col-label">Very<br>Poor</td>
						<td class="col-label">Poor</td>
						<td class="col-label">Satisfied</td>
						<td class="col-label">Good</td>
						<td class="col-label">Excellent</td>
					</tr>
				</thead>
				<tbody>${criteria_rows}</tbody>
			</table>

			<div class="total-row"><span>Total Marks</span><span>${total}/40</span></div>

			<div class="result-block">
				<div class="result-title">RESULT</div>
				${result_rows}
			</div>

			<div class="section2">
				<span class="q">2. Your overall assessment of the employee :</span>&nbsp;&nbsp;&nbsp;Please Tick (√)
				<div class="tick-row">${overall_rows}</div>
			</div>

			<div class="section3">
				<div class="q">3. Please summarize your comments on your sub-ordinate :</div>
				<div class="dotted-line">${esc(row.comments)}</div>
			</div>

			<div class="sign-area">
				<div>Submitted by</div>
				<div class="sign-caption">
					<div class="cap short">Name : ${esc(frm.doc.custom_submitted_by)}</div>
					<div class="cap short">Date&nbsp;&nbsp;&nbsp;${esc(date_only(frm.doc.custom_submitted_date))}</div>
				</div>
				<div class="sign-line">
					<div class="field short"></div>
					<div class="field short"></div>
				</div>
			</div>

			<div class="hr-band">EVALUATION BY THE HEAD OF HR DEPARTMENT</div>
			<div class="hr-box"></div>
			<div class="hr-sign">
				<div class="sign-caption">
					<div class="cap short">Reviewed by HR Head : ${esc(frm.doc.custom_reviewed_by_hr_head)}</div>
					<div class="cap short">Date&nbsp;&nbsp;&nbsp;${esc(date_only(frm.doc.custom_date))}</div>
				</div>
				<div class="sign-line">
					<div class="field short"></div>
					<div class="field short"></div>
				</div>
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