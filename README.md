# A10 Survey Manager

A minimal web-based application for managing site gravity surveys, preflight checklists, and measurement data for A10 gravimeter from Micro-g LaCoste.

## Features

- **Site Surveys**: Create, edit, and track survey sites with metadata and status.
- **Preflight Checklist**: Guided, multi-stage checklist workflow for survey preparation.
- **Measurements**: Upload, view, and report g9 project/set files, site images, and graphs.
- **Quality Metrics**: Automatic parsing and display of key measurement statistics.
- **Image & Graph Uploads**: Attach site photos and g9 graphs (images/PDFs) to measurements.
- **Reporting**: Generate printable measurement reports with all relevant data.

## Getting Started

### Requirements

- Python 3.9+
- [FastAPI](https://fastapi.tiangolo.com/)
- [Uvicorn](https://www.uvicorn.org/)
- SQLite (included)

### Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/mihail-cretu/a10_Survey_Manager.git
    cd a10_Survey_Manager/app
    ```

2. Install dependencies:
    ```sh
    pip install fastapi uvicorn
    ```

3. Run the app:
    ```sh
    uvicorn main:app --reload
    ```

4. Open [http://localhost:8000](http://localhost:8000) in your browser.

### Project Structure

```
app/
  main.py
  db.py
  measurement.py
  measurement_report.py
  preflight_checklist.py
  data/
    checklist_v3.json
    db.schema.sql
  templates/
    base.html
    ...
```

## Usage

- **Create a Site Survey**: Click "New Survey" on the homepage.
- **Run Preflight Checklist**: Open a survey and start the checklist workflow.
- **Add Measurements**: Upload g9 project/set files, images, and graphs for each survey.
- **View Reports**: Generate detailed measurement reports with parsed data and attachments.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Credits

Developed by Mihail Cretu, 2025.