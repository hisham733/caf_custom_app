// Copyright (c) 2026, CAF and contributors
// The list view is where an import STARTS — there is no "new batch" form to
// fill in, because a batch is a record of a run, not a request for one.

frappe.listview_settings["Ingress Import Batch"] = {
    add_fields: ["status", "purpose", "created", "held", "failed"],

    get_indicator(doc) {
        const map = {
            Running: "orange",
            Completed: doc.failed ? "yellow" : "green",
            Failed: "red",
            Reverted: "grey",
        };
        return [__(doc.status), map[doc.status] || "grey", "status,=," + doc.status];
    },

    onload(listview) {
        listview.page.add_inner_button(__("Import from Ingress"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Import from Ingress"),
                fields: [
                    {
                        fieldname: "from_date", fieldtype: "Date", reqd: 1,
                        label: __("From work date"),
                        default: frappe.datetime.add_days(frappe.datetime.get_today(), -3),
                    },
                    {
                        fieldname: "to_date", fieldtype: "Date", reqd: 1,
                        label: __("To work date"),
                        default: frappe.datetime.add_days(frappe.datetime.get_today(), -1),
                    },
                    { fieldtype: "Column Break" },
                    {
                        fieldname: "purpose", fieldtype: "Select", reqd: 1,
                        label: __("Purpose"), options: "Test\nProduction", default: "Test",
                        description: __("A Test batch can be reverted in one click. A Production batch needs a force."),
                    },
                    {
                        // Default ON — MG, 2026-08-18. The everyday act is
                        // "bring in yesterday and decide it", and a day that
                        // cannot be decided is HELD as a draft regardless of this
                        // box. So leaving it off does not make anything safer; it
                        // only leaves a pile of drafts nobody asked for, and the
                        // real worklist (the held ones) gets lost among them.
                        fieldname: "submit_logs", fieldtype: "Check", default: 1,
                        label: __("Submit the logs"),
                        description: __("On by default. Anything that cannot be decided — missing punches, no OT approval, unconfirmed roster — is held as a draft anyway, and those drafts are your worklist. Untick only to import without deciding anything."),
                    },
                    { fieldtype: "Section Break", label: __("Employees") },
                    {
                        fieldname: "employees", fieldtype: "MultiSelectList",
                        label: __("Limit to"),
                        description: __("Leave empty for EVERY active employee — that is the normal daily import. Name one or more only to redo specific people, e.g. after correcting their punches in Ingress. Type a name or an employee ID."),
                        // 🔴 `frappe.db.get_link_options` filters on `name`, which
                        // for Employee is the ID (HR-EMP-00023) — so typing a
                        // PERSON'S NAME matched nothing and the field looked
                        // broken or permission-filtered. It was neither.
                        // Reported by MG 2026-08-18: typing "rohit" returned
                        // nothing as natalie@.
                        // `search_link` is what an ordinary Link field uses, and
                        // it honours the doctype's search fields, so a name works.
                        get_data(txt) {
                            return frappe.call({
                                method: "frappe.desk.search.search_link",
                                args: {
                                    doctype: "Employee",
                                    txt: txt,
                                    filters: { status: "Active" },
                                },
                            }).then((r) => (r.message || []).map((o) => ({
                                value: o.value,
                                description: o.label && o.label !== o.value
                                    ? o.label : o.description,
                            })));
                        },
                    },
                ],
                primary_action_label: __("Import"),
                primary_action(values) {
                    d.hide();
                    frappe.dom.freeze(__("Reading the Ingress machine…"));
                    frappe.call({
                        method: "caf.caf.doctype.ingress_import_batch.ingress_import_batch.run_manual_import",
                        args: {
                            from_date: values.from_date,
                            to_date: values.to_date,
                            employees: values.employees && values.employees.length
                                ? values.employees : null,
                            submit: values.submit_logs ? 1 : 0,
                            purpose: values.purpose,
                        },
                        callback(r) {
                            frappe.dom.unfreeze();
                            if (!r.message) return;
                            const c = r.message.counts;
                            // 🔴 The FBR49 warning has to appear HERE, not only on
                            // the batch document. A day Ingress has not finished
                            // building imports as half a day — an IN with no OUT —
                            // and it looks like an ordinary held draft. Somebody
                            // who has to think to go and open the batch will not.
                            const stale = (r.message.unprocessed_dates || "").trim();
                            const counts = __("Read {0} · created {1} · updated {2} · submitted {3} · held {4} · already present {5} · human-owned {6} · drift {7} · failed {8}",
                                [c.read_rows, c.created, c.updated, c.submitted, c.held,
                                 c.already_present, c.skipped_locked, c.drift, c.failed]);
                            frappe.msgprint({
                                title: __("Batch {0}", [r.message.batch]),
                                indicator: stale ? "red" : (c.failed ? "orange" : "green"),
                                message: stale
                                    ? `<p style="color:var(--red-600)"><b>${__("⚠️ Ingress had not finished processing these days — punches are MISSING from this import:")}</b></p>
                                       <pre style="white-space:pre-wrap">${frappe.utils.escape_html(stale)}</pre>
                                       <p>${__("Go to Ingress → Attendance Sheet → <b>Generate</b> for those dates, then import again. Until then this day is incomplete.")}</p>
                                       <hr>${counts}`
                                    : counts,
                            });
                            listview.refresh();
                        },
                        error() {
                            frappe.dom.unfreeze();
                        },
                    });
                },
            });
            d.show();
        });

        // 🔴 The button FBR44 makes necessary. With no scheduled fetch, a punch
        // edited on the machine AFTER ERPNext imported that day is invisible
        // forever — nothing re-reads the date, and HR has no way to know which
        // date to ask for. Measured 2026-08-17: 543 rows revised in August,
        // carrying work dates back to January.
        //
        // It REPORTS only. Re-importing on HR's behalf would be the silent
        // auto-correction FBR39/FBR8 exist to prevent, one layer down.
        listview.page.add_inner_button(__("Check for amendments"), () => {
            frappe.call({
                method: "caf.caf.ingress.sync.check_amendments",
                freeze: true,
                freeze_message: __("Asking the machine what changed…"),
                callback(r) {
                    if (!r.message) return;
                    const m = r.message;
                    if (!m.needs_attention) {
                        frappe.msgprint({
                            title: __("Nothing to do"),
                            indicator: "green",
                            message: __("The machine revised {0} row(s) since {1}, and none of them disagree with what ERPNext already holds.",
                                [m.machine_rows_revised, m.checked_since]),
                        });
                        return;
                    }
                    const rows = m.findings.map((f) => `
                        <tr>
                          <td>${frappe.utils.escape_html(f.work_date)}</td>
                          <td>${frappe.utils.escape_html(f.employee_name || f.employee)}</td>
                          <td>${f.verdict.startsWith("SUBMITTED")
                                 ? `<b style="color:var(--red-600)">${frappe.utils.escape_html(f.verdict)}</b>`
                                 : frappe.utils.escape_html(f.verdict)}</td>
                          <td>${frappe.utils.escape_html(f.what_to_do)}</td>
                        </tr>`).join("");
                    frappe.msgprint({
                        title: __("{0} day(s) need attention", [m.needs_attention]),
                        indicator: m.submitted_conflicts ? "red" : "orange",
                        message: `
                          <p>${__("The machine revised {0} row(s) since {1}. {2} of the days below are already SUBMITTED in ERPNext and disagree — those need cancelling before a re-import can take effect.",
                                  [m.machine_rows_revised, m.checked_since, m.submitted_conflicts])}</p>
                          <div style="overflow-x:auto">
                          <table class="table table-bordered" style="font-size:var(--text-sm)">
                            <thead><tr>
                              <th>${__("Work date")}</th><th>${__("Employee")}</th>
                              <th>${__("State in ERPNext")}</th><th>${__("What to do")}</th>
                            </tr></thead>
                            <tbody>${rows}</tbody>
                          </table></div>
                          <p style="color:var(--text-muted)">${__("Nothing has been changed. Checked up to the machine's own clock: {0}", [m.machine_clock_now])}</p>`,
                    });
                },
            });
        });
    },
};
