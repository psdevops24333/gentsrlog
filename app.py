import streamlit as st, zipfile, json, io
import xml.etree.ElementTree as ET

# ฟังก์ชันแปลงหน่วย RAM เป็น GB
def f_ram(s):
    s = str(s).upper().replace('MB','').replace('BYTES','').replace(' ','')
    try:
        v = float(s)
        return f"{v/(1024**3):.0f} GB" if v > 1048576 else f"{v/1024:.0f} GB"
    except: return str(s)

# ฟังก์ชันแปลงหน่วย Disk เป็น GB / TB
def f_dsk(s):
    s = str(s).upper().replace('BYTES','').replace('B','').replace(' ','')
    try:
        v = float(s)
        if v > 1000**4: return f"{v/(1000**4):.2f} TB"
        if v > 1000**3: return f"{v/(1000**3):.0f} GB"
        if v > 1024**3: return f"{v/(1024**3):.0f} GB"
    except: pass
    return str(s)

def parse_tsr(up_file):
    ex = {}
    try:
        # เปิด ZIP และกวาดไฟล์
        with zipfile.ZipFile(up_file, 'r') as oz:
            fs = oz.namelist()
            izn = next((f for f in fs if f.lower().endswith('.zip')), None)
            tz = zipfile.ZipFile(io.BytesIO(oz.read(izn)), 'r') if izn else oz
            tfs = tz.namelist()
            jf = next((f for f in tfs if 'hardware_inventory.json' in f.lower() or 'hw_inventory.json' in f.lower()), None)
            xfs = [f for f in tfs if ('sysinfo_' in f.lower() and f.endswith('.xml')) or 'inventory.xml' in f.lower() or 'hw_inventory.xml' in f.lower()]

            def add_item(ad):
                id_ = ad.get("_ID_")
                if id_ and id_ not in ['PROPERTY', 'VALUE', 'ATTRIBUTE']:
                    if id_ not in ex: ex[id_] = ad
                    else: ex[id_].update(ad) # รวมร่างคุณสมบัติของอุปกรณ์ตัวเดียวกัน

            if jf:
                jd = json.loads(tz.read(jf).decode('utf-8', errors='ignore'))
                cs = jd.get("SystemInventory", jd).get("Component", [])
                if isinstance(cs, dict): cs = [cs]
                for c in cs:
                    ats = c.get("Attribute", [])
                    if isinstance(ats, dict): ats = [ats]
                    ad = {a.get("@Name", a.get("Name")).upper(): str(a.get("#text", a.get("Value", a.get("text")))).strip() for a in ats if a.get("@Name", a.get("Name"))}
                    ad["_ID_"] = c.get("@FQDD", c.get("FQDD", "")).upper()
                    add_item(ad)
                    
            if xfs:
                for f in xfs:
                    try:
                        rt = ET.fromstring(tz.read(f))
                        for el in rt.iter():
                            if '}' in el.tag: el.tag = el.tag.split('}', 1)[1]
                        for c in rt.iter():
                            ad = {k.upper(): str(v).strip() for k,v in c.attrib.items()}
                            for ch in c:
                                tg = ch.tag.upper()
                                na = ch.get('Name') or ch.get('NAME')
                                if tg in ['PROPERTY', 'ATTRIBUTE'] and na:
                                    ky = na.upper()
                                    vl = next((s.text.strip() for s in ch if s.tag.upper() == 'VALUE' and s.text), ch.text.strip() if ch.text else "")
                                    if vl: ad[ky] = vl
                                elif ch.text and ch.text.strip(): ad[tg] = ch.text.strip()
                            ad["_ID_"] = ad.get('INSTANCEID', ad.get('FQDD', ad.get('DEVICEID', c.tag))).upper()
                            add_item(ad)
                    except: pass

        si = {"Model": "-", "Service Tag": "-", "Hostname": "-", "IP iDRAC": "-"}
        cp, rm, dk, ct, nc = [], [], [], [], []
        
        # วนลูปสร้างตาราง (อิงตาม Slot จริง ห้ามตัดซ้ำ)
        for id_, ad in sorted(ex.items()):
            if 'SYSTEM' in id_ or 'BOARD' in id_:
                for k, n in [('MODEL','Model'), ('SERVICETAG','Service Tag'), ('HOSTNAME','Hostname')]:
                    if ad.get(k): si[n] = ad[k]
            elif 'IPV4' in id_ or 'IDRAC' in id_:
                ip = ad.get('CURRENTIPADDRESS', ad.get('ADDRESS'))
                if ip and ip not in ['0.0.0.0', '::', '127.0.0.1']: si['IP iDRAC'] = ip
                
            elif 'CPU' in id_:
                m = ad.get('MODEL', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '-')))
                if m != '-':
                    clk = f"{ad.get('CURRENTCLOCKSPEED','-')} (max {ad.get('MAXCLOCKSPEED','-')})"
                    cp.append({"Model": m, "Clock": clk, "Cores": ad.get('NUMBEROFPROCESSORCORES', ad.get('CORECOUNT', '-')), "Threads": ad.get('NUMBEROFENABLEDTHREADS', ad.get('THREADCOUNT', '-')), "L1": ad.get('PRIMARYCACHE', ad.get('L1CACHE', '-')), "L2": ad.get('SECONDARYCACHE', ad.get('L2CACHE', '-')), "L3": ad.get('TERTIARYCACHE', ad.get('L3CACHE', '-')), "Microcode": ad.get('MICROCODEVERSION', ad.get('MICROCODE', '-'))})
            
            elif 'DIMM' in id_ or 'MEMORY' in id_:
                sz = f_ram(ad.get('SIZE', ad.get('CAPACITY', '-')))
                if sz != '-':
                    rm.append({"Slot": ad.get('DEVICEDESCRIPTION', ad.get('NAME', id_.split(':')[-1])), "Capacity": sz, "Speed": ad.get('SPEED', ad.get('OPERATINGSPEED', '-')), "Manufacturer": ad.get('MANUFACTURER', '-'), "Part Number": ad.get('PARTNUMBER', '-'), "Serial Number": ad.get('SERIALNUMBER', '-')})
            
            elif 'DISK' in id_ or 'PHYSICALDISK' in id_:
                sz = f_dsk(ad.get('SIZE', ad.get('SIZEINBYTES', ad.get('CAPACITY', '-'))))
                if sz != '-':
                    slot = ad.get('FQDD', id_)
                    dk.append({"Slot": slot, "RAID State": ad.get('STATE', ad.get('RAIDSTATUS', '-')), "Vendor": ad.get('MANUFACTURER', ad.get('VENDORID', '-')), "Model": ad.get('MODEL', ad.get('PRODUCTID', '-')), "Size": sz, "Serial": ad.get('SERIALNUMBER', '-'), "SAS Address": ad.get('SASADDRESS', '-'), "Firmware": ad.get('REVISION', ad.get('FIRMWAREVERSION', '-'))})
            
            elif any(x in id_ for x in ['RAID', 'AHCI', 'CONTROLLER']):
                nm = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '-')))
                if nm != '-' and 'USB' not in nm.upper(): ct.append({"Device": nm, "Firmware": ad.get('FIRMWAREVERSION', '-'), "Driver": ad.get('DRIVERVERSION', '-')})
            
            elif 'NIC' in id_ or 'ETHERNET' in id_:
                nm = ad.get('PRODUCTNAME', ad.get('DEVICEDESCRIPTION', ad.get('NAME', '-')))
                if nm != '-': nc.append({"Device": nm, "MAC Address": ad.get('CURRENTMACADDRESS', ad.get('MACADDRESS', '-')), "Link Status": ad.get('LINKSTATUS', '-')})

        # เพิ่มคอลัมน์ Index อัตโนมัติ
        def add_idx(lst): return [{"Index": i+1, **d} for i, d in enumerate(lst)]

        return {
            "System Information": [{"Attribute": k, "Value": v} for k, v in si.items()],
            "Processors": add_idx(cp),
            "Memory": add_idx(rm),
            "Physical Disks": add_idx(dk),
            "Controller Cards": add_idx(ct),
            "Network Interfaces": add_idx(nc)
        }
    except Exception as e:
        st.error(f"Error: {e}")
        return {}

def exp_docx(pd):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    dc = Document()
    tp = dc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = tp.add_run("TSR Log Hardware Summary")
    tr.font.size = Pt(18); tr.font.bold = True; tr.font.color.rgb = RGBColor(26, 82, 118)
    for sn, rcs in pd.items():
        if not rcs: continue
        hd = dc.add_heading(sn, level=2)
        hd.runs[0].font.color.rgb = RGBColor(26, 82, 118)
        hs = list(rcs[0].keys())
        tb = dc.add_table(rows=1, cols=len(hs))
        tb.style = 'Table Grid'
        hc = tb.rows[0].cells
        for i, h in enumerate(hs):
            hc[i].text = str(h)
            hc[i].paragraphs[0].runs[0].font.bold = True
            hc[i].paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
            sh = OxmlElement('w:shd')
            sh.set(qn('w:val'), 'clear'); sh.set(qn('w:color'), 'auto'); sh.set(qn('w:fill'), "1A5276")
            hc[i]._tc.get_or_add_tcPr().append(sh)
        for rc in rcs:
            rc_cells = tb.add_row().cells
            for i, h in enumerate(hs): rc_cells[i].text = str(rc.get(h, ""))
        dc.add_paragraph()
    bf = io.BytesIO(); dc.save(bf); bf.seek(0)
    return bf

st.set_page_config(page_title="TSR Log Hardware Extractor", page_icon="🖥️", layout="wide")
st.title("🖥️ TSR Log Hardware Extractor")
st.subheader("ระบบแสดงผลสเปกเครื่องเชิงลึก (เทียบเท่า Dell HTML Report)")

uf = st.file_uploader("เลือกไฟล์ TSR Log (.zip)", type=["zip"])
if uf:
    with st.spinner("กำลังเจาะลึกข้อมูล Attributes ทั้งหมด..."):
        pd = parse_tsr(uf)
    if pd:
        for s, r in pd.items():
            if r:
                st.markdown(f"#### 🔹 {s}")
                st.dataframe(r, hide_index=True, use_container_width=True)
        st.write("---")
        if st.button("🔄 ส่งออกรายงานเป็น Word"):
            try:
                df = exp_docx(pd)
                stg = next((i['Value'] for i in pd.get("System Information", []) if i['Attribute'] == "Service Tag"), "Unknown")
                st.download_button("📥 ดาวน์โหลด Word", data=df, file_name=f"Summary_{stg}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            except Exception as e: st.error(f"Error: {e}")

# --- จบไฟล์ ---
