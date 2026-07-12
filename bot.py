import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
import os

CONFIG_FILE = "config.json"
API_URL = "https://panel.mc4.in/api/client"

# ฟังก์ชันโหลดการตั้งค่า
def load_config():
    default_config = {
        "api_key": "ยังไม่ได้ตั้งค่า",
        "server_id": "bf9e4ae6",
        "world_name": "Bedrock Level"
    }
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

# ฟังก์ชันบันทึกการตั้งค่า
def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    print(f'🤖 บอทพร้อมใช้งานแล้วในชื่อ: {bot.user}')

# --- ฟังก์ชันช่วยคุยกับ API ของ MC4 ---
async def get_remote_json(config, path):
    url = f"{API_URL}/servers/{config['server_id']}/files/contents?file={path}"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return json.loads(await resp.text())
            return []

async def save_remote_json(config, path, data):
    url = f"{API_URL}/servers/{config['server_id']}/files/write?file={path}"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=json.dumps(data, indent=4)) as resp:
            return resp.status in [204, 200]

def create_addon_embed(server_id, pack_type: str, packs: list) -> discord.Embed:
    is_bp = pack_type == 'bp'
    title = "🟢 Behavior Packs (MC4)" if is_bp else "🔵 Resource Packs (MC4)"
    color = discord.Color.green() if is_bp else discord.Color.blue()
    
    embed = discord.Embed(title=title, description="ระบบจัดลำดับแอดออนบนโฮสต์ MC4", color=color)
    list_text = ""
    if not packs:
        list_text = "*❌ ไม่พบไฟล์ หรือยังไม่มีแอดออนเปิดใช้งาน*"
    else:
        for index, item in enumerate(packs):
            list_text += f"**`[{index}]`** 🆔 `{item.get('pack_id')[:14]}...` | v`{'.'.join(map(str, item.get('version', [1,0,0])))}`\n"
            
    embed.add_field(name="📋 ลำดับปัจจุบันในเวิลด์", value=list_text, inline=False)
    embed.set_footer(text=f"Server ID: {server_id} • รีสตาร์ทเซิร์ฟเวอร์บนเว็บหลังจัดเสร็จ")
    return embed

# --- แผงปุ่มกดคอนโทรล ---
class AddonManagerView(discord.ui.View):
    def __init__(self, config: dict, pack_type: str, initial_packs: list):
        super().__init__(timeout=180)
        self.config = config
        self.pack_type = pack_type
        self.path = f"worlds/{config['world_name']}/world_behavior_packs.json" if pack_type == 'bp' else f"worlds/{config['world_name']}/world_resource_packs.json"
        self.packs = initial_packs
        self.selected_index = None
        self.update_components()

    def update_components(self):
        self.clear_items()
        if not self.packs:
            self.add_item(discord.ui.Button(label="ไม่มีแอดออนในระบบ", disabled=True, style=discord.ButtonStyle.gray))
            return

        options = []
        for index, item in enumerate(self.packs):
            options.append(discord.SelectOption(
                label=f"ลำดับ [{index}] - ID: {item.get('pack_id')[:8]}...",
                value=str(index),
                default=(self.selected_index == index)
            ))

        select = discord.ui.Select(placeholder="คลิกเลือกแอดออนที่จะปรับตำแหน่ง...", options=options)
        select.callback = self.select_callback
        self.add_item(select)

        is_disabled = self.selected_index is None
        self.add_item(discord.ui.Button(label="🔼 เลื่อนขึ้น", style=discord.ButtonStyle.primary, custom_id="move_up", disabled=is_disabled))
        self.add_item(discord.ui.Button(label="🔽 เลื่อนลง", style=discord.ButtonStyle.primary, custom_id="move_down", disabled=is_disabled))
        self.add_item(discord.ui.Button(label="❌ ลบออก", style=discord.ButtonStyle.danger, custom_id="remove_pack", disabled=is_disabled))

    async def select_callback(self, interaction: discord.Interaction):
        self.selected_index = int(interaction.data['values'][0])
        self.update_components()
        await interaction.response.edit_message(embed=create_addon_embed(self.config['server_id'], self.pack_type, self.packs), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get('component_type') == 2:
            custom_id = interaction.data.get('custom_id')
            idx = self.selected_index

            if idx is None:
                await interaction.response.send_message("❌ กรุณาเลือกแอดออนก่อนครับ", ephemeral=True)
                return False

            if custom_id == "move_up" and idx > 0:
                self.packs.insert(idx - 1, self.packs.pop(idx))
                self.selected_index = idx - 1
            elif custom_id == "move_down" and idx < len(self.packs) - 1:
                self.packs.insert(idx + 1, self.packs.pop(idx))
                self.selected_index = idx + 1
            elif custom_id == "remove_pack":
                self.packs.pop(idx)
                self.selected_index = None

            await interaction.response.defer()
            success = await save_remote_json(self.config, self.path, self.packs)
            
            if success:
                self.update_components()
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    embed=create_addon_embed(self.config['server_id'], self.pack_type, self.packs),
                    view=self
                )
            else:
                await interaction.followup.send("❌ โฮสปฏิเสธการบันทึกไฟล์ กรุณาตรวจสอบสิทธิ์ API Key", ephemeral=True)
            return True
        return True

# ==========================================
# 🛠️ คำสั่งที่ 1: ตั้งค่าโฮสต์ผ่านดิสคอร์ด 🛠️
# ==========================================
@bot.tree.command(name="set_config", description="ตั้งค่าการเชื่อมต่อโฮสต์ MC4 (API Key, Server ID, ชื่อโลก)")
@app_commands.describe(
    api_key="ใส่รหัส API Key (ptlc_...)", 
    server_id="ใส่ไอดีเซิร์ฟเวอร์ 8 หลักหลังลิงก์สแลช", 
    world_name="ใส่ชื่อโฟลเดอร์โลกในโฮสต์"
)
async def set_config(interaction: discord.Interaction, api_key: str = None, server_id: str = None, world_name: str = None):
    # โหลดค่าเก่าขึ้นมา
    config = load_config()
    
    # อัปเดตเฉพาะอันที่พิมพ์ส่งมา
    if api_key: config['api_key'] = api_key
    if server_id: config['server_id'] = server_id
    if world_name: config['world_name'] = world_name
    
    # เซฟลงไฟล์
    save_config(config)
    
    embed = discord.Embed(title="⚙️ อัปเดตการตั้งค่าเซิร์ฟเวอร์สำเร็จ!", color=discord.Color.purple())
    embed.add_field(name="🔑 API Key", value="`อัปเดตแล้ว (ซ่อนไว้เพื่อความปลอดภัย)`" if api_key else "ใช้ค่าเดิม", inline=False)
    embed.add_field(name="🆔 Server ID", value=f"`{config['server_id']}`", inline=True)
    embed.add_field(name="🌍 World Name", value=f"`{config['world_name']}`", inline=True)
    
    # ส่งแบบ ephemeral=True เพื่อให้เห็นเฉพาะคนที่กดใช้คำสั่ง (ป้องกันคนอื่นเห็นข้อมูลเซิร์ฟ)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- คำสั่งเรียกใช้งานบอทจัดการแอดออน ---
@bot.tree.command(name="manage", description="เปิดแผงควบคุมจัดเรียงแอดออนบนโฮสต์ MC4")
@app_commands.choices(pack_type=[
    app_commands.Choice(name="Behavior Pack (BP)", value="bp"),
    app_commands.Choice(name="Resource Pack (RP)", value="rp")
])
async def manage_addons(interaction: discord.Interaction, pack_type: app_commands.Choice[str]):
    await interaction.response.defer()
    
    # ดึงการตั้งค่าล่าสุดจากไฟล์ json
    config = load_config()
    
    if config['api_key'] == "ยังไม่ได้ตั้งค่า":
        await interaction.followup.send("❌ บอทยังไม่ได้ตั้งค่า API Key! กรุณาใช้คำสั่ง `/set_config` ก่อนครับ", ephemeral=True)
        return

    path = f"worlds/{config['world_name']}/world_behavior_packs.json" if pack_type.value == 'bp' else f"worlds/{config['world_name']}/world_resource_packs.json"
    
    packs = await get_remote_json(config, path)
    view = AddonManagerView(config, pack_type.value, packs)
    embed = create_addon_embed(config['server_id'], pack_type.value, packs)
    
    await interaction.followup.send(embed=embed, view=view)

# ใส่ Token บอทดิสคอร์ดของคุณตรงนี้เพื่อเปิดบอท
bot.run("YOUR_BOT_TOKEN_HERE")

