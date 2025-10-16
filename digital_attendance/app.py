import streamlit as st
import pandas as pd
import qrcode
from PIL import Image
import os
from datetime import datetime, date
import cv2
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase
import numpy as np
import time
import base64

# ==============================
# Setup directories & CSV files
# ==============================
USER_CSV = "users.csv"
ATTENDANCE_CSV = "attendance.csv"
os.makedirs("faces", exist_ok=True)
os.makedirs("qrcodes", exist_ok=True)

def init_csv(path, columns):
    if not os.path.exists(path):
        pd.DataFrame(columns=columns).to_csv(path, index=False)

init_csv(USER_CSV, ["user_id", "name", "roll_number", "branch", "image_path", "qr_path"])
init_csv(ATTENDANCE_CSV, ["user_id", "name", "roll_number", "branch", "image_path", "date", "timestamp"])

# ==============================
# Helper Functions
# ==============================
def safe_str(value):
    return str(value) if pd.notna(value) else ""

def save_user(name, roll, branch, image_file):
    user_id = f"{roll}_{name}".replace(" ", "_")
    df = pd.read_csv(USER_CSV)

    if user_id in df["user_id"].values:
        row = df[df["user_id"] == user_id].iloc[0]
        return row["qr_path"], row["image_path"], user_id, True

    # Save face image
    img_path = ""
    if image_file:
        img = Image.open(image_file).convert("RGB")
        img_path = os.path.join("faces", f"{user_id}.jpg")
        img.save(img_path)

    # Generate QR code
    qr_img = qrcode.make(user_id)
    qr_path = os.path.join("qrcodes", f"{user_id}.png")
    qr_img.save(qr_path)

    new_row = {
        "user_id": user_id,
        "name": name,
        "roll_number": roll,
        "branch": branch,
        "image_path": img_path,
        "qr_path": qr_path
    }
    df.loc[len(df)] = new_row
    df.to_csv(USER_CSV, index=False)
    return qr_path, img_path, user_id, False

def mark_attendance(user_id):
    df_users = pd.read_csv(USER_CSV)
    df_att = pd.read_csv(ATTENDANCE_CSV)
    user = df_users[df_users["user_id"] == user_id]

    if user.empty:
        return None, "not_found"

    user_info = user.iloc[0].to_dict()
    today = date.today().strftime("%Y-%m-%d")
    already = ((df_att["user_id"] == user_id) & (df_att["date"] == today)).any()
    if already:
        return user_info, "duplicate"

    now = datetime.now().strftime("%H:%M:%S")
    new_entry = {
        "user_id": user_id,
        "name": user_info["name"],
        "roll_number": user_info["roll_number"],
        "branch": user_info["branch"],
        "image_path": safe_str(user_info.get("image_path", "")),
        "date": today,
        "timestamp": now
    }
    df_att.loc[len(df_att)] = new_entry
    df_att.to_csv(ATTENDANCE_CSV, index=False)
    return user_info, "success"

# ==============================
# Buzzer Sound (base64 WAV)
# ==============================
BUZZER_WAV_BASE64 = """
UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YYwAAAD/////4P/g/8AA/wAA
AAAAAAAwAADAAADAAPAAwADwAPAAgADAAwADwAMAA8ADwAPgA8ADwA+AA8ADwAPgA8ADwA+AA8ADw
APgA8APwA8ADwAPwA/AAgADwAPgA8ADwAP4A/AAgADwA+AA8AAwAA8ADwAPAAPgA8ADwAPwAPAAgA
DPAA8ADwAPAAPgA8ADwAPgA8ADwAPwA+AA8ADwAPgA8APgA8ADwAPgA8ADwAPgA8AAPgA8ADwAPwA
""".replace("\n", "")

def play_buzzer():
    audio_bytes = base64.b64decode(BUZZER_WAV_BASE64)
    st.audio(audio_bytes, format="audio/wav")

# ==============================
# Streamlit UI Setup
# ==============================
st.set_page_config(page_title="Digital Attendance", page_icon="🧾", layout="wide")
st.title("🧾 Digital Attendance System")

menu = ["Register User", "Mark Attendance", "View Data"]
choice = st.sidebar.radio("Select Option", menu)

if "user_info" not in st.session_state:
    st.session_state["user_info"] = None
if "last_popup" not in st.session_state:
    st.session_state["last_popup"] = ""

def slidein_message(msg, type_="info"):
    css = f"""
        <style>
        .custom-slidein {{
            position: fixed;
            top: 80px;
            right: -400px;
            z-index: 9001;
            background: {'#22bb33' if type_=='success' else '#ffcc00' if type_=='warning' else '#ff5555' if type_=='error' else '#007bff'};
            color: white;
            padding: 1rem 2.5rem 1rem 1.5rem;
            border-radius: 8px;
            font-size: 1.1rem;
            font-weight: bold;
            box-shadow: 0 5px 18px 0 rgba(0,0,0,0.15);
            animation: slidein 10.5s cubic-bezier(.7,-0.27,.91,.17) forwards;
        }}
        @keyframes slidein {{
        0% {{ right: -400px; opacity: 0; }}
        17% {{ right: 36px; opacity: .86; }}
        90% {{ right: 36px; opacity: .86; }}
        100% {{right: -400px; opacity: 0; }}
        }}
        </style>
        <div class="custom-slidein">{msg}</div>
    """
    st.markdown(css, unsafe_allow_html=True)

# ==============================
# Register User
# ==============================
if choice == "Register User":
    st.header("👤 Register New User")
    with st.form("register_form", clear_on_submit=True):
        name = st.text_input("Name")
        roll = st.text_input("Roll Number")
        branch = st.text_input("Branch")
        image_file = st.file_uploader("Upload Face Image (Optional)", type=["jpg","jpeg","png"])
        submit_btn = st.form_submit_button("Register")

    if submit_btn:
        if name.strip() and roll.strip() and branch.strip():
            qr_path, img_path, user_id, exists = save_user(name, roll, branch, image_file)
            if exists:
                slidein_message("⚠️ User already registered.", type_="warning")
            else:
                slidein_message("✅ User registered successfully!", type_="success")

            st.image(qr_path, width=200)
            with open(qr_path, "rb") as f:
                st.download_button(
                    label="📥 Download QR",
                    data=f,
                    file_name=os.path.basename(qr_path),
                    mime="image/png",
                    use_container_width=True
                )
        else:
            slidein_message("❌ Fill all fields: Name, Roll, Branch.", type_="error")

# ==============================
# Mark Attendance
# ==============================
elif choice == "Mark Attendance":
    st.header("📸 Mark Attendance")
    st.info("Allow camera permission for best quality.")

    class QRScanner(VideoTransformerBase):
        def __init__(self):
            self.detector = cv2.QRCodeDetector()
            self.last_id = None
            self.last_time = time.time()

        def transform(self, frame):
            image = frame.to_ndarray(format="bgr24")
            data, bbox, _ = self.detector.detectAndDecode(image)
            # Draw QR bounding box
            if bbox is not None:
                pts = bbox.astype(int).reshape(-1, 2)
                for i in range(len(pts)):
                    cv2.line(image, tuple(pts[i]), tuple(pts[(i+1)%len(pts)]), (0,255,0), 2)
            # Process detected QR code
            if data:
                user_id = data.strip()
                if user_id and user_id != self.last_id and (time.time()-self.last_time>1.5):
                    user_info, status = mark_attendance(user_id)
                    st.session_state["user_info"] = user_info
                    st.session_state["last_popup"] = status
                    if status == "success":
                        play_buzzer()
                    self.last_id = user_id
                    self.last_time = time.time()
            return image

    webrtc_streamer(
        key="qrscan_hd",
        video_transformer_factory=QRScanner,
        media_stream_constraints={
            "video": {"width":{"ideal":1280}, "height":{"ideal":720}, "facingMode":"environment"},
            "audio": False
        },
        async_transform=True
    )

    last_popup = st.session_state.get("last_popup", "")
    if last_popup:
        if last_popup == "success":
            slidein_message("✅ Attendance marked successfully!", "success")
        elif last_popup == "duplicate":
            slidein_message("⚠️ Already registered today!", "warning")
        elif last_popup == "not_found":
            slidein_message("❌ User not found!", "error")

    user = st.session_state.get("user_info", None)
    if user:
        left, right = st.columns([2, 1])
        with left:
            st.write(f"**Name:** {user.get('name','')}")
            st.write(f"**Roll Number:** {user.get('roll_number','')}")
            st.write(f"**Branch:** {user.get('branch','')}")
        with right:
            img_path = safe_str(user.get("image_path",""))
            if img_path and os.path.exists(img_path):
                st.image(img_path, width=160)

# ==============================
# View Data
# ==============================
elif choice == "View Data":
    st.header("📋 Registered Users")
    st.dataframe(pd.read_csv(USER_CSV))
    st.header("🕒 Attendance Records")
    st.dataframe(pd.read_csv(ATTENDANCE_CSV))
