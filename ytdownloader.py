#!/usr/bin/env python3
"""Lightweight local YouTube downloader with a web UI."""

import json
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import yt_dlp

DOWNLOAD_DIR = str(Path.home() / "Downloads")
PORT = 8080

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YT Downloader</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f0f0f; color: #e1e1e1;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh;
  }
  .container {
    background: #1a1a1a; border-radius: 12px; padding: 2.5rem;
    width: 100%; max-width: 520px; box-shadow: 0 8px 32px rgba(0,0,0,.4);
  }
  h1 { font-size: 1.5rem; margin-bottom: 1.5rem; text-align: center; }
  h1 span { color: #ff4444; }
  label { display: block; font-size: .85rem; color: #aaa; margin-bottom: .35rem; }
  input[type=text] {
    width: 100%; padding: .7rem .9rem; border-radius: 8px; border: 1px solid #333;
    background: #111; color: #fff; font-size: 1rem; outline: none;
    transition: border-color .2s;
  }
  input[type=text]:focus { border-color: #ff4444; }
  .format-group {
    display: flex; gap: .75rem; margin: 1.2rem 0;
  }
  .format-group label {
    flex: 1; text-align: center; padding: .6rem; border-radius: 8px;
    border: 1px solid #333; cursor: pointer; font-size: .95rem;
    color: #ccc; transition: all .2s;
  }
  .format-group input { display: none; }
  .format-group input:checked + label {
    border-color: #ff4444; color: #fff; background: #2a1a1a;
  }
  button {
    width: 100%; padding: .75rem; border: none; border-radius: 8px;
    background: #ff4444; color: #fff; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background .2s;
  }
  button:hover { background: #e03030; }
  button:disabled { background: #555; cursor: not-allowed; }
  #status {
    margin-top: 1.2rem; padding: .8rem; border-radius: 8px;
    font-size: .9rem; line-height: 1.4; display: none;
    word-break: break-word;
  }
  #status.info { display: block; background: #1a2a3a; color: #7cb8ff; }
  #status.success { display: block; background: #1a2a1a; color: #6fcf6f; }
  #status.error { display: block; background: #2a1a1a; color: #ff6b6b; }
</style>
</head>
<body>
<div class="container">
  <h1><span>&#9654;</span> YT Downloader</h1>
  <label for="url">YouTube URL</label>
  <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=..." autofocus>

  <div class="format-group">
    <input type="radio" name="fmt" id="mp4" value="mp4" checked>
    <label for="mp4">&#127909; Video (MP4)</label>
    <input type="radio" name="fmt" id="mp3" value="mp3">
    <label for="mp3">&#127925; Audio (MP3)</label>
  </div>

  <button id="btn" onclick="startDownload()">Download</button>
  <div id="status"></div>
</div>
<script>
function setStatus(msg, cls) {
  const s = document.getElementById('status');
  s.textContent = msg;
  s.className = cls;
}
async function startDownload() {
  const url = document.getElementById('url').value.trim();
  const fmt = document.querySelector('input[name=fmt]:checked').value;
  const btn = document.getElementById('btn');
  if (!url) { setStatus('Please enter a URL.', 'error'); return; }
  btn.disabled = true;
  btn.textContent = 'Downloading...';
  setStatus('Starting download...', 'info');
  try {
    const res = await fetch('/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, format: fmt})
    });
    const data = await res.json();
    if (data.ok) {
      setStatus('Done! Saved to: ' + data.filename, 'success');
    } else {
      setStatus('Error: ' + data.error, 'error');
    }
  } catch (e) {
    setStatus('Request failed: ' + e.message, 'error');
  }
  btn.disabled = false;
  btn.textContent = 'Download';
}
document.getElementById('url').addEventListener('keydown', e => {
  if (e.key === 'Enter') startDownload();
});
</script>
</body>
</html>"""

YOUTUBE_RE = re.compile(
    r"^https?://(www\.)?(youtube\.com/(watch|shorts|live)|youtu\.be/)"
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode())

    def do_POST(self):
        if self.path != "/download":
            self._json(404, {"ok": False, "error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        url = body.get("url", "").strip()
        fmt = body.get("format", "mp4")

        if not YOUTUBE_RE.match(url):
            self._json(400, {"ok": False, "error": "Invalid YouTube URL"})
            return

        try:
            filename = download(url, fmt)
            self._json(200, {"ok": True, "filename": filename})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        print(f"  {args[0]}")


def download(url: str, fmt: str) -> str:
    """Download a YouTube video/audio and return the resulting filename."""
    opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }

    if fmt == "mp3":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp may change the extension after post-processing
        if fmt == "mp3":
            return info.get("title", "download") + ".mp3"
        return ydl.prepare_filename(info).split("/")[-1]


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"YT Downloader running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
