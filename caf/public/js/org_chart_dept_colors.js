// CAF — department background colours on the stock organisational chart.
// Each chart card is a `.node-card` div whose id is the employee name.
// Colour is derived deterministically from the department name; an employee
// with NO department gets NO background (MG, 2026-08-14).

frappe.provide("caf.org_chart_colors");

(function () {
	const DEPT_COLORS = new Map();
	let color_map = null;
	let on_chart_route = false;

	function dept_color(dept) {
		if (!DEPT_COLORS.has(dept)) {
			let hash = 5381;
			for (let i = 0; i < dept.length; i++) {
				hash = ((hash << 5) + hash + dept.charCodeAt(i)) >>> 0;
			}
			// pastel: readable text, distinct hues
			DEPT_COLORS.set(dept, `hsl(${hash % 360}, 45%, 90%)`);
		}
		return DEPT_COLORS.get(dept);
	}

	function decorate(card) {
		if (!color_map || !card.id) return;
		const dept = color_map[card.id];
		// MG's rule: no department -> plain white card
		card.style.backgroundColor = dept ? dept_color(dept) : "#ffffff";
	}

	function decorate_all(root) {
		if (root.querySelectorAll) root.querySelectorAll(".node-card[id]").forEach(decorate);
	}

	function start() {
		on_chart_route = true;
		if (color_map) return;
		frappe
			.call({ method: "caf.caf.org_chart.get_employee_departments" })
			.then((r) => {
				color_map = r.message || {};
				document.querySelectorAll(".node-card[id]").forEach(decorate);
			});
	}

	function route_changed() {
		const is_chart = frappe.get_route_str() === "organizational-chart";
		if (is_chart && !on_chart_route) start();
		if (!is_chart) on_chart_route = false;
	}

	// cards render lazily on expand — watch for them
	new MutationObserver((mutations) => {
		if (!on_chart_route || !color_map) return;
		for (const m of mutations) {
			m.addedNodes.forEach((n) => {
				if (n.nodeType !== 1) return;
				if (n.classList && n.classList.contains("node-card")) decorate(n);
				else decorate_all(n);
			});
		}
	}).observe(document.body, { childList: true, subtree: true });

	frappe.router.on("change", route_changed);
	route_changed();
})();
