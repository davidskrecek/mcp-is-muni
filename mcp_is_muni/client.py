"""
IS MU (Masaryk University Information System) HTTP Client
Provides high-level methods to fetch and parse student agendas, courses,
study materials, syllabi, timetables, and homework vaults from is.muni.cz.
"""

import os
import json
import logging
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, quote

import httpx
from bs4 import BeautifulSoup
import pypdf

logger = logging.getLogger("mcp_is_muni.client")

def get_config_dir() -> Path:
    """Return standard platform configuration directory."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "mcp-is-muni"
    return Path.home() / ".config" / "mcp-is-muni"

CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
BASE_URL = "https://is.muni.cz"


class ISMuniClient:
    def __init__(self, cookies: Optional[Dict[str, str]] = None):
        transport = httpx.HTTPTransport(retries=3)
        self.session = httpx.Client(
            transport=transport,
            base_url=BASE_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9,cs;q=0.8",
            },
            follow_redirects=True,
            timeout=30.0,
        )
        self.cookies_loaded = False
        if cookies:
            self.session.cookies.update(cookies)
            self.cookies_loaded = True
        else:
            self.load_stored_credentials()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute HTTP request with automated backoff retry for connection drops and rate pacing."""
        import time
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                return self.session.request(method, url, **kwargs)
            except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError):
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.4 * (attempt + 1))

    def _get(self, url: str, **kwargs) -> httpx.Response:
        return self._request("GET", url, **kwargs)

    def _post(self, url: str, **kwargs) -> httpx.Response:
        return self._request("POST", url, **kwargs)

    def parse_cookie_input(self, cookie_input: str) -> Dict[str, str]:
        """Parse cookie string, JSON array, or plain cookie header into a dict."""
        cookie_input = cookie_input.strip()
        parsed: Dict[str, str] = {}

        if cookie_input.startswith("[") or cookie_input.startswith("{"):
            try:
                data = json.loads(cookie_input)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "name" in item and "value" in item:
                            parsed[item["name"]] = item["value"]
                    return parsed
                elif isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except Exception:
                pass

        pairs = [p.strip() for p in cookie_input.split(";") if p.strip()]
        for p in pairs:
            if "=" in p:
                k, v = p.split("=", 1)
                parsed[k.strip()] = v.strip()
            else:
                parsed["__Host-issession"] = p.strip()

        return parsed

    def load_stored_credentials(self) -> bool:
        """Load session credentials from env or config file."""
        env_cookie = os.environ.get("IS_MUNI_COOKIE")
        if env_cookie:
            cookies = self.parse_cookie_input(env_cookie)
            self.session.cookies.update(cookies)
            self.cookies_loaded = True
            return True

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cookies = cfg.get("cookies", {})
                if isinstance(cookies, dict) and cookies:
                    self.session.cookies.update(cookies)
                    self.cookies_loaded = True
                    return True
                elif isinstance(cookies, str) and cookies:
                    parsed = self.parse_cookie_input(cookies)
                    self.session.cookies.update(parsed)
                    self.cookies_loaded = True
                    return True
            except Exception as e:
                logger.warning(f"Failed to read config file {CONFIG_FILE}: {e}")

        return False

    def save_credentials(self, cookies: Dict[str, str]) -> None:
        """Save cookies to config file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookies}, f, indent=2)
        self.session.cookies.update(cookies)
        self.cookies_loaded = True

    def check_auth_status(self) -> Dict[str, Any]:
        """
        Verify if the client is authenticated with IS MU.
        Returns student identity info if valid, or instructions if unauthenticated.
        """
        try:
            resp = self._get("/auth/student/?lang=en")
            final_url = str(resp.url)

            if "muni.islogin.cz" in final_url or "/login" in final_url or resp.status_code in (401, 403):
                return {
                    "authenticated": False,
                    "message": (
                        "Not authenticated with IS MU. Session cookie is missing or expired. "
                        "Call tool `set_session_cookies` with your cookie string from is.muni.cz "
                        "(containing `__Host-issession` and `__Host-iscreds`)."
                    ),
                    "redirect_url": final_url,
                }

            soup = BeautifulSoup(resp.text, "html.parser")

            student_name = ""
            uco = ""

            user_elem = soup.find(id="identita") or soup.find("div", class_="identita") or soup.find(class_="user-info")
            if user_elem:
                text = user_elem.get_text(" ", strip=True)
                uco_match = re.search(r"(\d{5,7})", text)
                if uco_match:
                    uco = uco_match.group(1)
                student_name = text.split(",")[0].strip()

            if not student_name:
                h1 = soup.find("h1")
                if h1:
                    student_name = h1.get_text(strip=True)

            sem_elem = soup.find("select", attrs={"name": "obdobi"}) or soup.find(id="obdobi")
            current_semester = sem_elem.find("option", selected=True).get_text(strip=True) if sem_elem else "Current"

            return {
                "authenticated": True,
                "student_name": student_name,
                "uco": uco,
                "current_semester": current_semester,
                "url": final_url,
            }
        except Exception as e:
            return {
                "authenticated": False,
                "error": str(e),
                "message": "Failed to connect to https://is.muni.cz",
            }

    def get_enrolled_courses(self, semester: str = "") -> List[Dict[str, Any]]:
        """
        Scrapes enrolled courses for the student from /auth/student/?lang=en.
        """
        url = "/auth/student/?lang=en"
        if semester:
            url += f"&obdobi={quote(semester)}"

        resp = self._get(url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required. Set active IS MU session cookie.")

        soup = BeautifulSoup(resp.text, "html.parser")
        courses: List[Dict[str, Any]] = []

        course_links = soup.find_all("a", href=re.compile(r"/auth/predmet[y]?/|#"))
        seen_codes = set()

        for a in course_links:
            text = a.get_text(" ", strip=True)
            href = a.get("href", "")

            code_match = re.search(r"\b([A-Z0-9]{2,8}[a-z]?)\b", text)
            if not code_match:
                code_match = re.search(r"/([A-Za-z0-9_]{3,10})\??", href)
            if not code_match:
                continue

            course_code = code_match.group(1).upper()
            if course_code in seen_codes or len(course_code) < 3 or course_code in ("PREDMET", "STUDENT", "PREDMETY", "COURSES"):
                continue
            seen_codes.add(course_code)

            container = a.find_parent(["div", "li", "tr", "p"])
            context_text = container.get_text(" ", strip=True) if container else text

            materials_link = ""
            mat_a = container.find("a", href=re.compile(r"rfmgr\.pl|/um/|/el/")) if container else None
            if mat_a:
                materials_link = urljoin(BASE_URL, mat_a.get("href", ""))

            syllabus_link = ""
            syl_a = container.find("a", href=re.compile(r"index\.qrich|osnova")) if container else None
            if syl_a:
                syllabus_link = urljoin(BASE_URL, syl_a.get("href", ""))

            vault_link = ""
            v_a = container.find("a", href=re.compile(r"odevzdavarny")) if container else None
            if v_a:
                vault_link = urljoin(BASE_URL, v_a.get("href", ""))

            courses.append({
                "code": course_code,
                "name": text,
                "course_url": urljoin(BASE_URL, href) if href != "#" else f"/predmety/predmet?kod={course_code}&lang=en",
                "summary": context_text,
                "materials_url": materials_link,
                "interactive_syllabus_url": syllabus_link,
                "homework_vault_url": vault_link,
            })

        return courses

    def get_course_details(self, course_code: str, faculty: str = "", semester: str = "") -> Dict[str, Any]:
        """
        Fetches full course syllabus, timetable, teachers, and completion requirements.
        Tries authenticated endpoint first, falls back to public course catalogue.
        """
        course_code = course_code.strip().upper()
        urls_to_try = []

        if faculty and semester:
            urls_to_try.append(f"/auth/predmet/{faculty.lower()}/{semester}/{course_code}?lang=en")
            urls_to_try.append(f"/course/{faculty.lower()}/{semester}/{course_code}?lang=en")

        urls_to_try.append(f"/auth/predmety/predmet?kod={course_code}&lang=en")
        urls_to_try.append(f"/predmety/predmet?kod={course_code}&lang=en")

        soup = None
        target_url = ""
        for u in urls_to_try:
            try:
                resp = self._get(u)
                if resp.status_code == 200 and "muni.islogin.cz" not in str(resp.url):
                    s = BeautifulSoup(resp.text, "html.parser")
                    title_elem = s.find("h1") or s.find("title")
                    if title_elem and course_code in title_elem.get_text():
                        soup = s
                        target_url = str(resp.url)
                        break
            except Exception:
                continue

        if not soup:
            search_resp = self._get(f"/auth/vyhledavani/?search={course_code}&lang=en")
            s = BeautifulSoup(search_resp.text, "html.parser")
            found_a = s.find("a", href=re.compile(rf"/predmet.*/{course_code}|/course/.*/{course_code}", re.IGNORECASE))
            if found_a:
                resp = self._get(found_a["href"])
                soup = BeautifulSoup(resp.text, "html.parser")
                target_url = str(resp.url)

        if not soup:
            raise FileNotFoundError(f"Course {course_code} not found.")

        title = soup.find("h1").get_text(strip=True) if soup.find("h1") else course_code
        course_info: Dict[str, Any] = {
            "code": course_code,
            "title": title,
            "url": target_url,
            "attributes": {},
            "sections": {},
        }

        for dt in soup.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            key = dt.get_text(" ", strip=True).rstrip(":")
            val = dd.get_text(" ", strip=True) if dd else ""
            if key and val:
                course_info["attributes"][key] = val

        for h in soup.find_all(["h2", "h3"]):
            header_text = h.get_text(" ", strip=True)
            if not header_text or header_text in ("Navigation", "Other applications"):
                continue

            content_parts = []
            curr = h.find_next_sibling()
            while curr and curr.name not in ["h2", "h3"]:
                text = curr.get_text("\n", strip=True)
                if text:
                    content_parts.append(text)
                curr = curr.find_next_sibling()

            if content_parts:
                course_info["sections"][header_text] = "\n\n".join(content_parts)

        return course_info

    def list_study_materials(self, course_code: str, folder_path: str = "") -> Dict[str, Any]:
        """
        Lists study materials and folders for a given course.
        """
        course_code = course_code.strip().upper()
        materials_url = f"/auth/dok/rfmgr.pl?furl=%2Fel%2Ffi%2Fcurrent%2F{course_code}%2Fum%2F&lang=en"

        try:
            courses = self.get_enrolled_courses()
            matched = next((c for c in courses if c["code"] == course_code), None)
            if matched and matched.get("materials_url"):
                materials_url = matched["materials_url"]
        except Exception:
            pass

        if folder_path:
            materials_url = urljoin(materials_url, folder_path)

        resp = self._get(materials_url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required to access course study materials.")

        soup = BeautifulSoup(resp.text, "html.parser")
        items: List[Dict[str, Any]] = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)

            if not text or href.startswith("javascript:") or href.startswith("#"):
                continue

            full_link = urljoin(str(resp.url), href)
            is_folder = "rfmgr.pl" in href or href.endswith("/")
            is_file = any(href.lower().split("?")[0].endswith(ext) for ext in [".pdf", ".zip", ".ipynb", ".py", ".c", ".java", ".txt", ".docx", ".pptx", ".html"])

            if is_folder or is_file or "/el/" in href or "/dok/" in href:
                parent_row = a.find_parent("tr")
                meta_info = parent_row.get_text(" | ", strip=True) if parent_row else text

                items.append({
                    "name": text,
                    "url": full_link,
                    "type": "folder" if is_folder else "file",
                    "details": meta_info,
                })

        return {
            "course_code": course_code,
            "base_url": str(resp.url),
            "items": items,
        }

    def read_study_material(self, url: str, max_pages: int = 15, max_chars: int = 25000) -> Dict[str, Any]:
        """
        Downloads and extracts textual content from a study material (PDF, HTML, code, or TXT).
        """
        full_url = urljoin(BASE_URL, url)
        resp = self._get(full_url)

        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required to read this material.")

        content_type = resp.headers.get("content-type", "").lower()

        if "application/pdf" in content_type or full_url.lower().split("?")[0].endswith(".pdf"):
            reader = pypdf.PdfReader(io.BytesIO(resp.content))
            total_pages = len(reader.pages)
            pages_to_read = min(total_pages, max_pages)

            extracted_text = []
            char_count = 0
            for i in range(pages_to_read):
                p_text = reader.pages[i].extract_text() or ""
                extracted_text.append(f"--- Page {i + 1} / {total_pages} ---\n{p_text}")
                char_count += len(p_text)
                if char_count >= max_chars:
                    extracted_text.append(f"\n[Truncated after page {i + 1} due to character limit]")
                    break

            return {
                "url": full_url,
                "type": "pdf",
                "total_pages": total_pages,
                "pages_read": pages_to_read,
                "text": "\n\n".join(extracted_text)[:max_chars],
            }

        elif any(t in content_type for t in ["text/html", "application/xhtml+xml"]):
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            clean_text = soup.get_text("\n", strip=True)
            return {
                "url": full_url,
                "type": "html",
                "text": clean_text[:max_chars],
                "truncated": len(clean_text) > max_chars,
            }

        else:
            text = resp.text
            return {
                "url": full_url,
                "type": "text",
                "text": text[:max_chars],
                "truncated": len(text) > max_chars,
            }

    def get_interactive_syllabus(self, course_code: str, faculty: str = "", semester: str = "") -> Dict[str, Any]:
        """
        Fetches interactive syllabus (interaktivní osnova) week-by-week topic breakdown.
        """
        course_code = course_code.strip().upper()
        syllabus_url = f"/auth/el/fi/current/{course_code}/index.qrich?lang=en"

        try:
            courses = self.get_enrolled_courses()
            matched = next((c for c in courses if c["code"] == course_code), None)
            if matched and matched.get("interactive_syllabus_url"):
                syllabus_url = matched["interactive_syllabus_url"]
            elif faculty and semester:
                syllabus_url = f"/auth/el/{faculty.lower()}/{semester}/{course_code}/index.qrich?lang=en"
        except Exception:
            pass

        resp = self._get(syllabus_url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for interactive syllabus.")

        soup = BeautifulSoup(resp.text, "html.parser")
        weeks_or_topics: List[Dict[str, Any]] = []

        blocks = soup.find_all(class_=re.compile(r"osnov|blok|tyden|week", re.IGNORECASE))
        if not blocks:
            blocks = soup.find_all(["h2", "h3"])

        for b in blocks:
            title = b.get_text(" ", strip=True)
            if not title:
                continue
            links = []
            for a in b.find_all("a", href=True):
                links.append({"text": a.get_text(strip=True), "url": urljoin(str(resp.url), a["href"])})
            weeks_or_topics.append({
                "title": title,
                "links": links,
            })

        body_text = soup.get_text("\n", strip=True)
        return {
            "course_code": course_code,
            "syllabus_url": str(resp.url),
            "topics": weeks_or_topics,
            "full_content_preview": body_text[:8000],
        }

    def get_homework_vaults(self, course_code: str) -> List[Dict[str, Any]]:
        """
        Retrieves homework vaults (odevzdávárny) and assignment deadlines.
        """
        course_code = course_code.strip().upper()
        vault_url = f"/auth/el/fi/current/{course_code}/odevzdavarny/?lang=en"

        try:
            courses = self.get_enrolled_courses()
            matched = next((c for c in courses if c["code"] == course_code), None)
            if matched and matched.get("homework_vault_url"):
                vault_url = matched["homework_vault_url"]
        except Exception:
            pass

        resp = self._get(vault_url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for homework vaults.")

        soup = BeautifulSoup(resp.text, "html.parser")
        vaults: List[Dict[str, Any]] = []

        for row in soup.find_all("tr"):
            a = row.find("a", href=True)
            if not a:
                continue
            name = a.get_text(strip=True)
            full_link = urljoin(str(resp.url), a["href"])
            row_text = row.get_text(" | ", strip=True)
            vaults.append({
                "name": name,
                "url": full_link,
                "details": row_text,
            })

        return vaults

    def get_timetable(self) -> List[Dict[str, Any]]:
        """
        Fetches student schedule / timetable from /auth/student/rozvrh?lang=en.
        """
        resp = self._get("/auth/student/rozvrh?lang=en")
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for timetable.")

        soup = BeautifulSoup(resp.text, "html.parser")
        schedule: List[Dict[str, Any]] = []

        events = soup.find_all(class_=re.compile(r"blok|udalost|rozvrh-bunka|item", re.IGNORECASE))
        for ev in events:
            txt = ev.get_text(" ", strip=True)
            if txt:
                schedule.append({"details": txt})

        for tr in soup.find_all("tr"):
            day_th = tr.find(["th", "td"], class_=re.compile(r"den|day", re.IGNORECASE))
            if day_th:
                day_name = day_th.get_text(strip=True)
                items = [td.get_text(" ", strip=True) for td in tr.find_all("td") if td.get_text(strip=True)]
                if items:
                    schedule.append({"day": day_name, "items": items})

        return schedule

    def get_grades_and_notebooks(self, course_code: str = "") -> List[Dict[str, Any]]:
        """
        Fetches evaluation notebooks (poznámkové bloky) and points.
        """
        resp = self._get("/auth/student/poznamkove_bloky?lang=en")
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for notebooks.")

        soup = BeautifulSoup(resp.text, "html.parser")
        results: List[Dict[str, Any]] = []

        tables = soup.find_all("table")
        for tbl in tables:
            rows = tbl.find_all("tr")
            for r in rows:
                text = r.get_text(" | ", strip=True)
                if not text:
                    continue
                if not course_code or course_code.upper() in text.upper():
                    results.append({"evaluation": text})

        return results

    def get_student_notices(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetches notices and announcements from student noticeboard.
        """
        resp = self._get("/auth/student/nastenka?lang=en")
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for noticeboard.")

        soup = BeautifulSoup(resp.text, "html.parser")
        notices: List[Dict[str, Any]] = []

        items = soup.find_all(class_=re.compile(r"zprava|prispevek|notice|post", re.IGNORECASE))
        if not items:
            items = soup.find_all(["article", "li"])

        for it in items[:limit]:
            title_elem = it.find(["h2", "h3", "h4", "strong", "a"])
            title = title_elem.get_text(strip=True) if title_elem else "Notice"
            body = it.get_text(" ", strip=True)
            if len(body) > 10:
                notices.append({"title": title, "content": body[:1000]})

        return notices

    def search_is(self, query: str) -> List[Dict[str, Any]]:
        """
        Executes search in IS MU across people, courses, and documents.
        Supports both authenticated (/auth/vyhledavani/) and public (/vyhledavani/) interfaces.
        """
        endpoint = "/auth/vyhledavani/" if self.cookies_loaded else "/vyhledavani/"
        url = f"{endpoint}?search={quote(query)}&lang=en"

        resp = self._get(url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            resp = self._get(f"/vyhledavani/?search={quote(query)}&lang=en")

        soup = BeautifulSoup(resp.text, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_urls = set()

        for li in soup.find_all(["li", "div"], class_=re.compile(r"vysledek|result|polozka", re.IGNORECASE)):
            a = li.find("a", href=True)
            if not a:
                continue
            link = urljoin(BASE_URL, a["href"])
            if link in seen_urls:
                continue
            seen_urls.add(link)
            results.append({
                "title": a.get_text(strip=True),
                "url": link,
                "snippet": li.get_text(" ", strip=True)[:400],
            })

        if not results:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if any(x in href for x in ["/course/", "/predmet", "/dok/", "/lide/", "/auth/"]):
                    link = urljoin(BASE_URL, href)
                    if link in seen_urls:
                        continue
                    seen_urls.add(link)
                    parent = a.find_parent(["p", "div", "li", "td"])
                    snippet = parent.get_text(" ", strip=True) if parent else a.get_text(strip=True)
                    results.append({
                        "title": a.get_text(strip=True),
                        "url": link,
                        "snippet": snippet[:400],
                    })

        return results[:25]

    def _discover_study_id(self) -> str:
        """Find active study ID from student portal."""
        r = self._get("/auth/student/?lang=en")
        m = re.search(r"studium=(\d+)", r.text)
        return m.group(1) if m else ""

    def get_study_progress_check(self, study_id: str = "") -> Dict[str, Any]:
        """
        Performs official degree audit check (Kontrola průchodu studiem) using assigned monitoring templates.
        Categorizes requirements into completed, enrolled/in-progress, and missing courses by group.
        """
        if not study_id:
            study_id = self._discover_study_id()
        if not study_id:
            raise ValueError("Could not determine student study ID (studium).")

        form_url = f"/auth/student/moje_kontrola_studia?studium={study_id};lang=en"
        r_form = self._get(form_url)
        if "login" in str(r_form.url) or "muni.islogin.cz" in str(r_form.url):
            raise PermissionError("Authentication required for study progress check.")

        soup_form = BeautifulSoup(r_form.text, "html.parser")
        form = soup_form.find("form", action=re.compile(r"moje_kontrola_studia"))

        post_data: Dict[str, str] = {}
        if form:
            for inp in form.find_all("input"):
                n = inp.get("name")
                v = inp.get("value", "")
                if n:
                    post_data[n] = v
            post_data["sabprokon_tl"] = "Check my studies"
        else:
            post_data = {
                "studium": study_id,
                "lang": "en",
                "sabprokon_tl": "Check my studies",
            }

        r_post = self._post(form_url, data=post_data)
        soup_res = BeautifulSoup(r_post.text, "html.parser")

        # Find the monitoring template results block
        template_node = soup_res.find(string=re.compile(r"The courses completed are marked green", re.I))
        if not template_node:
            raise RuntimeError("Could not find degree audit results in response.")

        p_container = soup_res.find(string=re.compile(r"Povinné předměty", re.I))
        if not p_container:
            p_container = template_node.find_parent("form") or soup_res.find("main")
        else:
            p_container = p_container.find_parent("p")

        lines = []
        curr = []
        for child in p_container.children:
            if child.name == "br":
                lines.append(curr)
                curr = []
            else:
                curr.append(child)
        if curr:
            lines.append(curr)

        groups: List[Dict[str, Any]] = []
        current_group: Optional[Dict[str, Any]] = None

        for line in lines:
            line_soup = BeautifulSoup("".join(str(c) for c in line), "html.parser")
            txt = line_soup.get_text(" ", strip=True)
            if not txt:
                continue

            status = "unknown"
            if line_soup.find("font", color="green") or txt.startswith("o "):
                status = "completed"
            elif line_soup.find("span", class_="maybe") or txt.startswith("? "):
                status = "enrolled"
            elif line_soup.find("font", color="red") or txt.startswith("x "):
                status = "missing"

            a = line_soup.find("a", href=re.compile(r"/course/|/predmet"))
            if a:
                course_code = a.get_text(strip=True)
                desc = txt
                for prefix in ["o ", "x ", "? "]:
                    if desc.startswith(prefix):
                        desc = desc[len(prefix):]
                if desc.startswith(course_code):
                    desc = desc[len(course_code):].strip()

                course_item = {
                    "code": course_code,
                    "status": status,
                    "description": desc,
                    "url": urljoin(BASE_URL, a["href"]),
                }
                if current_group:
                    current_group["courses"].append(course_item)
            else:
                clean_title = re.sub(r"^[ox\?]\s*", "", txt)
                if any(x in clean_title.lower() for x in ["check your studies", "templates assigned", "select one or more"]):
                    continue
                current_group = {
                    "group_name": clean_title,
                    "status": status,
                    "courses": [],
                }
                groups.append(current_group)

        # Summary count of missing vs completed groups
        missing_count = sum(1 for g in groups if g["status"] == "missing")
        completed_count = sum(1 for g in groups if g["status"] == "completed")

        return {
            "study_id": study_id,
            "groups_total": len(groups),
            "groups_completed": completed_count,
            "groups_pending": missing_count,
            "groups": groups,
        }

    def get_study_credit_summary(self, study_id: str = "") -> Dict[str, Any]:
        """
        Retrieves earned credits, grade averages, and enrolled credits per semester.
        """
        if not study_id:
            study_id = self._discover_study_id()
        if not study_id:
            raise ValueError("Could not determine student study ID (studium).")

        url = f"/auth/student/moje_znamky?studium={study_id};vsob=1;lang=en"
        resp = self._get(url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for grades and credit summary.")

        soup = BeautifulSoup(resp.text, "html.parser")
        semesters: List[Dict[str, Any]] = []
        current_sem: Optional[Dict[str, Any]] = None

        for tr in soup.find_all("tr"):
            span = tr.find("span", class_="table_obdobi_nadpis")
            if span:
                current_sem = {
                    "semester": span.get_text(strip=True),
                    "credits_earned": 0,
                    "credits_enrolled": 0,
                    "courses": [],
                }
                semesters.append(current_sem)
                continue

            if current_sem:
                tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if len(tds) >= 4 and not any(k in tds[0].lower() for k in ["course", "předmět", "grade average", "studijní průměr"]):
                    name_code = tds[0]
                    cr_str = tds[1]
                    eval_str = tds[3]
                    try:
                        cr = int(cr_str)
                    except ValueError:
                        cr = 0

                    is_completed = any(
                        eval_str.startswith(f"Evaluation: {g}") or eval_str.startswith(f"Evaluation:{g}")
                        for g in ["A", "B", "C", "D", "E", "Z", "P", "FC", "FE"]
                    )
                    if is_completed:
                        current_sem["credits_earned"] += cr
                    else:
                        current_sem["credits_enrolled"] += cr

                    current_sem["courses"].append({
                        "course": name_code,
                        "credits": cr,
                        "evaluation": eval_str,
                        "completed": is_completed,
                    })

        total_earned = sum(s["credits_earned"] for s in semesters)
        total_enrolled = sum(s["credits_enrolled"] for s in semesters)

        return {
            "study_id": study_id,
            "total_credits_earned": total_earned,
            "current_credits_enrolled": total_enrolled,
            "total_credits_expected_after_term": total_earned + total_enrolled,
            "degree_target_credits": 120,
            "credits_remaining_for_degree": max(0, 120 - (total_earned + total_enrolled)),
            "semesters": semesters,
        }

    def get_registration_timeline(self, term_id: str = "10383") -> Dict[str, Any]:
        """
        Retrieves course registration waves, enrolment periods, and change periods across all faculties.
        
        Args:
            term_id: Term ID (default '10383' for Spring 2027; '10103' for Autumn 2026).
        """
        study_id = self._discover_study_id()
        url = f"/auth/student/zapis?obdobi={term_id};studium={study_id};lang=en"
        resp = self._get(url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for registration timeline.")

        soup = BeautifulSoup(resp.text, "html.parser")
        posun_elem = soup.find(class_="rpa-obdobi-posun-info")
        student_info = posun_elem.get_text(" | ", strip=True) if posun_elem else ""

        faculties: List[Dict[str, str]] = []
        for row in soup.find_all(class_=re.compile(r"rpa-obdobi-pruh", re.I)):
            fac_elem = row.find(class_=re.compile(r"rpa-obdobi-fakulta", re.I))
            if not fac_elem:
                continue
            fac_name = fac_elem.get_text(strip=True)

            reg_el = row.find(class_=re.compile(r"rpa-obdobi-registrace", re.I))
            zap_el = row.find(class_=re.compile(r"rpa-obdobi-zapis", re.I))
            zme_el = row.find(class_=re.compile(r"rpa-obdobi-zmeny", re.I))

            faculties.append({
                "faculty": fac_name,
                "registration": reg_el.get_text(" ", strip=True) if reg_el else "",
                "enrolment": zap_el.get_text(" ", strip=True) if zap_el else "",
                "changes": zme_el.get_text(" ", strip=True) if zme_el else "",
            })

        return {
            "term_id": term_id,
            "student_credit_status": student_info,
            "faculties": faculties,
        }

    def browse_course_catalogue(self, query: str, faculty: str = "", limit: int = 25) -> List[Dict[str, Any]]:
        """
        Search and discover elective (volitelné - category C) and selective courses across all university faculties.
        
        Args:
            query: Search keywords (e.g. topic, discipline, course code prefix).
            faculty: Optional faculty acronym (e.g. 'fi', 'fss', 'econ', 'sci', 'phil', 'law', 'med').
            limit: Maximum results to return (default 25).
        """
        q = f"{query} {faculty}".strip()
        return self.search_is(q)[:limit]

    def get_exam_dates(self, term_id: str = "", study_id: str = "") -> Dict[str, Any]:
        """
        Retrieves examination dates, midterm test slots, enrolled reservations, capacities, and deadlines.
        
        Args:
            term_id: Optional term ID (e.g. '10103' for Autumn 2026). Uses active semester if empty.
            study_id: Optional study ID (e.g. '1234567'). Auto-discovered if empty.
        """
        url = "/auth/student/prihl_na_zkousky?lang=en"
        params = []
        if term_id:
            params.append(f"obdobi={term_id}")
        if study_id:
            params.append(f"studium={study_id}")
        if params:
            url += ";" + ";".join(params)

        resp = self._get(url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for examination dates.")

        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. Reserved slots
        reserved_slots: List[Dict[str, Any]] = []
        for table in soup.find_all("table", class_="data1"):
            rows = table.find_all("tr")
            for i in range(0, len(rows), 2):
                r_head = rows[i]
                course_series = r_head.get_text(strip=True)
                if i + 1 < len(rows):
                    r_detail = rows[i + 1]
                    detail_link = r_detail.find("a", href=lambda h: h and "zkt=" in h)
                    zkt_match = re.search(r"zkt=(\d+)", detail_link["href"]) if detail_link else None
                    zkt_id = zkt_match.group(1) if zkt_match else ""

                    tds = r_detail.find_all("td")
                    if len(tds) >= 2:
                        info_td = tds[1]
                        b_tag = info_td.find("b")
                        datetime_room = b_tag.get_text(strip=True) if b_tag else ""
                        full_text = info_td.get_text(" \n ", strip=True)

                        res_match = re.search(r"reservations:\s*(\d+),\s*max\.\s*(\d+)", full_text)
                        reservations = int(res_match.group(1)) if res_match else None
                        max_capacity = int(res_match.group(2)) if res_match else None

                        open_match = re.search(r"open for reservations from\s+([^\n]+)", full_text)
                        open_date = open_match.group(1).strip() if open_match else ""

                        note = ""
                        for f in info_td.find_all("font"):
                            f_txt = f.get_text(strip=True)
                            if (
                                not f_txt.startswith("open for")
                                and not f_txt.startswith("Posted:")
                                and "cancel" not in f_txt.lower()
                                and "swap" not in f_txt.lower()
                            ):
                                note = f_txt
                                break

                        course_code_match = re.match(r"([A-Z0-9]{4,8})\b", course_series)
                        course_code = course_code_match.group(1) if course_code_match else ""

                        reserved_slots.append({
                            "slot_id": zkt_id,
                            "course_code": course_code,
                            "course_series": course_series,
                            "datetime_room": datetime_room,
                            "reservations": reservations,
                            "max_capacity": max_capacity,
                            "open_for_reservations": open_date,
                            "note": note,
                            "can_cancel": bool(r_detail.find("a", class_="odhlaseni")),
                        })

        # 2. Upcoming series & dates
        series_list: List[Dict[str, Any]] = []
        for a in soup.find_all("a", href=lambda h: h and "serie=" in h and "odhlasit" not in h):
            href = a["href"]
            series_title = a.get_text(strip=True)
            predmet_match = re.search(r"predmet=(\d+)", href)
            serie_match = re.search(r"serie=(\d+)", href)
            predmet_id = predmet_match.group(1) if predmet_match else ""
            serie_id = serie_match.group(1) if serie_match else ""

            series_url = href
            if series_url.startswith("."):
                series_url = "/auth/student" + series_url[1:]

            s_resp = self._get(series_url)
            s_soup = BeautifulSoup(s_resp.text, "html.parser")
            slots: List[Dict[str, Any]] = []
            s_table = s_soup.find("table", class_="data1")
            if s_table:
                for s_tr in s_table.find_all("tr", valign="top"):
                    s_tds = s_tr.find_all("td")
                    if len(s_tds) >= 3:
                        st_enroll = s_tds[0].get_text(" ", strip=True)
                        s_detail_link = s_tds[1].find("a", href=lambda h: h and "zkt=" in h)
                        s_zkt_match = re.search(r"zkt=(\d+)", s_detail_link["href"]) if s_detail_link else None
                        s_zkt_id = s_zkt_match.group(1) if s_zkt_match else ""

                        s_info_td = s_tds[2]
                        s_b = s_info_td.find("b")
                        s_dt_room = s_b.get_text(strip=True) if s_b else ""
                        s_full_text = s_info_td.get_text(" \n ", strip=True)

                        s_res_match = re.search(r"reservations:\s*(\d+),\s*max\.\s*(\d+)", s_full_text)
                        s_res = int(s_res_match.group(1)) if s_res_match else None
                        s_max = int(s_res_match.group(2)) if s_res_match else None

                        s_open_match = re.search(r"open for reservations from\s+([^\n]+)", s_full_text)
                        s_open = s_open_match.group(1).strip() if s_open_match else ""

                        s_note = ""
                        for f in s_info_td.find_all("font"):
                            f_txt = f.get_text(strip=True)
                            if (
                                not f_txt.startswith("open for")
                                and not f_txt.startswith("Posted:")
                                and "attempt to" not in f_txt
                                and "swap at" not in f_txt
                            ):
                                s_note = f_txt
                                break

                        slots.append({
                            "slot_id": s_zkt_id,
                            "status": st_enroll,
                            "datetime_room": s_dt_room,
                            "reservations": s_res,
                            "max_capacity": s_max,
                            "open_for_reservations": s_open,
                            "note": s_note,
                        })

            course_code_match = re.match(r"([A-Z0-9]{4,8})\b", series_title)
            series_list.append({
                "course_code": course_code_match.group(1) if course_code_match else "",
                "series_title": series_title,
                "predmet_id": predmet_id,
                "serie_id": serie_id,
                "slots": slots,
            })

        # 3. Courses without dates
        no_exam_courses: List[str] = []
        for t in soup.find_all("table", class_="navodek"):
            if "no examination date has been posted" in t.get_text():
                ul = t.find_next_sibling("ul")
                if ul:
                    no_exam_courses = [item.strip() for item in re.findall(r"<li>\s*([^<\n]+)", str(ul)) if item.strip()]

        return {
            "reserved_slots": reserved_slots,
            "upcoming_series": series_list,
            "courses_without_exam_dates": no_exam_courses,
        }

    def get_student_emails(self, folder: str = "inbox", limit: int = 25) -> Dict[str, Any]:
        """
        Retrieves list of student emails from university webmail (/auth/mail/).
        
        Args:
            folder: Target folder name ('inbox', 'sent', 'spam', 'trash', 'archive') or custom folder_id.
            limit: Maximum messages to retrieve (default 25).
        """
        folder_map = {
            "inbox": "1560343",
            "sent": "1564947",
            "odeslana": "1564947",
            "spam": "1604035",
            "trash": "1606193",
            "kos": "1606193",
            "archive": "1560603",
            "archiv": "1560603",
        }
        fid = folder_map.get(folder.lower(), folder)
        url = f"/auth/mail/?lang=en;folder_id={fid};count={limit}"
        resp = self._get(url)
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for university email.")

        soup = BeautifulSoup(resp.text, "html.parser")
        messages: List[Dict[str, Any]] = []
        for r in soup.find_all("tr", id=lambda x: x and x.startswith("mail_")):
            mail_id = r["id"].replace("mail_", "")
            is_unread = "riadok_new" in r.get("class", [])

            from_col = r.find(id=f"from_id_{mail_id}")
            from_adr = from_col.get("data-from_adr") if from_col else ""

            sender_name = r.find(id=f"span_from_adr_{mail_id}") or r.find(id=f"span_from_uco_{mail_id}")
            sender = sender_name.get_text(strip=True) if sender_name else ""

            subj_link = r.find(id=f"read_link_{mail_id}")
            subject = subj_link.get_text(strip=True) if subj_link else ""

            cols = r.find_all("td")
            date = cols[5].get_text(strip=True) if len(cols) > 5 else ""
            size = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            messages.append({
                "id": mail_id,
                "is_unread": is_unread,
                "sender": sender,
                "sender_address": from_adr,
                "subject": subject,
                "date": date,
                "size": size,
            })
            if len(messages) >= limit:
                break

        return {
            "folder": folder,
            "folder_id": fid,
            "count": len(messages),
            "messages": messages,
        }

    def read_email_message(self, mail_id: str) -> Dict[str, Any]:
        """
        Reads full body, headers, and metadata of a specific university email message.
        
        Args:
            mail_id: Unique message identifier (e.g. '388608368').
        """
        import html
        resp = self._post(
            "/auth/mail/mail_ajax?lang=en",
            data={"akce": "read_mail", "mail_list": mail_id},
        )
        if "login" in str(resp.url) or "muni.islogin.cz" in str(resp.url):
            raise PermissionError("Authentication required for university email.")

        soup_xml = BeautifulSoup(resp.text, "xml")
        html_node = soup_xml.find("html")
        if not html_node:
            raise ValueError(f"Message {mail_id} could not be loaded or was deleted.")

        raw_html = html.unescape(html_node.text)
        soup = BeautifulSoup(raw_html, "html.parser")

        header_div = soup.find("div", class_="mailHeaders")
        sender = ""
        recipients = ""
        date = ""
        subject = ""

        if header_div:
            for line in header_div.get_text("\n", strip=True).splitlines():
                line_str = line.strip()
                if line_str.startswith("From:"):
                    sender = line_str.replace("From:", "").replace("add to contacts", "").strip()
                elif line_str.startswith("To:"):
                    recipients = line_str.replace("To:", "").strip()
                elif line_str.startswith("Date:"):
                    date = line_str.replace("Date:", "").strip()
                elif line_str.startswith("Subject:"):
                    subject = line_str.replace("Subject:", "").strip()

        body_div = soup.find("div", class_="mB_zprava")
        body_text = body_div.get_text("\n", strip=True) if body_div else ""

        dl_link = soup.find("a", id=lambda x: x and x.startswith("download_"))
        download_url = dl_link["href"] if dl_link else ""

        return {
            "mail_id": mail_id,
            "sender": sender,
            "recipients": recipients,
            "date": date,
            "subject": subject,
            "body": body_text,
            "download_url": download_url,
        }
