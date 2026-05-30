"""
scanner.py — Opportunity scanner for Sentinel Earn
Scrapes Algora.io, IssueHunt.io, GitHub Issues API
Scores and filters for JS/TS/Python bounties with complexity <= 5
APScheduler every 2 hours
"""
import asyncio
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional

import httpx
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import os

import db
import learning_memory as lm

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
TARGET_LANGUAGES = {"javascript", "typescript", "python"}
MAX_COMPLEXITY = 5
SCAN_INTERVAL_HOURS = int(os.getenv("SCAN_INTERVAL_HOURS", "2"))
MIN_REPO_STARS = 50
MIN_GITHUB_REPO_STARS = 200
GITHUB_SEARCH_REPO_STARS = 500
MIN_GITCOIN_BOUNTY = 50

REJECT_REPO_TERMS = {
    "bounty-board",
    "bounties",
    "bountyscout",
    "artifact",
    "test",
    "demo",
    "template",
    "example",
    "securebananalabs",
    "bug-bounty",
    "rustchain-bounties",
    "marketplace-service-template",
    "bounty",
    "airdrop",
    "socialfi",
    "quest",
}

REJECT_TITLE_TERMS = {
    "[grant]",
    "[claim]",
    "challenge",
    "contest",
    "social mining",
    "artifact",
    "new issue for a bounty",
    "bounty alert",
    "hacktoberfest",
    "low handing fruit",
    "pixel art",
    "technical poem",
    "grandma",
}

logger = logging.getLogger(__name__)


# ─── Scoring & Complexity ─────────────────────────────────────────────────────

def score_opportunity(bounty_amount: float, comment_count: int, label_count: int,
                      repo_stars: int, issue_age_days: float, language: str,
                      platform: str = "", title: str = "", labels: List[str] = None,
                      repo_url: str = "") -> float:
    """Score 1-10 based on payout, engagement, repo credibility, recency, language with adaptive learning."""
    score = 0.0

    # Bounty amount (0–3 pts)
    if bounty_amount >= 500:
        score += 3.0
    elif bounty_amount >= 100:
        score += 2.0
    elif bounty_amount >= 50:
        score += 1.5
    elif bounty_amount > 0:
        score += 1.0

    # Comment count: fewer = simpler = more actionable (0–2 pts)
    if comment_count == 0:
        score += 2.0
    elif comment_count <= 3:
        score += 1.5
    elif comment_count <= 10:
        score += 1.0
    else:
        score += 0.3

    # Label richness (0–1 pt)
    score += min(label_count * 0.25, 1.0)

    # Repo stars — legitimacy signal (0–2 pts)
    if repo_stars >= 10000:
        score += 2.0
    elif repo_stars >= 1000:
        score += 1.5
    elif repo_stars >= 100:
        score += 1.0
    elif repo_stars >= 10:
        score += 0.5

    # Recency (0–1 pt)
    if issue_age_days <= 7:
        score += 1.0
    elif issue_age_days <= 30:
        score += 0.7
    elif issue_age_days <= 90:
        score += 0.3

    # Language match (0–1 pt)
    if language and language.lower() in TARGET_LANGUAGES:
        score += 1.0

    base_score = min(round(score, 2), 10.0)

    # Apply adaptive learning if platform and title provided
    if platform and title:
        try:
            adaptive_score = lm.calculate_adaptive_score(
                base_score, platform, title, labels or [], repo_url
            )
            return adaptive_score
        except Exception:
            pass  # Fallback to base score if learning system unavailable

    return base_score


def estimate_complexity(title: str, body: str, comment_count: int, labels: List[str] = None) -> float:
    """Estimate fix complexity 1–10 from issue text and engagement with adaptive learning."""
    text = (title + " " + body).lower()
    score = 3.0

    hard_signals = [
        "refactor", "rewrite", "architecture", "performance", "memory leak",
        "race condition", "concurrency", "deadlock", "security", "cve",
        "distributed", "breaking change", "regression", "flaky", "intermittent",
    ]
    easy_signals = [
        "typo", "spelling", "doc", "readme", "deprecation warning",
        "simple", "minor", "add test", "missing test", "update dependency",
        "bump version", "lint", "formatting",
    ]

    for s in hard_signals:
        if s in text:
            score += 0.7
    for s in easy_signals:
        if s in text:
            score -= 0.5

    if comment_count > 20:
        score += 1.5
    elif comment_count > 10:
        score += 0.8

    # Apply adaptive learning adjustment
    try:
        adjustment = lm.get_adaptive_complexity_adjustment(title, labels or [])
        score += adjustment
    except Exception:
        pass  # Fallback to base score if learning system unavailable

    return max(1.0, min(round(score, 1), 10.0))


# ─── Amount Parsing Helpers ───────────────────────────────────────────────────

def _parse_amount(text: str) -> float:
    """Parse dollar amount from '$150', '150 USD', '$1.5k', etc."""
    text = (text or "").replace(",", "").upper().strip()
    m = re.search(r'(?:\$|USD|USDC)\s*(\d+(?:\.\d+)?)\s*([KM]?)', text)
    if not m:
        m = re.search(r'(\d+(?:\.\d+)?)\s*([KM]?)\s*(?:USD|USDC|DOLLARS?)', text)
    if not m:
        m = re.search(r'BOUNTY[^\d$]*(?:\$|USD|USDC)?\s*(\d+(?:\.\d+)?)\s*([KM]?)', text)
    if not m:
        return 0.0
    amount = float(m.group(1))
    mult = m.group(2)
    if mult == "K":
        amount *= 1000
    elif mult == "M":
        amount *= 1_000_000
    return amount


def _repo_name_from_url(repo_url: str) -> str:
    return repo_url.rstrip("/").split("/")[-1].lower()


def _passes_quality_filter(
    title: str,
    repo_url: str,
    bounty_amount: float,
    repo_stars: int,
    min_stars: int = MIN_REPO_STARS,
) -> bool:
    title_l = (title or "").lower()
    repo_l = (repo_url or "").lower()
    repo_name = _repo_name_from_url(repo_url)

    if bounty_amount <= 0:
        return False
    if repo_stars < min_stars:
        return False
    if any(term in repo_l or term in repo_name for term in REJECT_REPO_TERMS):
        return False
    if any(term in title_l for term in REJECT_TITLE_TERMS):
        return False
    return True


def _has_error_signal(title: str, body: str) -> bool:
    text = f"{title}\n{body}".lower()
    signals = (
        "traceback",
        "stack trace",
        "exception",
        " error",
        "error:",
        "typeerror",
        "valueerror",
        "keyerror",
        "attributeerror",
        "importerror",
        "modulenotfounderror",
        "referenceerror",
        "cannot read",
        "undefined is not",
        "line ",
        ".py:",
        ".js:",
        ".ts:",
    )
    return any(signal in text for signal in signals)


def _is_github_quality_issue(
    title: str,
    body: str,
    repo_url: str,
    repo_stars: int,
) -> bool:
    title_l = (title or "").lower()
    repo_l = (repo_url or "").lower()
    repo_name = _repo_name_from_url(repo_url)
    if repo_stars < MIN_GITHUB_REPO_STARS:
        return False
    if any(term in repo_l or term in repo_name for term in REJECT_REPO_TERMS):
        return False
    if any(term in title_l for term in REJECT_TITLE_TERMS):
        return False
    return _has_error_signal(title, body)


def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SentinelEarn/1.0"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


async def _fetch_github_repo(client: httpx.AsyncClient, repo_api_url: str, headers: Dict[str, str]) -> Optional[Dict]:
    if not repo_api_url:
        return None
    resp = await client.get(repo_api_url, headers=headers)
    if resp.status_code != 200:
        return None
    return resp.json()


async def _issue_has_linked_pr(
    client: httpx.AsyncClient,
    timeline_url: str,
    headers: Dict[str, str],
) -> bool:
    if not timeline_url:
        return False
    timeline_headers = dict(headers)
    timeline_headers["Accept"] = "application/vnd.github.mockingbird-preview+json"
    resp = await client.get(timeline_url, params={"per_page": 100}, headers=timeline_headers)
    if resp.status_code != 200:
        return False
    for event in resp.json():
        source = event.get("source") or {}
        issue = source.get("issue") or {}
        if issue.get("pull_request") or "/pull/" in str(issue.get("html_url", "")):
            return True
    return False


def _extract_bounty_from_text(text: str) -> float:
    """Extract bounty amount mentioned anywhere in issue text."""
    return _parse_amount(text)


def _detect_language_from_labels(labels: List[str]) -> str:
    for lbl in labels:
        lbl = lbl.lower()
        if "python" in lbl:
            return "python"
        if "typescript" in lbl or lbl == "ts":
            return "typescript"
        if "javascript" in lbl or lbl == "js":
            return "javascript"
    return ""


def _detect_language_from_url(url: str) -> str:
    u = url.lower()
    if any(x in u for x in ["python", "django", "flask", "fastapi", "-py"]):
        return "python"
    if any(x in u for x in ["typescript", "angular", "nest", "-ts"]):
        return "typescript"
    if any(x in u for x in ["javascript", "node", "react", "vue", "-js"]):
        return "javascript"
    return ""


def _calc_age_days(created_at: str) -> float:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 30.0


# ─── Algora Scraper ───────────────────────────────────────────────────────────

async def scrape_algora() -> List[Dict]:
    """Scrape Algora.io bounty listings via Playwright."""
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://algora.io/bounties", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=20_000)

            # Try multiple selector patterns — Algora updates their markup occasionally
            selectors = [
                "[data-testid='bounty-item']",
                ".bounty-card",
                "article[class*='bounty']",
                "li[class*='bounty']",
                "div[class*='bounty-row']",
            ]
            items = []
            for sel in selectors:
                items = await page.query_selector_all(sel)
                if items:
                    break

            # Fallback: grab all <a> links containing '/issues/' or '/bounty/'
            if not items:
                links = await page.query_selector_all("a[href*='/issues/'], a[href*='/bounty/']")
                for link in links[:30]:
                    try:
                        title = (await link.inner_text()).strip()
                        href = await link.get_attribute("href") or ""
                        issue_url = href if href.startswith("http") else f"https://algora.io{href}"
                        amount = _extract_bounty_from_text(title)
                        if len(title) > 10 and amount > 0:
                            complexity = estimate_complexity(title, "", 0)
                            if complexity <= MAX_COMPLEXITY and _passes_quality_filter(title, issue_url, amount, MIN_REPO_STARS):
                                results.append({
                                    "source": "algora",
                                    "title": title[:255],
                                    "repo_url": "",
                                    "issue_url": issue_url,
                                    "bounty_amount": amount,
                                    "currency": "USD",
                                    "complexity_score": complexity,
                                    "score": score_opportunity(amount, 0, 1, MIN_REPO_STARS, 30, ""),
                                })
                    except Exception:
                        continue
            else:
                for item in items[:30]:
                    try:
                        title_el = await item.query_selector("h2, h3, [class*='title'], a[href]")
                        title = (await title_el.inner_text() if title_el else "").strip()

                        link_el = await item.query_selector("a[href]")
                        href = await link_el.get_attribute("href") if link_el else ""
                        issue_url = href if href.startswith("http") else f"https://algora.io{href}"

                        amount_el = await item.query_selector(
                            "[class*='amount'], [class*='reward'], [class*='bounty-value']"
                        )
                        amount = _parse_amount(await amount_el.inner_text() if amount_el else "0")

                        lang_el = await item.query_selector("[class*='lang'], [class*='language']")
                        language = (await lang_el.inner_text() if lang_el else "").strip().lower()

                        if (
                            title and issue_url
                            and amount > 0
                            and (not language or language in TARGET_LANGUAGES)
                            and _passes_quality_filter(title, issue_url, amount, MIN_REPO_STARS)
                        ):
                            complexity = estimate_complexity(title, "", 0)
                            if complexity <= MAX_COMPLEXITY:
                                results.append({
                                    "source": "algora",
                                    "title": title[:255],
                                    "repo_url": "",
                                    "issue_url": issue_url,
                                    "bounty_amount": amount,
                                    "currency": "USD",
                                    "complexity_score": complexity,
                                    "score": score_opportunity(amount, 0, 1, 0, 30, language),
                                })
                    except Exception as e:
                        logger.debug(f"Algora item error: {e}")
                        continue

        except PWTimeout:
            logger.warning("Algora: page load timed out")
        except Exception as e:
            logger.error(f"Algora scrape error: {e}")
        finally:
            await browser.close()

    logger.info(f"Algora: {len(results)} opportunities found")
    return results


# ─── IssueHunt Scraper ────────────────────────────────────────────────────────

async def scrape_issuehunt() -> List[Dict]:
    """Scrape IssueHunt.io via Playwright."""
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://issuehunt.io/repos", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=20_000)

            # IssueHunt shows funded issues
            items = await page.query_selector_all(
                ".issue-item, [class*='issue-card'], article, [class*='funded']"
            )

            if not items:
                # Fallback to link scan
                links = await page.query_selector_all("a[href*='/issues/']")
                for link in links[:30]:
                    try:
                        title = (await link.inner_text()).strip()
                        href = await link.get_attribute("href") or ""
                        issue_url = href if href.startswith("http") else f"https://issuehunt.io{href}"
                        amount = _extract_bounty_from_text(title)
                        if len(title) > 10 and amount > 0:
                            complexity = estimate_complexity(title, "", 0)
                            if complexity <= MAX_COMPLEXITY and _passes_quality_filter(title, issue_url, amount, MIN_REPO_STARS):
                                results.append({
                                    "source": "issuehunt",
                                    "title": title[:255],
                                    "repo_url": "",
                                    "issue_url": issue_url,
                                    "bounty_amount": amount,
                                    "currency": "USD",
                                    "complexity_score": complexity,
                                    "score": score_opportunity(amount, 0, 1, MIN_REPO_STARS, 30, ""),
                                })
                    except Exception:
                        continue
            else:
                for item in items[:30]:
                    try:
                        title_el = await item.query_selector(
                            "h2, h3, [class*='title'], a.title, [class*='issue-title']"
                        )
                        title = (await title_el.inner_text() if title_el else "").strip()

                        link_el = await item.query_selector("a[href*='/issues/']")
                        href = await link_el.get_attribute("href") if link_el else ""
                        issue_url = href if href.startswith("http") else f"https://issuehunt.io{href}"

                        amount_el = await item.query_selector(
                            "[class*='amount'], [class*='fund'], [class*='bounty']"
                        )
                        amount = _parse_amount(await amount_el.inner_text() if amount_el else "0")

                        lang_el = await item.query_selector("[class*='lang'], [class*='language']")
                        language = (await lang_el.inner_text() if lang_el else "").strip().lower()

                        if (
                            title and issue_url
                            and amount > 0
                            and (not language or language in TARGET_LANGUAGES)
                            and _passes_quality_filter(title, issue_url, amount, MIN_REPO_STARS)
                        ):
                            complexity = estimate_complexity(title, "", 0)
                            if complexity <= MAX_COMPLEXITY:
                                results.append({
                                    "source": "issuehunt",
                                    "title": title[:255],
                                    "repo_url": "",
                                    "issue_url": issue_url,
                                    "bounty_amount": amount,
                                    "currency": "USD",
                                    "complexity_score": complexity,
                                    "score": score_opportunity(amount, 0, 1, 0, 30, language),
                                })
                    except Exception as e:
                        logger.debug(f"IssueHunt item error: {e}")
                        continue

        except PWTimeout:
            logger.warning("IssueHunt: page load timed out")
        except Exception as e:
            logger.error(f"IssueHunt scrape error: {e}")
        finally:
            await browser.close()

    logger.info(f"IssueHunt: {len(results)} opportunities found")
    return results


# ─── GitHub Issues API Scanner ────────────────────────────────────────────────

async def scan_gitcoin_bounties() -> List[Dict]:
    results = []
    url = "https://app.gitcoin.co/api/v0.1/bounties/"
    params = {"limit": 50, "idx_status": "open", "network": "mainnet"}

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, params=params, headers={"User-Agent": "SentinelEarn/1.0"})
            if resp.status_code != 200:
                logger.warning(f"Gitcoin API returned {resp.status_code}")
                return results

            payload = resp.json()
            items = payload.get("results", payload if isinstance(payload, list) else [])
            for item in items:
                title = item.get("title") or item.get("issueTitle") or ""
                issue_url = item.get("github_url") or item.get("issue_url") or item.get("url") or ""
                repo_url = item.get("repo_url") or item.get("github_repo_url") or ""
                amount = _parse_amount(str(
                    item.get("value_in_usdt")
                    or item.get("value_in_usd")
                    or item.get("bounty_amount")
                    or item.get("amount")
                    or ""
                ))

                if amount <= MIN_GITCOIN_BOUNTY or not title or not issue_url:
                    continue

                language = _detect_language_from_url(repo_url or issue_url)
                if language not in TARGET_LANGUAGES:
                    continue

                complexity = estimate_complexity(title, item.get("description", "") or "", 0)
                if complexity > MAX_COMPLEXITY:
                    continue

                if not _passes_quality_filter(title, repo_url or issue_url, amount, MIN_REPO_STARS):
                    continue

                results.append({
                    "source": "gitcoin",
                    "title": title[:255],
                    "repo_url": repo_url,
                    "issue_url": issue_url,
                    "bounty_amount": amount,
                    "currency": "USD",
                    "complexity_score": complexity,
                    "score": score_opportunity(amount, 0, 1, MIN_REPO_STARS, 30, language),
                })
        except Exception as e:
            logger.error(f"Gitcoin scan error: {e}")

    logger.info(f"Gitcoin: {len(results)} opportunities found")
    return results


async def scan_github_issues() -> List[Dict]:
    """Search GitHub Issues API for concrete good-first bug reports on established repos."""
    results = []
    headers = _github_headers()

    queries = [
        f'label:bug label:"good first issue" is:open is:issue language:python stars:>{GITHUB_SEARCH_REPO_STARS} traceback',
        f'label:bug label:"good first issue" is:open is:issue language:python stars:>{GITHUB_SEARCH_REPO_STARS} exception',
        f'label:bug label:"good first issue" is:open is:issue language:python stars:>{GITHUB_SEARCH_REPO_STARS} error',
        f'label:bug label:"good first issue" is:open is:issue language:javascript stars:>{GITHUB_SEARCH_REPO_STARS} traceback',
        f'label:bug label:"good first issue" is:open is:issue language:javascript stars:>{GITHUB_SEARCH_REPO_STARS} exception',
        f'label:bug label:"good first issue" is:open is:issue language:javascript stars:>{GITHUB_SEARCH_REPO_STARS} error',
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                resp = await client.get(
                    "https://api.github.com/search/issues",
                    params={"q": query, "sort": "created", "order": "desc", "per_page": 20},
                    headers=headers,
                )
                if resp.status_code == 200:
                    for item in resp.json().get("items", []):
                        try:
                            issue_url = item["html_url"]
                            repo_api_url = item.get("repository_url", "")
                            repo_url = repo_api_url.replace(
                                "https://api.github.com/repos/", "https://github.com/"
                            )
                            title = item.get("title", "")
                            body = item.get("body", "") or ""
                            comment_count = item.get("comments", 0)
                            labels = item.get("labels", [])
                            label_names = [lb["name"].lower() for lb in labels]

                            repo = await _fetch_github_repo(client, repo_api_url, headers)
                            if not repo:
                                continue

                            repo_stars = int(repo.get("stargazers_count") or 0)
                            language = (repo.get("language") or "").lower()
                            if language not in TARGET_LANGUAGES:
                                language = _detect_language_from_labels(label_names)
                            if language not in TARGET_LANGUAGES:
                                continue

                            amount = _extract_bounty_from_text(title + " " + body)
                            age_days = _calc_age_days(item.get("created_at", ""))
                            if not _is_github_quality_issue(title, body, repo_url, repo_stars):
                                continue
                            if await _issue_has_linked_pr(client, item.get("timeline_url", ""), headers):
                                continue

                            s_score = score_opportunity(
                                amount, comment_count, len(labels), repo_stars, age_days, language,
                                platform="github", title=title, labels=label_names, repo_url=repo_url
                            )
                            complexity = estimate_complexity(title, body, comment_count)

                            if complexity <= MAX_COMPLEXITY:
                                results.append({
                                    "source": "github",
                                    "title": title[:255],
                                    "repo_url": repo_url,
                                    "issue_url": issue_url,
                                    "bounty_amount": amount,
                                    "currency": "USD",
                                    "complexity_score": complexity,
                                    "score": s_score,
                                })
                        except Exception as e:
                            logger.debug(f"GitHub issue parse error: {e}")

                elif resp.status_code == 403:
                    logger.warning("GitHub API rate-limited — pausing 60s")
                    await asyncio.sleep(60)
                    break
                elif resp.status_code == 422:
                    logger.debug(f"GitHub search query invalid: {query}")

                await asyncio.sleep(1.5)  # Gentle rate limiting

            except Exception as e:
                logger.error(f"GitHub search error for '{query[:40]}': {e}")

    logger.info(f"GitHub: {len(results)} opportunities found")
    return results


# ─── Main scan entrypoint ─────────────────────────────────────────────────────

async def run_scan(dry_run: bool = False) -> int:
    """Run all scanners, deduplicate, score, insert. Returns new opportunity count."""
    db.log_event("scan_started", "Full scan of Algora, IssueHunt, Gitcoin, GitHub")

    algora = await scrape_algora()
    issuehunt = await scrape_issuehunt()
    gitcoin = await scan_gitcoin_bounties()
    github = await scan_github_issues()

    all_results = [
        opp for opp in algora + issuehunt + gitcoin + github
        if (
            True
            if opp.get("source") == "github"
            else _passes_quality_filter(
            opp.get("title", ""),
            opp.get("repo_url", "") or opp.get("issue_url", ""),
            float(opp.get("bounty_amount") or 0),
            MIN_GITHUB_REPO_STARS if opp.get("source") == "github" else MIN_REPO_STARS,
            MIN_GITHUB_REPO_STARS if opp.get("source") == "github" else MIN_REPO_STARS,
        )
        )
    ]
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    added = 0
    for opp in all_results:
        if dry_run:
            print(
                f"[DRY RUN] {opp['source']:12s} | ${opp['bounty_amount']:7.2f} | "
                f"cx={opp['complexity_score']} | {opp['title'][:55]}"
            )
            added += 1
            continue

        opp_id = db.insert_opportunity(
            source=opp["source"],
            title=opp["title"],
            repo_url=opp["repo_url"],
            issue_url=opp["issue_url"],
            bounty_amount=opp["bounty_amount"],
            currency=opp["currency"],
            complexity_score=opp["complexity_score"],
        )
        if opp_id:
            added += 1
            db.log_event(
                "opportunity_found",
                f"src={opp['source']} bounty=${opp['bounty_amount']} score={opp.get('score')}",
                opp_id,
            )

    db.log_event("scan_complete", f"Added {added} new from {len(all_results)} found")
    logger.info(f"Scan complete — {added} new opportunities added")
    return added


# ─── Scheduler hook ──────────────────────────────────────────────────────────

def start_scheduler(scheduler: AsyncIOScheduler, dry_run: bool = False):
    """Register scan job on a shared AsyncIOScheduler."""
    from datetime import datetime as _dt

    scheduler.add_job(
        lambda: asyncio.create_task(run_scan(dry_run=dry_run)),
        "interval",
        hours=SCAN_INTERVAL_HOURS,
        id="scanner",
        replace_existing=True,
        next_run_time=_dt.now(),  # fire immediately on startup
    )
    logger.info(f"Scanner scheduled every {SCAN_INTERVAL_HOURS}h (dry_run={dry_run})")
