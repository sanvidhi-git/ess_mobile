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
