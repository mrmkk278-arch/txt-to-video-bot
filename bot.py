import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


BOT_TOKEN = os.environ.get("BOT_TOKEN")

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720

FPS = 2
SECONDS_PER_PAGE = 4

PAGES_PER_CHUNK = 50

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf"


# -----------------------------
# Render health server
# -----------------------------

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    server.serve_forever()


# -----------------------------
# Create page images
# -----------------------------

def make_pages(page_texts, output_dir, start_number):
    font = ImageFont.truetype(
        FONT_PATH,
        32
    )

    title_font = ImageFont.truetype(
        FONT_PATH,
        42
    )

    created_files = []

    for index, page_text in enumerate(
        page_texts,
        start=start_number
    ):

        image = Image.new(
            "RGB",
            (VIDEO_WIDTH, VIDEO_HEIGHT),
            "white"
        )

        draw = ImageDraw.Draw(image)

        draw.text(
            (50, 35),
            "TXT TO VIDEO",
            font=title_font,
            fill="black"
        )

        draw.multiline_text(
            (60, 110),
            page_text,
            font=font,
            fill="black",
            spacing=12
        )

        draw.text(
            (1190, 660),
            str(index),
            font=font,
            fill="gray"
        )

        filename = output_dir / f"page_{index:04d}.png"

        image.save(
            filename,
            optimize=True
        )

        created_files.append(filename)

        del draw
        del image

    return created_files


# -----------------------------
# Create video chunk
# -----------------------------

def make_chunk_video(image_dir, output_file):
    command = [
        "ffmpeg",
        "-y",

        "-framerate",
        f"1/{SECONDS_PER_PAGE}",

        "-i",
        str(image_dir / "page_%04d.png"),

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-crf",
        "28",

        "-threads",
        "1",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(FPS),

        "-movflags",
        "+faststart",

        str(output_file),
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


# -----------------------------
# Join video chunks
# -----------------------------

def join_chunks(chunk_files, final_file):
    concat_file = final_file.parent / "concat.txt"

    with open(
        concat_file,
        "w",
        encoding="utf-8"
    ) as f:

        for chunk in chunk_files:
            f.write(
                f"file '{chunk.as_posix()}'\n"
            )

    command = [
        "ffmpeg",
        "-y",

        "-f",
        "concat",

        "-safe",
        "0",

        "-i",
        str(concat_file),

        "-c",
        "copy",

        "-movflags",
        "+faststart",

        str(final_file),
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    concat_file.unlink(
        missing_ok=True
    )


# -----------------------------
# Start command
# -----------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "नमस्ते! 👋\n\n"
        "मुझे कोई भी .txt file भेजो।\n"
        "मैं उसे horizontal video में convert करके "
        "इसी Telegram chat में भेज दूँगा।"
    )


# -----------------------------
# TXT -> VIDEO
# -----------------------------

async def txt_to_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    document = update.message.document

    if not document.file_name.lower().endswith(".txt"):

        await update.message.reply_text(
            "❌ केवल .txt file भेजो।"
        )

        return

    status = await update.message.reply_text(
        "⏳ TXT मिल गई है...\n"
        "Video तैयार कर रहा हूँ।"
    )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="txt_video_"
        )
    )

    try:

        txt_file = temp_dir / "input.txt"

        chunks_dir = temp_dir / "chunks"

        chunks_dir.mkdir()

        final_video = temp_dir / "output.mp4"

        # Download TXT

        telegram_file = await context.bot.get_file(
            document.file_id
        )

        await telegram_file.download_to_drive(
            txt_file
        )

        # Read TXT

        text = txt_file.read_text(
            encoding="utf-8",
            errors="replace"
        )

        if not text.strip():

            await status.edit_text(
                "❌ TXT file खाली है।"
            )

            return

        # -----------------------------
        # Prepare pages
        # -----------------------------

        lines = text.splitlines()

        pages = []

        current = []

        for line in lines:

            current.append(line)

            if len(current) >= 14:

                pages.append(
                    "\n".join(current)
                )

                current = []

        if current:

            pages.append(
                "\n".join(current)
            )

        total_pages = len(pages)

        await status.edit_text(
            f"📄 कुल {total_pages} pages मिले हैं.\n"
            f"अब chunks में video बनाया जा रहा है..."
        )

        # -----------------------------
        # Make chunks
        # -----------------------------

        chunk_files = []

        chunk_number = 1

        for start_index in range(
            0,
            total_pages,
            PAGES_PER_CHUNK
        ):

            chunk_pages = pages[
                start_index:
                start_index + PAGES_PER_CHUNK
            ]

            image_dir = (
                temp_dir /
                f"images_{chunk_number}"
            )

            image_dir.mkdir()

            make_pages(
                chunk_pages,
                image_dir,
                start_index + 1
            )

            chunk_file = (
                chunks_dir /
                f"chunk_{chunk_number:04d}.mp4"
            )

            await status.edit_text(
                f"🎬 Video बन रहा है...\n"
                f"Pages: "
                f"{start_index + 1}-"
                f"{min(start_index + PAGES_PER_CHUNK, total_pages)}\n"
                f"Chunk: {chunk_number}"
            )

            make_chunk_video(
                image_dir,
                chunk_file
            )

            chunk_files.append(
                chunk_file
            )

            # Images immediately delete
            shutil.rmtree(
                image_dir,
                ignore_errors=True
            )

            chunk_number += 1

        # -----------------------------
        # Join all chunks
        # -----------------------------

        await status.edit_text(
            "🔗 सभी video parts को जोड़ रहा हूँ..."
        )

        join_chunks(
            chunk_files,
            final_video
        )

        # -----------------------------
        # Upload to Telegram
        # -----------------------------

        await status.edit_text(
            "📤 Video तैयार है...\n"
            "Telegram पर upload कर रहा हूँ..."
        )

        with open(
            final_video,
            "rb"
        ) as video:

            await update.message.reply_video(
                video=video,
                caption="✅ TXT से तैयार की गई Video"
            )

        await status.delete()

    except Exception as e:

        print(
            "ERROR:",
            repr(e)
        )

        try:

            await status.edit_text(
                "❌ Video बनाने में error आया।\n"
                "Render logs में error check करना होगा।"
            )

        except Exception:
            pass

    finally:

        # Everything temporary gets deleted
        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )


# -----------------------------
# Main
# -----------------------------

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable नहीं मिला।"
        )

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            txt_to_video
        )
    )

    print(
        "Bot started..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
