import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

# --- ฟังก์ชันหลักในการแกะข้อมูลแบบครอบคลุมทั้ง XML และไฟล์แยกส่วน ---
def parse_tsr_log(uploaded_file):
    hardware_data = {
        "Model": "-",
        "Serial Number (Service Tag)": "-",
        "Hostname": "-",
        "IP iDRAC": "-",
        "CPU": "-",
        "RAM": "-",
        "Physical Disk": "-",
        "Controller Card": "-",
        "Interface LAN": "-",
        "FC Channel": "-"
    }
    
    cpu_list, ram_list, disk_list = [], [], []
    nic_list, fc_list, controller_list = [], [], []
    
    try:
        with zipfile.ZipFile(uploaded_file, 'r') as outer_z:
            all_files = outer_z.namelist()
            
            # ตรวจสอบโครงสร้าง ZIP ซ้อนภายใน (Nested ZIP)
            inner_zip_name = None
            for fname in all_files:
                if fname.lower().endswith('.zip'):
                    inner_zip_name = fname
                    break
            
            if inner_zip_name:
                inner_zip_bytes = io.BytesIO(outer_z.read(inner_zip_name))
                target_z = zipfile.ZipFile(inner_zip_bytes, 'r')
                target_files = target_z.namelist()
            else:
                target_z = outer_z
                target_files = all_files

            with st.expander("🔍 ดูโครงสร้างไฟล์ภายใน TSR ZIP (สำหรับตรวจสอบ)"):
                st.write(f"จำนวนไฟล์ทั้งหมดที่ค้นหา: {len(target_files)} ไฟล์")
                st.code("\n".join(target_files[:30]))

            inventory_json_file = None
            xml_files_to_parse = []
            
            for fname in target_files:
                fname_lower = fname.lower()
                if 'hardware_inventory.json' in fname_lower or 'hw_inventory.json' in fname_lower:
                    inventory_json_file = fname
                    break
                
                if 'inventory.xml' in fname_lower or 'hw_inventory.xml' in fname_lower:
                    xml_files_to_parse = [fname]
                    break
                    
                if 'sysinfo_' in fname_lower and fname_lower.endswith('.xml'):
                    xml_files_to_parse.append(fname)

            # --- กรณีที่ 1: จัดการไฟล์แบบ JSON ---
            if inventory_json_file:
                st.info(f"📄 ตรวจพบไฟล์ข้อมูลแบบ JSON: `{inventory_json_file}`")
                json_data = json.loads(target_z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                system_inventory = json_data.get("SystemInventory", json_data)
                components = system_
