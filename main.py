from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from bs4 import BeautifulSoup
import requests
import re

app = FastAPI(title="UQ Course Profile Extractor")


class CourseRequest(BaseModel):
    course_url: HttpUrl
    section: str


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def base_course_url(url: str) -> str:
    # Remove any anchor if someone pastes one
    return url.split("#")[0].strip()


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; UQCourseProfileBot/1.0)"
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def extract_title(soup: BeautifulSoup) -> str:
    # Try common patterns first
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))

    title_tag = soup.find("title")
    if title_tag:
        return clean_text(title_tag.get_text(" ", strip=True))

    return ""


def extract_course_code(course_url: str, title: str) -> str:
    # Try URL first
    match = re.search(r"/course-profiles/([A-Z]{4}\d{4})", course_url)
    if match:
        return match.group(1)

    # Fallback: title text
    match = re.search(r"\b([A-Z]{4}\d{4})\b", title)
    if match:
        return match.group(1)

    return ""


def extract_section_by_anchor_or_heading(soup: BeautifulSoup, anchor_id: str, heading_patterns: list[str]) -> str:
    """
    Tries:
    1. exact id match
    2. any element with matching id
    3. heading text match
    Then returns nearby text.
    """

    # 1) Exact anchor/id
    node = soup.find(id=anchor_id)

    if node:
        # Sometimes the section container is the node itself, sometimes it's just a small anchor.
        # Prefer a parent section/article/div if available.
        container = node.find_parent(["section", "article", "div"]) or node
        text = clean_text(container.get_text(" ", strip=True))
        if text:
            return text

    # 2) Match heading text
    for tag_name in ["h1", "h2", "h3", "h4", "button", "a", "span"]:
        for tag in soup.find_all(tag_name):
            txt = clean_text(tag.get_text(" ", strip=True)).lower()
            if any(pattern.lower() in txt for pattern in heading_patterns):
                container = tag.find_parent(["section", "article", "div"]) or tag.parent or tag
                text = clean_text(container.get_text(" ", strip=True))
                if text:
                    return text

    return ""


@app.post("/get-uq-course-profile")
def get_uq_course_profile(request: CourseRequest):
    url = base_course_url(str(request.course_url))
    section = request.section

    if "course-profiles.uq.edu.au/course-profiles/" not in url:
        raise HTTPException(status_code=400, detail="Invalid UQ course profile URL")

    valid_sections = {
        "course_overview": ("course-overview", ["course overview"]),
        "aim_and_outcomes": ("aim-and-outcomes", ["aim and outcomes", "aim & outcomes", "learning outcomes"]),
        "assessment": ("assessment", ["assessment"]),
        "learning_activities": ("learning-activities", ["learning activities"]),
    }

    if section not in valid_sections:
        raise HTTPException(status_code=400, detail="Invalid section")

    try:
        html = fetch_html(url)
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch course profile: {e}")

    soup = BeautifulSoup(html, "lxml")

    course_title = extract_title(soup)
    course_code = extract_course_code(url, course_title)

    anchor_id, heading_patterns = valid_sections[section]
    content = extract_section_by_anchor_or_heading(
        soup,
        anchor_id=anchor_id,
        heading_patterns=heading_patterns
    )

    if not content:
        content = "Not found on course profile"

    # Optional safety limit
    content = content[:12000]

    return {
        "course_url": url,
        "course_code": course_code or "Not found on course profile",
        "course_title": course_title or "Not found on course profile",
        "section": section,
        "content": content,
        "source_note": "Content retrieved from the supplied UQ course profile URL."
    }
