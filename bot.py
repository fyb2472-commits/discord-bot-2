import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import json
import os
import zipfile
import io
import shutil

CONFIG_FILE = "config.json"
API_URL = "https://panel.mc4.in/api/client"

# --- ฟังก์ชันจัดการ Config ---
def load_config():
    default_config = {"api_key": "ยังไม่ได้ตั้งค่า", "server_id": "bf9e4ae6", "world_name": "Bedrock Level"}
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(default_config, f, indent=4)
        return default_config
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)

# --- Class บอท ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    print(f'🤖 บอทเชื่อมต่อโฮส MC4 พร้อมใช้งาน: {bot.user}')

# --- ฟังก์ชันเสริม (API & File Processing) ---
async def get_remote_json(config, path):
    url = f"{API_URL}/servers/{config['server_id']}/files/contents?file={path}"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            return json.loads(await resp.text()) if resp.status == 200 else []

async def save_remote_json(config, path, data):
    url = f"{API_URL}/servers/{config['server_id']}/files/write?file={path}"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=json.dumps(data, indent=4)) as resp:
            return resp.status in [204, 200]

async def get_upload_url(config):
    url = f"{API_URL}/servers/{config['server_id']}/files/upload"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            return (await resp.json())['attributes']['url'] if resp.status == 200 else None

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
            options.append(discord.SelectOption(label=f"ลำดับ [{index}] - ID: {item.get('pack_id')[:8]}...", value=str(index), default=(self.selected_index == index)))
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
            if idx is None: return False
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
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=create_addon_embed(self.config['server_id'], self.pack_type, self.packs), view=self)
            return True
        return True

# --- ฟังก์ชันหลักสำหรับแกะไฟล์และอัปโหลด ---
async def process_and_upload(config, file_bytes, filename, interaction):
    upload_url = await get_upload_url(config)
    if not upload_url:
        return 0
    temp_dir = f"temp_{interaction.id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    zip_buffer = io.BytesIO(file_bytes)
    files_to_upload = []
    
    try:
        with zipfile.ZipFile(zip_buffer, 'r') as archive:
            inner_files = archive.namelist()
            if any(f.endswith('.mcpack') for f in inner_files):
                for f_name in inner_files:
                    if f_name.endswith('.mcpack'):
                        archive.extract(f_name, path=temp_dir)
                        sub_path = os.path.join(temp_dir, f_name)
                        with zipfile.ZipFile(sub_path, 'r') as sub_archive:
                            sub_content = sub_archive.read('manifest.json').decode('utf-8', errors='ignore')
                            target = "development_behavior_packs" if '"behavior"' in sub_content or '"data"' in sub_content else "development_resource_packs"
                        with open(sub_path, 'rb') as f: 
                            files_to_upload.append((target, os.path.basename(f_name), f.read()))
            elif 'manifest.json' in inner_files:
                manifest_content = archive.read('manifest.json').decode('utf-8', errors='ignore')
                target = "development_behavior_packs" if '"behavior"' in manifest_content or '"data"' in manifest_content else "development_resource_packs"
                files_to_upload.append((target, filename, file_bytes))
    except Exception:
        pass
    
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    success_count = 0
    async with aiohttp.ClientSession() as session:
        for folder, name, data in files_to_upload:
            form = aiohttp.FormData()
            form.add_field('files', data, filename=name)
            async with session.post(f"{upload_url}&directory={folder}", data=form) as resp:
                if resp.status in [200, 204]:
                    success_count += 1
    return success_count

# --- คำสั่งหลัก ---
@bot.tree.command(name="upload", description="อัปโหลดแอดออนจากไฟล์แนบ")
async def upload(interaction: discord.Interaction, file: discord.Attachment):
    config = load_config()
    if config['api_key'] == "ยังไม่ได้ตั้งค่า":
        await interaction.response.send_message("❌ กรุณาตั้งค่าบอทด้วยคำสั่ง `/set_config` ก่อนครับ", ephemeral=True)
        return
    await interaction.response.defer()
    count = await process_and_upload(config, await file.read(), file.filename, interaction)
    await interaction.followup.send(f"✅ อัปโหลดและแยกประเภทสำเร็จ {count} ไฟล์")

@bot.tree.command(name="download", description="ดาวน์โหลดแอดออนจากลิงก์ตรง (สำหรับคนไม่มี Nitro)")
async def download(interaction: discord.Interaction, url: str):
    config = load_config()
    if config['api_key'] == "ยังไม่ได้ตั้งค่า":
        await interaction.response.send_message("❌ กรุณาตั้งค่าบอทด้วยคำสั่ง `/set_config` ก่อนครับ", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ ดาวน์โหลดไฟล์จากลิงก์ไม่สำเร็จ เช็กว่าเป็นลิงก์โหลดตรงไหม")
                    return
                file_bytes = await resp.read()
        count = await process_and_upload(config, file_bytes, "downloaded_addon.mcaddon", interaction)
        await interaction.followup.send(f"✅ บอทดาวน์โหลดและแยกติดตั้งสำเร็จ {count} ไฟล์")
    except Exception as e:
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")

@bot.tree.command(name="set_config", description="ตั้งค่าการเชื่อมต่อโฮสต์ MC4")
async def set_config(interaction: discord.Interaction, api_key: str = None, server_id: str = None, world_name: str = None):
    config = load_config()
    if api_key: config['api_key'] = api_key
    if server_id: config['server_id'] = server_id
    if world_name: config['world_name'] = world_name
    save_config(config)
    embed = discord.Embed(title="⚙️ อัปเดตการตั้งค่าสำเร็จ!", color=discord.Color.purple())
    embed.add_field(name="🆔 Server ID", value=f"`{config['server_id']}`", inline=True)
    embed.add_field(name="🌍 World Name", value=f"`{config['world_name']}`", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="manage", description="เปิดแผงควบคุมจัดเรียงแอดออนบนโฮสต์ MC4")
@app_commands.choices(pack_type=[
    app_commands.Choice(name="Behavior Pack (BP)", value="bp"),
    app_commands.Choice(name="Resource Pack (RP)", value="rp")
])
async def manage_addons(interaction: discord.Interaction, pack_type: app_commands.Choice[str]):
    await interaction.response.defer()
    config = load_config()
    if config['api_key'] == "ยังไม่ได้ตั้งค่า":
        await interaction.followup.send("❌ กรุณาตั้งค่าด้วยคำสั่ง `/set_config` ก่อนครับ", ephemeral=True)
        return
    path = f"worlds/{config['world_name']}/world_behavior_packs.json" if pack_type.value == 'bp' else f"worlds/{config['world_name']}/world_resource_packs.json"
    packs = await get_remote_json(config, path)
    view = AddonManagerView(config, pack_type.value, packs)
    await interaction.followup.send(embed=create_addon_embed(config['server_id'], pack_type.value, packs), view=view)

@bot.command(name="sync")
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("✅ Sync ระบบคำสั่งสแลชทั้งหมดสำเร็จแล้ว!")

bot.run(os.getenv("DISCORD_TOKEN"))
