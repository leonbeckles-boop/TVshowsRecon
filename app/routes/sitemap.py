from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()


@router.get("/sitemap.xml")
async def sitemap():

    urls = [
        "/shows-like",
        "/shows-like/breaking-bad",
        "/shows-like/dark",
        "/shows-like/fargo",
        "/shows-like/severance",
    ]

    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'

    for url in urls:
        xml += f"<url><loc>https://whatnext-app.com{url}</loc></url>"

    xml += "</urlset>"

    return Response(content=xml, media_type="application/xml")