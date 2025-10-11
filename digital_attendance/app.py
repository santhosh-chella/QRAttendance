import os
import pandas as pd
import cv2
import qrcode
from datetime import datetime, date
from PIL import Image
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
import av
import streamlit as st
from queue import Queue, Empty

# ==============================
# Setup directories & files
# ==============================
USER_CSV = "users.csv"
ATTENDANCE_CSV = "attendance.csv"
os.makedirs("qrcodes", exist_ok=True)
os.makedirs("faces", exist_ok=True)

def init_csv(path, columns):
    if not os.path.exists(path):
        pd.DataFrame(columns=columns).to_csv(path, index=False)

init_csv(USER_CSV, ["user_id", "name", "roll_number", "branch", "image_path", "qr_path"])
init_csv(ATTENDANCE_CSV, ["user_id", "name", "roll_number", "branch", "image_path", "date", "timestamp"])

# ==============================
# Helper functions
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
    if "date" not in df_att.columns:
        df_att["date"] = ""
    user = df_users[df_users["user_id"] == user_id]
    if user.empty:
        return None, "❌ User not found!"
    user_info = user.iloc[0]
    today = date.today().strftime("%Y-%m-%d")
    already = ((df_att["user_id"] == user_id) & (df_att["date"] == today)).any()
    if already:
        return user_info, "⚠️ Already Registered Today!"
    now = datetime.now().strftime("%H:%M:%S")
    new_entry = {
        "user_id": user_id,
        "name": user_info["name"],
        "roll_number": user_info["roll_number"],
        "branch": user_info["branch"],
        "image_path": safe_str(user_info["image_path"]),
        "date": today,
        "timestamp": now
    }
    df_att.loc[len(df_att)] = new_entry
    df_att.to_csv(ATTENDANCE_CSV, index=False)
    return user_info, "✅ Attendance Marked Successfully!"

# ==============================
# Streamlit UI
# ==============================
st.set_page_config(page_title="Digital Attendance", page_icon="🧾", layout="wide")
st.title("🧾 Digital Attendance System")

menu = ["Register User", "Mark Attendance", "View Data"]
choice = st.sidebar.radio("Select Option", menu)

# ------------------------------
# 1️⃣ Register User
# ------------------------------
if choice == "Register User":
    st.header("👤 Register New User")
    submitted_user_data = None

    with st.form("register_form", clear_on_submit=True):
        name = st.text_input("Enter Name")
        roll = st.text_input("Enter Roll Number")
        branch = st.text_input("Enter Branch")
        image_file = st.file_uploader("Upload Face Image (Optional)", type=["jpg","jpeg","png","bmp","webp"])
        submit_btn = st.form_submit_button("Submit")
        if submit_btn:
            if name.strip() and roll.strip() and branch.strip():
                qr_path, img_path, user_id, exists = save_user(name, roll, branch, image_file)
                submitted_user_data = {
                    "qr_path": qr_path,
                    "img_path": img_path,
                    "user_id": user_id,
                    "exists": exists,
                    "name": name
                }
            else:
                st.error("⚠️ Please fill all required fields!")

    if submitted_user_data:
        if submitted_user_data["exists"]:
            st.warning(f"⚠️ User {submitted_user_data['name']} already registered!")
        else:
            st.success(f"✅ User {submitted_user_data['name']} registered successfully!")
        st.image(submitted_user_data["qr_path"], width=150)
        with open(submitted_user_data["qr_path"], "rb") as f:
            st.download_button("📥 Download QR Code", f, file_name=f"{submitted_user_data['user_id']}.png", mime="image/png")

# ------------------------------
# 2️⃣ Mark Attendance (Live QR Scanner)
# ------------------------------
elif choice == "Mark Attendance":
    st.header("📸 QR Code Scanner (Auto Camera Resolution)")

    if "qr_queue" not in st.session_state:
        st.session_state["qr_queue"] = Queue()

    detector = cv2.QRCodeDetector()
    scanned_set = set([u["user_id"] for u in st.session_state.get("scanned_users", [])])

    class QRCodeScanner(VideoProcessorBase):
        def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
            img = frame.to_ndarray(format="bgr24")
            # Optional: resize to small display frame to reduce lag in Streamlit
            display_img = cv2.resize(img, (320, 240))
            data, bbox, _ = detector.detectAndDecode(img)  # full resolution for detection
            if data:
                user_id = data.strip()
                if user_id not in scanned_set:
                    st.session_state["qr_queue"].put(user_id)
                    scanned_set.add(user_id)
            return av.VideoFrame.from_ndarray(display_img, format="bgr24")

    webrtc_streamer(
        key="scanner",
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=QRCodeScanner,
        media_stream_constraints={"video": True, "audio": False},  # use device native resolution
        async_processing=True,
    )

    if "scanned_users" not in st.session_state:
        st.session_state["scanned_users"] = []

    qr_container = st.container()

    while not st.session_state["qr_queue"].empty():
        try:
            user_id = st.session_state["qr_queue"].get_nowait()
            user_info, msg = mark_attendance(user_id)
            if user_info:
                st.session_state["scanned_users"].insert(0, {
                    "user_id": user_info["user_id"],
                    "name": user_info["name"],
                    "roll": user_info["roll_number"],
                    "branch": user_info["branch"],
                    "image": user_info["image_path"],
                    "msg": msg
                })
        except Empty:
            break

    # Display scanned users
    for user in st.session_state["scanned_users"]:
        container = qr_container.container()
        msg = user["msg"]
        if "✅" in msg:
            container.success(msg)
        elif "⚠️" in msg:
            container.warning(msg)
        elif "❌" in msg:
            container.error(msg)
        container.write(f"👤 Name: {user['name']}")
        container.write(f"**Roll Number:** {user['roll']}")
        container.write(f"**Branch:** {user['branch']}")
        if user["image"] and os.path.exists(user["image"]):
            container.image(user["image"], width=120)
        container.markdown("---")

# ------------------------------
# 3️⃣ View Data
# ------------------------------
elif choice == "View Data":
    st.header("📋 Registered Users")
    df_users = pd.read_csv(USER_CSV)
    st.dataframe(df_users)
    st.header("🕒 Attendance Records")
    df_att = pd.read_csv(ATTENDANCE_CSV)
    st.dataframe(df_att)
