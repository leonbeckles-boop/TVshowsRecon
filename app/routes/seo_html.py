"""Standalone server-rendered /shows-like/ pages; mounts under /seo-pages."""
import html
import logging
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.routes import seo

router = APIRouter(prefix="/seo-pages", tags=["seo-html"])
log = logging.getLogger(__name__)
BASE = "https://whatnexttv.org"


def esc(value):
    return html.escape(str(value or ""), quote=True)


def slug_for(title):
    return re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")


def render_page(slug, data):
    anchor = data.get("anchor") or {}
    recs = data.get("recommendations") or []
    copy = data.get("page_copy") or {}
    title = anchor.get("title")
    if not title or not recs:
        return None
    url = f"{BASE}/shows-like/{quote(slug, safe='-')}"
    description = str(copy.get("seo_blurb") or copy.get("intro") or f"Discover TV shows like {title}.")[:160]
    cards = []
    for rec in recs[:12]:
        name = rec.get("title")
        if not name:
            continue
        why = rec.get("why_recommended") or rec.get("source_explanation") or rec.get("overview") or ""
        rec_id = rec.get("tmdb_id")
        detail_link = f'{BASE}/show/{int(rec_id)}' if str(rec_id).isdigit() else f'{BASE}/search'
        poster = rec.get("poster_path") or rec.get("poster_url") or ""
        if isinstance(poster, str) and poster.startswith("/"):
            poster = f"https://image.tmdb.org/t/p/w500{poster}"
        elif not (isinstance(poster, str) and poster.startswith("https://image.tmdb.org/t/p/")):
            poster = ""
        poster_html = (
            f'<a href="{esc(detail_link)}" aria-label="View {esc(name)}">'
            f'<img class="poster" src="{esc(poster)}" alt="{esc(name)} poster" '
            f'loading="lazy" width="500" height="750"></a>'
            if poster else '<div class="poster placeholder" aria-hidden="true">Poster unavailable</div>'
        )
        cards.append(
            f'<article class="card">{poster_html}<div class="card-content">'
            f'<h3><a href="{esc(detail_link)}">{esc(name)}</a></h3>'
            f'<p>{esc(why)}</p></div></article>'
        )
    if not cards:
        return None
    sections = []
    for section in (copy.get("content_sections") or [])[:5]:
        sections.append(f'<section><h2>{esc(section.get("heading"))}</h2><p>{esc(section.get("body"))}</p></section>')
    faqs = []
    for item in (copy.get("faq_items") or [])[:8]:
        q = item.get("question") or item.get("q")
        a = item.get("answer") or item.get("a")
        if q and a:
            faqs.append(f'<section><h3>{esc(q)}</h3><p>{esc(a)}</p></section>')
    links = []
    for item in (copy.get("related_page_links") or [])[:12]:
        related_title = item.get("title") or ""
        href = item.get("href") or ""
        # Construct internal links ourselves; do not trust API-provided hrefs.
        related_slug = slug_for(re.sub(r"^Shows like\s+", "", related_title, flags=re.I))
        if related_slug and related_slug != slug:
            links.append(f'<a href="{BASE}/shows-like/{related_slug}">{esc(related_title)}</a>')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(f'Shows Like {title}: What to Watch Next | WhatNextTV')}</title>
<meta name="description" content="{esc(description)}"><link rel="canonical" href="{esc(url)}">
<style>body{{margin:0;background:#020617;color:#e2e8f0;font:16px/1.6 system-ui,sans-serif}}a{{color:#93c5fd}}header,main,footer{{max-width:1100px;margin:auto;padding:22px}}header{{display:flex;gap:22px;flex-wrap:wrap}}h1{{font-size:clamp(2rem,5vw,3.5rem);line-height:1.15}}h2{{margin-top:36px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}.card,section{{background:#101b32;border:1px solid #334155;border-radius:12px;padding:18px}}.card{{padding:0;overflow:hidden}}.poster{{display:block;width:100%;height:auto;aspect-ratio:2/3;object-fit:cover}}.placeholder{{display:grid;place-items:center;background:#1e293b;color:#94a3b8}}.card-content{{padding:18px}}.card h3{{margin-top:0}}.card p{{margin-bottom:0}}.links{{display:flex;flex-wrap:wrap;gap:16px}}footer{{border-top:1px solid #334155;margin-top:35px}}</style></head>
<body><header><a href="{BASE}/">WhatNextTV</a><a href="{BASE}/discover">Discover</a><a href="{BASE}/search">Search</a><a href="{BASE}/register">Create an account</a></header>
<main><nav><a href="{BASE}/">Home</a> / <a href="{BASE}/shows-like">Shows Like</a> / {esc(title)}</nav>
<h1>Shows Like {esc(title)}</h1><p>{esc(copy.get('intro') or description)}</p>
<h2>TV recommendations for {esc(title)}</h2><div class="grid">{''.join(cards)}</div>
{''.join(sections)}<h2>Frequently asked questions</h2>{''.join(faqs)}
<h2>Explore more recommendations</h2><div class="links">{''.join(links)}</div>
<p><a href="{BASE}/register">Create an account to save favourites and get personalised recommendations</a></p></main>
<footer>WhatNextTV · <a href="{BASE}/search">Search TV shows</a></footer></body></html>'''


@router.get('/shows-like/{slug}', response_class=HTMLResponse)
async def shows_like_html(slug: str, db: AsyncSession = Depends(get_async_session)):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise HTTPException(status_code=404, detail='Invalid show slug')
    try:
        payload = await seo.shows_like(slug=slug, taxonomy_shadow=True, refresh=False, x_seo_refresh_key=None, db=db)
    except HTTPException:
        raise
    except Exception:
        log.exception('SEO HTML generation failed for %s', slug)
        return Response('Temporarily unavailable', status_code=503, headers={'Retry-After': '300'})
    page = render_page(slug, payload)
    if page is None:
        raise HTTPException(status_code=404, detail='No recommendation page available')
    return HTMLResponse(page, headers={'Cache-Control': 'public, max-age=300'})
