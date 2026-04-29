import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import time
import random

# ===== CONFIG =====
TOKEN = "YOUR_TOKEN_HERE" 

HOSTER_ROLE_ID = 1490336481976389722
OWNER_ID = 1469693949068185621
LOG_CHANNEL_ID = 1492884980303528126

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="u.", intents=intents)

leagues = {}

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect("league.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER DEFAULT 0,
            loses INTEGER DEFAULT 0
        )
        """)
        await db.commit()

async def add_win(uid):
    async with aiosqlite.connect("league.db") as db:
        await db.execute("""
        INSERT INTO stats(user_id,wins,loses)
        VALUES(?,1,0)
        ON CONFLICT(user_id) DO UPDATE SET wins=wins+1
        """, (uid,))
        await db.commit()

async def add_lose(uid):
    async with aiosqlite.connect("league.db") as db:
        await db.execute("""
        INSERT INTO stats(user_id,wins,loses)
        VALUES(?,0,1)
        ON CONFLICT(user_id) DO UPDATE SET loses=loses+1
        """, (uid,))
        await db.commit()

# ================= UTILS =================
def is_hoster(user):
    return any(r.id == HOSTER_ROLE_ID for r in user.roles)

def is_owner(user):
    return user.id == OWNER_ID

def max_players(mode):
    return {"2v2": 4, "3v3": 6, "4v4": 8}.get(mode, 4)

def build_embed(data, guild):
    host = guild.get_member(data["creator"])
    status_map = {
        "running": "🟢 Running",
        "ended": "⚪ Ended",
        "cancelled": "🔴 Cancelled"
    }

    embed = discord.Embed(title="🏆 League Match", color=discord.Color.blurple())
    embed.add_field(
        name="📌 Information",
        value=(
            f"👤 Host: {host.mention if host else f'<@{data["creator"]}>'}\n"
            f"🌍 Region: {data['region']}\n"
            f"🎮 Mode: {data['mode']}\n"
            f"⚔️ Type: {data['type']}\n"
            f"✨ Perk: {data['perk']}\n"
            f"📊 Status: {status_map.get(data['status'], 'Unknown')}"
        ),
        inline=False
    )
    embed.add_field(
        name="👥 Players",
        value="\n".join([f"• <@{p}>" for p in data["players"]]) if data["players"] else "No players",
        inline=False
    )
    embed.add_field(
        name="📊 Slots",
        value=f"{len(data['players'])}/{data['max']}"
    )
    return embed

# ================= VIEW =================
class LeagueView(discord.ui.View):
    def __init__(self, thread_id):
        super().__init__(timeout=None)
        self.thread_id = thread_id

    async def refresh(self, message):
        if self.thread_id not in leagues:
            return
        data = leagues[self.thread_id]
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label == "Join":
                item.disabled = len(data["players"]) >= data["max"] or data["status"] != "running"
        await message.edit(embed=build_embed(data, message.guild), view=self)

    @discord.ui.button(label="Join", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        data = leagues.get(self.thread_id)
        
        if not data or data["status"] != "running":
            return await interaction.followup.send("League closed")
        if interaction.user.id in data["players"]:
            return await interaction.followup.send("Already joined")
        if len(data["players"]) >= data["max"]:
            return await interaction.followup.send("League full")

        data["players"].append(interaction.user.id)
        thread = interaction.guild.get_thread(self.thread_id)
        if thread:
            await thread.add_user(interaction.user)

        if len(data["players"]) == data["max"]:
            temp_players = list(data["players"])
            random.shuffle(temp_players)
            half = len(temp_players) // 2
            data["teams"] = {
                "1": temp_players[:half],
                "2": temp_players[half:]
            }
            if thread:
                await thread.send(
                    "🔥 **League FULL!**\n\n"
                    "🔵 Team 1:\n" + "\n".join([f"<@{u}>" for u in data["teams"]["1"]]) +
                    "\n\n🔴 Team 2:\n" + "\n".join([f"<@{u}>" for u in data["teams"]["2"]])
                )

        await self.refresh(interaction.message)
        await interaction.followup.send("Joined")

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        data = leagues.get(self.thread_id)

        if not data: return
        if interaction.user.id == data["creator"]:
            return await interaction.followup.send("Host cannot leave")
        if interaction.user.id not in data["players"]:
            return await interaction.followup.send("Not in league")

        data["players"].remove(interaction.user.id)
        thread = interaction.guild.get_thread(self.thread_id)
        if thread:
            await thread.remove_user(interaction.user)

        await self.refresh(interaction.message)
        await interaction.followup.send("Left")

# ================= CREATE VIEW =================
class CreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.data = {}

    @discord.ui.select(
        placeholder="Region",
        options=[discord.SelectOption(label=x) for x in ["Asia","Europe","Australia","North America","Africa","South America"]]
    )
    async def region(self, i, select):
        self.data["region"] = select.values[0]
        await i.response.defer()

    @discord.ui.select(
        placeholder="Mode",
        options=[discord.SelectOption(label=x) for x in ["2v2","3v3","4v4"]]
    )
    async def mode(self, i, select):
        self.data["mode"] = select.values[0]
        await i.response.defer()

    @discord.ui.select(
        placeholder="Type",
        options=[discord.SelectOption(label=x) for x in ["War","Swift"]]
    )
    async def type(self, i, select):
        self.data["type"] = select.values[0]
        await i.response.defer()

    @discord.ui.select(
        placeholder="Perk",
        options=[discord.SelectOption(label=x) for x in ["Perk","No Perk"]]
    )
    async def perk(self, i, select):
        self.data["perk"] = select.values[0]
        await i.response.defer()

    @discord.ui.button(label="Create League", style=discord.ButtonStyle.green)
    async def create(self, i: discord.Interaction, button: discord.ui.Button):
        if len(self.data) < 4:
            return await i.response.send_message("Bạn chưa chọn đủ thông số!", ephemeral=True, delete_after=5)

        if not (is_hoster(i.user) or is_owner(i.user)):
            return await i.response.send_message("Bạn không có quyền!", ephemeral=True, delete_after=5)

        await i.response.defer(ephemeral=True)

        thread = await i.channel.create_thread(
            name=f"League-{i.user.name}",
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        await thread.add_user(i.user)

        data = {
            "creator": i.user.id,
            "players": [i.user.id],
            "max": max_players(self.data["mode"]),
            "status": "running",
            "created": time.time(),
            **self.data
        }

        msg = await i.channel.send(embed=build_embed(data, i.guild))
        data["message"] = msg.id
        leagues[thread.id] = data

        view = LeagueView(thread.id)
        await msg.edit(view=view)
        
        await i.delete_original_response()
        await i.followup.send(f"✅ Created league in {thread.mention}", ephemeral=True, delete_after=5)

# ================= COG =================
class League(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="create", description="Tạo một trận đấu mới")
    async def create(self, i: discord.Interaction):
        await i.response.send_message("Select league settings:", view=CreateView(), ephemeral=True)

    @app_commands.command(name="end", description="Kết thúc trận đấu (Chỉ cho Host)")
    async def end(self, i: discord.Interaction):
        data = leagues.get(i.channel.id)
        if not data:
            return await i.response.send_message("Đây không phải kênh League!", ephemeral=True)

        if not (i.user.id == data["creator"] or is_owner(i.user)):
            return await i.response.send_message("No permission", ephemeral=True)

        data["status"] = "ended"
        try:
            parent_channel = i.channel.parent
            msg = await parent_channel.fetch_message(data["message"])
            await msg.edit(embed=build_embed(data, i.guild), view=None)
        except: pass

        await i.response.send_message("League Ended. Thread will be deleted.")
        leagues.pop(i.channel.id)
        await i.channel.delete()

    @app_commands.command(name="winner", description="Cập nhật thắng/thua")
    @app_commands.choices(team=[
        app_commands.Choice(name="Team 1", value="1"),
        app_commands.Choice(name="Team 2", value="2")
    ])
    async def winner(self, i: discord.Interaction, team: app_commands.Choice[str]):
        data = leagues.get(i.channel.id)
        if not data or "teams" not in data:
            return await i.response.send_message("Teams not ready or not in a league thread", ephemeral=True)

        if not (i.user.id == data["creator"] or is_owner(i.user)):
            return await i.response.send_message("No permission", ephemeral=True)

        win_team = data["teams"][team.value]
        lose_team = data["teams"]["1" if team.value == "2" else "2"]

        for u in win_team: await add_win(u)
        for u in lose_team: await add_lose(u)

        await i.response.send_message(f"🏆 Result saved! Team {team.value} won.")

# ================= TASKS & EVENTS =================
@tasks.loop(minutes=5)
async def auto_cancel():
    now = time.time()
    for tid in list(leagues.keys()):
        data = leagues[tid]
        if data["status"] == "running" and (now - data["created"] > 5400):
            # Tự động hủy sau 90 phút nếu chưa đủ người
            leagues.pop(tid)

@bot.event
async def on_ready():
    await init_db()
    # Kiểm tra xem Cog đã được add chưa để tránh lỗi sync lại nhiều lần
    if not bot.get_cog("League"):
        await bot.add_cog(League(bot))
    
    await bot.tree.sync()
    if not auto_cancel.is_running():
        auto_cancel.start()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

bot.run(TOKEN)