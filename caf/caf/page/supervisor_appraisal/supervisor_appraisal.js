/*
CAF Supervisor Bulk Appraisal Page - client-side SPA
=====================================================
Purpose : Full-page JS for the supervisor-appraisal Frappe Page.
          Renders compact setup header + KRA grid. Next/Prev navigation
          with auto-save. Single "Submit for Review" button.
Doctype : Page (supervisor-appraisal)  |  Route: /app/supervisor-appraisal
Plan ref: supervisor_page_plan.md 5 Step 3

Changelog
---------
1.1  2026-08-06  Fix: duplicate cycle picker (created on each refresh).
                 Redesign header layout compact/horizontal - single row,
                 inline fields, no stacked labels.
1.0  2026-08-06  Initial: full SPA with Next/Prev, auto-save, Submit
*/

frappe.provide("caf.supervisor_appraisal");

frappe.pages["supervisor-appraisal"].on_page_load = function (wrapper) {
    frappe.supervisor_appraisal = new caf.supervisor_appraisal.SupervisorBoard(wrapper);
};

frappe.pages["supervisor-appraisal"].on_page_show = function () {
    if (frappe.supervisor_appraisal) {
        frappe.supervisor_appraisal.refresh();
    }
};

caf.supervisor_appraisal.SupervisorBoard = class SupervisorBoard {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.state = {
            cycle: null,
            started: false,
            docList: [],
            currentIdx: 0,
            currentDoc: null,
            total: 0,
            templates: [],
            isDirty: false,
        };
        this._cycleField = null;
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: __("Supervisor Bulk Appraisal"),
            single_column: true,
        });
        this.make();
    }

    // ---- BOOTSTRAP ----

    make() {
        this.page.main.html(this._layout_html());
        this._setup_events();
        this._buildCyclePicker();
        this.renderPreStart();
    }

    refresh() {
        this.renderPreStart();
    }

    _layout_html() {
        return (
            '<div class="sa-container">' +
            this._header_html() +
            this._body_html() +
            "</div>"
        );
    }

    _header_html() {
        return (
            '<div class="sa-header">' +
            // Row 1: Cycle picker + Start + stats + Status
            '<div class="sa-header-top">' +
            '<div id="sa-cycle-picker" class="sa-cycle-wrap"></div>' +
            '<button id="sa-btn-start" class="btn btn-primary sa-start-btn">' +
            __("Start") + "</button>" +
            '<span class="sa-sep">|</span>' +
            '<span class="sa-inline-stat">' + __("Total") +
            ': <b id="sa-total">-</b></span>' +
            '<span class="sa-inline-stat">' + __("Template") +
            ': <b id="sa-template">-</b></span>' +
            '<span id="sa-status" class="sa-status-badge">-</span>' +
            "</div>" +
            // Row 2: actions first, then Emp : Dept
            '<div class="sa-header-bottom">' +
            '<div class="sa-actions-block">' +
            '<button id="sa-btn-prev" class="btn btn-sm btn-prev" disabled>' +
            '<i class="fa fa-chevron-left"></i> ' + __("Prev") + "</button>" +
            '<button id="sa-btn-next" class="btn btn-sm btn-next" disabled>' +
            __("Next") + ' <i class="fa fa-chevron-right"></i>' + "</button>" +
            '<a id="sa-link-feedback" class="btn btn-sm btn-default" ' +
            'target="_blank" style="display:none">' + __("Feedback") + "</a>" +
            '<button id="sa-btn-refresh" class="btn btn-sm btn-default" ' +
            'style="display:none">' + __("Refresh") + "</button>" +
            '<button id="sa-btn-submit" class="btn btn-sm btn-primary" ' +
            'style="display:none">' + __("Submit for Review") + "</button>" +
            "</div>" +
            '<span class="sa-sep sa-divider">|</span>' +
            '<span class="sa-inline-stat">' + __("Emp : Dept") +
            ': <b id="sa-emp-dept">-</b></span>' +
            "</div>"
        );
    }

    _body_html() {
        return (
            '<div id="sa-body" class="sa-body" style="display:none">' +
            '<table id="sa-kra-grid" class="sa-kra-grid">' +
            "<thead><tr>" +
            "<th>" + __("KRA") + "</th>" +
            "<th>" + __("Date") + "</th>" +
            "<th>" + __("Description") + "</th>" +
            "<th>" + __("Root Cause") + "</th>" +
            "<th>" + __("Corrective Action") + "</th>" +
            "<th>" + __("Remarks") + "</th>" +
            "</tr></thead>" +
            '<tbody id="sa-kra-body"></tbody>' +
            "</table>" +
            "</div>"
        );
    }

    _setup_events() {
        var self = this;
        this.page.wrapper.on("click", "#sa-btn-start", function () { self.onStart(); });
        this.page.wrapper.on("click", "#sa-btn-next", function () { self.onNext(); });
        this.page.wrapper.on("click", "#sa-btn-prev", function () { self.onPrev(); });
        this.page.wrapper.on("click", "#sa-btn-refresh", function () { self.onRefresh(); });
        this.page.wrapper.on("click", "#sa-btn-submit", function () { self.onSubmit(); });
        // Track edits to contenteditable cells
        this.page.wrapper.on("input", "#sa-kra-body td[contenteditable]", function () {
            self._markDirty();
        });
    }

    // ---- CYCLE PICKER (created once, never duplicated) ----

    _buildCyclePicker() {
        if (this._cycleField) return;
        var self = this;
        this._cycleField = frappe.ui.form.make_control({
            parent: this.page.wrapper.find("#sa-cycle-picker"),
            df: {
                fieldtype: "Link",
                fieldname: "appraisal_cycle",
                options: "Appraisal Cycle",
                placeholder: __("Select Appraisal Cycle"),
                onchange: function () {
                    self.state.cycle = this.get_value();
                },
            },
            only_input: true,
            render_input: true,
        });
        // Shrink the link field wrapper to inline
        this.page.wrapper.find("#sa-cycle-picker .frappe-control").css("margin-bottom", "0");
    }

    // ---- RENDER PHASES ----

    renderPreStart() {
        this.state.started = false;
        this.state.docList = [];
        this.state.currentIdx = 0;
        this.state.currentDoc = null;
        this.state.isDirty = false;

        // Reset header displays
        this.page.wrapper.find("#sa-total").text("-");
        this.page.wrapper.find("#sa-template").text("-");
        this.page.wrapper.find("#sa-emp-dept").text("-");
        this.page.wrapper.find("#sa-status").text("-").removeClass("draft pending completed");
        this.page.wrapper.find("#sa-btn-prev, #sa-btn-next").prop("disabled", true);
        this.page.wrapper.find("#sa-btn-refresh, #sa-btn-submit, #sa-link-feedback").hide();
        this.page.wrapper.find("#sa-body").hide();
    }

    renderActive() {
        var doc = this.state.currentDoc;
        if (!doc) return;

        this.page.wrapper.find("#sa-body").show();
        this.page.wrapper.find("#sa-btn-prev, #sa-btn-next").prop("disabled", false);
        this.page.wrapper.find("#sa-link-feedback").show();

        // Header info
        this.page.wrapper.find("#sa-total").text(this.state.total);
        this.page.wrapper.find("#sa-template").text(doc.header.appraisal_template || "-");
        var empDept = (doc.header.employee_name || "") + " - " + (doc.header.department || "");
        this.page.wrapper.find("#sa-emp-dept").text(empDept || "-");
        this.page.wrapper.find("#sa-btn-prev").prop("disabled", this.state.currentIdx === 0);
        this.page.wrapper.find("#sa-btn-next").prop("disabled",
            this.state.currentIdx >= this.state.docList.length - 1);

        // Status badge
        var state = doc.header.workflow_state || "Draft";
        var $status = this.page.wrapper.find("#sa-status");
        $status.text(state).removeClass("draft pending completed");
        if (state === "Pending HR Review") {
            $status.addClass("pending-hr-review");
        } else {
            $status.addClass(state.toLowerCase().replace(/ /g, "-"));
        }

        // Feedback deep link
        this.page.wrapper.find("#sa-link-feedback").attr("href", "/app/appraisal/" + doc.header.name);

        // Button visibility per is_editable and isDirty
        this._updateSubmitButton(doc.is_editable, false);

        this.renderKRAGrid(doc);
    }

    renderKRAGrid(doc) {
        var rows = doc.kra_rows || [];
        var editable = doc.is_editable;
        var autoFillKras = ["Attendance", "Punctuality", "OT Hours"];

        var html = "";
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var isAuto = autoFillKras.indexOf(row.kra) !== -1;
            var isAttendance = row.kra === "Attendance";
            html += "<tr class='" + (isAuto ? "sa-row-auto" : "") + "'>";
            html += "<td>" + frappe.utils.escape_html(row.kra || "") + "</td>";

            // caf_date_cell - pink if auto, editable for non-auto rows
            html += "<td class='" + (isAuto ? "cell-auto-fill" : "cell-editable") + "' ";
            html += "data-row-name='" + row.name + "' data-field='caf_date_cell'";
            if (editable && !isAuto) {
                html += " contenteditable='true'";
            }
            html += ">" + frappe.utils.escape_html(row.caf_date_cell || "") + "</td>";

            // Editable text columns
            var fields = ["caf_description", "caf_root_cause", "caf_corrective_action", "caf_remarks"];
            for (var f = 0; f < fields.length; f++) {
                var val = row[fields[f]] || "";
                var fieldName = fields[f];
                var isRemarks = fieldName === "caf_remarks";
                // Only Attendance remarks is auto-fill (working days count).
                // Punctuality and OT Hours remarks are supervisor-editable.
                var cellAuto = isAttendance && isRemarks;

                html += "<td class='" + (cellAuto ? "cell-auto-fill" : "cell-editable") + "' ";
                html += "data-row-name='" + row.name + "' data-field='" + fieldName + "'";
                if (editable) {
                    html += " contenteditable='true'";
                }
                html += ">" + frappe.utils.escape_html(val) + "</td>";
            }
            html += "</tr>";
        }
        this.page.wrapper.find("#sa-kra-body").html(html);
    }

    // ---- ACTIONS ----

    onStart() {
        if (!this.state.cycle) {
            frappe.msgprint(__("Please select an Appraisal Cycle first."));
            return;
        }

        var self = this;
        frappe.call({
            method: "caf.caf.page.supervisor_appraisal.supervisor_appraisal.get_direct_reports_appraisals",
            args: { appraisal_cycle: this.state.cycle },
            callback: function (r) {
                if (r.message) {
                    self.state.docList = r.message.doc_list || [];
                    self.state.total = r.message.total || 0;
                    self.state.templates = r.message.templates || [];
                    self.state.currentIdx = 0;
                    self.state.started = true;

                    if (self.state.total === 0) {
                        frappe.msgprint(__("No direct reports found for this cycle."));
                        return;
                    }
                    self.loadDoc(self.state.docList[0].name);
                }
            },
        });
    }

    onNext() {
        if (this.state.isNavigating) return;
        this.saveAndNavigate(1);
    }

    onPrev() {
        if (this.state.isNavigating) return;
        this.saveAndNavigate(-1);
    }

    saveAndNavigate(delta) {
        var self = this;
        self.state.isNavigating = true;

        var doNavigate = function () {
            self.state.currentIdx += delta;
            self.state.isDirty = false;
            var next = self.state.docList[self.state.currentIdx];
            if (next) {
                self.loadDoc(next.name);
            }
            self.state.isNavigating = false;
        };

        if (!self.state.currentDoc || !self.state.currentDoc.is_editable) {
            doNavigate();
            return;
        }

        var kraRows = self._collectKraText();
        frappe.call({
            method: "caf.caf.page.supervisor_appraisal.supervisor_appraisal.save_appraisal_kra",
            args: {
                appraisal_name: self.state.currentDoc.header.name,
                kra_rows: kraRows,
            },
            callback: function () { doNavigate(); },
            error: function () { self.state.isNavigating = false; },
        });
    }

    onRefresh() {
        if (!this.state.currentDoc) return;
        var self = this;
        // Save KRA text first so user input is not lost, then refresh
        var kraRows = this._collectKraText();
        frappe.call({
            method: "caf.caf.page.supervisor_appraisal.supervisor_appraisal.save_appraisal_kra",
            args: {
                appraisal_name: self.state.currentDoc.header.name,
                kra_rows: kraRows,
            },
            callback: function () {
                        self.state.isDirty = false;
                        frappe.call({
                    method: "run_doc_method",
                    args: {
                        dt: "Appraisal",
                        dn: self.state.currentDoc.header.name,
                        method: "refresh_auto_fill_action",
                    },
                    callback: function () {
                        self.loadDoc(self.state.currentDoc.header.name);
                    },
                });
            },
        });
    }

    onSubmit() {
        if (!this.state.currentDoc) return;
        var self = this;

        if (this.state.isDirty) {
            // Save mode: persist text, then button changes to "Submit for Review"
            var kraRows = this._collectKraText();
            frappe.call({
                method: "caf.caf.page.supervisor_appraisal.supervisor_appraisal.save_appraisal_kra",
                args: {
                    appraisal_name: self.state.currentDoc.header.name,
                    kra_rows: kraRows,
                },
                callback: function () {
                    self.state.isDirty = false;
                    self._updateSubmitButton(true, false);
                    frappe.show_alert({message: __("Saved"), indicator: "green"});
                },
            });
        } else {
            // Submit mode: trigger workflow transition
            frappe.call({
                method: "caf.caf.page.supervisor_appraisal.supervisor_appraisal.submit_for_review",
                args: { appraisal_name: self.state.currentDoc.header.name },
                callback: function (r) {
                    if (r.message) {
                        frappe.msgprint(r.message.message || __("Submitted for review."));
                        self.loadDoc(self.state.currentDoc.header.name);
                    }
                },
            });
        }
    }

    _markDirty() {
        if (!this.state.isDirty) {
            this.state.isDirty = true;
            this._updateSubmitButton(true, true);
        }
    }

    _updateSubmitButton(isEditable, isDirty) {
        var $btn = this.page.wrapper.find("#sa-btn-submit");
        var $refresh = this.page.wrapper.find("#sa-btn-refresh");
        if (!isEditable) {
            $refresh.hide();
            $btn.show().prop("disabled", true).text(__("Submit for Review"))
                .removeClass("btn-primary").addClass("btn-default");
            return;
        }
        $refresh.show();
        $btn.show().prop("disabled", false);
        if (isDirty) {
            $btn.text(__("Save")).removeClass("btn-primary").addClass("btn-default");
        } else {
            $btn.text(__("Submit for Review")).removeClass("btn-default").addClass("btn-primary");
        }
    }

    loadDoc(name) {
        var self = this;
        frappe.call({
            method: "caf.caf.page.supervisor_appraisal.supervisor_appraisal.get_appraisal_doc",
            args: { appraisal_name: name },
            callback: function (r) {
                if (r.message) {
                    self.state.currentDoc = r.message;
                    self.state.isDirty = false;
                    self.renderActive();
                }
            },
        });
    }

    _collectKraText() {
        var rows = [];
        this.page.wrapper.find("#sa-kra-body td[contenteditable]").each(function () {
            var $td = $(this);
            var rowName = $td.data("row-name");
            var field = $td.data("field");
            var val = $td.text().trim();

            var existing = null;
            for (var i = 0; i < rows.length; i++) {
                if (rows[i].name === rowName) { existing = rows[i]; break; }
            }
            if (existing) {
                existing[field] = val;
            } else {
                var obj = { name: rowName };
                obj[field] = val;
                rows.push(obj);
            }
        });
        return rows;
    }
};
