import streamlit as st
from openai import OpenAI
import base64, re, json

# -------------------------
# 페이지 설정
# -------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown(
    "<h3 style='text-align:center; font-size:22px; margin-bottom:10px;'>🚗 도로주행 근무자동배정 (GPT OCR + 순번/차량 통합 완전본)</h3>",
    unsafe_allow_html=True
)

# -------------------------
# OpenAI 초기화 (GPT-4o 고정)
# -------------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY가 설정되어 있지 않습니다.")
    st.stop()

MODEL_NAME = "gpt-4o"

# -------------------------
# 사이드바 설정
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
10호 김성연
14호 김면정"""
default_cha2 = """4호 김남균
5호 김병욱
6호 김지은
12호 안유미
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
    """괄호 포함, 공백 포함 이름 대응"""
    name_clean = re.sub(r"\s+", "", name)
    if name_clean in veh_map:
        return veh_map[name_clean]
    base = re.sub(r"\(.*?\)", "", name_clean).strip()
    for key, val in veh_map.items():
        key_clean = re.sub(r"\s+", "", key)
        if key_clean == base:
            return val
    return ""

key_order = parse_list(st.session_state.key_order)
gyoyang_order = parse_list(st.session_state.gyoyang_order)
sudong_order = parse_list(st.session_state.sudong_order)
veh1 = parse_vehicle_map(st.session_state.cha1)
veh2 = parse_vehicle_map(st.session_state.cha2)

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

# -------------------------
# GPT OCR 함수
# -------------------------
def gpt_extract_names_from_image(image_bytes, hint="도로주행"):
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system = "당신은 표에서 사람 이름을 추출하는 전문 도구입니다. 결과는 반드시 JSON으로만 반환해야 합니다."
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "이미지에서 '학과', '기능장', '초소' 를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "이름 옆 괄호 안 내용(예: A-불, B-합 등)은 그대로 유지하되, 하이픈(-)은 제거해 'A합'처럼 붙여주세요.\n"
        "괄호 안이 '지원', '인턴', '연수' 중 하나인 경우 그 이름은 제외하세요.\n"
        "결과는 반드시 JSON 형식으로:\n"
        '{"names": ["김남균(A합)", "김주현(B불)", "권한솔", "김성연"], "notes": []}'
    )

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
    except Exception as e:
        return [], f"GPT 호출 실패: {e}"

    try:
        raw = resp.choices[0].message.content
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not m:
            return [], f"형식 오류: {raw}"
        js = json.loads(m.group(0))
        names = js.get("names", [])
        clean = []
        for n in names:
            if not isinstance(n, str):
                continue
            n2 = re.sub(r"-", "", n)
            n2 = re.sub(r"\s+", "", n2)  # 공백 제거
            n2 = re.sub(r"[^가-힣A-Za-z0-9\(\)]", "", n2)
            if re.search(r"(지원|인턴|연수)", n2):
                continue
            if 2 <= len(re.sub(r"[^가-힣]", "", n2)) <= 5:
                clean.append(n2)
        return clean, raw
    except Exception as e:
        return [], f"파싱 실패: {e}"

# -------------------------
# 1️⃣ 근무표 이미지 업로드
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
                m_names, _ = gpt_extract_names_from_image(morning_file.read(), "오전 도로주행")
                st.session_state.m_names = m_names
                st.success(f"오전 인식: {len(m_names)}명")
            if afternoon_file:
                a_names, _ = gpt_extract_names_from_image(afternoon_file.read(), "오후 도로주행")
                st.session_state.a_names = a_names
                st.success(f"오후 인식: {len(a_names)}명")
        st.rerun()

# -------------------------
# 2️⃣ 인식 결과 확인
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

# -------------------------
# 3️⃣ 오전 근무 배정 생성
# -------------------------
st.markdown("<h4 style='font-size:18px; margin-top:10px;'>3️⃣ 오전 근무 배정 생성</h4>", unsafe_allow_html=True)

if st.button("📋 오전 근무 배정 생성"):
    present_m = set(morning_list) - excluded_set
    all_allowed = set(key_order) - excluded_set
    today_key = next_valid_after(prev_key, key_order, all_allowed) if prev_key else next_valid_after(None, key_order, all_allowed) or key_order[0]

    gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order) if prev_gyoyang5 else gyoyang_order[0]
    gy_candidates = []
    cur = gy_start
    for _ in range(len(gyoyang_order)*2):
        if cur in present_m:
            gy_candidates.append(cur)
        if len(gy_candidates) >= 2:
            break
        cur = next_in_cycle(cur, gyoyang_order)
    gy1 = gy_candidates[0] if len(gy_candidates) >= 1 else ""
    gy2 = gy_candidates[1] if len(gy_candidates) >= 2 else ""

    sudong_assigned = []
    cur_s = prev_sudong if prev_sudong else sudong_order[0]
    for _ in range(len(sudong_order)*2):
        cand = next_in_cycle(cur_s, sudong_order)
        cur_s = cand
        if cand in present_m and cand not in sudong_assigned:
            sudong_assigned.append(cand)
        if len(sudong_assigned) >= sudong_count:
            break

    morning_2jong = [p for p in morning_list if p in present_m and p not in sudong_assigned]

    lines = [
        f"📅 오전 배정",
        f"열쇠: {today_key}",
        f"교양 1교시: {gy1}",
        f"교양 2교시: {gy2}",
    ]
    for nm in sudong_assigned:
    lines.append(f"1종수동: {format_name_with_car(nm, veh1)}")

    lines.append("2종 자동:")
    for nm in morning_2jong:
    lines.append(f" - {format_name_with_car(nm, veh2)}")


    st.session_state.morning_assigned_set = set(morning_list)
    st.session_state.morning_veh2_used = set([veh2.get(n, "") for n in morning_2jong if veh2.get(n, "")])

    result = "\n".join([ln for ln in lines if ln.strip()])
    st.code(result, language="text")
    st.download_button("📥 오전 결과 다운로드", data=result.encode("utf-8-sig"), file_name="오전근무배정.txt")


# -------------------------
# 4️⃣ 오후 근무 배정 생성
# -------------------------
st.markdown("<h4 style='font-size:18px; margin-top:10px;'>4️⃣ 오후 근무 배정 생성</h4>", unsafe_allow_html=True)

if st.button("📋 오후 근무 배정 생성"):
    present_a = set(afternoon_list) - excluded_set
    all_allowed = set(key_order) - excluded_set
    today_key = next_valid_after(prev_key, key_order, all_allowed) if prev_key else next_valid_after(None, key_order, all_allowed) or key_order[0]

    last_gy = prev_gyoyang5
    aft_gy_candidates = []
    curg = last_gy if last_gy else gyoyang_order[0]
    for _ in range(len(gyoyang_order)*2):
        curg = next_in_cycle(curg, gyoyang_order)
        if curg in present_a and curg not in aft_gy_candidates:
            aft_gy_candidates.append(curg)
        if len(aft_gy_candidates) >= 3:
            break
    gy3 = aft_gy_candidates[0] if len(aft_gy_candidates) >= 1 else ""
    gy4 = aft_gy_candidates[1] if len(aft_gy_candidates) >= 2 else ""
    gy5 = aft_gy_candidates[2] if len(aft_gy_candidates) >= 3 else ""

    aft_sudong = None
    curs2 = prev_sudong if prev_sudong else sudong_order[0]
    for _ in range(len(sudong_order)*2):
        cand = next_in_cycle(curs2, sudong_order)
        curs2 = cand
        if cand in present_a:
            aft_sudong = cand
            break

    aft_2jong = [p for p in afternoon_list if p in present_a and p != aft_sudong]

    lines = [
        f"📅 오후 배정",
        f"열쇠: {today_key}",
        f"교양 3교시: {gy3}",
        f"교양 4교시: {gy4}",
        f"교양 5교시: {gy5}",
    ]
    if aft_sudong:
        car = get_vehicle(aft_sudong, veh1)
        mark = " (정비)" if car and car in repair_cars else ""
        lines.append(f"1종수동 (오후): {aft_sudong}{(' ' + car) if car else ''}{mark}")
    lines.append("2종 자동:")
    aft_used_cars = set()
    for nm in aft_2jong:
        car = get_vehicle(nm, veh2)
        if car: aft_used_cars.add(car)
        mark = " (정비)" if car and car in repair_cars else ""
        lines.append(f" - {nm}{(' ' + car) if car else ''}{mark}")

    # 비교/점검
    morning_list_prev = st.session_state.get("morning_assigned_set", set())
    newbies = set(afternoon_list) - set(morning_list)
    missing = set(morning_list) - set(afternoon_list)
    all_veh2_cars = set(veh2.values())
    unassigned_cars = all_veh2_cars - aft_used_cars

    lines.append("\n🔎 비교/점검")
    if newbies: lines.append("• 신규 인원: " + ", ".join(sorted(newbies)))
    if missing: lines.append("• 누락 인원: " + ", ".join(sorted(missing)))
    if unassigned_cars:
        closed = sorted([c for c in unassigned_cars if c in repair_cars])
        free = sorted([c for c in unassigned_cars if c not in repair_cars])
        if free: lines.append("• 미배정 2종 차량: " + ", ".join(free))
        if closed: lines.append("• 정비 차량: " + ", ".join(closed))

    result = "\n".join([ln for ln in lines if ln.strip()])
    st.code(result, language="text")
    st.download_button("📥 오후 결과 다운로드", data=result.encode("utf-8-sig"), file_name="오후근무배정.txt")
