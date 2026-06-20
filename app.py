import discord
from discord.ext import commands, tasks
import os
import traceback
from flask import Flask
import sys
import aiohttp
import asyncio
from dotenv import load_dotenv

# Initialize environment variables
load_dotenv()

# Flask Setup
app = Flask(__name__)
bot_name = "Loading..."

@app.route('/')
def home():
    """Health check endpoint for Render"""
    return f"Bot {bot_name} is operational"

@app.route('/ping')
def ping():
    """Extra ping endpoint for keep-alive"""
    return "pong", 200

def run_flask():
    """Run Flask with Render-compatible settings"""
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Discord Bot Setup
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Missing TOKEN in environment")

# Render service URL for self-ping keep-alive
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

class Bot(commands.Bot):
    def __init__(self):
        # Configure minimal required intents
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self.session = None

    async def setup_hook(self):
        """Initialize bot components"""
        self.session = aiohttp.ClientSession()
        
        # Load cogs
        try:
            await self.load_extension("cogs.infoCommands")
            print("✅ Successfully loaded InfoCommands cog")
        except Exception as e:
            print(f"❌ Failed to load cog: {e}")
            traceback.print_exc()
        
        await self.tree.sync()
        self.update_status.start()
        self.keep_alive_ping.start()

    async def on_ready(self):
        """When bot connects to Discord"""
        global bot_name
        bot_name = str(self.user)
        
        print(f"\n🔗 Connected as {bot_name}")
        print(f"🌐 Serving {len(self.guilds)} servers")
        
        # Start Flask if running on Render
        if os.environ.get('RENDER'):
            import threading
            flask_thread = threading.Thread(target=run_flask, daemon=True)
            flask_thread.start()
            print("🚀 Flask server started in background")

    async def on_disconnect(self):
        """Log when bot disconnects"""
        print("⚠️ Bot disconnected from Discord. Will auto-reconnect...")

    async def on_resumed(self):
        """Log when bot reconnects"""
        print("✅ Bot reconnected to Discord!")

    @tasks.loop(minutes=5)
    async def update_status(self):
        """Update bot presence periodically"""
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            print(f"⚠️ Status update failed: {e}")

    @update_status.before_loop
    async def before_status_update(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=4)
    async def keep_alive_ping(self):
        """
        Self-ping task to prevent Render from sleeping the service.
        Render free tier sleeps after ~15 min of inactivity.
        Pinging every 4 minutes keeps it awake 24/7.
        """
        if not RENDER_URL:
            return  # Only run on Render
        try:
            async with self.session.get(f"{RENDER_URL}/ping", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"✅ Keep-alive ping successful ({RENDER_URL}/ping)")
                else:
                    print(f"⚠️ Keep-alive ping returned status {resp.status}")
        except Exception as e:
            print(f"⚠️ Keep-alive ping failed: {e}")

    @keep_alive_ping.before_loop
    async def before_keep_alive(self):
        await self.wait_until_ready()
        await asyncio.sleep(30)  # Wait 30s after ready before first ping

    async def close(self):
        """Cleanup on shutdown"""
        if self.session:
            await self.session.close()
        await super().close()

async def main():
    """
    Main entry point with auto-reconnect logic.
    If bot crashes/disconnects, it waits and retries automatically.
    """
    retry_delay = 5  # seconds
    max_retry_delay = 120  # max 2 minutes between retries

    while True:
        bot = Bot()
        try:
            print("🚀 Starting bot...")
            await bot.start(TOKEN)
        except KeyboardInterrupt:
            print("🛑 Shutting down bot (KeyboardInterrupt)...")
            await bot.close()
            break
        except discord.LoginFailure:
            print("❌ Invalid TOKEN! Please check your TOKEN environment variable.")
            await bot.close()
            break
        except Exception as e:
            print(f"⚠️ Bot crashed: {e}")
            traceback.print_exc()
        finally:
            try:
                await bot.close()
            except Exception:
                pass

        print(f"🔄 Reconnecting in {retry_delay} seconds...")
        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_retry_delay)  # Exponential backoff

if __name__ == "__main__":
    if os.environ.get('RENDER'):
        asyncio.run(main())
    else:
        # Local development - simple run
        bot = Bot()
        bot.run(TOKEN)
