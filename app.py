import streamlit as st
from openai import OpenAI
import base64, re, json

# -------------------------
# 페이지 설정
# -------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown(
    "<h3 style='text-align:center; font-size:22px; margin-bottom:10px;'>🚗 도로주행 근무자동배정 (GPT OCR + 순번/차량/조퇴 통합 완전본)</h3>",
    unsafe_allow_html=True
)

# -------------------------
# OpenAI 초기화
# -------------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY가 설정되어 있지 않습니다.")
    st.stop()

MODEL_NAME = "gpt-4o"

# -------------------------
# 사이드바
# -------------------------
st.sidebar.header("순번 및 차량표 설정")

default_key_order = """권한솔
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
default_gyoyang_order = """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래"""
default_sudong_order = """권한솔
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

st.sidebar.text_area("열쇠 순번", default_key_order, key="key_order", height=160)
st.sidebar.text_area("교양 순번", default_gyoyang_order, key="gyoyang_order", height=160)
st.sidebar.text_area("1종 수동 순번", default_sudong_order, key="sudong_order", height=160)
st.sidebar.text_area("1종 수동 차량표", default_cha1, key="cha1", height=140)
st.sidebar.text_area("2종 자동 차량표", default_cha2, key="cha2", height=200)

prev_key = st.sidebar.text_input("전일 열쇠", value="")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value="")
prev_sudong = st.sidebar.text_input("전일 1종수동", value="")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)

st.sidebar.markdown("---")
absent_text = st.sidebar.text_area("휴가/교육자 (한 줄에 한 명)", height=100, value="")
repair_cars_text = st.sidebar.text_input("정비 차량 (쉼표로 구분, 예: 12호,6호)", value="")

excluded_set = set([x.strip() for x in absent_text.splitlines() if x.strip()])
repair_cars = [x.strip() for x in repair_cars_text.split(",") if x.strip()]

# -------------------------
# 유틸 함수
# -------------------------
def parse_list(text): return [t.strip() for t in text.splitlines() if t.strip()]
def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            car = parts[0]
            name = " ".join(parts[1:])
            m[name] = car
    return m

def get_vehicle(name, veh_map):
    """괄호 포함 이름 대응"""
    base = re.sub(r"\(.*?\)", "", name).strip()
    for key, val in veh_map.items():
        if re.sub(r"\s+", "", key) == re.sub(r"\s+", "", base):
            return val
    return ""

def format_name_with_car(name, veh_map):
    """이름 + 차량호수 + 괄호내용 (A합 등)"""
    car = get_vehicle(name, veh_map)
    mark = " (정비)" if car and car in repair_cars else ""
    note = ""
    m = re.search(r"\((.*?)\)", name)
    if m:
        note = m.group(1).replace("-", "").strip()
    base = re.sub(r"\(.*?\)", "", name).strip()
    if note:
        return f"{base}{(' ' + car) if car else ''} ({note}){mark}"
    else:
        return f"{base}{(' ' + car) if car else ''}{mark}"

def next_in_cycle(current, cycle):
    if not cycle: return None
    if current not in cycle: return cycle[0]
    return cycle[(cycle.index(current) + 1) % len(cycle)]

def next_valid_after(current, cycle, allowed_set):
    if not cycle: return None
    start = 0 if current not in cycle else (cycle.index(current) + 1) % len(cycle)
    for i in range(len(cycle)):
        cand = cycle[(start + i) % len(cycle)]
        if cand in allowed_set:
            return cand
    return None

def can_attend_period(name, period, early_leave_list):
    """조퇴 시간 이후 교시는 배정 불가"""
    time_map = {3: 13.0, 4: 14.5, 5: 16.0}
    leave_time = None
    for e in early_leave_list:
        if e["name"] in name:
            leave_time = e["time"]
            break
    if leave_time and leave_time <= time_map[period]:
        return False
    return True

# -------------------------
# GPT OCR 함수
# -------------------------
def gpt_extract_names_from_image(image_bytes, hint="도로주행"):
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system = "당신은 표에서 사람 이름을 추출하는 전문 도구입니다. 결과는 반드시 JSON으로만 반환해야 합니다."
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1️⃣ '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "2️⃣ 이미지 상단에 '조퇴 :' 문구가 있으면 조퇴자 이름과 시간을 추출하세요.\n"
        "   예: '조퇴 : 김병욱(14시~)' → {'name':'김병욱','time':14}\n"
        "3️⃣ 괄호 안 시간은 정수(14, 14.5 등)로 변환하여 JSON으로 반환하세요.\n"
        "4️⃣ 괄호 안이 '지원', '인턴', '연수' 중 하나인 경우 제외하세요.\n"
        "JSON 형식으로 반환:\n"
        '{"names":["김남균(A합)","김주현(B불)"],"early_leave":[{"name":"김병욱","time":14}]}'
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url","image_url":{"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
    except Exception as e:
        return [], [], f"GPT 호출 실패: {e}"

    try:
        raw = resp.choices[0].message.content
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        js = json.loads(m.group(0))
        names = js.get("names", [])
        early_leave = js.get("early_leave", [])
        clean_names = []
        for n in names:
            if not isinstance(n, str): continue
            n2 = re.sub(r"-", "", n)
            n2 = re.sub(r"\s+", "", n2)
            if re.search(r"(지원|인턴|연수)", n2): continue
            clean_names.append(n2)
        return clean_names, early_leave, raw
    except Exception as e:
        return [], [], f"파싱 실패: {e}"

# -------------------------
# UI
# -------------------------
st.markdown("<h4 style='font-size:18px; margin-top:10px;'>1️⃣ 근무표 이미지 업로드</h4>", unsafe_allow_html=True)
morning_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="morning")
afternoon_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="afternoon")

if st.button("🧠 GPT로 이름 추출"):
    if not morning_file and not afternoon_file:
        st.warning("오전 또는 오후 이미지를 업로드하세요.")
    else:
        with st.spinner("GPT 분석 중..."):
            if morning_file:
                m_names, _, _ = gpt_extract_names_from_image(morning_file.read(), "오전 도로주행")
                st.session_state.m_names = m_names
                st.success(f"오전 인식: {len(m_names)}명")
            if afternoon_file:
                a_names, early_leave, _ = gpt_extract_names_from_image(afternoon_file.read(), "오후 도로주행")
                st.session_state.a_names = a_names
                st.session_state.early_leave = early_leave
                st.success(f"오후 인식: {len(a_names)}명 (조퇴 {len(early_leave)}명)")
        st.rerun()

# -------------------------
# 인식 결과 확인
# -------------------------
st.markdown("<h4 style='font-size:18px; margin-top:10px;'>2️⃣ 인식 결과 확인 (필요시 수정)</h4>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("오전 근무자")
    morning_txt = "\n".join(st.session_state.get("m_names", []))
    morning_final = st.text_area("오전 최종", value=morning_txt, height=150)
with col2:
    st.subheader("오후 근무자")
    afternoon_txt = "\n".join(st.session_state.get("a_names", []))
    afternoon_final = st.text_area("오후 최종", value=afternoon_txt, height=150)

morning_list = [x.strip() for x in morning_final.splitlines() if x.strip()]
afternoon_list = [x.strip() for x in afternoon_final.splitlines() if x.strip()]
early_leave_list = st.session_state.get("early_leave", [])

# -------------------------
# 오전 배정
# -------------------------
st.markdown("<h4 style='font-size:18px; margin-top:10px;'>3️⃣ 오전 근무 배정 생성</h4>", unsafe_allow_html=True)
if st.button("📋 오전 근무 배정 생성"):
    present_m = set(morning_list) - excluded_set
    all_allowed = set(st.session_state.key_order.splitlines()) - excluded_set
    today_key = next_valid_after(prev_key, st.session_state.key_order.splitlines(), all_allowed)
    gy_start = next_in_cycle(prev_gyoyang5, st.session_state.gyoyang_order.splitlines())
    gy_candidates = [x for x in st.session_state.gyoyang_order.splitlines() if x in present_m]
    gy1 = gy_candidates[0] if len(gy_candidates) > 0 else "-"
    gy2 = gy_candidates[1] if len(gy_candidates) > 1 else "-"
    sudong_assigned = [x for x in st.session_state.sudong_order.splitlines() if x in present_m][:sudong_count]
    morning_2jong = [x for x in morning_list if x not in sudong_assigned]

    lines = [f"📅 오전 배정", f"열쇠: {today_key}", f"교양 1교시: {gy1}", f"교양 2교시: {gy2}"]
    for nm in sudong_assigned:
        lines.append(f"1종수동: {format_name_with_car(nm, parse_vehicle_map(st.session_state.cha1))}")
    lines.append("2종 자동:")
    for nm in morning_2jong:
        lines.append(f" - {format_name_with_car(nm, parse_vehicle_map(st.session_state.cha2))}")

    st.code("\n".join(lines), language="text")
    st.download_button("📥 오전 결과 다운로드", "\n".join(lines).encode("utf-8-sig"), file_name="오전근무배정.txt")

# -------------------------
# 오후 배정 (조퇴 반영)
# -------------------------
st.markdown("<h4 style='font-size:18px; margin-top:10px;'>4️⃣ 오후 근무 배정 생성</h4>", unsafe_allow_html=True)
if st.button("📋 오후 근무 배정 생성"):
    present_a = set(afternoon_list) - excluded_set
    all_allowed = set(st.session_state.key_order.splitlines()) - excluded_set
    afternoon_key = next_valid_after(prev_key, st.session_state.key_order.splitlines(), all_allowed)
    aft_gy_candidates = [x for x in st.session_state.gyoyang_order.splitlines() if x in present_a]

    gy3, gy4, gy5 = None, None, None
    used = set()
    for cand in aft_gy_candidates:
        if not gy3 and can_attend_period(cand, 3, early_leave_list):
            gy3, used = cand, used | {cand}
            continue
        if not gy4 and cand not in used and can_attend_period(cand, 4, early_leave_list):
            gy4, used = cand, used | {cand}
            continue
        if not gy5 and cand not in used and can_attend_period(cand, 5, early_leave_list):
            gy5, used = cand, used | {cand}
            continue
        if gy3 and gy4 and gy5:
            break

    lines = [
        "📅 오후 배정",
        f"열쇠: {afternoon_key}",
        f"교양 3교시: {gy3 or '-'}",
        f"교양 4교시: {gy4 or '-'}",
        f"교양 5교시: {gy5 or '-'}",
    ]

    if early_leave_list:
        lines.append("조퇴자:")
        for e in early_leave_list:
            lines.append(f" - {e['name']}({int(e['time'])}시~)")

    st.code("\n".join(lines), language="text")
    st.download_button("📥 오후 결과 다운로드", "\n".join(lines).encode("utf-8-sig"), file_name="오후근무배정.txt")
