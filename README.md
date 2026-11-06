# IS MU MCP Server (Masaryk University Study Assistant)

Model Context Protocol (MCP) server connecting AI agents to the Information System of Masaryk University (**IS MU** - `is.muni.cz`). 

Allows LLM assistants (Claude, Cursor, Antigravity, Windsurf) to access enrolled courses, syllabi, study materials (extracting lecture slides, PDFs, code), homework vaults (*odevzdávárny*), personal timetables, grades (*poznámkové bloky*), and noticeboards.

---

## Capabilities

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`check_auth_status`** | _none_ | Verifies active session on `is.muni.cz/auth/student/?lang=en`. Returns student name, UČO, and semester. |
| **`set_session_cookies`** | `cookie_string` | Configures and saves session cookies (`__Host-issession`, `__Host-iscreds`). |
| **`get_enrolled_courses`** | `semester` _(optional)_ | Lists student's enrolled courses with direct links to materials and syllabi. |
| **`get_course_details`** | `course_code`, `faculty`, `semester` | Scrapes course objectives, syllabus topics, instructors, timetable, and completion rules. |
| **`list_study_materials`** | `course_code`, `folder_path` | Browses course study materials repository (`učební materiály`), folders, and files. |
| **`read_study_material`** | `url`, `max_pages`, `max_chars` | Downloads and extracts clean text from PDFs (slides, assignments), HTML, or plain text. |
| **`get_interactive_syllabus`**| `course_code`, `faculty`, `semester` | Fetches week-by-week interactive syllabus (`interaktivní osnova`) and topics. |
| **`get_homework_vaults`** | `course_code` | Checks homework submission boxes (`odevzdávárny`), instructions, and deadlines. |
| **`get_student_timetable`** | _none_ | Retrieves personal weekly lecture, lab, and seminar timetable. |
| **`get_grades_and_notebooks`**| `course_code` _(optional)_ | Fetches test points, homework scores, and grades from `poznámkové bloky`. |
| **`get_student_notices`** | `limit` | Reads announcements from the student noticeboard (`nástěnka`). |
| **`search_is`** | `query` | Queries people, courses, documents, and publications across IS MU. |
| **`get_study_progress_check`** | `study_id` _(optional)_ | Official degree audit check (*Kontrola průchodu studiem*). Reports status of all required course groups, completed/enrolled/missing courses. |
| **`get_study_credit_summary`** | `study_id` _(optional)_ | Academic credit progress, earned credits per semester, currently enrolled credits, and remaining credits to graduate. |
| **`get_registration_timeline`** | `term_id` _(optional)_ | Course registration opening waves, enrolment periods, and change dates across all faculties. |
| **`browse_course_catalogue`** | `query`, `faculty`, `limit` | Searches and discovers elective (volitelné - category C) and selective courses across all university faculties. |
| **`get_exam_dates`** | `term_id` _(optional)_, `study_id` _(optional)_ | Upcoming examination dates, midterm test slots, enrolled reservations, capacities, and deadlines. |
| **`get_student_emails`** | `folder` _(optional)_, `limit` _(optional)_ | Lists university email messages (`/auth/mail/`) with unread flags, sender, date, and subject. |
| **`read_email_message`** | `mail_id` | Full email reading: message headers, sender, recipients, date, subject, body, and download link. |

---

## Quickstart & Agent Integration

### Option 1: Run via `uvx` directly from GitHub (Recommended)

Requires [`uv`](https://docs.astral.sh/uv/).

#### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "is-muni": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/<username>/mcp-is-muni.git",
        "mcp-is-muni"
      ],
      "env": {
        "IS_MUNI_COOKIE": "__Host-issession=YOUR_SESSION; __Host-iscreds=YOUR_CREDS"
      }
    }
  }
}
```

#### Cursor (`.cursor/mcp.json`) / Antigravity (`mcp_config.json`)
```json
{
  "mcpServers": {
    "is-muni": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/<username>/mcp-is-muni.git",
        "mcp-is-muni"
      ]
    }
  }
}
```

---

### Option 2: Local Installation (Clone & Run)

```bash
git clone https://github.com/<username>/mcp-is-muni.git
cd mcp-is-muni
uv run mcp-is-muni
```

Or install in your Python environment:
```bash
pip install .
mcp-is-muni
```

MCP Client configuration for local install:
```json
{
  "mcpServers": {
    "is-muni": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/mcp-is-muni",
        "mcp-is-muni"
      ]
    }
  }
}
```

---

## Authentication Setup

IS MU uses secure HTTP session cookies (`__Host-issession` and `__Host-iscreds`).

### Step 1: Obtain Cookies from Browser
1. Log in to [https://is.muni.cz/auth/student/?lang=en](https://is.muni.cz/auth/student/?lang=en).
2. Open Developer Tools (`F12`) → **Network** tab.
3. Refresh the page and click the first request (`student/?lang=en`).
4. In **Request Headers**, copy the value of `Cookie:` (e.g. `__Host-issession=...; __Host-iscreds=...`).

### Step 2: Configure Authentication

Choose any of the following methods:

* **Method A: CLI Helper**
  ```bash
  mcp-is-muni-auth --cookie "__Host-issession=...; __Host-iscreds=..."
  ```
  Check status anytime:
  ```bash
  mcp-is-muni-auth --status
  ```

* **Method B: Environment Variable**
  Set `IS_MUNI_COOKIE`:
  ```bash
  export IS_MUNI_COOKIE="__Host-issession=...; __Host-iscreds=..."
  ```

* **Method C: Ask your Agent**
  Instruct the agent:
  > *"Use tool `set_session_cookies` with `__Host-issession=...; __Host-iscreds=...`"*

Credentials are saved locally to `~/.config/mcp-is-muni/config.json`.

---

## License

MIT
