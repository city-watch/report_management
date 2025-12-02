# Report Management Service

This service is a FastAPI-based application for managing civic issue reports. It allows users to submit, view, and comment on issues, while also providing functionality for city employees to manage the status of these reports.

## Features

- **Issue Reporting:** Users can submit issues with a title, description, location (latitude/longitude), and an optional image.
- **Authentication:** The service uses JWT for authentication, with distinct roles for regular users and "City Employees".
- **AI Integration:** It communicates with an AI service for automatic issue categorization and priority assessment.
- **Duplicate Detection:** The system automatically checks for and merges duplicate issue reports.
- **Gamification:** Users are awarded points for various activities, such as submitting new reports or confirming existing ones.
- **Image Storage:** Issue-related images are uploaded to Google Cloud Storage.

## Setup and Installation

### 1. Create a Virtual Environment

It is recommended to use a virtual environment to manage the project's dependencies.

```bash
python3 -m venv .venv
```

### 2. Activate the Virtual Environment

On macOS and Linux:

```bash
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

### 3. Install Dependencies

Install the required Python packages using pip:

```bash
pip install -r requirements.txt
```

### 4. Environment Variables

The service requires a `.env` file in the project root for configuration. Create a file named `.env` and add the following line:

```
DATABASE_URL="postgresql://user:password@host:port/database"
```

Replace `"postgresql://user:password@host:port/database"` with your actual database connection string.

## Running the Service

To run the service, use the following command:

```bash
uvicorn main:app --reload
```

The service will be available at `http://127.0.0.1:8000`.

## API Endpoints

Here is a summary of the available API endpoints:

- `GET /`: Root endpoint.
- `GET /health/live`: Liveness check.
- `GET /db-check`: Database connection check.
- `POST /api/v1/issues`: Submit a new issue.
- `GET /api/v1/issues`: Get a list of all issues.
- `GET /api/v1/issues/{id}`: Get details of a specific issue.
- `POST /api/v1/issues/{id}/confirm`: Confirm an existing issue.
- `PUT /api/v1/issues/{id}/status`: Update the status of an issue (for City Employees only).
- `POST /api/v1/issues/{id}/comments`: Add a comment to an issue.
