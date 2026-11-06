"""
FastMCP Server for Masaryk University Information System (IS MU)
"""

import json
from fastmcp import FastMCP
from .client import ISMuniClient

mcp = FastMCP(
    name="is-muni",
    instructions=(
        "You are an academic study assistant connected directly to the Masaryk University "
        "Information System (IS MU, is.muni.cz). You can retrieve enrolled courses, course syllabi, "
        "study materials (slides, PDFs, documents), interactive weekly syllabi, homework vaults, "
        "timetables, grades, and noticeboards. If authentication is not configured or expired, instruct "
        "the user to provide their session cookies using `set_session_cookies` or the `mcp-is-muni-auth` CLI."
    ),
)

client = ISMuniClient()


@mcp.tool()
def check_auth_status() -> str:
    """
    Check whether the IS MU client is authenticated.
    Returns student profile information (Name, UČO, semester) or setup instructions if unauthenticated.
    """
    status = client.check_auth_status()
    return json.dumps(status, indent=2, ensure_ascii=False)


@mcp.tool()
def set_session_cookies(cookie_string: str) -> str:
    """
    Configure session cookies for IS MU authentication.
    
    Accepts:
    - Raw Cookie HTTP header: "__Host-issession=...; __Host-iscreds=..."
    - JSON array/object exported from browser extensions
    - Single session token string
    
    Persists configuration to ~/.config/mcp-is-muni/config.json.
    """
    parsed = client.parse_cookie_input(cookie_string)
    if not parsed:
        return "Error: No valid cookies parsed from input string."
    client.save_credentials(parsed)
    status = client.check_auth_status()
    return json.dumps({
        "status": "Cookies saved successfully",
        "auth_verification": status
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def get_enrolled_courses(semester: str = "") -> str:
    """
    Retrieve all enrolled courses for the student from https://is.muni.cz/auth/student/?lang=en.
    
    Args:
        semester: Optional semester code (e.g. 'jaro2026', 'podzim2026'). If omitted, current semester is used.
    """
    courses = client.get_enrolled_courses(semester=semester)
    return json.dumps(courses, indent=2, ensure_ascii=False)


@mcp.tool()
def get_course_details(course_code: str, faculty: str = "", semester: str = "") -> str:
    """
    Get full course details, syllabus, objectives, lecture/seminar instructors,
    assessment rules, timetable, and recommended literature.
    
    Args:
        course_code: Course code (e.g. 'IB111', 'PB071', 'PV281').
        faculty: Optional faculty acronym (e.g. 'fi', 'sci', 'fss', 'econ', 'med', 'phil').
        semester: Optional semester code (e.g. 'autumn2026', 'podzim2026').
    """
    details = client.get_course_details(course_code, faculty=faculty, semester=semester)
    return json.dumps(details, indent=2, ensure_ascii=False)


@mcp.tool()
def list_study_materials(course_code: str, folder_path: str = "") -> str:
    """
    List files and folders in the course study materials repository (učební materiály).
    
    Args:
        course_code: Course code (e.g. 'PV281').
        folder_path: Optional relative folder path or subfolder URL.
    """
    materials = client.list_study_materials(course_code, folder_path=folder_path)
    return json.dumps(materials, indent=2, ensure_ascii=False)


@mcp.tool()
def read_study_material(url: str, max_pages: int = 15, max_chars: int = 25000) -> str:
    """
    Download and extract textual content from a study material (PDF slides, HTML, code, or TXT).
    Allows the AI assistant to read lecture materials, assignments, or slides and summarize or explain them.
    
    Args:
        url: Full URL or relative path to the file in IS MU.
        max_pages: Maximum number of PDF pages to extract (default 15).
        max_chars: Maximum characters to return (default 25000).
    """
    result = client.read_study_material(url, max_pages=max_pages, max_chars=max_chars)
    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def get_interactive_syllabus(course_code: str, faculty: str = "", semester: str = "") -> str:
    """
    Fetch the interactive syllabus (interaktivní osnova) showing week-by-week topic outline,
    homework assignments, reading tasks, and linked lecture resources.
    
    Args:
        course_code: Course code (e.g. 'PV281').
        faculty: Optional faculty acronym (e.g. 'fi').
        semester: Optional semester code.
    """
    syllabus = client.get_interactive_syllabus(course_code, faculty=faculty, semester=semester)
    return json.dumps(syllabus, indent=2, ensure_ascii=False)


@mcp.tool()
def get_homework_vaults(course_code: str) -> str:
    """
    List homework submission vaults (odevzdávárny), assignment instructions, and deadlines for a course.
    
    Args:
        course_code: Course code (e.g. 'PV281').
    """
    vaults = client.get_homework_vaults(course_code)
    return json.dumps(vaults, indent=2, ensure_ascii=False)


@mcp.tool()
def get_student_timetable() -> str:
    """
    Fetch the student's personal timetable (lectures, seminars, labs, rooms, and times)
    from https://is.muni.cz/auth/student/rozvrh?lang=en.
    """
    timetable = client.get_timetable()
    return json.dumps(timetable, indent=2, ensure_ascii=False)


@mcp.tool()
def get_grades_and_notebooks(course_code: str = "") -> str:
    """
    Fetch student evaluation records, test points, homework scores, and grades
    from course evaluation notebooks (poznámkové bloky).
    
    Args:
        course_code: Optional course code filter (e.g. 'PV281').
    """
    grades = client.get_grades_and_notebooks(course_code=course_code)
    return json.dumps(grades, indent=2, ensure_ascii=False)


@mcp.tool()
def get_student_notices(limit: int = 10) -> str:
    """
    Fetch announcements, updates, and notices from the student noticeboard (nástěnka).
    
    Args:
        limit: Maximum number of recent notices to retrieve (default 10).
    """
    notices = client.get_student_notices(limit=limit)
    return json.dumps(notices, indent=2, ensure_ascii=False)


@mcp.tool()
def search_is(query: str) -> str:
    """
    Search people (teachers/students), courses, documents, and publications in IS MU.
    
    Args:
        query: Search term (e.g. teacher name, course code, topic).
    """
    results = client.search_is(query)
    return json.dumps(results, indent=2, ensure_ascii=False)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
