frappe.views.calendar["Meeting Room Reservation"] = {
	field_map: {
		start: "starts_on",
		end: "ends_on",
		id: "name",
		title: "title",
		color: "color",
	},
	get_events_method:
		"caf.caf.utils.meeting_room_reservation.get_meeting_room_reservation_events",
};
