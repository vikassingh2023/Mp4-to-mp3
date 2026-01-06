import os
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
import zipfile

import streamlit as st


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r"[^\w.\-() ]+", "_", name)
    return name or "file"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10_000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many duplicate filenames.")


# -------------------------
# App config
# -------------------------
st.set_page_config(page_title="MP4 → MP3 (Private)", layout="centered")
st.title("MP4 → MP3 Converter")

# -------------------------
# Simple "private" password gate
# -------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()

if APP_PASSWORD:
    if "authed" not in st.session_state:
        st.session_state.authed = False

    if not st.session_state.authed:
        st.info("Password required.")
        pwd = st.text_input("Password", type="password")
        if st.button("Unlock", type="primary"):
            if pwd == APP_PASSWORD:
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("Wrong password.")
        st.stop()
else:
    st.warning("APP_PASSWORD is not set. This app will be accessible to anyone with the link.")


if not ffmpeg_available():
    st.error("ffmpeg is not installed in this environment.")
    st.stop()

st.caption('FFmpeg settings: -vn -ac 1 -ar 16000 -b:a 96k')

uploads = st.file_uploader(
    "Upload .mp4 files",
    type=["mp4", "MP4"],
    accept_multiple_files=True
)

if not uploads:
    st.stop()

if st.button("Convert and Download ZIP", type="primary"):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        in_dir = tmpdir / "input"
        out_dir = tmpdir / "output_mp3"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        saved_inputs = []
        for up in uploads:
            safe_name = sanitize_filename(up.name)
            in_path = unique_path(in_dir / safe_name)
            in_path.write_bytes(up.getbuffer())
            saved_inputs.append(in_path)

        converted = failed = 0
        progress = st.progress(0)
        status = st.empty()

        for i, in_path in enumerate(saved_inputs, start=1):
            base = in_path.stem
            out_path = unique_path(out_dir / f"{base}.mp3")

            status.write(f"Converting **{in_path.name}** ({i}/{len(saved_inputs)}) …")

            # EXACT cmd you requested
            cmd = ["ffmpeg", "-y", "-i", str(in_path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "96k", str(out_path)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                converted += 1
            else:
                failed += 1
                st.warning(f"❌ Failed: {in_path.name}")
                st.code(res.stderr.decode("utf-8", errors="ignore")[:2000])

            progress.progress(i / len(saved_inputs))

        # Zip results in memory
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for mp3 in out_dir.glob("*.mp3"):
                zf.write(mp3, arcname=mp3.name)
        zip_buffer.seek(0)

        status.empty()
        st.success(f"Done. Converted: {converted} | Failed: {failed}")

        st.download_button(
            "Download mp3_outputs.zip",
            data=zip_buffer,
            file_name="mp3_outputs.zip",
            mime="application/zip"
        )
