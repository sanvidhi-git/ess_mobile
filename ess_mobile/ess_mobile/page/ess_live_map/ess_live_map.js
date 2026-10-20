// ESS Live Map: today's punches, live trip positions and routes, geofences.

frappe.pages["ess-live-map"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("ESS Live Map"),
		single_column: true,
	});
	new ESSLiveMap(page, wrapper);
};

frappe.pages["ess-live-map"].refresh = function (wrapper) {
	wrapper.ess_map && wrapper.ess_map.load();
};

class ESSLiveMap {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		wrapper.ess_map = this;
		this.markers = {};
		this.timer = null;

		this.date = page.add_field({
			fieldname: "date", label: __("Date"), fieldtype: "Date",
			default: frappe.datetime.get_today(), change: () => this.load(),
		});
		this.company = page.add_field({
			fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), change: () => this.load(),
		});
		this.branch = page.add_field({
			fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch",
			change: () => this.load(),
		});
		this.auto = page.add_field({
			fieldname: "auto", label: __("Auto refresh (1 min)"), fieldtype: "Check", default: 1,
			change: () => this.schedule(),
		});
		page.set_primary_action(__("Refresh"), () => this.load(), "refresh");

		this.$body = $(`
			<div class="ess-map-wrap">
				<div class="ess-map-stats"></div>
				<div class="ess-map-grid">
					<div class="ess-map" id="ess-map-${frappe.utils.get_random(6)}"></div>
					<div class="ess-map-list"></div>
				</div>
			</div>`).appendTo(page.main);
		this.inject_css();

		Promise.all([frappe.require("leaflet.bundle.js"), frappe.require("leaflet.bundle.css")]).then(() => {
			try {
				this.init_map();
			} catch (e) {
				console.error("ESS Live Map: map setup failed", e);
				this.$body.find(".ess-map").html(
					`<div class="text-muted text-center p-4">${__("The map could not be drawn; the employee list below is still current.")}</div>`);
			}
			this.load();
			this.schedule();
		});

		$(wrapper).on("hide", () => clearInterval(this.timer));
		$(wrapper).on("show", () => this.schedule());
	}

	init_map() {
		const el = this.$body.find(".ess-map")[0];
		this.map = L.map(el, { zoomControl: true }).setView([20.59, 78.96], 5);
		// v16: map_defaults.tiles is {default_tile: {url, options}, satellite_tile: {...}};
		// older Frappe: tiles is a URL string with options alongside.
		const defaults = frappe.utils.map_defaults || {};
		const osm = {
			url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
			options: { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' },
		};
		let layers = {};
		if (defaults.tiles && typeof defaults.tiles === "object") {
			// Only the street and satellite base maps; the other v16 entries are Stadia overlays
			// that need an API key on a public domain.
			for (const [key, label] of [["default_tile", __("Map")], ["satellite_tile", __("Satellite")]]) {
				const t = defaults.tiles[key];
				if (t && typeof t.url === "string") {
					layers[label] = L.tileLayer(t.url, Object.assign({ maxZoom: 19 }, t.options || {}));
				}
			}
		} else if (typeof defaults.tiles === "string") {
			layers[__("Map")] = L.tileLayer(defaults.tiles, defaults.options || osm.options);
		}
		if (!Object.keys(layers).length) layers[__("Map")] = L.tileLayer(osm.url, osm.options);
		Object.values(layers)[0].addTo(this.map);
		if (Object.keys(layers).length > 1) L.control.layers(layers, null, { position: "topright" }).addTo(this.map);
		this.layer = L.featureGroup().addTo(this.map);
		this.fence_layer = L.featureGroup().addTo(this.map);
		setTimeout(() => this.map.invalidateSize(), 300);
	}

	schedule() {
		clearInterval(this.timer);
		if (this.auto.get_value()) {
			this.timer = setInterval(() => {
				if (this.date.get_value() === frappe.datetime.get_today()) this.load(true);
			}, 60 * 1000);
		}
	}

	load(silent) {
		frappe.call({
			method: "ess_mobile.api.admin.live_map_data",
			args: {
				date: this.date.get_value(),
				company: this.company.get_value(),
				branch: this.branch.get_value(),
			},
			freeze: !silent,
			callback: (r) => this.render(r.message || {}, silent),
		});
	}

	render(data, keep_view) {
		const hasMap = !!(this.map && this.layer);
		// Without a map, collect markers into throwaway groups so the stats and list still render.
		const layer = hasMap ? this.layer : L.featureGroup();
		const fences = hasMap ? this.fence_layer : L.featureGroup();
		layer.clearLayers();
		fences.clearLayers();
		this.markers = {};
		const emps = data.employees || [];

		(data.geofences || []).forEach((g) => {
			L.circle([g.latitude, g.longitude], {
				radius: g.radius_m, color: "#0F766E", weight: 1, fillOpacity: 0.08,
			}).bindTooltip(frappe.utils.escape_html(g.name)).addTo(fences);
		});

		let checked_in = 0, on_trip = 0, km = 0, outside = 0;
		emps.forEach((e) => {
			if (e.state === "in") checked_in++;
			e.trips.forEach((t) => {
				km += t.distance_km || 0;
				if (t.status === "Active") on_trip++;
				if (t.route && t.route.length > 1) {
					L.polyline(t.route, { color: t.status === "Active" ? "#2490EF" : "#7575FF", weight: 4, opacity: 0.7 })
						.bindTooltip(`${frappe.utils.escape_html(e.employee_name)} · ${t.distance_km} km`)
						.addTo(layer);
				}
				if (t.status === "Active" && t.last) {
					const m = L.circleMarker([t.last.lat, t.last.lng], {
						radius: 9, color: "#fff", weight: 2, fillColor: "#2490EF", fillOpacity: 1,
					}).bindPopup(this.popup_trip(e, t)).addTo(layer);
					this.markers[e.employee] = m;
				}
			});
			e.punches.forEach((p) => {
				if (!p.lat && !p.lng) return;
				if (p.geofence && !p.inside) outside++;
				const m = L.circleMarker([p.lat, p.lng], {
					radius: 7, color: "#fff", weight: 2,
					fillColor: p.type === "IN" ? "#28A745" : "#E24C4C", fillOpacity: 1,
				}).bindPopup(this.popup_punch(e, p)).addTo(layer);
				if (!this.markers[e.employee]) this.markers[e.employee] = m;
			});
		});

		this.$body.find(".ess-map-stats").html(`
			${this.stat(__("Checked in now"), checked_in, "green")}
			${this.stat(__("On a trip"), on_trip, "blue")}
			${this.stat(__("Not punched"), data.absent_count || 0, "gray")}
			${this.stat(__("Outside geofence"), outside, outside ? "orange" : "gray")}
			${this.stat(__("km travelled"), format_number(km, null, 1), "purple")}
		`);
		this.render_list(emps);

		if (!hasMap) return;
		const bounds = this.layer.getBounds();
		if (!keep_view) {
			if (bounds.isValid()) this.map.fitBounds(bounds.pad(0.15), { maxZoom: 16 });
			else if (this.fence_layer.getBounds().isValid()) this.map.fitBounds(this.fence_layer.getBounds().pad(0.2));
		}
	}

	stat(label, value, color) {
		return `<div class="ess-stat"><span class="indicator-pill ${color}">${value}</span>
			<span class="text-muted small">${label}</span></div>`;
	}

	render_list(emps) {
		const $list = this.$body.find(".ess-map-list").empty();
		if (!emps.length) {
			$list.html(`<div class="text-muted text-center p-4">${__("No mobile punches for this day")}</div>`);
			return;
		}
		emps.forEach((e) => {
			const last = e.punches[e.punches.length - 1];
			const trip = e.trips.find((t) => t.status === "Active") || e.trips[e.trips.length - 1];
			const state = e.state === "in"
				? `<span class="indicator-pill green">${__("In")}</span>`
				: `<span class="indicator-pill gray">${__("Out")}</span>`;
			const sub = [
				last ? `${last.type === "IN" ? __("In") : __("Out")} ${this.time(last.time)}` : "",
				trip ? `${trip.distance_km} km` : "",
				last && last.geofence ? frappe.utils.escape_html(last.geofence) : "",
			].filter(Boolean).join(" · ");
			$(`<div class="ess-emp">
					${frappe.avatar(null, "avatar-small", e.employee_name, e.image)}
					<div class="ess-emp-body">
						<div class="ess-emp-name">${frappe.utils.escape_html(e.employee_name || e.employee)}</div>
						<div class="text-muted small">${sub}</div>
					</div>
					${state}
				</div>`)
				.on("click", () => {
					const m = this.markers[e.employee];
					if (m && this.map) {
						this.map.setView(m.getLatLng(), 16);
						m.openPopup();
					}
				})
				.appendTo($list);
		});
	}

	time(dt) {
		return frappe.datetime.str_to_user(dt).split(" ").slice(1).join(" ") || dt;
	}

	popup_punch(e, p) {
		const selfie = p.selfie
			? `<a href="${encodeURI(p.selfie)}" target="_blank"><img src="${encodeURI(p.selfie)}" class="ess-selfie"></a>`
			: "";
		return `<div class="ess-pop">${selfie}
			<b>${frappe.utils.escape_html(e.employee_name)}</b><br>
			${p.type === "IN" ? __("Check in") : __("Check out")} · ${this.time(p.time)}<br>
			${p.geofence ? `${frappe.utils.escape_html(p.geofence)} · ${p.inside ? __("inside") : __("outside")}<br>` : ""}
			${__("Accuracy")}: ${Math.round(p.accuracy || 0)} m<br>
			<a href="/desk/employee-checkin/${encodeURIComponent(p.name)}">${__("Open check-in")}</a></div>`;
	}

	popup_trip(e, t) {
		return `<div class="ess-pop">
			<b>${frappe.utils.escape_html(e.employee_name)}</b><br>
			${__("On trip since")} ${this.time(t.start_time)} · ${t.distance_km} km<br>
			${__("Last seen")} ${this.time(t.last.time)}${t.last.battery > 0 ? ` · 🔋 ${t.last.battery}%` : ""}<br>
			<a href="/desk/ess-trip/${encodeURIComponent(t.name)}">${__("Open trip")}</a></div>`;
	}

	inject_css() {
		if (document.getElementById("ess-live-map-css")) return;
		$(`<style id="ess-live-map-css">
			.ess-map-stats { display:flex; flex-wrap:wrap; gap:16px; margin-bottom:12px; }
			.ess-stat { display:flex; align-items:center; gap:6px; }
			.ess-map-grid { display:grid; grid-template-columns: 1fr 300px; gap:12px; }
			.ess-map { height: calc(100vh - 260px); min-height: 420px; border-radius: var(--border-radius-md);
				border:1px solid var(--border-color); z-index:0; }
			.ess-map-list { height: calc(100vh - 260px); min-height: 420px; overflow-y:auto;
				border:1px solid var(--border-color); border-radius: var(--border-radius-md); }
			.ess-emp { display:flex; align-items:center; gap:10px; padding:10px 12px; cursor:pointer;
				border-bottom:1px solid var(--border-color); }
			.ess-emp:hover { background: var(--fg-hover-color); }
			.ess-emp-body { flex:1; min-width:0; }
			.ess-emp-name { font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
			.ess-pop { min-width:180px; line-height:1.6; }
			.ess-selfie { width:72px; height:72px; object-fit:cover; border-radius:8px; float:right; margin-left:8px; }
			@media (max-width: 991px) {
				.ess-map-grid { grid-template-columns: 1fr; }
				.ess-map-list { height:auto; max-height: 360px; }
			}
		</style>`).appendTo("head");
	}
}
