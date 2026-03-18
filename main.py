from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from bs4 import BeautifulSoup
from typing import List
import requests
import re

app = FastAPI(title="UQ Course Profile Extractor")


class CourseRequest(BaseModel):
    course_url: HttpUrl
    section: str


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def base_course_url(url: str) -> str:
    return url.split("#")[0].strip()


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; UQCourseProfileBot/1.0)"
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))

    title_tag = soup.find("title")
    if title_tag:
        return clean_text(title_tag.get_text(" ", strip=True))

    return ""


def extract_course_code(course_url: str, title: str) -> str:
    match = re.search(r"/course-profiles/([A-Z]{4}\d{4})", course_url)
    if match:
        return match.group(1)

    match = re.search(r"\b([A-Z]{4}\d{4})\b", title)
    if match:
        return match.group(1)

    return ""


def extract_section_by_anchor_or_heading(
    soup: BeautifulSoup,
    anchor_id: str,
    heading_patterns: List[str]
) -> str:
    node = soup.find(id=anchor_id)

    if node:
        container = node.find_parent(["section", "article"]) or node.find_parent("div") or node
        text = clean_text(container.get_text(" ", strip=True))
        if text:
            return text

    for tag_name in ["h1", "h2", "h3", "h4", "button", "a", "span"]:
        for tag in soup.find_all(tag_name):
            txt = clean_text(tag.get_text(" ", strip=True)).lower()
            if any(pattern.lower() in txt for pattern in heading_patterns):
                container = tag.find_parent(["section", "article"]) or tag.find_parent("div") or tag.parent or tag
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

    content = clean_text(content)[:6000]

    return {
        "course_url": url,
        "course_code": course_code or "Not found on course profile",
        "course_title": course_title or "Not found on course profile",
        "section": section,
        "content": content,
        "source_note": "Content retrieved from the supplied UQ course profile URL."
    }
