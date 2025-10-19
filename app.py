import streamlit as st
import json
from google.cloud import vision
from google.oauth2 import service_account

st.title("📷 Road Vision (안전 버전)")

# --- Google Vision 인증 ---
service_account_info = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
credentials = service_account.Credentials.from_service_account_info(service_account_info)
client = vision.ImageAnnotatorClient(credentials=credentials)

# --- 이미지 업로드 ---
uploaded_file = st.file_uploader("이미지를 업로드하세요", type=["jpg", "jpeg", "png"])

if uploaded_file:
    image = vision.Image(content=uploaded_file.read())
    response = client.text_detection(image=image)
    texts = response.text_annotations

    if texts:
        st.subheader("📄 인식된 한글 텍스트:")
        st.write(texts[0].description)
    else:
        st.warning("텍스트를 찾지 못했습니다 😢")

if 'error' in locals():
    st.error("오류가 발생했습니다. API 키 또는 Secrets 설정을 확인하세요.")
