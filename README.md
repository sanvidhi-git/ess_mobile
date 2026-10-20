# ESS Mobile — Frappe app (server side of Sanvidhi ESS)

Server side for the **Sanvidhi ESS** Android app (`sanvidhi-git/ess_app`), for ERPNext v16 + Frappe HR v16.

- Mobile API: login + device binding, selfie / liveness / GPS / geofence check-in, live tracking, leave, payslips, expenses
- **Attendance Mode** per company (ESS Settings) and per employee: *Check-in Only* or *Live Tracking*
- HR desk: ESS Mobile workspace, Live Map, Attendance Register and Travel Summary reports, rejected check-in log

## Install (bench)
```bash
bench get-app https://github.com/sanvidhi-git/ess_mobile
bench --site <site> install-app ess_mobile
bench --site <site> migrate && bench build --app ess_mobile && bench restart
```

## Docker (frappe_docker custom image)
Add after `hrms` in `apps.json`:
```json
{"url": "https://github.com/sanvidhi-git/ess_mobile", "branch": "main"}
```
Rebuild the image, then per site: `bench --site <site> install-app ess_mobile` and `migrate`.

## Travel claims (v1.3)

**ESS Settings → Travel Expense Claim**

- **Modes of Transport**: one row per mode with its rate per km. Tick *Own Vehicle (Odometer)* for modes where the employee drives their own vehicle (Two Wheeler, Car). Seeded with Public Transport ₹3, Two Wheeler ₹4, Car ₹10; set your company's real rates.
- **Default Mode of Transport**: used for employees with no mode set.
- **Employee → Mobile App → Mode of Transport**: each employee's usual mode.
- **Odometer Reading at Check-in / Check-out**: Off, Optional or Required. Applies to Live Tracking employees whose mode is an own vehicle. They enter the reading and photograph the odometer at check-in and again at check-out.
- **Allow Claim Above Tracked Distance (%)**: 0 means a claim can never exceed the km recorded by live tracking.

**Claim rules (app and HR's Create Travel Claim button)**

- The mode defaults to the employee's own. They can pick another; the claim text records the change for the approver.
- Distance to claim is entered by the employee. It's suggested as odometer distance minus personal km (or the tracked km when there's no odometer), and it can't exceed the tracked km (plus the tolerance), nor the odometer distance minus personal km.
- The Expense Claim's description records mode, rate, tracked km, odometer readings and personal km. Odometer photos are attached to the claim.

After updating: `bench --site <site> migrate`, `bench build --app ess_mobile`, `bench --site <site> clear-cache`, then hard-refresh the browser.
