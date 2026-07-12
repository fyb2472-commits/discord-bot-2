import zipfile
import io
import shutil

# ==========================================
# 📥 คำสั่งเดียวจบ: ส่งไฟล์รวม บอทแยกพาร์ทให้เอง 📥
# ==========================================
@bot.tree.command(name="upload", description="ส่งไฟล์รวม (.mcaddon / .zip) บอทจะแกะแยกฝั่ง BP/RP เข้าโฮสต์ให้เอง")
async def upload_combined_addon(interaction: discord.Interaction, file: discord.Attachment):
    config = load_config()
    if config['api_key'] == "ยังไม่ได้ตั้งค่า":
        await interaction.response.send_message("❌ กรุณาตั้งค่าบอทด้วยคำสั่ง `/set_config` ก่อนครับ", ephemeral=True)
        return

    # รองรับไฟล์รวมทุกรูปแบบ
    if not (file.filename.endswith('.mcaddon') or file.filename.endswith('.zip') or file.filename.endswith('.mcpack')):
        await interaction.response.send_message("❌ รองรับเฉพาะไฟล์ `.mcaddon`, `.zip` หรือ `.mcpack` เท่านั้นครับ", ephemeral=True)
        return

    await interaction.response.defer() # ป้องกันบอทค้างเวลาเจอไฟล์ใหญ่

    # 1. ขอลิงก์อัปโหลดจากโฮสต์ MC4
    upload_url = await get_upload_url(config)
    if not upload_url:
        await interaction.followup.send("❌ ไม่สามารถดึงลิงก์อัปโหลดจากโฮสได้ กรุณาเช็ก API Key")
        return

    # ดาวน์โหลดไฟล์จากดิสคอร์ดเข้ามาอ่านในแรมของบอทก่อน
    file_bytes = await file.read()
    
    # สร้างโฟลเดอร์ชั่วคราวเอาไว้แอบแกะของ
    temp_dir = f"temp_{interaction.id}"
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # แปลงข้อมูลไฟล์เพื่อเตรียมแตกซิบ
        zip_buffer = io.BytesIO(file_bytes)
        
        # ลิสต์เก็บไฟล์ที่จะเตรียมยิงเข้าโฮส
        files_to_upload = [] # เก็บ tuple: (ฝั่งไหน, ชื่อไฟล์, ข้อมูลไบต์)

        with zipfile.ZipFile(zip_buffer, 'r') as archive:
            # ตรวจสอบเบื้องต้นว่าในไฟล์ซิบมีไฟล์ย่อยข้างในอีกทีไหม (สไตล์ .mcaddon)
            inner_files = archive.namelist()
            has_sub_packs = any(f.endswith('.mcpack') for f in inner_files)

            if has_sub_packs:
                # กรณีไฟล์ .mcaddon ที่ซ่อนไฟล์ .mcpack ไว้ข้างใน
                for f_name in inner_files:
                    if f_name.endswith('.mcpack'):
                        # แตกไฟล์ย่อยออกมาดูเนื้อในชั่วคราว
                        archive.extract(f_name, path=temp_dir)
                        sub_path = os.path.join(temp_dir, f_name)
                        
                        # ส่องดูว่าไฟล์ย่อยนี้เป็น BP หรือ RP
                        with zipfile.ZipFile(sub_path, 'r') as sub_archive:
                            sub_content = sub_archive.read('manifest.json').decode('utf-8', errors='ignore')
                            target = "development_behavior_packs" if '"behavior"' in sub_content or '"data"' in sub_content else "development_resource_packs"
                        
                        with open(sub_path, 'rb') as f:
                            files_to_upload.append((target, os.path.basename(f_name), f.read()))
            else:
                # กรณีเป็นไฟล์เดี่ยว หรือไฟล์ .zip ที่ข้างในมี manifest.json เลย
                if 'manifest.json' in inner_files:
                    manifest_content = archive.read('manifest.json').decode('utf-8', errors='ignore')
                    target = "development_behavior_packs" if '"behavior"' in manifest_content or '"data"' in manifest_content else "development_resource_packs"
                    files_to_upload.append((target, file.filename, file_bytes))
                else:
                    await interaction.followup.send("❌ ไม่พบไฟล์ `manifest.json` ข้างในแอดออน ไม่สามารถแยกประเภทได้ครับ")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return

        # ลบโฟลเดอร์ชั่วคราวทิ้งทันทีหลังอ่านเสร็จ
        shutil.rmtree(temp_dir, ignore_errors=True)

        if not files_to_upload:
            await interaction.followup.send("❌ ไม่พบพาร์ทแอดออนที่ถูกต้องในไฟล์นี้")
            return

        # 2. ยิงไฟล์แยกฝั่งส่งเข้าโฮสต์ MC4 ตามที่คำนวณไว้
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

        # 3. สรุปผลส่งกลับในดิสคอร์ด
        if success_count == len(files_to_upload):
            embed = discord.Embed(
                title="⚙️ บอทแยกไฟล์และอัปโหลดสำเร็จ!",
                description="บอทส่องเนื้อในแอดออน แล้วทำการสับเปลี่ยนโฟลเดอร์ส่งเข้าโฮสต์ให้ตรงฝั่งเรียบร้อยครับ",
                color=discord.Color.green()
            )
            embed.add_field(name="📋 รายละเอียดการจัดส่งไฟล์", value="\n".join(uploaded_details), inline=False)
            embed.set_footer(text="⚠️ อย่าลืมเข้าเว็บไปกดแตกไฟล์ (Unarchive) และสั่งรีเซิร์ฟเวอร์ด้วยนะ")
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(f"❌ อัปโหลดสำเร็จบางส่วน ({success_count}/{len(files_to_upload)} ไฟล์สำเร็จ)")

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการแกะไฟล์รวม: {e}")
