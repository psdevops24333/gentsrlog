import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import json
import io

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

            # --- 1. จัดการไฟล์ JSON ---
            if inventory_json_file:
                st.info(f"📄 ตรวจพบไฟล์ข้อมูลแบบ JSON: `{inventory_json_file}`")
                json_data = json.loads(target_z.read(inventory_json_file).decode('utf-8', errors='ignore'))
                system_inventory = json_data.get("SystemInventory", json_data)
                components = system_inventory.get("Component", [])
                if isinstance(components, dict): components = [components]
                
                for comp in components:
                    fqdd = comp.get("@FQDD", comp.get("FQDD", ""))
                    attributes = comp.get("Attribute", [])
                    if isinstance(attributes, dict): attributes = [attributes]
                        
                    attr_dict = {attr.get("@Name", attr.get("Name")): attr.get("#text", attr.get("Value", attr.get("text"))) for attr in attributes if attr.get("@Name", attr.get("Name"))}

                    if "System.Board" in fqdd:
                        if "Model" in attr_dict: hardware_data["Model"] = attr_dict["Model"]
                        if "ServiceTag" in attr_dict: hardware_data["Serial Number (Service Tag)"] = attr_dict["ServiceTag"]
                    elif "iDRAC.Embedded" in fqdd and "HostName" in attr_dict:
                        hardware_data["Hostname"] = attr_dict["HostName"]
                    elif "IPv4." in fqdd and "Address" in attr_dict and attr_dict["Address"] != "0.0.0.0":
                        hardware_data["IP iDRAC"] = attr_dict["Address"]
                    
                    # แกะ CPU ให้ละเอียดขึ้น
                    elif "CPU.Socket" in fqdd and "Model" in attr_dict:
                        model = attr_dict["Model"]
                        cores = attr_dict.get("NumberOfProcessorCores", "")
                        threads = attr_dict.get("NumberOfEnabledThreads", "")
                        cpu_info = model
                        if cores and threads: cpu_info += f" ({cores} Cores / {threads} Threads)"
                        cpu_list.append(cpu_info)
                        
                    # แกะ RAM ให้แยก Slot
                    elif "DIMM.Socket" in fqdd and attr_dict.get("Size") not in ["0 MB", "0", "0 Bytes", "-", None]:
                        size = attr_dict.get('Size')
                        speed = attr_dict.get('Speed', '')
                        desc = f"[{fqdd}] {size}"
                        if speed: desc += f" @ {speed}"
                        ram_list.append(desc)
                        
                    # แกะ Disk แปลง Bytes เป็น GB
                    elif ("Disk." in fqdd or "PhysicalDisk." in fqdd) and "Size" in attr_dict:
                        size_raw = attr_dict['Size']
                        media = attr_dict.get('MediaType', '')
                        protocol = attr_dict.get('BusProtocol', '')
                        size_str = str(size_raw)
                        if size_str.isdigit() and int(size_str) > 1000000:
                            gb = int(size_str) / (1024**3)
                            size_str = f"{gb/1024:.2f} TB" if gb >= 1000 else f"{gb:.2f} GB"
                        disk_list.append(f"[{fqdd}] {size_str} {media} {protocol}".strip())
                        
                    elif ("RAID." in fqdd or "AHCI." in fqdd) and "ProductName" in attr_dict:
                        controller_list.append(attr_dict["ProductName"])
                    elif "NIC." in fqdd and "ProductName" in attr_dict:
                        nic_list.append(attr_dict["ProductName"])
                    elif ("FC." in fqdd or "FibreChannel." in fqdd) and "ProductName" in attr_dict:
                        fc_list.append(attr_dict["ProductName"])

            # --- 2. จัดการไฟล์ XML ---
            elif xml_files_to_parse:
                st.info(f"📄 ตรวจพบไฟล์ Inventory แยกส่วนจำนวน {len(xml_files_to_parse)} ไฟล์ (กำลังสกัดข้อมูล...)")

                for fname in xml_files_to_parse:
                    try:
                        xml_content = target_z.read(fname)
                        root = ET.fromstring(xml_content)
                        
                        for elem in root.iter():
                            if '}' in elem.tag:
                                elem.tag = elem.tag.split('}', 1)[1]
                        
                        for comp in root.iter():
                            attr_dict = {}
                            for k, v in comp.attrib.items():
                                attr_dict[k.upper()] = str(v).strip()
                                
                            for child in comp:
                                tag = child.tag.split('}')[-1].upper()
