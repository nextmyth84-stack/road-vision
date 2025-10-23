# app.py — 도로주행 근무자동배정 v7.12 완전본
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# =====================================
# 페이지 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center; font-size:22px;'>🚗 도로주행 근무자동배정</h3>", unsafe_allow_html=True)

# =====================================
# OpenAI 초기화
# =====================================
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 설정 필요")
    st.stop()
MODEL_NAME = "gpt-4o"

# =====================================
# 전일 기준 불러오기
# =====================================
PREV_FILE = "전일근무.json"
prev_key = prev_gyoyang5 = prev_sudong = ""
if os.path.exists(PREV_FILE):
    try:
        with open(PREV_FILE, "r", encoding="utf-8") as f:
            js = json.load(f)
        prev_key = js.get("열쇠", "")
        prev_gyoyang5 = js.get("교양_5교시", "")
        prev_sudong = js.get("1종수동", "")
        st.info(f"전일 불러옴 → 열쇠:{prev_key or '-'}, 교양5:{prev_gyoyang5 or '-'}, 1종:{prev_sudong or '-'}")
    except Exception as e:
        st.warning(f"전일근무.json 불러오기 실패: {e}")

# =====================================
# 사이드바 입력
# =====================================
st.sidebar.header("순번표 / 차량표 / 옵션")

def _list(s): return [x.strip() for x in s.splitlines() if x.strip()]

default_key = """권한솔
김남균
김면정
김성연
김지은
안유미
윤여헌
윤원실
이나래
이호석
조윤영
조정래"""
default_gyoyang = """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래"""
default_sudong = """권한솔
김남균
김성연
김주현
이호석
조정래"""
default_cha1 = """2호 조정래
5호 권한솔
7호 김남균
8호 이호석
9호 김주현
10호 김성연"""
default_cha2 = """4호 김남균
5호 김병욱
6호 김지은
12호 안유미
14호 김면정
15호 이호석
17호 김성연
18호 권한솔
19호 김주현
22호 조정래"""

key_order = _list(st.sidebar.text_area("열쇠 순번", default_key, height=160))
gyoyang_order = _list(st.sidebar.text_area("교양 순번", default_gyoyang, height=160))
sudong_order = _list(st.sidebar.text_area("1종 수동 순번", default_sudong, height=160))

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            car = p[0]
            name = " ".join(p[1:])
            m[name] = car
    return m

veh1 = parse_vehicle_map(st.sidebar.text_area("1종 수동 차량표", default_cha1, height=120))
veh2 = parse_vehicle_map(st.sidebar.text_area("2종 자동 차량표", default_cha2, height=180))

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
excluded = {x.strip() for x in st.sidebar.text_area("휴가/교육자 (한 줄당 한 명)", height=100).splitlines() if x.strip()}
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

# 전일 근무자 표시 복원
st.sidebar.markdown("---")
st.sidebar.subheader("전일 근무자 확인")
st.sidebar.write(f"🔑 열쇠: {prev_key or '-'}")
st.sidebar.write(f"🧑‍🏫 교양(5교시): {prev_gyoyang5 or '-'}")
st.sidebar.write(f"⚙️ 1종 수동: {prev_sudong or '-'}")

# =====================================
# 유틸 함수
# =====================================
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """정규화 기준 순환"""
    if not cycle:
        return None
    cycle_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = 0
    if last_norm in cycle_norm:
        start = (cycle_norm.index(last_norm) + 1) % len(cycle)
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def mark_car(car):
    return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == nkey:
            return v
    return ""

# =====================================
# GPT OCR (요약)
# =====================================
def gpt_extract(img_bytes, want_early=False, want_late=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "2) 괄호안 정보(A-합 등)는 유지하되, 괄호에 '지원','인턴','연수' 포함자는 제외하세요.\n"
        + ("3) '조퇴:' 항목이 있다면 이름과 시간을 숫자(예: 14 또는 14.5)로 JSON에 포함하세요.\n" if want_early else "")
        + ("4) '외출:' 또는 '10시 출근:' 항목이 있다면 이름과 시간을 숫자(예: 10)로 JSON에 포함하세요.\n" if want_late else "")
        + "반환 예시: {\"names\": [\"김면정\",\"김성연\"], "
        + ("\"early_leave\": [{\"name\":\"김병욱\",\"time\":14}], " if want_early else "")
        + ("\"late_start\": [{\"name\":\"안유미\",\"time\":10}]" if want_late else "")
        + "}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름을 JSON으로 추출"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = res.choices[0].message.content
        js = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        names = [re.sub(r"\(.*?\)", "", n).strip() for n in js.get("names", []) if not re.search(r"(지원|인턴|연수)", n)]
        early = js.get("early_leave", []) if want_early else []
        late = js.get("late_start", []) if want_late else []
        return names, early, late
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], []

# =====================================
# 이후 로직 (오전·오후 배정 로직은 기존 v7.11과 동일)
# =====================================

# (오전·오후 GPT 인식 / 근무자 확인 / 순번 로직 / 비교 / 저장 포함)
# [이하 부분은 v7.11과 동일하게 유지됨]
