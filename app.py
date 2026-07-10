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
        with zipfile.ZipFile(uploaded_file, 'r') as z:
            # 1. แสดงรายชื่อไฟล์ที่น่าจะเป็น Inventory ให้เห็นบนเว็บเพื่อช่วย Debug
            potential_files = [f for f in z.namelist() if 'inventory' in f.lower() or 'sysinfo' in f.lower()]
            st.info(f"🔍 ไฟล์ที่ตรวจพบที่เกี่ยวข้องใน ZIP: {', '.join(potential_files) if potential_files else 'ไม่พบไฟล์ inventory'}")
            
            # 2. ค้นหาไฟล์ XML
            inventory_file = None
            for fname in z.namelist():
                if fname.lower().endswith('inventory.xml') or 'hw_inventory.xml' in fname.lower():
                    inventory_file = fname
                    break
            
            if inventory_file:
                xml_content = z.read(inventory_file)
                root = ET.fromstring(xml_content)
                
                # --- แก้ปัญหาหลัก: ลบ XML Namespaces ออกทั้งหมดเพื่อให้ค้นหาได้ง่ายขึ้น ---
                for elem in root.iter():
                    if '}' in elem.tag:
                        elem.tag = elem.tag.split('}', 1)[1]
                # -------------------------------------------------------------------------
                
                # วนลูปหาข้อมูลตาม Component FQDD
                for comp in root.findall('.//Component'):
                    fqdd = comp.get('FQDD', '')
                    
                    # 1. Model & Serial Number
                    if 'System.Board' in fqdd:
                        for attr in comp.findall('Attribute'):
                            if attr.get('Name') == 'Model': hardware_data['Model'] = attr.text
                            if attr.get('Name') == 'ServiceTag': hardware_data['Serial Number (Service Tag)'] = attr.text
                            
                    # 2. Hostname & IP iDRAC
                    elif 'iDRAC.Embedded' in fqdd:
                        for attr in comp.findall('Attribute'):
                            if attr.get('Name') == 'HostName': hardware_data['Hostname'] = attr.text
                    elif 'IPv4.' in fqdd:
                        for attr in comp.findall('Attribute'):
                            if attr.get('Name') == 'Address' and attr.text != '0.0.0.0': 
                                hardware_data['IP iDRAC'] = attr.text

                    # 3. CPU
                    elif 'CPU.Socket' in fqdd:
                        model = comp.find("Attribute[@Name='Model']")
                        if model is not None: cpu_list.append(model.text)
                        
                    # 4. RAM
                    elif 'DIMM.Socket' in fqdd:
                        size = comp.find("Attribute[@Name='Size']")
                        speed = comp.find("Attribute[@Name='Speed']")
                        if size is not None and size.text not in ['0 MB', '0']:
                            ram_info = size.text
                            if speed is not None: ram_info += f" ({speed.text})"
                            ram_list.append(ram_info)
                            
                    # 5. Physical Disk
                    elif 'Disk.' in fqdd or 'PhysicalDisk.' in fqdd:
                        size = comp.find("Attribute[@Name='Size']")
                        media = comp.find("Attribute[@Name='MediaType']")
                        if size is not None:
                            desc = size.text
                            if media is not None: desc += f" {media.text}"
                            disk_list.append(desc)
                            
                    # 6. Controller Card
                    elif 'RAID.' in fqdd or 'AHCI.' in fqdd:
                        prod = comp.find("Attribute[@Name='ProductName']")
                        if prod is not None: controller_list.append(prod.text)
                        
                    # 7. Interface LAN
                    elif 'NIC.' in fqdd:
                        prod = comp.find("Attribute[@Name='ProductName']")
                        if prod is not None and prod.text not in nic_list:
                            nic_list.append(prod.text)
                            
                    # 8. FC Channel
                    elif 'FC.' in fqdd or 'FibreChannel.' in fqdd:
                        prod = comp.find("Attribute[@Name='ProductName']")
                        if prod is not None and prod.text not in fc_list:
                            fc_list.append(prod.text)

        # สรุปผลข้อมูล
        if cpu_list: hardware_data['CPU'] = f"{len(cpu_list)}x {cpu_list[0]}"
        if ram_list: hardware_data['RAM'] = f"{len(ram_list)} DIMMs (e.g., {ram_list[0]})"
        if disk_list: hardware_data['Physical Disk'] = f"รวม {len(disk_list)} ลูก (e.g., {disk_list[0]})"
        if controller_list: hardware_data['Controller Card'] = ", ".join(list(set(controller_list)))
        if nic_list: hardware_data['Interface LAN'] = ", ".join(list(set(nic_list)))
        if fc_list: hardware_data['FC Channel'] = ", ".join(list(set(fc_list)))
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่านโครงสร้าง XML: {e}")
        
    return hardware_data
