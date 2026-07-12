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
        intents.message_content = True  # เปิดรับข้อมูลข้อความสำหรับคำสั่งธรรมดา
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

# สร้างตัวแปรบอท (ประกาศตัวแปรไว้ตรงนี้เพื่อให้คำสั่งด้านล่างมองเห็นทั้งหมด)
bot = MyBot()

@bot.event
async def on_ready():
    print(f'🤖 บอทเชื่อมต่อโฮส MC4 พร้อมใช้งาน: {bot.user}')

# --- ฟังก์ชันจัดการไฟล์ฝั่ง API MC4 ---
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

async def get_upload_url(config):
    url = f"{API_URL}/servers/{config['server_id']}/files/upload"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                res_data = await resp.json()
                return res_data['attributes']['url']
            return None

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
    embed.set_footer(text=f"Server ID: {server_id}")
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

# ==========================================
# 📥 คำสั่ง: ส่งไฟล์รวม บอทแยกฝั่งให้เอง 📥
# ==========================================
@bot.tree.command(name="upload", description="ส่งไฟล์รวม (.mcaddon / .zip) บอทจะแกะแยกฝั่ง BP/RP เข้าโฮสต์ให้เอง")
async def upload_combined_addon(interaction: discord.Interaction, file: discord.Attachment):
    config = load_config()
    if config['api_key'] == "ยังไม่ได้ตั้งค่า":
        await interaction.response.send_message("❌ กรุณาตั้งค่าบอทด้วยคำสั่ง `/set_config` ก่อนครับ", ephemeral=True)
        return

    if not (file.filename.endswith('.mcaddon') or file.filename.endswith('.zip') or file.filename.endswith('.mcpack')):
        await interaction.response.send_message("❌ รองรับเฉพาะไฟล์ `.mcaddon`, `.zip` หรือ `.mcpack` เท่านั้นครับ", ephemeral=True)
        return

    await interaction.response.defer()

    upload_url = await get_upload_url(config)
    if not upload_url:
        await interaction.followup.send("❌ ไม่สามารถดึงลิงก์อัปโหลดจากโฮสได้ กรุณาเช็ก API Key")
        return

    file_bytes = await file.read()
    temp_dir = f"temp_{interaction.id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        zip_buffer = io.BytesIO(file_bytes)
        files_to_upload = []

        with zipfile.ZipFile(zip_buffer, 'r') as archive:
            inner_files = archive.namelist()
            has_sub_packs = any(f.endswith('.mcpack') for f in inner_files)

            if has_sub_packs:
                for f_name in inner_files:
                    if f_name.endswith('.mcpack'):
                        archive.extract(f_name, path=temp_dir)
                        sub_path = os.path.join(temp_dir, f_name)
                        
                        with zipfile.ZipFile(sub_path, 'r') as sub_archive:
                            sub_content = sub_archive.read('manifest.json').decode('utf-8', errors='ignore')
                            target = "development_behavior_packs" if '"behavior"' in sub_content or '"data"' in sub_content else "development_resource_packs"
                        
                        with open(sub_path, 'rb') as f:
                            files_to_upload.append((target, os.path.basename(f_name), f.read()))
            else:
                if 'manifest.json' in inner_files:
                    manifest_content = archive.read('manifest.json').decode('utf-8', errors='ignore')
                    target = "development_behavior_packs" if '"behavior"' in manifest_content or '"data"' in manifest_content else "development_resource_packs"
                    files_to_upload.append((target, file.filename, file_bytes))
                else:
                    await interaction.followup.send("❌ 不พบไฟล์ `manifest.json` ข้างในไฟล์แอดออน ไม่สามารถแยกประเภทได้")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return

        shutil.rmtree(temp_dir, ignore_errors=True)

        if not files_to_upload:
            await interaction.followup.send("❌ ไม่พบพาร์ทแอดออนที่ถูกต้องในไฟล์นี้")
            return

        success_count = 0
        uploaded_details = []

        async with aiohttp.ClientSession() as session:
            for folder_target, final_name, data_bytes in files_to_upload:
                upload_endpoint = f"{upload_url}&directory={folder_target}"
                form_data = aiohttp.FormData()
                form_data.add_field('files', data_bytes, filename=final_name)
                
                async with session.post(upload_endpoint, data=form_data) as resp:
                    if resp.status in [200, 204]:
                        success_count += 1
                        short_folder = "BP (พฤติกรรม)" if "behavior" in folder_target else "RP (ทรัพยากร)"
                        uploaded_details.append(f"📦 `{final_name}` ➡️ แยกเข้าฝั่ง {short_folder}")

        if success_count == len(files_to_upload):
            embed = discord.Embed(
                title="⚙️ บอทแยกไฟล์และอัปโหลดสำเร็จ!",
                description="บอทส่องเนื้อในแอดออน แล้วทำการแยกโฟลเดอร์ส่งเข้าโฮสต์ให้ตรงฝั่งเรียบร้อยครับ",
                color=discord.Color.green()
            )
            embed.add_field(name="📋 รายละเอียดการจัดส่งไฟล์", value="\n".join(uploaded_details), inline=False)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(f"❌ อัปโหลดสำเร็จบางส่วน ({success_count}/{len(files_to_upload)} ไฟล์สำเร็จ)")

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการแกะไฟล์รวม: {e}")

# --- คำสั่งตั้งค่าเซิร์ฟเวอร์ ---
@bot.tree.command(name="set_config", description="ตั้งค่าการเชื่อมต่อโฮสต์ MC4")
@app_commands.describe(api_key="ใส่รหัส API Key", server_id="ใส่ไอดีเซิร์ฟเวอร์", world_name="ใส่ชื่อโฟลเดอร์โลก")
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

# --- คำสั่งเปิดแผงจัดแถวแอดออน ---
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

# --- คำสั่งพิมพ์มือสำหรับกระตุ้นระบบคำสั่งสแลช ---
@bot.command(name="sync")
async def sync_commands(ctx):
    try:
        fmt = await bot.tree.sync()
        await ctx.send(f"✅ บังคับอัปเดตระบบคำสั่งสำเร็จ! จำนวน {len(fmt)} คำสั่งใช้งานได้แล้ว")
    except Exception as e:
        await ctx.send(f"❌ เกิดข้อผิดพลาดในการซิงค์: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))
