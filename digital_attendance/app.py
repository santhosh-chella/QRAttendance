# app.py
import streamlit as st
import pandas as pd
import qrcode
from PIL import Image
import os
from datetime import datetime, date
import cv2
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase

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

    # Duplicate detection
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

    # Add user to CSV
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
        return None, "❌ User not found!"

    user_info = user.iloc[0].to_dict()
    today = date.today().strftime("%Y-%m-%d")

    # Prevent duplicate attendance
    already = ((df_att["user_id"] == user_id) & (df_att["date"] == today)).any()
    if already:
        return user_info, "⚠️ Already registered today!"

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
    return user_info, "✅ Attendance marked successfully!"

# ==============================
# Streamlit UI Setup
# ==============================
st.set_page_config(page_title="Digital Attendance", page_icon="🧾", layout="wide")
st.title("🧾 Digital Attendance System ")

menu = ["Register User", "Mark Attendance", "View Data"]
choice = st.sidebar.radio("Select Option", menu)

if "user_info" not in st.session_state:
    st.session_state["user_info"] = None

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
                st.warning("⚠️ User already registered.")
            else:
                st.success("✅ User registered successfully!")

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
            st.error("❌ Fill all fields: Name, Roll, Branch.")

# ==============================
# Mark Attendance
# ==============================
elif choice == "Mark Attendance":
    st.header("📸 Mark Attendance ")
    st.info("Allow camera permission for best quality.")

    class QRScanner(VideoTransformerBase):
        def __init__(self):
            self.detector = cv2.QRCodeDetector()
            self.last_id = None

        def transform(self, frame):
            image = frame.to_ndarray(format="bgr24")
            data, bbox, _ = self.detector.detectAndDecode(image)

            # Draw QR bounding box
            if bbox is not None:
                pts = bbox.astype(int).reshape(-1,2)
                for i in range(len(pts)):
                    cv2.line(image, tuple(pts[i]), tuple(pts[(i+1)%len(pts)]), (0,255,0), 2)

            # Process detected QR code
            if data:
                user_id = data.strip()
                if user_id and user_id != self.last_id:
                    user_info, msg = mark_attendance(user_id)
                    st.session_state["user_info"] = user_info
                    st.toast(msg)  # <-- Real popup notification
                    self.last_id = user_id

            return image

    # Launch camera with HD resolution
    webrtc_streamer(
        key="qrscan_hd",
        video_transformer_factory=QRScanner,
        media_stream_constraints={
            "video": {"width":{"ideal":1280}, "height":{"ideal":720}, "facingMode":"environment"},
            "audio": False
        },
        async_transform=True
    )

    # Show user info panel
    user = st.session_state.get("user_info", None)
    if user:
        left, right = st.columns([2,1])
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
