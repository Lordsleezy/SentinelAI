"""
repo_analyzer.py — Repository quality analysis for Sentinel Earn
Detects monorepos, archived repos, test presence, and quality heuristics
Helps prioritize high-quality, fixable repositories
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class RepoQuality:
    """Repository quality assessment."""
    score: float  # 0.0-10.0
    is_monorepo: bool
    is_archived: bool
    has_tests: bool
    has_ci: bool
    file_count: int
    primary_language: str
    languages: Dict[str, int]  # language -> line count
    last_commit_days_ago: Optional[int]
    issues: List[str]
    warnings: List[str]
    recommendations: List[str]


# ─── Monorepo Detection ───────────────────────────────────────────────────────

def detect_monorepo(repo_dir: Path) -> Tuple[bool, List[str]]:
    """
    Detect if repository is a monorepo.
    
    Indicators:
    - Multiple package.json files
    - Lerna/Nx/Turborepo configuration
    - Multiple setup.py/pyproject.toml files
    - packages/ or apps/ directory with multiple projects
    
    Args:
        repo_dir: Repository root directory
    
    Returns:
        (is_monorepo: bool, indicators: List[str])
    """
    indicators = []
    
    # Check for monorepo tools
    monorepo_files = [
        'lerna.json', 'nx.json', 'turbo.json', 'pnpm-workspace.yaml',
        'rush.json', 'workspace.json'
    ]
    
    for file in monorepo_files:
        if (repo_dir / file).exists():
            indicators.append(f"Monorepo tool config: {file}")
    
    # Check for multiple package.json
    package_jsons = list(repo_dir.rglob("package.json"))
    if len(package_jsons) > 3:
        indicators.append(f"Multiple package.json files: {len(package_jsons)}")
    
    # Check for multiple Python projects
    python_projects = list(repo_dir.rglob("setup.py")) + list(repo_dir.rglob("pyproject.toml"))
    if len(python_projects) > 2:
        indicators.append(f"Multiple Python projects: {len(python_projects)}")
    
    # Check for packages/apps directory structure
    for subdir in ['packages', 'apps', 'services', 'modules']:
        subdir_path = repo_dir / subdir
        if subdir_path.exists() and subdir_path.is_dir():
            subdirs = [d for d in subdir_path.iterdir() if d.is_dir()]
            if len(subdirs) > 2:
                indicators.append(f"Multiple projects in {subdir}/: {len(subdirs)}")
    
    is_monorepo = len(indicators) >= 2
    
    return is_monorepo, indicators


# ─── Test Detection ───────────────────────────────────────────────────────────

def detect_tests(repo_dir: Path) -> Tuple[bool, Dict[str, int]]:
    """
    Detect presence and type of tests.
    
    Args:
        repo_dir: Repository root directory
    
    Returns:
        (has_tests: bool, test_counts: Dict[framework, count])
    """
    test_counts = {}
    
    # Python tests
    pytest_files = list(repo_dir.rglob("test_*.py")) + list(repo_dir.rglob("*_test.py"))
    if pytest_files:
        test_counts['pytest'] = len(pytest_files)
    
    # JavaScript/TypeScript tests
    js_test_patterns = [
        "*.test.js", "*.test.ts", "*.test.jsx", "*.test.tsx",
        "*.spec.js", "*.spec.ts", "*.spec.jsx", "*.spec.tsx"
    ]
    
    js_tests = []
    for pattern in js_test_patterns:
        js_tests.extend(repo_dir.rglob(pattern))
    
    if js_tests:
        test_counts['jest/vitest'] = len(js_tests)
    
    # Check for test directories
    test_dirs = ['tests', 'test', '__tests__', 'spec']
    for test_dir in test_dirs:
        test_path = repo_dir / test_dir
        if test_path.exists() and test_path.is_dir():
            test_files = list(test_path.rglob("*"))
            if test_files:
                test_counts[f'{test_dir}/'] = len([f for f in test_files if f.is_file()])
    
    has_tests = sum(test_counts.values()) > 0
    
    return has_tests, test_counts


# ─── CI/CD Detection ──────────────────────────────────────────────────────────

def detect_ci(repo_dir: Path) -> Tuple[bool, List[str]]:
    """
    Detect CI/CD configuration.
    
    Args:
        repo_dir: Repository root directory
    
    Returns:
        (has_ci: bool, ci_systems: List[str])
    """
    ci_systems = []
    
    # GitHub Actions
    if (repo_dir / ".github" / "workflows").exists():
        workflows = list((repo_dir / ".github" / "workflows").glob("*.yml")) + \
                   list((repo_dir / ".github" / "workflows").glob("*.yaml"))
        if workflows:
            ci_systems.append(f"GitHub Actions ({len(workflows)} workflows)")
    
    # GitLab CI
    if (repo_dir / ".gitlab-ci.yml").exists():
        ci_systems.append("GitLab CI")
    
    # Travis CI
    if (repo_dir / ".travis.yml").exists():
        ci_systems.append("Travis CI")
    
    # Circle CI
    if (repo_dir / ".circleci" / "config.yml").exists():
        ci_systems.append("Circle CI")
    
    # Jenkins
    if (repo_dir / "Jenkinsfile").exists():
        ci_systems.append("Jenkins")
    
    has_ci = len(ci_systems) > 0
    
    return has_ci, ci_systems


# ─── Language Analysis ────────────────────────────────────────────────────────

def analyze_languages(repo_dir: Path) -> Tuple[str, Dict[str, int]]:
    """
    Analyze programming languages used in repository.
    
    Args:
        repo_dir: Repository root directory
    
    Returns:
        (primary_language: str, languages: Dict[language, line_count])
    """
    language_lines = {}
    
    # Language extensions
    extensions = {
        'Python': ['.py'],
        'JavaScript': ['.js', '.mjs', '.cjs', '.jsx'],
        'TypeScript': ['.ts', '.tsx'],
        'Java': ['.java'],
        'Go': ['.go'],
        'Rust': ['.rs'],
        'C++': ['.cpp', '.cc', '.cxx', '.hpp', '.h'],
        'C': ['.c', '.h'],
        'Ruby': ['.rb'],
        'PHP': ['.php'],
    }
    
    skip_dirs = {
        'node_modules', '.git', '__pycache__', 'dist', 'build',
        'vendor', 'target', '.venv', 'venv'
    }
    
    for language, exts in extensions.items():
        line_count = 0
        
        for ext in exts:
            for filepath in repo_dir.rglob(f'*{ext}'):
                # Skip excluded directories
                if any(skip_dir in filepath.parts for skip_dir in skip_dirs):
                    continue
                
                try:
                    content = filepath.read_text(encoding='utf-8', errors='ignore')
                    line_count += content.count('\n') + 1
                except Exception:
                    continue
        
        if line_count > 0:
            language_lines[language] = line_count
    
    # Determine primary language
    if language_lines:
        primary_language = max(language_lines.items(), key=lambda x: x[1])[0]
    else:
        primary_language = "Unknown"
    
    return primary_language, language_lines


# ─── GitHub Metadata Analysis ─────────────────────────────────────────────────

def analyze_github_metadata(
    owner: str,
    repo: str,
    github_token: Optional[str] = None
) -> Dict:
    """
    Fetch and analyze GitHub repository metadata.
    
    Args:
        owner: Repository owner
        repo: Repository name
        github_token: Optional GitHub token for authentication
    
    Returns:
        Dictionary with metadata
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "SentinelEarn/1.0"
    }
    
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        with httpx.Client(timeout=10.0) as client:
            # Get repository info
            r = client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers
            )
            
            if r.status_code != 200:
                logger.warning(f"GitHub API returned {r.status_code}")
                return {}
            
            data = r.json()
            
            # Calculate last commit age
            pushed_at = data.get("pushed_at")
            if pushed_at:
                pushed_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                days_ago = (datetime.now(timezone.utc) - pushed_dt).days
            else:
                days_ago = None
            
            return {
                "is_archived": data.get("archived", False),
                "is_fork": data.get("fork", False),
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "last_commit_days_ago": days_ago,
                "default_branch": data.get("default_branch", "main"),
                "has_wiki": data.get("has_wiki", False),
                "has_pages": data.get("has_pages", False),
                "language": data.get("language", ""),
            }
    
    except Exception as e:
        logger.warning(f"Failed to fetch GitHub metadata: {e}")
        return {}


# ─── Quality Scoring ──────────────────────────────────────────────────────────

def score_repository_quality(
    repo_dir: Path,
    github_metadata: Optional[Dict] = None
) -> RepoQuality:
    """
    Comprehensive repository quality assessment.
    
    Args:
        repo_dir: Repository root directory
        github_metadata: Optional GitHub metadata
    
    Returns:
        RepoQuality assessment
    """
    issues = []
    warnings = []
    recommendations = []
    score = 5.0  # Start at neutral
    
    # Detect monorepo
    is_monorepo, monorepo_indicators = detect_monorepo(repo_dir)
    if is_monorepo:
        score -= 3.0
        issues.append("Monorepo detected - complex to fix")
        warnings.extend(monorepo_indicators)
    
    # Detect tests
    has_tests, test_counts = detect_tests(repo_dir)
    if has_tests:
        score += 2.0
        logger.info(f"Tests found: {test_counts}")
    else:
        score -= 1.5
        warnings.append("No tests detected")
        recommendations.append("Add tests to verify fixes")
    
    # Detect CI
    has_ci, ci_systems = detect_ci(repo_dir)
    if has_ci:
        score += 1.0
        logger.info(f"CI detected: {ci_systems}")
    else:
        warnings.append("No CI/CD detected")
    
    # Analyze languages
    primary_language, languages = analyze_languages(repo_dir)
    
    # Prefer supported languages
    supported_languages = {'Python', 'JavaScript', 'TypeScript'}
    if primary_language in supported_languages:
        score += 1.0
    else:
        score -= 1.0
        warnings.append(f"Primary language {primary_language} not in preferred set")
    
    # Count files
    file_count = sum(1 for _ in repo_dir.rglob("*") if _.is_file())
    
    if file_count > 5000:
        score -= 2.0
        issues.append(f"Too many files: {file_count}")
    elif file_count > 1000:
        score -= 0.5
        warnings.append(f"Large repository: {file_count} files")
    
    # GitHub metadata analysis
    is_archived = False
    last_commit_days_ago = None
    
    if github_metadata:
        is_archived = github_metadata.get("is_archived", False)
        last_commit_days_ago = github_metadata.get("last_commit_days_ago")
        
        if is_archived:
            score -= 5.0
            issues.append("Repository is archived")
        
        if last_commit_days_ago:
            if last_commit_days_ago > 365:
                score -= 2.0
                warnings.append(f"Stale repository: last commit {last_commit_days_ago} days ago")
            elif last_commit_days_ago < 30:
                score += 0.5  # Active repo
        
        # Stars indicate quality/popularity
        stars = github_metadata.get("stars", 0)
        if stars > 1000:
            score += 1.0
        elif stars > 100:
            score += 0.5
        elif stars < 10:
            score -= 0.5
            warnings.append("Low star count - may be low quality")
    
    # Clamp score to 0-10
    score = max(0.0, min(10.0, score))
    
    return RepoQuality(
        score=round(score, 1),
        is_monorepo=is_monorepo,
        is_archived=is_archived,
        has_tests=has_tests,
        has_ci=has_ci,
        file_count=file_count,
        primary_language=primary_language,
        languages=languages,
        last_commit_days_ago=last_commit_days_ago,
        issues=issues,
        warnings=warnings,
        recommendations=recommendations
    )


# ─── Formatting ───────────────────────────────────────────────────────────────

def format_repo_quality(quality: RepoQuality) -> str:
    """
    Format repository quality assessment for logging.
    
    Args:
        quality: RepoQuality assessment
    
    Returns:
        Formatted string
    """
    lines = []
    
    lines.append(f"Repository Quality Score: {quality.score}/10")
    lines.append(f"  Primary Language: {quality.primary_language}")
    lines.append(f"  File Count: {quality.file_count}")
    lines.append(f"  Has Tests: {'✓' if quality.has_tests else '✗'}")
    lines.append(f"  Has CI: {'✓' if quality.has_ci else '✗'}")
    lines.append(f"  Is Monorepo: {'✓' if quality.is_monorepo else '✗'}")
    lines.append(f"  Is Archived: {'✓' if quality.is_archived else '✗'}")
    
    if quality.last_commit_days_ago is not None:
        lines.append(f"  Last Commit: {quality.last_commit_days_ago} days ago")
    
    if quality.issues:
        lines.append(f"\nIssues ({len(quality.issues)}):")
        for issue in quality.issues:
            lines.append(f"  - {issue}")
    
    if quality.warnings:
        lines.append(f"\nWarnings ({len(quality.warnings)}):")
        for warning in quality.warnings[:5]:
            lines.append(f"  - {warning}")
    
    if quality.recommendations:
        lines.append(f"\nRecommendations:")
        for rec in quality.recommendations:
            lines.append(f"  - {rec}")
    
    return '\n'.join(lines)


# ─── Decision Helper ──────────────────────────────────────────────────────────

def should_attempt_fix(quality: RepoQuality, min_score: float = 4.0) -> Tuple[bool, str]:
    """
    Decide if we should attempt to fix issues in this repository.
    
    Args:
        quality: RepoQuality assessment
        min_score: Minimum quality score required
    
    Returns:
        (should_attempt: bool, reason: str)
    """
    # Hard blockers
    if quality.is_archived:
        return False, "Repository is archived"
    
    if quality.is_monorepo:
        return False, "Monorepo - too complex"
    
    if quality.file_count > 5000:
        return False, f"Too many files: {quality.file_count}"
    
    # Score-based decision
    if quality.score < min_score:
        return False, f"Quality score too low: {quality.score}/10 < {min_score}"
    
    # Prefer repos with tests
    if not quality.has_tests:
        return False, "No tests detected - cannot verify fixes"
    
    # All checks passed
    return True, f"Quality score: {quality.score}/10"
