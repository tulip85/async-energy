# async-energy

Home Assistant custom integration that imports your **EKZ** (Elektrizitätswerk des Kantons Zürich) electricity consumption and cost from the [my.ekz.ch](https://my.ekz.ch) customer portal into Home Assistant's **long-term statistics**, so it can be used in the **Energy dashboard**.

> **Unofficial.** This project is not affiliated with or endorsed by EKZ. It logs in to the customer portal the same way your browser does, because EKZ offers no public API. EKZ can change the portal at any time, which may break the integration until it is updated.

## What you get

- Hourly consumption (kWh) and cost (CHF) as two statistics:
  - `asyncenergy:energy_consumption`
  - `asyncenergy:energy_cost`
- Smart-meter data arrives with a delay of about a day. The integration imports whole days, so the newest data is always **yesterday**.
- Cost is calculated from your tariffs (peak / off-peak), which you can edit in the options. See [Tariffs](#tariffs).
- No entities and no add-on or separate service: it is a single integration.
- Optional archive of the raw EKZ responses to a local folder or Google Drive. See [Archive](#archive-raw-data-optional).

## Requirements

- Home Assistant 2025.5.0 or newer.
- A my.ekz.ch account whose login is a plain username and password. If your account needs two-factor verification, login will fail.
- The **installation ID** of your meter, see [Finding the installation ID](#finding-the-installation-id).

## Installation

**HACS (recommended):** HACS → ⋮ → *Custom repositories* → add `https://github.com/tulip85/async-energy` as type *Integration* → download → restart Home Assistant.

**Manual:** copy the contents of `custom_components/async-energy/` into `<config>/custom_components/asyncenergy/` (the folder name must be `asyncenergy`, the integration's domain) and restart Home Assistant.

## Setup

1. *Settings → Devices & services → Add integration → async-energy*.
2. Enter your my.ekz.ch **username**, **password** and **installation ID**, plus a **location name** (any label).
3. The integration logs in, fetches yesterday to check everything works, and starts importing.

Only one installation is supported for now: the statistic IDs are fixed, so a second entry would write to the same statistics.

### Finding the installation ID

1. Log in at [my.ekz.ch](https://my.ekz.ch) and open the page that shows your consumption.
2. Open your browser's developer tools (F12) → *Network* tab and reload the page.
3. Find a request named `consumption-data`. Its URL contains `installationId=<number>`. That number is your installation ID.

### Add it to the Energy dashboard

*Settings → Dashboards → Energy → Electricity grid → Add consumption*:

- Choose the statistic **Energy consumption** (`asyncenergy:energy_consumption`).
- Select **Use an entity tracking the total costs** and choose **Energy cost** (`asyncenergy:energy_cost`).

## How it works

1. Every 6 hours (and when Home Assistant starts) the integration logs in to my.ekz.ch with an HTTP session. No browser is involved.
2. It fetches the 15-minute values for the last **8 days** (ending yesterday), adds the high- and low-tariff series and sums them per hour.
3. Each hour is multiplied by the tariff valid at that time to get the cost.
4. The hourly values are written as cumulative statistics. Re-importing the same days is safe: they are overwritten with the same values.

The 8-day window means short outages heal themselves. For longer gaps or for history, use the [backfill action](#backfill-action).

## Tariffs

Costs use the tariffs of the periods below. A built-in default covers **2022 to 2027** (annual rates until 2025, quarterly rates from 2026), so it works without any configuration. When EKZ publishes new rates you don't have to wait for a release: edit them yourself.

*Settings → Devices & services → async-energy → Configure → Tariffs*. The field holds YAML, one entry per period. Both dates are inclusive and rates are CHF per kWh:

```yaml
- from: 2026-01-01
  to: 2026-03-31
  peak: 0.2593
  off_peak: 0.2593
- from: 2026-04-01
  to: 2026-06-30
  peak: 0.2128
  off_peak: 0.2128
```

Rules:

- Periods must not overlap. Gaps are allowed, but days in a gap are **not imported** and a **Repairs** issue tells you which days are missing.
- Clearing the field goes back to the built-in tariffs.
- Your tariffs fully replace the built-in ones. Start from the pre-filled text and edit it.
- Which hours count as peak is fixed: **Mon–Fri 07:00–19:59 and Sat 07:00–12:59**. All other hours, including Sundays, are off-peak. Public holidays are not treated specially.
- Only newly imported days use changed tariffs. To recalculate earlier days, run the backfill action.

## Backfill action

`asyncenergy.backfill` re-imports the last *N* days (1–366, counted back from yesterday) and recalculates cost with your current tariffs. Use it:

- once after setup to load history,
- after changing tariffs,
- after an outage longer than 8 days, or after fixing a missing tariff.

*Developer tools → Actions → async-energy: Backfill*. How far back EKZ still serves data is up to EKZ. The 15-minute format may not be available for periods before an EKZ API change in 2024.

## Archive raw data (optional)

By default nothing but statistics is stored. If you also want the raw JSON responses from EKZ (15-minute and daily values, one pair of files per day, e.g. `2026-11-10-detailed.json`), choose a target under *Configure → Archive raw data*:

| Target | Where the files go |
|---|---|
| Don't archive | Nowhere (default) |
| Local folder | `<config>/ekz_raw/`, included in Home Assistant backups |
| Google Drive | A Drive folder you choose |

### Google Drive

The integration uploads with a **service account**, so there is no sign-in flow:

1. In the [Google Cloud Console](https://console.cloud.google.com) create a project and enable the **Google Drive API**.
2. Create a **service account** and create a **JSON key** for it.
3. In Google Drive create a folder and **share it with the service account's e-mail address** (the `client_email` in the JSON) as *Editor*.
4. In the options, paste the whole JSON key and the **folder ID** (the last part of the folder's URL).

Notes:

- The integration only requests the `drive.file` scope: it can only see files it created itself, in the folder you shared.
- The key is stored in Home Assistant's config entry, so it is also in Home Assistant backups. Treat backups as sensitive.
- Files created by a service account belong to that account and count against its storage quota. If uploads fail with a quota error, use a Shared Drive.
- A failed upload only logs a warning. It never blocks the statistics import.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| *Re-authentication* notification | EKZ rejected the login (changed password, or an unexpected extra verification step). Enter the login again. |
| *No tariff for some days* under Repairs | No tariff period covers those days. Add it under *Configure → Tariffs*, then run the backfill action. |
| Newest data is a day old | Expected: EKZ publishes meter data for whole days. |
| Warnings *Skipping <date>* in the log | EKZ returned nothing or something unexpected for that day. It is retried on the next run (every 6 hours) while the day is inside the 8-day window. |
| Setup fails with *cannot connect* | Check the installation ID and that you can log in at my.ekz.ch with the same credentials. |

To see what the integration does, enable debug logging for `custom_components.asyncenergy` under *Settings → System → Logs*.

## Upgrading from the version with the separate service

Earlier versions needed a separate Python service (a Playwright scraper plus a small API) and asked for its URL. That service is no longer used. After updating, Home Assistant asks you to log in again (*re-authentication*): enter your EKZ login and installation ID. The statistic IDs are unchanged, so your history and Energy dashboard setup carry over. Afterwards you can shut the old service down.

## Removing

Remove the integration under *Devices & services*. Imported statistics stay in Home Assistant. To delete them too, use *Developer tools → Statistics* and remove the `asyncenergy:` entries.
