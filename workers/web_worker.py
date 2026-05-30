from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = "SentinelAI/1.0 (+https://localhost)"
TIMEOUT = 10


def _result(status: str, task_id: str, data=None, error: Optional[str] = None) -> Dict:
    return {"status": status, "task_id": task_id, "data": data, "error": error}


def search_web(query, max_results=5) -> List[Dict[str, str]]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(str(query))}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for node in soup.select(".result")[: int(max_results)]:
        title_node = node.select_one(".result__title a") or node.select_one("a.result__a")
        snippet_node = node.select_one(".result__snippet")
        if not title_node:
            continue
        results.append(
            {
                "title": title_node.get_text(" ", strip=True),
                "url": title_node.get("href", ""),
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
    return results


def fetch_page(url) -> Dict:
    response = requests.get(str(url), headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    links = []
    for anchor in soup.find_all("a", href=True):
        links.append({"text": anchor.get_text(" ", strip=True), "url": urljoin(str(url), anchor["href"])})
    return {"title": title, "text": text, "links": links}


def find_github_issues(repo, label=None, max=10) -> List[Dict]:
    repo = str(repo).strip().removeprefix("https://github.com/").strip("/")
    params = {"state": "open", "per_page": int(max)}
    if label:
        params["labels"] = str(label)
    url = f"https://api.github.com/repos/{repo}/issues"
    response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    issues = []
    for item in response.json():
        if "pull_request" in item:
            continue
        issues.append(
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "url": item.get("html_url", ""),
                "labels": [label.get("name", "") for label in item.get("labels", [])],
                "state": item.get("state", ""),
            }
        )
    return issues[: int(max)]


def run_web_task(task_id, task_description) -> Dict:
    try:
        task = str(task_description)
        lower = task.lower()
        if "github" in lower and "issue" in lower:
            match = re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", task)
            if not match:
                return _result("error", task_id, None, "GitHub repo not found in task")
            return _result("ok", task_id, find_github_issues(match.group(1)))
        if lower.startswith("fetch ") or "fetch page" in lower:
            match = re.search(r"https?://\S+", task)
            if not match:
                return _result("error", task_id, None, "URL not found in task")
            return _result("ok", task_id, fetch_page(match.group(0)))
        if "search" in lower or "web" in lower:
            query = re.sub(r"\b(search|web|for)\b", " ", task, flags=re.I).strip()
            return _result("ok", task_id, search_web(query or task))
        return _result("error", task_id, None, "Unknown web task")
    except Exception as exc:
        return _result("error", task_id, None, str(exc))
