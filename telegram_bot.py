import os
import datetime
import asyncio
import glob
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InputMediaPhoto, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Import your library
from strava.strava_intelligence import StravaIntelligence

import matplotlib
matplotlib.use("Agg")  # Use non-GUI backend for matplotlib

# --- Configuration ---
WORKDIR = Path("./strava_intelligence_workdir")
WEEKLY_DIR = WORKDIR / "weekly_reports" 
YEAR_DIR = WORKDIR / "year_in_sport"

# Timezone config
TZ = ZoneInfo("UTC") 
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", 0))

# --- Helpers ---

def _generate_weekly_and_get_path() -> Path | None:
    """
    Runs the weekly report generation and returns the path to the 
    most recently created image file in the weekly folder.
    """
    si = StravaIntelligence(workdir=WORKDIR)
    si.ensure_activities_with_streams()
    si.get_weekly_report()  # Generates the file
    
    # Find the newest .png file in the directory
    list_of_files = glob.glob(str(WEEKLY_DIR / "*.png"))
    if not list_of_files:
        return None
    
    # Return the file with the latest creation time
    return Path(max(list_of_files, key=os.path.getctime))

def _generate_yearly_and_get_images(year: int) -> list[Path]:
    """
    Runs the yearly report and returns a list of all image paths 
    in that year's folder.
    """
    si = StravaIntelligence(workdir=WORKDIR)
    si.ensure_activities_with_streams()
    
    # Generate the report
    si.get_year_in_sport(
        year=year,
        main_sport='Run', 
        comparison_year=year - 1, 
        neon_color="#de0606", 
        comparison_neon_color="#91ffe9"
    )
    
    # Scan the specific year folder for images
    target_dir = YEAR_DIR / str(year)
    if not target_dir.exists():
        return []
        
    # Grab all typical image formats
    extensions = ["*.png", "*.jpg", "*.jpeg"]
    images = []
    for ext in extensions:
        images.extend(target_dir.glob(ext))
    
    return sorted(images)

async def _run_blocking(fn, *args):
    """Run blocking synchronous code in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args))

# --- Job Callbacks ---

async def send_weekly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and sends the weekly report image."""
    try:
        # Run generation in thread to avoid blocking bot loop
        image_path = await _run_blocking(_generate_weekly_and_get_path)
        
        if image_path and image_path.exists():
            await context.bot.send_photo(
                chat_id=CHAT_ID, 
                photo=image_path
            )
        else:
            await context.bot.send_message(chat_id=CHAT_ID, text="Weekly report generation failed: No file found.")
            
    except Exception as e:
        print(f"Error in weekly job: {e}")
        await context.bot.send_message(chat_id=CHAT_ID, text=f"Error sending weekly report: {e}")


async def send_month_end_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and sends the Year in Sport images as an album."""
    try:
        this_year = datetime.datetime.now(TZ).year
        
        # Run generation
        image_paths = await _run_blocking(_generate_yearly_and_get_images, this_year)
        
        for img_path in image_paths:
            # "Smart" send_photo handles the opening automatically
            await context.bot.send_photo(chat_id=CHAT_ID, photo=img_path)
            
    except Exception as e:
        print(f"Error in monthly job: {e}")
        await context.bot.send_message(chat_id=CHAT_ID, text=f"Error sending monthly report: {e}")


async def post_init(app: Application) -> None:
    # Schedule: Sunday at 21:00
    when_21 = datetime.time(hour=21, minute=0, tzinfo=TZ)
    app.job_queue.run_daily(
        send_weekly_job,
        time=when_21,
        days=(0,),  # 0 = Sunday
        name="weekly_report_job"
    )

    # Schedule: Last day of the month at 21:00
    app.job_queue.run_monthly(
        send_month_end_job,
        when=when_21,
        day=-1,  # -1 = Last day
        name="month_end_report_job"
    )
    
    await app.bot.send_message(chat_id=CHAT_ID, text="Strava Bot started. Queues aligned.")


# Wrapper for the /weekly command
async def manual_weekly_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Triggering weekly report manually...")
    await send_weekly_job(context)

# Wrapper for the /monthly command
async def manual_monthly_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Triggering monthly report manually...")
    await send_month_end_job(context)


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars.")
        return

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Optional: Manual trigger commands for testing
    app.add_handler(CommandHandler("weekly", manual_weekly_trigger))
    app.add_handler(CommandHandler("monthly", manual_monthly_trigger))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
