"""
OpenClaw Notes — Simple note management in memory vault
"""
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

NOTES_DIR = Path(__file__).parent.parent.parent / "memory" / "vault" / "notes"


def _slugify(title: str) -> str:
    """Convert title to filename-safe slug"""
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug[:50]  # Limit length


def create_note(title: str, content: str) -> Dict[str, Any]:
    """Create a new note"""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    slug = _slugify(title)
    filepath = NOTES_DIR / f"{slug}.md"

    # If file exists, append timestamp to make it unique
    if filepath.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = NOTES_DIR / f"{slug}_{timestamp}.md"

    note_content = f"""# {title}

**Created:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{content}
"""

    filepath.write_text(note_content, encoding='utf-8')

    return {
        "status": "ok",
        "path": str(filepath),
        "title": title
    }


def list_notes() -> List[Dict[str, Any]]:
    """List all notes"""
    if not NOTES_DIR.exists():
        return []

    notes = []
    for filepath in sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        # Extract title from first line
        try:
            content = filepath.read_text(encoding='utf-8')
            first_line = content.split('\n')[0]
            title = first_line.replace('#', '').strip()
        except:
            title = filepath.stem

        notes.append({
            'title': title,
            'path': str(filepath),
            'created_at': datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()
        })

    return notes


def search_notes(query: str) -> List[Dict[str, Any]]:
    """Search notes for a query"""
    if not NOTES_DIR.exists():
        return []

    query_lower = query.lower()
    results = []

    for filepath in NOTES_DIR.glob("*.md"):
        try:
            content = filepath.read_text(encoding='utf-8')

            if query_lower in content.lower():
                # Extract title
                first_line = content.split('\n')[0]
                title = first_line.replace('#', '').strip()

                # Extract matching lines
                matches = [
                    line for line in content.split('\n')
                    if query_lower in line.lower()
                ]

                results.append({
                    'title': title,
                    'path': str(filepath),
                    'matches': matches[:3]  # First 3 matching lines
                })

        except Exception:
            continue

    return results


def append_to_note(title: str, content: str) -> Dict[str, Any]:
    """Append content to an existing note"""
    slug = _slugify(title)

    # Find the note file
    candidates = list(NOTES_DIR.glob(f"{slug}*.md"))

    if not candidates:
        # Note doesn't exist, create it
        return create_note(title, content)

    # Use the most recent match
    filepath = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]

    # Append content
    existing = filepath.read_text(encoding='utf-8')
    updated = f"{existing}\n\n---\n\n**Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{content}"

    filepath.write_text(updated, encoding='utf-8')

    return {
        "status": "ok",
        "path": str(filepath),
        "title": title
    }
