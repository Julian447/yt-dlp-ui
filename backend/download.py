import os
import yt_dlp
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse
import re

router = APIRouter()

def progress_hook(d):
    if d['status'] == 'downloading':
        downloads[d['info_dict']['id']] = d['_percent_str']

async def download_audio(download_id: str, url: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'progress_hooks': [progress_hook],
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", info['title'])
        orig_path = os.path.join(DOWNLOAD_DIR, f"{info['id']}.mp3")
        file_path = os.path.join(DOWNLOAD_DIR, f"{safe_title}.mp3")
        if os.path.exists(orig_path):
            os.rename(orig_path, file_path)
        return file_path

@router.post("/download/audio")
async def start_audio_download(url: str, background_tasks: BackgroundTasks, proxy: bool = False):
    download_id = url.split('=')[-1]
    downloads[download_id] = "Starting audio download"
    if proxy:
        temp_path = await download_audio(download_id, url)
        def cleanup(path):
            try:
                os.remove(path)
            except Exception:
                pass
        background_tasks.add_task(cleanup, temp_path)
        return FileResponse(temp_path, media_type='audio/mpeg', filename=os.path.basename(temp_path))
    else:
        file_path = await download_audio(download_id, url)
        return {"download_id": download_id, "type": "audio", "file_path": file_path}
