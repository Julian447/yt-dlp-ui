import uuid
import time
import asyncio
import yt_dlp
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter()

# in-memory store for short-lived preview entries: {id: (stream_url, expires_at)}
PREVIEW_STORE: dict[str, tuple[str, float]] = {}
PREVIEW_TTL = 60  # seconds; adjust


async def preview_audio(url: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
    }

    # run blocking extraction off the event loop
    info = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False))

    # pick best audio format URL (browser-friendly fallback as before)
    formats = info.get('formats') or [info]
    audio_formats = [f for f in formats if f.get('acodec') and f.get('acodec') != 'none']
    preferred_exts = ('m4a', 'webm', 'mp3', 'ogg', 'opus')
    non_hls = [f for f in audio_formats if not ('m3u8' in (f.get('protocol') or ''))]
    candidates = [f for f in non_hls if f.get('ext') in preferred_exts] or non_hls or audio_formats
    best = max(candidates, key=lambda f: f.get('abr') or f.get('tbr') or 0) if candidates else None
    stream_url = best.get('url') if best else info.get('url')

    # create short-lived preview id and store the direct media URL server-side
    preview_id = str(uuid.uuid4())
    PREVIEW_STORE[preview_id] = (stream_url, time.time() + PREVIEW_TTL)

    # return metadata and the server-side preview endpoint (frontend should call this)
    preview_path = f"/preview/{preview_id}"
    return info.get('title'), info.get('duration'), info.get('thumbnail'), preview_path

@router.get("/preview/{preview_id}")
async def proxy_preview(preview_id: str):
    entry = PREVIEW_STORE.get(preview_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Preview not found or expired")
    stream_url, expires_at = entry
    if time.time() > expires_at:
        PREVIEW_STORE.pop(preview_id, None)
        raise HTTPException(status_code=404, detail="Preview expired")

    # Optionally remove entry on first use:
    # PREVIEW_STORE.pop(preview_id, None)

    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
        # stream the remote media and forward chunks to the browser
        resp = await client.get(stream_url, timeout=None, stream=True)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Upstream error")

        headers = {}
        if 'content-type' in resp.headers:
            headers['content-type'] = resp.headers['content-type']
        if 'content-length' in resp.headers:
            headers['content-length'] = resp.headers['content-length']

        async def stream_iter():
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                yield chunk

        return StreamingResponse(stream_iter(), headers=headers, status_code=200)
