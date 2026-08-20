import frappe

COLORS_BY_BOOKING_TYPE = {
	"Internal": "#FF9800",
	"External": "#E53935",
	"Employee": "#FF9800",
	"Visitor": "#E53935",
}


@frappe.whitelist()
def get_meeting_room_reservation_events(start, end, filters=None):
	events = frappe.db.sql(
		"""
		select rb.name, rb.starts_on, rb.starts_time, rb.ends_on, rb.ends_time,
			r.room_name, rb.booking_type, rb.purpose, rb.visitor_name
		from `tabMeeting Room Reservation` rb
		inner join `tabRoom` r on r.name = rb.room
		where rb.docstatus = 1
			and r.status = 'Active'
			and TIMESTAMP(rb.starts_on, rb.starts_time) < %(end)s
			and TIMESTAMP(rb.ends_on, rb.ends_time) > %(start)s
		order by rb.starts_on, rb.starts_time
		""",
		{"start": start, "end": end},
		as_dict=True,
	)
	for e in events:
		if e["booking_type"] == "External":
			e["title"] = f"{e.room_name}\n{e.visitor_name}\n{e.purpose}"
		else:
			e["title"] = f"{e.room_name}\n{e.purpose}"
		e["color"] = COLORS_BY_BOOKING_TYPE.get(e.booking_type, "#607D8B")
		e["docstatus"] = 1
		e["starts_on"] = f"{e.starts_on} {e.starts_time}:00"
		e["ends_on"] = f"{e.ends_on} {e.ends_time}:00"
	return events
