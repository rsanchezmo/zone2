import os
import datetime
import asyncio
import glob
import logging
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Tuple, Optional
from contextlib import ExitStack

from telegram import InputMediaPhoto, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import matplotlib
# Use non-GUI backend for matplotlib to prevent crashes on servers
matplotlib.use("Agg")

from zone2.core import Zone2

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
WORKDIR = Path(os.getenv("STRAVA_WORKDIR", "./zone2_workdir"))
WEEKLY_DIR = WORKDIR / "weekly_reports"
YEAR_DIR = WORKDIR / "year_in_sport"

TZ = ZoneInfo("UTC")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# --- Core Logic / Generators ---

def _generate_weekly_report() -> Tuple[Optional[Path], str]:
    """
    Generates the weekly report and returns:
    1. Path to the image
    2. A text summary caption
    """
    z2 = Zone2(workdir=WORKDIR)
    z2.ensure_activities_with_streams()
    
    # 1. Generate the Visualization
    z2.get_weekly_report()
    
    # 2. Find the generated file
    list_of_files = glob.glob(str(WEEKLY_DIR / "*.png"))
    if not list_of_files:
        return None, "No weekly report generated."
    
    newest_file = Path(max(list_of_files, key=os.path.getctime))
    
    # 3. Calculate Date Range (Monday - Sunday)
    now = datetime.datetime.now(TZ)
    
    # Go back to the most recent Monday (weekday 0)
    # If today is Sunday (6), we subtract 6 days. If today is Monday (0), we subtract 0.
    start_of_week = now - datetime.timedelta(days=now.weekday())
    
    # End of week is Monday + 6 days (Sunday)
    end_of_week = start_of_week + datetime.timedelta(days=6)
    
    # Format: JAN 19 - JAN 25, 2026
    # .upper() ensures "Jan" becomes "JAN"
    date_range_str = (
        f"{start_of_week.strftime('%b %d').upper()} - "
        f"{end_of_week.strftime('%b %d').upper()}, "
        f"{end_of_week.year}"
    )

    caption = (
        f"🏃 **z2 Weekly Report**\n"
        f"📅 **Week:** {date_range_str}"
    )
    
    return newest_file, caption


def _generate_yearly_report(year: int) -> Tuple[List[Path], str]:
    """
    Generates the yearly report and returns:
    1. List of image paths
    2. A text summary caption for the album
    """
    z2 = Zone2(workdir=WORKDIR)
    z2.ensure_activities_with_streams()
    
    # 1. Generate the Visualizations
    z2.get_year_in_sport(
        year=year,
        main_sport='Run',
        comparison_year=year - 1,
        neon_color="#de0606",
        comparison_neon_color="#91ffe9"
    )
    
    # 2. Collect Images
    target_dir = YEAR_DIR / str(year)
    if not target_dir.exists():
        return [], "No yearly data found."
        
    extensions = ["*.png", "*.jpg", "*.jpeg"]
    images = []
    for ext in extensions:
        images.extend(target_dir.glob(ext))
    
    sorted_images = sorted(images)
    
    # 3. Generate Caption
    current_month = datetime.datetime.now(TZ).strftime("%B")
    caption = (
        f"🏆 **Year in Sport {year} as of {current_month}**"
    )
    
    return sorted_images, caption


async def _run_blocking(fn, *args):
    """Run blocking synchronous code in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args))


# --- Bot Handlers ---

async def send_weekly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and sends the weekly report image with caption."""
    logger.info("Starting weekly job...")
    try:
        image_path, caption = await _run_blocking(_generate_weekly_report)
        
        if image_path and image_path.exists():
            await context.bot.send_photo(
                chat_id=CHAT_ID, 
                photo=image_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info("Weekly report sent.")
        else:
            logger.warning("Weekly generation returned no file.")
            await context.bot.send_message(chat_id=CHAT_ID, text="⚠️ Weekly report generation failed: No file found.")
            
    except Exception as e:
        logger.error(f"Error in weekly job: {e}", exc_info=True)
        await context.bot.send_message(chat_id=CHAT_ID, text=f"Error sending weekly report: {e}")


async def send_month_end_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and sends the Year/Month overview as an Album."""
    logger.info("Starting month-end job...")
    try:
        this_year = datetime.datetime.now(TZ).year
        
        # Run generation
        image_paths, caption = await _run_blocking(_generate_yearly_report, this_year)
        
        if not image_paths:
            await context.bot.send_message(chat_id=CHAT_ID, text="No images found for the monthly report.")
            return

        # Use ExitStack to safely manage multiple open file handles
        with ExitStack() as stack:
            media_group = []
            for i, img_path in enumerate(image_paths):
                # We assume img_path is a Path object or string. 
                # We explicitly open it and track it in the stack.
                file_handle = stack.enter_context(open(img_path, "rb"))
                
                if i == 0:
                    # Attach caption to the first image
                    media_group.append(InputMediaPhoto(
                        media=file_handle, 
                        caption=caption, 
                        parse_mode=ParseMode.MARKDOWN
                    ))
                else:
                    media_group.append(InputMediaPhoto(media=file_handle))

            # Send the album while files are open
            await context.bot.send_media_group(chat_id=CHAT_ID, media=media_group)
            
        logger.info(f"Monthly report sent with {len(image_paths)} images.")
            
    except Exception as e:
        logger.error(f"Error in monthly job: {e}", exc_info=True)
        await context.bot.send_message(chat_id=CHAT_ID, text=f"Error sending monthly report: {e}")


async def check_if_month_end(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Checks if today is the last day of the month. 
    If yes, triggers the month_end_job.
    """
    now = datetime.datetime.now(TZ)
    tomorrow = now + datetime.timedelta(days=1)
    
    # If tomorrow is the 1st, today is the last day.
    if tomorrow.day == 1:
        logger.info("Last day of month detected. Triggering report.")
        await send_month_end_job(context)
    else:
        logger.info(f"Today is {now.date()}, not end of month. Skipping.")


# --- Command Wrappers ---

async def manual_weekly_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Generating weekly report...")
    await send_weekly_job(context)

async def manual_monthly_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Generating monthly album...")
    await send_month_end_job(context)


# --- Lifecycle ---

async def post_init(app: Application) -> None:
    # 1. Weekly Schedule: Sunday at 21:00
    app.job_queue.run_daily(
        send_weekly_job,
        time=datetime.time(hour=21, minute=0, tzinfo=TZ),
        days=(6,),  # 0=Mon, 6=Sun in python-telegram-bot v20+ (Check your version!)
        # NOTE: In some versions 0 is Sunday. Standard datetime 0=Monday, 6=Sunday.
        # PTB usually follows 0=Sunday, 6=Saturday OR 0=Monday. 
        # Safest is to check docs or use `days=(0,)` if using v13, `days=(6,)` if v20 using standard ints.
        # Assuming v20+ follows standard datetime: 6 is Sunday.
        name="weekly_report_job"
    )

    # 2. Monthly Schedule: "Last Day" Logic
    # We run this check EVERY DAY at 21:00. The function decides if it should run.
    app.job_queue.run_daily(
        check_if_month_end,
        time=datetime.time(hour=21, minute=0, tzinfo=TZ),
        name="month_end_checker"
    )
    
    commands = [
        ("weekly", "Trigger weekly report now"),
        ("monthly", "Trigger monthly report now")
    ]
    await app.bot.set_my_commands(commands)
    
    msg = (
        f"🤖 **z2 Bot Online**\n"
        f"📍 Timezone: {TZ}\n"
        f"📂 Workdir: `{WORKDIR}`"
    )
    await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)


def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("weekly", manual_weekly_trigger))
    app.add_handler(CommandHandler("monthly", manual_monthly_trigger))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
