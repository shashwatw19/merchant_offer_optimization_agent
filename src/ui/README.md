# Merchant Offer Agent UI

This folder contains a small FastAPI web interface for viewing open campaign alerts and running the existing merchant offer optimization agent. The UI is isolated in `src/ui`; it reuses the agent and BigQuery code in the project and does not change campaign data or alert statuses.

## Folder structure

```text
src/ui/
├── __init__.py
├── app.py                   # FastAPI app, routes, alert queries, investigation action
├── README.md                # UI setup and usage
├── static/
│   └── css/
│       └── styles.css       # Responsive UI styles
└── templates/
    ├── base.html            # Shared page layout
    ├── dashboard.html       # Open-alert dashboard
    ├── error.html           # User-facing error page
    └── report.html          # Saved investigation report
```

Investigation reports are written at runtime to `output/ui_reports/` in the project root.

## Technology

- **FastAPI** serves the dashboard and investigation/report routes.
- **Jinja2** renders the HTML templates.
- **HTML and CSS** provide the pages and responsive styling.
- **Google Cloud BigQuery** supplies the open alerts.
- The existing **Google ADK agent** runs investigations and returns structured reports.

## Requirements

- Python 3.11 or newer.
- Project dependencies from the root `requirements.txt`.
- Additional UI packages: `fastapi`, `uvicorn`, and `jinja2`.
- Google Cloud credentials with permission to read the configured BigQuery alerts table.
- A configured Gemini API credential and project settings required by the existing agent. Follow the project’s existing configuration and credential setup.

The UI dependencies are not added to the root dependency manifests. Install them explicitly:

```powershell
python -m pip install -r requirements.txt fastapi uvicorn jinja2
```

## Run locally

From the project root (the directory containing `requirements.txt` and `campaign.yaml`), start the development server:

```powershell
uvicorn ui.app:app --app-dir src --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. The health endpoint is available at [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

## Use the UI

1. The dashboard lists up to 100 alerts whose status is `OPEN`, with a readable name and explanation for rules R1, R2, and R3.
2. Select **Run investigation** to execute the existing agent for an alert.
3. Review the saved report, including findings, evidence references, hypotheses, and the proposal.
4. Reports can be reopened from the dashboard while the corresponding alert is still listed.

The UI does not write alert status changes or apply campaign proposals. All proposals remain advisory and require human review. Reports are stored locally under `output/ui_reports/`; this directory is not intended as shared or durable report storage.

## Troubleshooting

- **Dashboard cannot load alerts:** check BigQuery project configuration, credentials, and table read permissions. The app logs provide the underlying error.
- **Investigation fails:** verify the existing agent's Gemini credentials and required BigQuery access, then check application logs.
- **No open alerts:** the dashboard only lists alerts with status `OPEN`.
