import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


BOT_TOKEN = os.environ.get("BOT_TOKEN")

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30
SECONDS_PER_PAGE = 4

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf"


# Render Web Service ke liye simple health server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def make_pages(text, output_dir):
    font = ImageFont.truetype(FONT_PATH, 42)
    title_font = ImageFont.truetype(FONT_PATH, 52)

    lines = text.splitlines()

    pages = []
    current = []

    for line in lines:
        current.append(line)

        if len(current) >= 14:
            pages.append("\n".join(current))
            current = []

    if current:
        pages.append("\n".join(current))

    for page_number, page_text in enumerate(pages, start=1):
        image = Image.new(
            "RGB",
            (VIDEO_WIDTH, VIDEO_HEIGHT),
            "white"
        )

        draw = ImageDraw.Draw(image)

        draw.text(
            (70, 50),
            "TXT TO VIDEO",
            font=title_font,
            fill="black"
        )

        draw.multiline_text(
            (80, 150),
            page_text,
            font=font,
            fill="black",
            spacing=18
        )

        draw.text(
            (1800, 1000),
            f"{page_number}",
            font=font,
            fill="gray"
        )

        filename = output_dir / f"page_{page_number:04d}.png"
        image.save(filename)

    return len(pages)


def make_video(image_dir, output_file):
    command = [
        "ffmpeg",
        "-y",
        "-framerate",
        f"1/{SECONDS_PER_PAGE}",
        "-i",
        str(image_dir / "page_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-vf",
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
        str(output_file)
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "नमस्ते! 👋\n\n"
        "मुझे कोई भी .txt file भेजो।\n"
        "मैं उसे video में convert करके इसी Telegram chat में भेज दूँगा।"
    )


async def txt_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document

    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text(
            "❌ केवल .txt file भेजो।"
        )
        return

    status = await update.message.reply_text(
        "⏳ TXT मिल गई है...\nVideo तैयार कर रहा हूँ।"
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="txt_video_"))

    try:
        txt_file = temp_dir / "input.txt"
        image_dir = temp_dir / "pages"
        image_dir.mkdir()

        video_file = temp_dir / "output.mp4"

        telegram_file = await context.bot.get_file(document.file_id)
        await telegram_file.download_to_drive(txt_file)

        text = txt_file.read_text(
            encoding="utf-8",
            errors="replace"
        )

        if not text.strip():
            await status.edit_text("❌ TXT file खाली है।")
            return

        page_count = make_pages(
            text,
            image_dir
        )

        await status.edit_text(
            f"⏳ {page_count} pages तैयार हो गए हैं...\n"
            "अब video बना रहा हूँ।"
        )

        make_video(
            image_dir,
            video_file
        )

        await status.edit_text(
            "📤 Video तैयार है...\nTelegram पर upload कर रहा हूँ।"
        )

        with open(video_file, "rb") as video:
            await update.message.reply_video(
                video=video,
                caption="✅ TXT से तैयार की गई Video"
            )

        await status.delete()

    except Exception as e:
        print("ERROR:", e)

        try:
            await status.edit_text(
                "❌ Video बनाने में error आया।\n"
                "Logs देखकर इसे ठीक करेंगे।"
            )
        except Exception:
            pass

    finally:
        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable नहीं मिला।"
        )

    # Health server अलग thread में
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
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            txt_to_video
        )
    )

    print("Bot started...")

    app.run_polling()


if __name__ == "__main__":
    main()
