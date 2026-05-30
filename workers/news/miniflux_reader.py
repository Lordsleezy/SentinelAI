"""
News Reader — Miniflux integration with RSS fallback
"""
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False

# Fallback RSS feeds
FALLBACK_FEEDS = [
    "https://feeds.npr.org/1001/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://feeds.arstechnica.com/arstechnica/index"
]


class NewsReader:
    """News reader with Miniflux and RSS fallback"""

    def __init__(self):
        self.miniflux_url = os.getenv('MINIFLUX_URL')
        self.miniflux_api_key = os.getenv('MINIFLUX_API_KEY')
        self.use_miniflux = bool(self.miniflux_url and self.miniflux_api_key and HTTPX_AVAILABLE)

    def get_unread(self, limit: int = 10) -> Dict[str, Any]:
        """Get unread articles"""
        if self.use_miniflux:
            return self._miniflux_unread(limit)
        else:
            return self._rss_fallback(limit)

    def get_headlines(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get top headlines"""
        unread = self.get_unread(limit)

        if unread.get('error'):
            return []

        return [
            {
                "title": article.get('title'),
                "url": article.get('url'),
                "published": article.get('published_at', article.get('published'))
            }
            for article in unread.get('articles', [])[:limit]
        ]

    def mark_read(self, entry_id: str) -> Dict[str, Any]:
        """Mark an article as read (Miniflux only)"""
        if not self.use_miniflux:
            return {"status": "error", "message": "Miniflux not configured"}

        try:
            with httpx.Client() as client:
                response = client.put(
                    f"{self.miniflux_url}/v1/entries/{entry_id}",
                    headers={"X-Auth-Token": self.miniflux_api_key},
                    json={"status": "read"},
                    timeout=5.0
                )
                response.raise_for_status()

                return {"status": "ok", "message": "Marked as read"}

        except Exception as e:
            logger.error(f"Failed to mark as read: {e}")
            return {"status": "error", "message": str(e)}

    def news_summary(self) -> str:
        """Get plain-English news summary"""
        headlines = self.get_headlines(5)

        if not headlines:
            return "No news headlines available"

        summary = "\n".join([
            f"{i+1}. {h['title']}"
            for i, h in enumerate(headlines)
        ])

        return summary

    def _miniflux_unread(self, limit: int) -> Dict[str, Any]:
        """Get unread articles from Miniflux"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.miniflux_url}/v1/entries",
                    headers={"X-Auth-Token": self.miniflux_api_key},
                    params={"status": "unread", "limit": limit},
                    timeout=10.0
                )
                response.raise_for_status()

                data = response.json()

                return {
                    "error": None,
                    "articles": data.get('entries', [])
                }

        except Exception as e:
            logger.error(f"Miniflux request failed: {e}")
            return {"error": str(e), "articles": []}

    def _rss_fallback(self, limit: int) -> Dict[str, Any]:
        """Get articles from RSS feeds as fallback"""
        if not FEEDPARSER_AVAILABLE:
            return {"error": "feedparser not available", "articles": []}

        articles = []

        for feed_url in FALLBACK_FEEDS:
            try:
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:limit // len(FALLBACK_FEEDS)]:
                    articles.append({
                        "title": entry.get('title', 'Untitled'),
                        "url": entry.get('link'),
                        "published": entry.get('published'),
                        "summary": entry.get('summary', '')
                    })

            except Exception as e:
                logger.error(f"Failed to parse feed {feed_url}: {e}")
                continue

        return {
            "error": None,
            "articles": articles[:limit]
        }


# Global instance
_news_reader: NewsReader = None


def get_news_reader() -> NewsReader:
    """Get or create the global news reader"""
    global _news_reader
    if _news_reader is None:
        _news_reader = NewsReader()
    return _news_reader
