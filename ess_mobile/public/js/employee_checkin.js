// ESS Mobile: show the selfie and location prominently on mobile-app check-ins.

frappe.ui.form.on("Employee Checkin", {
	refresh(frm) {
		if (!frm.doc.ess_device && !frm.doc.ess_selfie) return;

		const lat = frm.doc.ess_latitude, lng = frm.doc.ess_longitude;
		const fence = frm.doc.ess_geofence
			? `${frappe.utils.escape_html(frm.doc.ess_geofence)} · ${frm.doc.ess_within_geofence
				? `<span class="text-success">${__("inside")}</span>`
				: `<span class="text-warning">${__("outside")}</span>`} (${Math.round(frm.doc.ess_distance_m || 0)} m)`
			: __("No geofence");
		const checks = [
			frm.doc.ess_liveness_passed ? `✅ ${__("Liveness")}` : `⚠️ ${__("No liveness")}`,
			frm.doc.ess_is_mocked ? `⛔ ${__("Mock GPS")}` : `✅ ${__("Real GPS")}`,
			`📍 ±${Math.round(frm.doc.ess_accuracy || 0)} m`,
		].join(" &nbsp; ");
		const img = frm.doc.ess_selfie
			? `<a href="${encodeURI(frm.doc.ess_selfie)}" target="_blank">
				<img src="${encodeURI(frm.doc.ess_selfie)}" style="width:96px;height:96px;object-fit:cover;border-radius:12px"></a>`
			: "";
		frm.dashboard.set_headline_alert(`
			<div class="d-flex align-items-center" style="gap:16px">
				${img}
				<div>
					<div><b>${__("Mobile App")} · ${frm.doc.log_type || ""}</b></div>
					<div>${fence}</div>
					<div class="small text-muted">${checks}</div>
				</div>
			</div>`, "blue");

		if (lat || lng) {
			frm.add_custom_button(__("Open in Maps"), () =>
				window.open(`https://www.google.com/maps?q=${lat},${lng}`, "_blank"), __("ESS"));
		}
		frm.add_custom_button(__("Live Map"), () => frappe.set_route("ess-live-map"), __("ESS"));
		if (frm.doc.ess_trip) {
			frm.add_custom_button(__("Trip"), () => frappe.set_route("Form", "ESS Trip", frm.doc.ess_trip), __("ESS"));
		}
	},
});
