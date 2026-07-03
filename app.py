"""
Ingress Data Visualizer — entry point.
ZIP + password stored in browser IndexedDB via st.components.v2.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json

import pyzipper
import streamlit as st

st.set_page_config(page_title="Ingress Viz", page_icon="📡", layout="wide")

# ── init ──────────────────────────────────────────────────────

for k, v in {
    "source_loaded": False, "source_id": "", "source_name": "", "data": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── ZIP loader ────────────────────────────────────────────────

def do_load(zip_b64: str, password: str, fname: str, fsize: int):
    from data_loader import parse_archive
    sid = hashlib.sha256(f"{fname}{fsize}{password}".encode()).hexdigest()[:12]

    try:
        raw = base64.b64decode(zip_b64)
        archive_files: dict[str, bytes] = {}
        with pyzipper.AESZipFile(io.BytesIO(raw)) as zf:
            zf.setpassword(password.encode("utf-8"))
            for info in zf.infolist():
                if not info.is_dir():
                    archive_files[info.filename] = zf.read(info)
        st.session_state.data = parse_archive(archive_files, sid)
        st.session_state.source_loaded = True
        st.session_state.source_id = sid
        st.session_state.source_name = fname
    except Exception as e:
        st.error(f"Failed: {e}")


# ── v2 component: IndexedDB manager ───────────────────────────

IDB_JS = """
const DB = 'ingress_viz2', STORE = 'sources';
let db;

  const CSS = `
:host { display:block; max-width:600px; margin:0 auto; color:#262730; }
.row { display:flex; align-items:center; justify-content:space-between; padding:10px 14px;
       margin:4px 0; background:#f8f9fa; border-radius:8px; border:1px solid #e0e0e0; }
.row:hover { border-color:#c0c0c0; }
.name { font-weight:600; font-size:13px; }
.meta { font-size:11px; color:#888; margin-top:2px; }
.btns { display:flex; gap:6px; flex-shrink:0; }
button { border:none; border-radius:5px; cursor:pointer; font-size:12px; font-weight:600; }
.btn-load { padding:6px 16px; background:#4CAF50; color:#fff; }
.btn-del { padding:6px 9px; background:#e53935; color:#fff; }
.empty { color:#aaa; text-align:center; padding:20px 0; font-size:12px; line-height:1.6; }
.saved-title { font-size:13px; font-weight:600; color:#555; margin:0 0 8px; }
.from { margin-top:16px; padding-top:16px; border-top:1px solid #e0e0e0; }
.from label { display:block; font-size:12px; color:#555; margin:6px 0 4px; font-weight:600; }
.from input[type=file] { display:block; width:100%; font-size:13px; }
.from input[type=file]::file-selector-button { padding:5px 14px; background:#fff; border:1px solid #ccc; border-radius:5px; cursor:pointer; font-size:12px; margin-right:8px; }
.pwd-input { display:block; width:100%; margin:4px 0; padding:7px 10px; background:#fff; border:1px solid #ccc; border-radius:5px; color:#262730; font-size:13px; box-sizing:border-box; }
.pwd-input:focus { border-color:#4CAF50; outline:none; }
.btn-primary { display:block; width:100%; margin-top:8px; padding:8px 0; background:#4CAF50; color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:14px; font-weight:600; }
.btn-primary:disabled { opacity:0.4; cursor:default; }
.status { font-size:11px; color:#aaa; margin-top:6px; }
  `;

function openDB() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = e => { e.target.result.createObjectStore(STORE, {keyPath:'id'}); };
    r.onsuccess = e => { db = e.target.result; res(); };
    r.onerror = e => rej(e.target.error);
  });
}

function getAll() {
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE,'readonly');
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => res((req.result||[]).sort((a,b)=>(b.time||0)-(a.time||0)));
    req.onerror = e => rej(e.target.error);
  });
}

function putSource(s) {
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE,'readwrite');
    const req = tx.objectStore(STORE).put(s);
    req.onsuccess = () => res();
    req.onerror = e => rej(e.target.error);
  });
}

function delSource(id) {
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE,'readwrite');
    const req = tx.objectStore(STORE).delete(id);
    req.onsuccess = () => res();
    req.onerror = e => rej(e.target.error);
  });
}

function getSource(id) {
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE,'readonly');
    const req = tx.objectStore(STORE).get(id);
    req.onsuccess = () => res(req.result);
    req.onerror = e => rej(e.target.error);
  });
}

function blobToBase64(blob) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result.split(',')[1]);
    r.onerror = rej;
    r.readAsDataURL(blob);
  });
}

function hashCode(s) { let h=0; for(let i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h|=0;} return h; }
function fmtTime(ts) { return ts ? new Date(ts).toLocaleString() : ''; }
function fmtSize(b) { return b>1e6 ? (b/1e6).toFixed(1)+'MB' : b>1024 ? (b/1024).toFixed(0)+'KB' : b+'B'; }

export default async function(component) {
  const { setTriggerValue } = component;
  const shadow = component.parentElement;
  await openDB();

  const style = document.createElement('style');
  style.textContent = CSS;
  shadow.appendChild(style);

  const root = document.createElement('div');
  shadow.appendChild(root);

  async function render() {
    const sources = await getAll();
    root.innerHTML = '';

    if (sources.length > 0) {
      const savedTitle = document.createElement('div');
      savedTitle.className = 'saved-title';
      savedTitle.textContent = 'Saved exports';
      root.appendChild(savedTitle);

      for (const s of sources) {
        const row = document.createElement('div');
        row.className = 'row';
        const info = document.createElement('div');
        info.className = 'info';
        const name = document.createElement('div');
        name.className = 'name';
        name.textContent = s.name || '';
        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.textContent = fmtSize(s.size) + ' · ' + fmtTime(s.time);
        info.appendChild(name);
        info.appendChild(meta);
        row.appendChild(info);
        const btns = document.createElement('div');
        btns.className = 'btns';
        const loadBtn = document.createElement('button');
        loadBtn.className = 'btn-load';
        loadBtn.textContent = 'Load';
        loadBtn.onclick = async () => {
          const full = await getSource(s.id);
          if (!full || !full.zip_blob) { alert('Source missing.'); return; }
          loadBtn.textContent = '...'; loadBtn.disabled = true;
          const b64 = await blobToBase64(full.zip_blob);
          setTriggerValue('load', JSON.stringify({
            name: s.name, zip_b64: b64, password: s.password, id: s.id,
          }));
        };
        btns.appendChild(loadBtn);
        const delBtn = document.createElement('button');
        delBtn.className = 'btn-del';
        delBtn.textContent = '✕';
        delBtn.onclick = async () => { if(confirm('Delete '+s.name+'?')){await delSource(s.id); render();} };
        btns.appendChild(delBtn);
        row.appendChild(btns);
        root.appendChild(row);
      }
    } else {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No saved exports yet. Import one below.';
      root.appendChild(empty);
    }

    // import form
    const from = document.createElement('div');
    from.className = 'from';
    const lbl = document.createElement('label');
    lbl.textContent = 'Import new export (.zip)';
    from.appendChild(lbl);
    const fileInput = document.createElement('input');
    fileInput.type = 'file'; fileInput.accept = '.zip';
    from.appendChild(fileInput);
    const pwdLabel = document.createElement('label');
    pwdLabel.textContent = 'Password';
    from.appendChild(pwdLabel);
    const pwdInput = document.createElement('input');
    pwdInput.className = 'pwd-input';
    pwdInput.type = 'password';
    pwdInput.placeholder = 'ZIP decryption password';
    from.appendChild(pwdInput);
    const saveBtn = document.createElement('button');
    saveBtn.className = 'btn-primary';
    saveBtn.textContent = 'Save & Load';
    saveBtn.onclick = async () => {
      const file = fileInput.files[0];
      const pwd = pwdInput.value;
      if (!file) { alert('Choose a ZIP file'); return; }
      if (!pwd) { alert('Enter password'); return; }
      saveBtn.textContent = 'Saving...'; saveBtn.disabled = true;
      const id = Math.abs(hashCode(file.name + file.size + Date.now())).toString(36);
      await putSource({id, name: file.name, password: pwd, size: file.size, time: Date.now(), zip_blob: file});
      const b64 = await blobToBase64(file);
      setTriggerValue('load', JSON.stringify({
        name: file.name, zip_b64: b64, password: pwd, id,
      }));
    };
    from.appendChild(saveBtn);
    const status = document.createElement('div');
    status.className = 'status';
    status.textContent = 'ZIP + password stored only in your browser.';
    from.appendChild(status);
    root.appendChild(from);
  }

  render();
}
"""

IDB_COMPONENT = st.components.v2.component("idb_manager", js=IDB_JS)


# ── source page ───────────────────────────────────────────────

def render_source_page():
    st.title("📡 Ingress Data Visualizer")
    st.markdown("Your ZIP + password are saved **in your browser**. Server-side parsing stays in memory.")

    result = IDB_COMPONENT(key="idb_mgr", on_load_change=lambda: None)

    if result.load:
        try:
            payload = json.loads(result.load)
            zip_b64 = payload.get("zip_b64")
            password = payload.get("password")
            name = payload.get("name", "export.zip")
            if zip_b64 and password:
                with st.spinner(f"Decrypting & parsing {name}..."):
                    do_load(zip_b64, password, name, 0)
                if st.session_state.source_loaded:
                    st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")

    st.caption("Server-side processing stays in memory — nothing written to server disk.")


def _switch_source():
    for k in ["source_loaded", "source_id", "source_name", "data", "load_now"]:
        st.session_state[k] = None
    st.session_state.pop("_map_cache", None)
    st.session_state.pop("_game_log_cache", None)


# ── main flow ─────────────────────────────────────────────────

if not st.session_state.source_loaded:
    render_source_page()
else:
    pg = st.navigation({
        "Dashboard": [
            st.Page("views/1_Overview.py", title="Overview", icon="📊"),
            st.Page("views/2_Map.py", title="Map", icon="🗺️"),
            st.Page("views/3_Activity.py", title="Activity", icon="📈"),
            st.Page("views/4_Badges.py", title="Badges", icon="🏅"),
            st.Page("views/5_Economy.py", title="Economy", icon="💰"),
            st.Page("views/6_Events.py", title="Events", icon="🎯"),
            st.Page("views/7_Game_Log.py", title="Game Log", icon="🧾"),
            st.Page("views/8_History.py", title="History", icon="📚"),
        ],
    })
    pg.run()
    st.sidebar.button("🔄 Switch source", on_click=_switch_source, width="stretch")
