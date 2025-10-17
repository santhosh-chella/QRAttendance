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

    # Ensure unique roll number
    if int(roll) in df["roll_number"].values:
        row = df[df["roll_number"] == int(roll)].iloc[0]
        return row["qr_path"], row["image_path"], row["user_id"], True

    img_path = ""
    if image_file:
        img = Image.open(image_file).convert("RGB")
        img_path = os.path.join("faces", f"{user_id}.jpg")
        img.save(img_path)

    qr_img = qrcode.make(user_id)
    qr_path = os.path.join("qrcodes", f"{user_id}.png")
    qr_img.save(qr_path)

    new_row = {
        "user_id": user_id,
        "name": name,
        "roll_number": int(roll),
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
    color_map = {
        "success": "#22bb33",
        "warning": "#ffcc00",
        "error": "#ff4444",
        "info": "#007bff"
    }
    bg_color = color_map.get(type_, "#007bff")
    css = f"""
    <style>
    .custom-slidein {{
        position: fixed;
        top: 8vh;
        right: 2vw;
        left: 2vw;
        z-index: 9999;
        background: {bg_color};
        color: #fff;
        padding: 1rem 2rem;
        border-radius: 1em;
        font-size: 1.1rem;
        font-weight: 600;
        box-shadow: 0 5px 20px rgba(0,0,0,0.2);
        max-width: 96vw;
        word-wrap: break-word;
        text-align: left;
        animation: slidein 2.4s cubic-bezier(.25,.1,.25,1) forwards;
    }}
    @keyframes slidein {{
        0% {{ top: -80px; opacity: 0; }}
        10% {{ top: 8vh; opacity: 1; }}
        80% {{ top: 8vh; opacity: 1; }}
        100% {{ top: -80px; opacity: 0; }}
    }}
    @media (max-width: 600px) {{
        .custom-slidein {{
            font-size: 0.95rem;
            padding: 0.7rem 1rem;
            border-radius: 0.7em;
            text-align: center;
            max-width: 98vw;
        }}
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
        name = st.text_input("Name", "")
        roll = st.text_input("Roll Number", "")
        branch = st.text_input("Branch", "")
        image_file = st.file_uploader("Upload Face Image (Optional)", type=["jpg","jpeg","png"])
        submit_btn = st.form_submit_button("Submit")

    if submit_btn:
        if name.strip() and roll.strip() and branch.strip():
            if not roll.isdigit():
                st.session_state["last_popup"] = "error"
            else:
                qr_path, img_path, user_id, exists = save_user(name.strip(), roll.strip(), branch.strip(), image_file)
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
            self.current_user = None

        def _draw_transparent_rect(self, img, x, y, w, h, color=(0,0,0), alpha=0.6):
            overlay = img.copy()
            cv2.rectangle(overlay, (x, y), (x+w, y+h), color, -1)
            cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

        def transform(self, frame):
            image = frame.to_ndarray(format="bgr24")
            data, bbox, _ = self.detector.detectAndDecode(image)

            if bbox is not None:
                pts = bbox.astype(int).reshape(-1,2)
                for i in range(len(pts)):
                    cv2.line(image, tuple(pts[i]), tuple(pts[(i+1)%len(pts)]), (0,255,0), 2)

            if data:
                user_id = data.strip()
                if user_id and user_id != self.last_id and (time.time() - self.last_time > 1.5):
                    user_info, status = mark_attendance(user_id)
                    st.session_state["user_info"] = user_info
                    st.session_state["last_popup"] = status
                    self.current_user = user_info

                    if status == "success":
                        self.overlay_message = " Attendance Marked"
                        self.overlay_color = (0,200,0)
                    elif status == "duplicate":
                        self.overlay_message = " Already Marked"
                        self.overlay_color = (0,200,200)
                    elif status == "not_found":
                        self.overlay_message = " User Not Found"
                        self.overlay_color = (0,0,200)

                    self.last_id = user_id
                    self.last_time = time.time()
                    self.message_shown_time = time.time()

            if self.overlay_message and (time.time() - self.message_shown_time > self.message_timeout):
                self.overlay_message = ""
                self.overlay_color = (255,255,255)
                self.current_user = None

            
            # ==============================
            # Responsive Overlay + User Info
            # ==============================
            if self.overlay_message:
                txt = self.overlay_message
                frame_h, frame_w = image.shape[:2]

                # scale factor based on video width (1280px reference)
                scale = frame_w / 1280

                # status box text size & padding
                font_scale = 1.0 * scale
                thickness = max(int(3 * scale), 1)
                (text_w, text_h), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
                pad_x, pad_y = int(20 * scale), int(18 * scale)

                # status box position
                box_w = text_w + pad_x * 2
                box_h = text_h + pad_y
                box_x = int(30 * scale)
                box_y = int(30 * scale)

                # draw status background
                self._draw_transparent_rect(image, box_x, box_y, box_w, box_h, color=self.overlay_color[::-1], alpha=0.8)
                # draw status text
                cv2.putText(image, txt, (box_x + pad_x, box_y + box_h - int(8*scale)),
                            cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255,255,255), thickness, cv2.LINE_AA)

                # draw user info box below status if user exists
                user = self.current_user if self.current_user else st.session_state.get("user_info", None)
                if user:
                    # user info text lines
                    lines = [
                        f"Name: {user.get('name','')}",
                        f"Roll: {user.get('roll_number','')}",
                        f"Branch: {user.get('branch','')}",
                        f"ID: {user.get('user_id','')}"
                    ]

                    # thumbnail size & position
                    thumb_w = int(100 * scale)
                    thumb_h = int(100 * scale)
                    thumb_x = box_x + int(10 * scale)
                    thumb_y = box_y + box_h + int(14 * scale)

                    # compute max text width
                    text_font_scale = 0.7 * scale
                    text_thickness = max(int(2 * scale), 1)
                    max_text_w = max(cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, text_font_scale, text_thickness)[0][0] for line in lines)

                    # info box dimensions
                    info_w = thumb_w + int(14*scale) + max_text_w + int(10*scale)  # thumbnail + gap + text + padding
                    info_h = max(thumb_h + int(20*scale), int(len(lines)*26*scale + 10*scale))  # enough for all text
                    info_x = box_x
                    info_y = thumb_y - int(10*scale)

                    # draw info box background
                    self._draw_transparent_rect(image, info_x, info_y, info_w, info_h, color=(40,40,40), alpha=0.6)

                    # draw thumbnail
                    if user.get("image_path"):
                        try:
                            img_path = safe_str(user.get("image_path",""))
                            if img_path and os.path.exists(img_path):
                                thumb = cv2.imread(img_path)
                                if thumb is not None:
                                    thumb = cv2.resize(thumb, (thumb_w, thumb_h))
                                    image[thumb_y:thumb_y+thumb_h, thumb_x:thumb_x+thumb_w] = thumb
                                else:
                                    cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)
                            else:
                                cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)
                        except:
                            cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)
                    else:
                        cv2.rectangle(image, (thumb_x, thumb_y), (thumb_x+thumb_w, thumb_y+thumb_h), (120,120,120), 2)

                    # draw text to right of thumbnail
                    text_x = thumb_x + thumb_w + int(14*scale)
                    text_y = thumb_y + int(20*scale)
                    line_height = int(26*scale)

                    for i, line in enumerate(lines):
                        # wrap text if too long
                        max_width = info_w - (thumb_w + int(14*scale) + int(10*scale))
                        wrapped_lines = []
                        words = line.split(" ")
                        current_line = ""
                        for word in words:
                            test_line = (current_line + " " + word).strip()
                            w, _ = cv2.getTextSize(test_line, cv2.FONT_HERSHEY_SIMPLEX, text_font_scale, text_thickness)[0]
                            if w <= max_width:
                                current_line = test_line
                            else:
                                wrapped_lines.append(current_line)
                                current_line = word
                        wrapped_lines.append(current_line)

                        # draw wrapped lines
                        for j, wline in enumerate(wrapped_lines):
                            y_pos = text_y + (i*len(wrapped_lines) + j)*line_height
                            cv2.putText(image, wline, (text_x, y_pos), cv2.FONT_HERSHEY_SIMPLEX,
                                        text_font_scale, (255,255,255), text_thickness, cv2.LINE_AA)

            return image

    webrtc_streamer(
        key="qrscan_hd",
        video_transformer_factory=QRScanner,
        media_stream_constraints={"video":{"width":{"ideal":1280},"height":{"ideal":720},"facingMode":"environment"},"audio":False},
        async_transform=True
    )

# ==============================
# Slide-in popup handler
# ==============================
if st.session_state.get("last_popup"):
    popup = st.session_state["last_popup"]
    if popup == "success":
        slidein_message("✔ Registered Successfully!", "success")
    elif popup == "duplicate":
        slidein_message("! User already registered!", "warning")
    elif popup == "not_found":
        slidein_message("X User not found!", "error")
    elif popup == "error":
        slidein_message("⚠ Fill all fields correctly!", "error")
    st.session_state["last_popup"] = ""  # reset

# ==============================
# Show user info in UI
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
