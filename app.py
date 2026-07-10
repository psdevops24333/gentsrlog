import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import io

# --- ฟังก์ชันหลักในการแกะข้อมูลจริงจาก TSR Log (.zip) ---
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
            # ค้นหาไฟล์ inventory.xml ภายใน TSR Zip
            inventory_file = None
            for fname in z.namelist():
                if 'inventory.xml' in fname.lower() or 'hw_inventory.xml' in fname.lower():
                    inventory_file = fname
                    break
            
            if inventory_file:
                xml_content = z.read(inventory_file)
                root = ET.fromstring(xml_content)
                
                # ลบ XML Namespaces ออกทั้งหมดเพื่อให้ค้นหาข้อมูลได้แม่นยำ
                for elem in root.iter():
                    if '}' in elem.tag:
                        elem.tag = elem.tag.split('}', 1)[1]
                
                # วนลูปสกัดข้อมูลตาม FQDD ของ Dell iDRAC
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
                        if size is not None and size.text not in ['0 MB', '0', '-', 'None']:
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

        # สรุปผลข้อมูลจัดกลุ่ม (Grouping)
        if cpu_list: hardware_data['CPU'] = f"{len(cpu_list)}x {cpu_list[0]}"
        if ram_list: hardware_data['RAM'] = f"{len(ram_list)} DIMMs (เช่น {ram_list[0]})"
        if disk_list: hardware_data['Physical Disk'] = f"รวม {len(disk_list)} ลูก (เช่น {disk_list[0]})"
        if controller_list: hardware_data['Controller Card'] = ", ".join(list(set(controller_list)))
        if nic_list: hardware_data['Interface LAN'] = ", ".join(list(set(nic_list)))
        if fc_list: hardware_data['FC Channel'] = ", ".join(list(set(fc_list)))
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่านโครงสร้างไฟล์ XML: {e}")
        
    return hardware_data

# --- ฟังก์ชันสร้างไฟล์ .docx (ย้ายการโหลด Library มาไว้ข้างในเพื่อความปลอดภัย) ---
def export_to_docx(data):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    
    doc = Document()
    
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("Lifecycle Log Summary Inventory")
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(26, 82, 118)
    
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Table Grid'
    
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Hardware Component'
    hdr_cells[1].text = 'Details / Value'
    
    for cell in hdr_cells:
        cell.paragraphs[0].runs[0].font.bold = True
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        
        # ใส่สีพื้นหลังหัวตาราง สีกรมท่า
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), "1A5276")
        tcPr.append(shd)
        
    for key, value in data.items():
        row_cells = table.add_row().cells
        row_cells[0].text = str(key)
        row_cells[1].text = str(value)
        row_cells[0].paragraphs[0].runs[0].font.bold = True
        
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    return docx_buffer

# --- การตั้งค่าหน้าจอและ UI ของ Streamlit ---
st.set_page_config(page_title="TSR Log Hardware Extractor", page_icon="🖥️", layout="wide")

st.title("🖥️ TSR Log Hardware Extractor")
st.subheader("อัปโหลดไฟล์ Dell TSR Log (.zip) เพื่อดึงข้อมูล Inventory เสมือนในหน้า Lifecycle")

uploaded_file = st.file_uploader("เลือกไฟล์ TSR Log (.zip)", type=["zip"])

if uploaded_file is not None:
    st.success("โหลดไฟล์สำเร็จ! กำลังทำการวิเคราะห์ XML และดึงข้อมูลจริง...")
    
    # เรียกฟังก์ชันแกะข้อมูลจริง
    parsed_data = parse_tsr_log(uploaded_file)
    
    st.write("### 📊 Lifecycle Log Summary Inventory")
    
    # แปลงผลลัพธ์ดั้งเดิมเป็นโครงสร้างตารางแสดงผลบนเว็บ (โดยไม่ใช้ pandas)
    table_rows = [{"Hardware Component": k, "Details / Value": v} for k, v in parsed_data.items()]
    st.table(table_rows)
    
    st.write("---")
    
    # สร้างปุ่มสำหรับกด Export ป้องกันเว็บแครชตอนโหลดหน้าแรก
    if st.button("🔄 คลิกที่นี่เพื่อเตรียมไฟล์ Word (.docx)"):
        try:
            docx_file = export_to_docx(parsed_data)
            st.download_button(
                label="📥 ดาวน์โหลดไฟล์ Word (.docx) สำเร็จ",
                data=docx_file,
                file_name=f"Inventory_{parsed_data['Serial Number (Service Tag)']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        except Exception as e:
            st.error(f"ไม่สามารถสร้างไฟล์ Word ได้เนื่องจากคลังโปรแกรมฝั่งเซิร์ฟเวอร์มีปัญหา: {e}")
