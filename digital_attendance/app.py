import streamlit as st
import pandas as pd
import qrcode
from PIL import Image
import os
from datetime import datetime, date
import cv2
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase
import time
import numpy as np

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

    img_path = ""
    if image_file:
        img = Image.open(image_file).convert("RGB")
        img_path = os.path.join("faces", f"{user_id}.jpg")
        img.save(img_path)

    qr_img = qrcode.make(user_id)
    qr_path = os.path.join("qrcodes", f"{user_id}.png")
    qr_img.save(qr_path)

    # append new user
    if os.path.exists(USER_CSV):
        df = pd.read_csv(USER_CSV)
    else:
        df = pd.DataFrame(columns=["user_id", "name", "roll_number", "branch", "image_path", "qr_path"])

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
# Slide-in popup message
# ==============================
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
        animation: slidein 2.5s cubic-bezier(.7,-0.27,.91,.17) forwards;
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
        submit_btn = st.form_submit_button("Submit")

    if submit_btn:
        if name.strip() and roll.strip() and branch.strip():
            qr_path, img_path, user_id, exists = save_user(name, roll, branch, image_file)
            st.session_state["last_popup"] = "duplicate" if exists else "success"
            st.image(qr_path, width=200)
            with open(qr_path, "rb") as f:
                st.download_button("📥 Download QR", f, os.path.basename(qr_path), mime="image/png", use_container_width=True)
        else:
            st.session_state["last_popup"] = "error"

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
            self.overlay_message = ""
            self.overlay_color = (255,255,255)
            self.message_timeout = 4  # seconds
            self.message_shown_time = 0
            self.current_user = None  # store current user info here (dict) for easy access in transform()

        def _draw_transparent_rect(self, img, x, y, w, h, color=(0,0,0), alpha=0.6):
            """Draw a filled, semi-transparent rectangle"""
            overlay = img.copy()
            cv2.rectangle(overlay, (x, y), (x+w, y+h), color, -1)
            cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

        def _put_text_multiline(self, img, lines, origin, line_height=24, font_scale=0.7, color=(255,255,255), thickness=1):
            x, y = origin
            for i, line in enumerate(lines):
                cv2.putText(img, line, (x, y + i*line_height), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)

        def transform(self, frame):
            image = frame.to_ndarray(format="bgr24")
            h, w, _ = image.shape

            data, bbox, _ = self.detector.detectAndDecode(image)

            # Draw QR bounding box
            if bbox is not None:
                pts = bbox.astype(int).reshape(-1,2)
                for i in range(len(pts)):
                    cv2.line(image, tuple(pts[i]), tuple(pts[(i+1)%len(pts)]), (0,255,0), 2)

            # Process QR code
            if data:
                user_id = data.strip()
                if user_id and user_id != self.last_id and (time.time() - self.last_time > 1.5):
                    user_info, status = mark_attendance(user_id)
                    # store info both in session_state and locally
                    st.session_state["user_info"] = user_info
                    st.session_state["last_popup"] = status
                    self.current_user = user_info

                    # Overlay message (short text)
                    if status == "success":
                        self.overlay_message = "✅ Attendance Marked"
                        self.overlay_color = (0,200,0)
                    elif status == "duplicate":
                        self.overlay_message = "⚠️ Already Marked"
                        self.overlay_color = (0,200,200)
                    elif status == "not_found":
                        self.overlay_message = "❌ User Not Found"
                        self.overlay_color = (0,0,200)

                    self.last_id = user_id
                    self.last_time = time.time()
                    self.message_shown_time = time.time()

            # Reset overlay after timeout
            if self.overlay_message and (time.time() - self.message_shown_time > self.message_timeout):
                self.overlay_message = ""
                self.overlay_color = (255,255,255)
                self.current_user = None

            # Draw overlay on video: status text at top-left
            if self.overlay_message:
                # background rounded-ish box for status
                txt = self.overlay_message
                (text_w, text_h), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)
                pad_x, pad_y = 20, 18
                box_w = text_w + pad_x*2
                box_h = text_h + pad_y
                box_x, box_y = 30, 30

                # semi-transparent rectangle for status
                self._draw_transparent_rect(image, box_x, box_y, box_w, box_h, color=self.overlay_color[::-1], alpha=0.8)
                # put status text (white)
                cv2.putText(image, txt, (box_x + pad_x, box_y + box_h - 8), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 2, cv2.LINE_AA)

                # draw user details box below status if user data exists
                user = self.current_user if self.current_user else st.session_state.get("user_info", None)
                if user:
                    # info box dimensions
                    info_w = 360
                    info_h = 120
                    info_x = box_x
                    info_y = box_y + box_h + 14

                    # background
                    self._draw_transparent_rect(image, info_x, info_y, info_w, info_h, color=(40,40,40), alpha=0.6)

                    # optional thumbnail
                    thumb_w = 100
                    thumb_h = 100
                    thumb_x = info_x + 10
                    thumb_y = info_y + 10
                    if user.get("image_path"):
                        try:
                            img_path = safe_str(user.get("image_path",""))
                            if img_path and os.path.exists(img_path):
                                thumb = cv2.imread(img_path)
                                if thumb is not None:
                                    thumb = cv2.resize(thumb, (thumb_w, thumb_h))
                                    # paste thumbnail onto image
                                    image[thumb_y:thumb_y+thumb_h, thumb_x:thumb_x+thumb_w] = thumb
                                else:
                                    # draw placeholder
                                    cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)
                            else:
                                cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)
                        except Exception as e:
                            cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)
                    else:
                        cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)

                    # text lines to the right of thumbnail
                    text_x = thumb_x + thumb_w + 14
                    text_y = thumb_y + 20
                    lines = [
                        f"Name: {user.get('name','')}",
                        f"Roll: {user.get('roll_number','')}",
                        f"Branch: {user.get('branch','')}",
                        f"ID: {user.get('user_id','')}"
                    ]
                    for i, line in enumerate(lines):
                        cv2.putText(image, line, (text_x, text_y + i*26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)

            return image

    webrtc_streamer(
        key="qrscan_hd",
        video_transformer_factory=QRScanner,
        media_stream_constraints={
            "video": {"width":{"ideal":1280},"height":{"ideal":720},"facingMode":"environment"},
            "audio": False
        },
        async_transform=True
    )

# ==============================
# Handle slide-in popup outside video
# ==============================
if st.session_state.get("last_popup"):
    popup = st.session_state["last_popup"]
    if popup == "success":
        slidein_message("✅ Attendance marked successfully!", "success")
    elif popup == "duplicate":
        slidein_message("⚠️ Already registered today!", "warning")
    elif popup == "not_found":
        slidein_message("❌ User not found!", "error")
    elif popup == "error":
        slidein_message("❌ Fill all fields!", "error")
    st.session_state["last_popup"] = ""  # reset

# ==============================
# Show user info in UI (beside video)
# ==============================
if choice=="Mark Attendance":
    user = st.session_state.get("user_info", None)
    if user:
        left, right = st.columns([2,1])
        with left:
            st.markdown("### 👤 User Details")
            st.write(f"**Name:** {user.get('name','')}")
            st.write(f"**Roll Number:** {user.get('roll_number','')}")
            st.write(f"**Branch:** {user.get('branch','')}")
            st.write(f"**User ID:** {user.get('user_id','')}")
        with right:
            img_path = safe_str(user.get("image_path",""))
            if img_path and os.path.exists(img_path):
                st.image(img_path, width=160)

# ==============================
# View Data
# ==============================
if choice=="View Data":
    st.header("📋 Registered Users")
    st.dataframe(pd.read_csv(USER_CSV))
    st.header("🕒 Attendance Records")
    st.dataframe(pd.read_csv(ATTENDANCE_CSV))
