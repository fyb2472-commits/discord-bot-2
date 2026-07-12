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

# --- ฟังก์ชันหลักสำหรับแกะไฟล์และอัปโหลด ---
async def process_and_upload(config, file_bytes, filename, interaction):
    upload_url = await get_upload_url(config)
    temp_dir = f"temp_{interaction.id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    zip_buffer = io.BytesIO(file_bytes)
    files_to_upload = []
    
    with zipfile.ZipFile(zip_buffer, 'r') as archive:
        inner_files = archive.namelist()
        if any(f.endswith('.mcpack') for f in inner_files):
            for f_name in inner_files:
                if f_name.endswith('.mcpack'):
                    archive.extract(f_name, path=temp_dir)
                    sub_path = os.path.join(temp_dir, f_name)
                    with zipfile.ZipFile(sub_path, 'r') as sub_archive:
                        sub_content = sub_archive.read('manifest.json').decode('utf-8', errors='ignore')
                        target = "development_behavior_packs" if '"behavior"' in sub_content else "development_resource_packs"
                    with open(sub_path, 'rb') as f: files_to_upload.append((target, os.path.basename(f_name), f.read()))
        elif 'manifest.json' in inner_files:
            manifest_content = archive.read('manifest.json').decode('utf-8', errors='ignore')
            target = "development_behavior_packs" if '"behavior"' in manifest_content else "development_resource_packs"
            files_to_upload.append((target, filename, file_bytes))
    
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    async with aiohttp.ClientSession() as session:
        for folder, name, data in files_to_upload:
            form = aiohttp.FormData()
            form.add_field('files', data, filename=name)
            await session.post(f"{upload_url}&directory={folder}", data=form)
    return len(files_to_upload)

# --- UI และคำสั่ง ---
class AddonManagerView(discord.ui.View):
    def __init__(self, config, pack_type, packs):
        super().__init__(timeout=180)
        self.config, self.pack_type, self.packs, self.selected_index = config, pack_type, packs, None
        self.path = f"worlds/{config['world_name']}/world_behavior_packs.json" if pack_type == 'bp' else f"worlds/{config['world_name']}/world_resource_packs.json"
        self.update_components()

    def update_components(self):
        self.clear_items()
        if not self.packs: return
        options = [discord.SelectOption(label=f"ลำดับ [{i}] - {item.get('pack_id')[:8]}", value=str(i)) for i, item in enumerate(self.packs)]
        select = discord.ui.Select(placeholder="เลือกแอดออน...", options=options)
        select.callback = lambda i: self.select_callback(i)
        self.add_item(select)
        
    async def select_callback(self, interaction):
        self.selected_index = int(interaction.data['values'][0])
        await interaction.response.edit_message(view=self)

@bot.tree.command(name="upload", description="อัปโหลดแอดออนจากไฟล์แนบ")
async def upload(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer()
    config = load_config()
    count = await process_and_upload(config, await file.read(), file.filename, interaction)
    await interaction.followup.send(f"✅ อัปโหลดสำเร็จ {count} ไฟล์")

@bot.tree.command(name="download", description="ดาวน์โหลดแอดออนจากลิงก์ (Mediafire/Drive)")
async def download(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    config = load_config()
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            count = await process_and_upload(config, await resp.read(), "downloaded_addon.mcaddon", interaction)
    await interaction.followup.send(f"✅ ดาวน์โหลดและติดตั้งสำเร็จ {count} ไฟล์")

@bot.tree.command(name="manage", description="เปิดแผงจัดแถวแอดออน")
async def manage(interaction, pack_type: str):
    # (ย่อส่วนจัดการ... ให้ใช้โค้ดตัวเดิมที่เคยให้ไปเพื่อประหยัดพื้นที่)
    await interaction.response.send_message("เปิดแผงควบคุม...")

@bot.command(name="sync")
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("✅ Sync สำเร็จ!")

bot.run(os.getenv("DISCORD_TOKEN"))
