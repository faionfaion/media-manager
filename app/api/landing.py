"""Landing page — public showcase of Faion media outlets."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from config.settings import MEDIA_OUTLETS


def _load_recent_articles(project_dir: Path, limit: int = 3) -> list[dict]:
    """Load most recent articles from content/ directory."""
    content_dir = project_dir / "content"
    if not content_dir.exists():
        return []

    articles = []
    today = date.today()
    cutoff = (today - timedelta(days=7)).isoformat()

    for md_path in sorted(content_dir.glob("*.md"), key=lambda p: p.name, reverse=True):
        if md_path.name[:10] < cutoff:
            break
        try:
            text = md_path.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            fm = yaml.safe_load(parts[1])
            if not fm:
                continue

            # For neromedia only show EN articles
            lang = fm.get("lang", "en")
            slug = fm.get("slug", "")

            # Skip non-primary language duplicates
            if lang not in ("en", "ua"):
                continue
            # For neromedia prefer EN
            if "neromedia" in str(project_dir) and lang != "en":
                continue

            articles.append({
                "title": fm.get("title", ""),
                "slug": slug,
                "date": str(fm.get("date", "")),
                "type": fm.get("type", ""),
                "description": fm.get("description", ""),
                "tags": fm.get("tags", [])[:3],
                "image": fm.get("image", ""),
            })
            if len(articles) >= limit:
                break
        except Exception:
            continue

    return articles


def _count_total_articles(project_dir: Path) -> int:
    """Count total articles in content/."""
    content_dir = project_dir / "content"
    if not content_dir.exists():
        return 0
    return len(list(content_dir.glob("*.md")))


OUTLET_META = {
    "neromedia": {
        "emoji": "&#128225;",
        "tagline": "AI-powered tech news in 8 languages",
        "description": "Daily coverage of AI, developer tools, and the tech industry. Written by Nero, an AI cat-hacker who tracks the frontier of artificial intelligence.",
        "color": "#4fc3f7",
        "gradient": "linear-gradient(135deg, #0d47a1 0%, #1565c0 50%, #1e88e5 100%)",
        "features": ["8 languages", "Hourly updates", "AI-generated images", "Claude Agent SDK pipeline"],
    },
    "pashtelka": {
        "emoji": "&#127479;&#127481;",
        "tagline": "Ukrainian news from Portugal",
        "description": "Daily news for 56,000+ Ukrainians in Portugal. Local news, immigration updates, community events. Portuguese vocabulary glossary in every post.",
        "color": "#ffa726",
        "gradient": "linear-gradient(135deg, #e65100 0%, #f57c00 50%, #ff9800 100%)",
        "features": ["Ukrainian language", "Portuguese RSS sources", "Vocabulary glossary", "Immigration guides"],
    },
    "longlife": {
        "emoji": "&#127793;",
        "tagline": "Evidence-based health and longevity",
        "description": "Science-backed articles on nutrition, fitness, sleep, and longevity. Hosted by Vita, an illustrated health coach with comic-style art.",
        "color": "#66bb6a",
        "gradient": "linear-gradient(135deg, #1b5e20 0%, #2e7d32 50%, #43a047 100%)",
        "features": ["Evidence levels", "Comic illustrations", "Medical disclaimers", "8 health categories"],
    },
    "ender": {
        "emoji": "&#127918;",
        "tagline": "Roblox news, guides and lifehacks for kids",
        "description": "Daily Roblox content by EnderFaion and her dad FaionEnder. Game reviews, building guides, obby tips, dev tutorials, trends and records.",
        "color": "#ab47bc",
        "gradient": "linear-gradient(135deg, #4a148c 0%, #7b1fa2 50%, #9c27b0 100%)",
        "features": ["Bilingual UA+EN", "Roblox characters", "Kid-friendly", "5 articles daily"],
    },
}


def build_landing_html() -> str:
    """Build the public landing page with live data."""
    outlet_cards = []
    total_articles = 0
    total_channels = 0

    for slug, cfg in MEDIA_OUTLETS.items():
        meta = OUTLET_META.get(slug, {})
        articles = _load_recent_articles(cfg.project_dir, limit=3)
        count = _count_total_articles(cfg.project_dir)
        total_articles += count

        langs = cfg.lang if isinstance(cfg.lang, list) else [cfg.lang]
        total_channels += len(langs) if slug == "neromedia" else 1

        # Build article preview cards
        article_html = ""
        for a in articles:
            tags_html = " ".join(
                f'<span class="tag">{t}</span>' for t in a.get("tags", [])
            )
            article_html += f"""
            <a href="{cfg.site_url}/{a['slug']}/" target="_blank" class="article-link">
                <div class="article-preview">
                    <div class="article-date">{a['date']}</div>
                    <div class="article-title">{a['title']}</div>
                    <div class="article-desc">{a.get('description', '')[:120]}</div>
                    <div class="article-tags">{tags_html}</div>
                </div>
            </a>"""

        if not article_html:
            article_html = '<div class="no-articles">Content coming soon</div>'

        # Features list
        features_html = " ".join(
            f'<span class="feature">{f}</span>' for f in meta.get("features", [])
        )

        # Language badges
        card = f"""
        <div class="outlet-card" style="--accent: {meta.get('color', '#4fc3f7')}">
            <div class="outlet-header" style="background: {meta.get('gradient', '')}">
                <div class="outlet-emoji">{meta.get('emoji', '')}</div>
                <div>
                    <h2>{cfg.name}</h2>
                    <p class="outlet-tagline">{meta.get('tagline', '')}</p>
                </div>
            </div>
            <div class="outlet-body">
                <p class="outlet-desc">{meta.get('description', '')}</p>
                <div class="outlet-stats">
                    <div class="outlet-stat">
                        <span class="outlet-stat-num">{count}</span>
                        <span class="outlet-stat-label">articles</span>
                    </div>
                    <div class="outlet-stat">
                        <span class="outlet-stat-num">{len(langs)}</span>
                        <span class="outlet-stat-label">{'languages' if len(langs) > 1 else 'language'}</span>
                    </div>
                </div>
                <div class="outlet-features">{features_html}</div>
                <h3 class="recent-title">Recent</h3>
                <div class="articles-list">{article_html}</div>
                <div class="outlet-links">
                    <a href="{cfg.site_url}" target="_blank" class="link-btn">Visit site</a>
                    <a href="https://t.me/{cfg.tg_channel_username}" target="_blank" class="link-btn tg">Telegram</a>
                </div>
            </div>
        </div>"""
        outlet_cards.append(card)

    cards_html = "\n".join(outlet_cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Faion Media Network</title>
    <meta name="description" content="AI-powered media pipelines: tech news, Portuguese community news, health content. Fully automated with Claude Agent SDK.">
    <style>
        :root {{
            --bg: #050505;
            --surface: #0f0f0f;
            --card: #161616;
            --border: #252525;
            --text: #d4d4d4;
            --text-muted: #707070;
            --white: #f0f0f0;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}

        /* Hero */
        .hero {{
            padding: 80px 24px 60px;
            text-align: center;
            background: radial-gradient(ellipse at 50% 0%, rgba(79, 195, 247, 0.08) 0%, transparent 70%);
        }}
        .hero-label {{
            display: inline-block;
            padding: 4px 14px;
            border: 1px solid #333;
            border-radius: 20px;
            font-size: 12px;
            color: var(--text-muted);
            letter-spacing: 0.5px;
            text-transform: uppercase;
            margin-bottom: 24px;
        }}
        .hero h1 {{
            font-size: clamp(32px, 5vw, 56px);
            font-weight: 700;
            color: var(--white);
            margin-bottom: 16px;
            letter-spacing: -1px;
        }}
        .hero h1 span {{
            background: linear-gradient(135deg, #4fc3f7 0%, #81c784 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .hero-sub {{
            font-size: clamp(16px, 2vw, 20px);
            color: var(--text-muted);
            max-width: 600px;
            margin: 0 auto 40px;
        }}

        /* Stats bar */
        .stats-bar {{
            display: flex;
            justify-content: center;
            gap: 48px;
            padding: 0 24px 60px;
            flex-wrap: wrap;
        }}
        .stats-item {{
            text-align: center;
        }}
        .stats-num {{
            font-size: 36px;
            font-weight: 700;
            color: var(--white);
        }}
        .stats-label {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 4px;
        }}

        /* Grid */
        .outlets {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 24px 80px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 24px;
        }}

        /* Outlet card */
        .outlet-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
            transition: border-color 0.2s;
        }}
        .outlet-card:hover {{
            border-color: var(--accent);
        }}
        .outlet-header {{
            padding: 28px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .outlet-emoji {{
            font-size: 32px;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(255,255,255,0.15);
            border-radius: 12px;
            flex-shrink: 0;
        }}
        .outlet-header h2 {{
            font-size: 22px;
            color: #fff;
            font-weight: 700;
        }}
        .outlet-tagline {{
            font-size: 13px;
            color: rgba(255,255,255,0.7);
            margin-top: 2px;
        }}
        .outlet-body {{
            padding: 0 24px 24px;
        }}
        .outlet-desc {{
            font-size: 14px;
            color: var(--text);
            margin-bottom: 20px;
            line-height: 1.7;
        }}
        .outlet-stats {{
            display: flex;
            gap: 32px;
            margin-bottom: 16px;
        }}
        .outlet-stat {{
            display: flex;
            align-items: baseline;
            gap: 6px;
        }}
        .outlet-stat-num {{
            font-size: 24px;
            font-weight: 700;
            color: var(--accent);
        }}
        .outlet-stat-label {{
            font-size: 13px;
            color: var(--text-muted);
        }}
        .outlet-features {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 24px;
        }}
        .feature {{
            display: inline-block;
            padding: 3px 10px;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 11px;
            color: var(--text-muted);
        }}

        /* Articles */
        .recent-title {{
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }}
        .articles-list {{
            margin-bottom: 20px;
        }}
        .article-link {{
            text-decoration: none;
            color: inherit;
            display: block;
        }}
        .article-preview {{
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: 10px;
            margin-bottom: 8px;
            transition: border-color 0.2s, background 0.2s;
        }}
        .article-preview:hover {{
            border-color: var(--accent);
            background: rgba(255,255,255,0.02);
        }}
        .article-date {{
            font-size: 11px;
            color: var(--text-muted);
        }}
        .article-title {{
            font-size: 14px;
            color: var(--white);
            font-weight: 600;
            margin: 4px 0;
            line-height: 1.4;
        }}
        .article-desc {{
            font-size: 12px;
            color: var(--text-muted);
            line-height: 1.5;
        }}
        .article-tags {{
            margin-top: 6px;
        }}
        .tag {{
            display: inline-block;
            padding: 1px 7px;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
            font-size: 10px;
            color: var(--text-muted);
            margin-right: 4px;
        }}
        .no-articles {{
            padding: 24px;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
        }}

        /* Links */
        .outlet-links {{
            display: flex;
            gap: 8px;
        }}
        .link-btn {{
            display: inline-block;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            transition: opacity 0.2s;
            flex: 1;
            text-align: center;
        }}
        .link-btn:hover {{ opacity: 0.85; }}
        .link-btn {{
            background: var(--accent);
            color: #000;
        }}
        .link-btn.tg {{
            background: #2aabee;
            color: #fff;
        }}

        /* Tech section */
        .tech {{
            max-width: 800px;
            margin: 0 auto;
            padding: 0 24px 80px;
            text-align: center;
        }}
        .tech h2 {{
            font-size: 28px;
            color: var(--white);
            margin-bottom: 12px;
        }}
        .tech p {{
            color: var(--text-muted);
            font-size: 15px;
            margin-bottom: 24px;
        }}
        .tech-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            text-align: left;
        }}
        .tech-item {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
        }}
        .tech-item strong {{
            color: var(--white);
            font-size: 13px;
            display: block;
            margin-bottom: 4px;
        }}
        .tech-item span {{
            font-size: 12px;
            color: var(--text-muted);
        }}

        /* Footer */
        footer {{
            border-top: 1px solid var(--border);
            padding: 32px 24px;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
        }}
        footer a {{ color: var(--text); text-decoration: none; }}
        footer a:hover {{ text-decoration: underline; }}

        @media (max-width: 600px) {{
            .outlets {{ grid-template-columns: 1fr; }}
            .stats-bar {{ gap: 24px; }}
            .hero {{ padding: 48px 16px 40px; }}
        }}
    </style>
</head>
<body>

<div class="hero">
    <div class="hero-label">AI-Powered Media</div>
    <h1>Faion <span>Media Network</span></h1>
    <p class="hero-sub">Autonomous content pipelines powered by Claude Agent SDK. From research to publication, fully automated.</p>
</div>

<div class="stats-bar">
    <div class="stats-item">
        <div class="stats-num">{total_articles}</div>
        <div class="stats-label">Articles published</div>
    </div>
    <div class="stats-item">
        <div class="stats-num">{total_channels}</div>
        <div class="stats-label">TG channels</div>
    </div>
    <div class="stats-item">
        <div class="stats-num">{len(MEDIA_OUTLETS)}</div>
        <div class="stats-label">Media outlets</div>
    </div>
    <div class="stats-item">
        <div class="stats-num">8</div>
        <div class="stats-label">Languages</div>
    </div>
</div>

<div class="outlets">
    {cards_html}
</div>

<div class="tech">
    <h2>How it works</h2>
    <p>Each outlet runs an autonomous pipeline: editorial planning, web research, article generation, review loop, translation, image creation, site deployment, and Telegram publishing.</p>
    <div class="tech-grid">
        <div class="tech-item">
            <strong>Claude Agent SDK</strong>
            <span>Structured output, tool use, retry logic</span>
        </div>
        <div class="tech-item">
            <strong>Multi-stage pipeline</strong>
            <span>12+ stages per article with quality gates</span>
        </div>
        <div class="tech-item">
            <strong>AI image generation</strong>
            <span>OpenAI gpt-image-1 with character consistency</span>
        </div>
        <div class="tech-item">
            <strong>Automated deploy</strong>
            <span>Gatsby SSG, git push, remote build</span>
        </div>
        <div class="tech-item">
            <strong>Health monitoring</strong>
            <span>Self-healing checks, audit logging</span>
        </div>
        <div class="tech-item">
            <strong>Security guardrails</strong>
            <span>Prompt injection detection, rate limiting</span>
        </div>
    </div>
</div>

<footer>
    <p>Faion Media Network &mdash; <a href="https://faion.net">faion.net</a></p>
</footer>

</body>
</html>"""
