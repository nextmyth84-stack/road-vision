# app.py — 도로주행 근무자동배정 (GPT OCR + 순번/차량 통합, 오전·오후 분리)
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# -------------------------
# 페이지 설정
# -------------------------
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.title("🚗 도로주행 근무자동배정 (GPT OCR + 순번/차량 통합 개선버전)")

# -------------------------
# OpenAI 초기화
# -------------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception as e:
    st.error("⚠️ OPENAI_API_KEY가 없거나 접근 불가합니다.")
    st.stop()

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
sudong_count = st.sidebar.radio("1종 수동 인원수", [1,2], index=0)
model_name = st.sidebar.selectbox("GPT 모델", ["gpt-4o-mini", "gpt-4o"], index=0)

# -------------------------
# 파싱 함수
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

key_order = parse_list(st.session_state.key_order)
gyoyang_order = parse_list(st.session_state.gyoyang_order)
sudong_order = parse_list(st.session_state.sudong_order)
veh1 = parse_vehicle_map(st.session_state.cha1)
veh2 = parse_vehicle_map(st.session_state.cha2)

# -------------------------
# GPT OCR
# -------------------------
def gpt_extract_names_from_image(image_bytes, hint="도로주행"):
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    system = (
        "당신은 표에서 사람 이름을 추출하는 전문 도구입니다. "
        "항상 JSON 형식으로 응답해야 합니다."
    )
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "표의 **맨 왼쪽에 '도로주행'이라고 적힌 칸**에 있는 이름만 추출하세요.\n"
        "이름 옆 괄호 내용(예: A-불, B-합 등)은 그대로 유지합니다.\n"
        "단, 괄호 안이 '지원' 또는 '인턴'이면 그 이름은 제외하세요.\n"
        "반드시 아래 JSON 형식으로만 응답하세요:\n"
        '{"names": ["김남균(A-불)", "김주현(B-합)", "권한솔", "김성연"], "notes": []}'
    )

    try:
        resp = client.chat.completions.create(
            model=model_name,
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
            if not isinstance(n, str): continue
            n2 = re.sub(r"[^가-힣A-Za-z0-9\-\(\)]", "", n).strip()
            # '지원' 또는 '인턴' 제외
            if re.search(r"(지원|인턴)", n2):
                continue
            if 2 <= len(re.sub(r"[^가-힣]", "", n2)) <= 5:
                clean.append(n2)
        return clean, raw
    except Exception as e:
        return [], f"파싱 실패: {e}"

# -------------------------
# 이미지 업로드
# -------------------------
st.markdown("---")
st.header("1️⃣ 근무표 이미지 업로드")

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
# 인식 결과 확인
# -------------------------
st.markdown("---")
st.header("2️⃣ 인식 결과 확인 (필요시 수정)")

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
# 순번 계산
# -------------------------
def next_in_cycle(current, cycle):
    if not cycle: return None
    if current not in cycle: return cycle[0]
    return cycle[(cycle.index(current)+1) % len(cycle)]

# -------------------------
# 오전 배정 버튼
# -------------------------
st.markdown("---")
st.header("3️⃣ 오전 근무 배정 생성")

if st.button("📋 오전 근무 배정 생성"):
    if not morning_list:
        st.warning("오전 근무자 목록이 없습니다.")
    else:
        today_key = next_in_cycle(prev_key, key_order) if prev_key else key_order[0]
        gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order) if prev_gyoyang5 else gyoyang_order[0]

        gy_candidates = []
        cur = gy_start
        for _ in range(len(gyoyang_order)*2):
            if cur in morning_list: gy_candidates.append(cur)
            if len(gy_candidates) >= 2: break
            cur = next_in_cycle(cur, gyoyang_order)

        gy1 = gy_candidates[0] if gy_candidates else "-"
        gy2 = gy_candidates[1] if len(gy_candidates) >= 2 else "-"

        sudong_assigned = []
        cur_s = prev_sudong if prev_sudong else sudong_order[0]
        for _ in range(len(sudong_order)*2):
            cand = next_in_cycle(cur_s, sudong_order)
            cur_s = cand
            if cand in morning_list:
                sudong_assigned.append(cand)
            if len(sudong_assigned) >= sudong_count: break

        morning_2jong = [p for p in morning_list if p not in sudong_assigned]

        morning_lines = [
            f"📅 오전 배정",
            f"열쇠: {today_key}",
            f"교양 1교시: {gy1}",
            f"교양 2교시: {gy2}",
        ]
        for i, nm in enumerate(sudong_assigned, start=1):
            car = veh1.get(nm, "-")
            morning_lines.append(f"1종수동 #{i}: {nm} → {car}")
        morning_lines.append("2종 자동:")
        for nm in morning_2jong:
            car = veh2.get(nm, "-")
            morning_lines.append(f" - {nm} → {car}")

        result = "\n".join(morning_lines)
        st.text_area("오전 배정 결과", result, height=300)
        st.download_button("📥 오전 결과 다운로드", data=result.encode("utf-8-sig"),
                           file_name="오전근무배정.txt", mime="text/plain")

# -------------------------
# 오후 배정 버튼
# -------------------------
st.markdown("---")
st.header("4️⃣ 오후 근무 배정 생성")

if st.button("📋 오후 근무 배정 생성"):
    if not afternoon_list:
        st.warning("오후 근무자 목록이 없습니다.")
    else:
        today_key = next_in_cycle(prev_key, key_order) if prev_key else key_order[0]
        last_gy = prev_gyoyang5
        last_sudong = prev_sudong

        aft_gy_candidates = []
        curg = last_gy if last_gy else gyoyang_order[0]
        for _ in range(len(gyoyang_order)*2):
            curg = next_in_cycle(curg, gyoyang_order)
            if curg in afternoon_list: aft_gy_candidates.append(curg)
            if len(aft_gy_candidates) >= 3: break
        gy3 = aft_gy_candidates[0] if aft_gy_candidates else "-"
        gy4 = aft_gy_candidates[1] if len(aft_gy_candidates) >= 2 else "-"
        gy5 = aft_gy_candidates[2] if len(aft_gy_candidates) >= 3 else "-"

        aft_sudong = None
        curs2 = last_sudong if last_sudong else sudong_order[0]
        for _ in range(len(sudong_order)*2):
            cand = next_in_cycle(curs2, sudong_order)
            curs2 = cand
            if cand in afternoon_list:
                aft_sudong = cand
                break

        aft_2jong = [p for p in afternoon_list if p != aft_sudong]

        afternoon_lines = [
            f"📅 오후 배정",
            f"열쇠: {today_key}",
            f"교양 3교시: {gy3}",
            f"교양 4교시: {gy4}",
            f"교양 5교시: {gy5}",
        ]
        if aft_sudong:
            car = veh1.get(aft_sudong, "-")
            afternoon_lines.append(f"1종수동 (오후): {aft_sudong} → {car}")
        else:
            afternoon_lines.append("1종수동 (오후): -")

        afternoon_lines.append("2종 자동:")
        for nm in aft_2jong:
            car = veh2.get(nm, "-")
            afternoon_lines.append(f" - {nm} → {car}")

        result = "\n".join(afternoon_lines)
        st.text_area("오후 배정 결과", result, height=300)
        st.download_button("📥 오후 결과 다운로드", data=result.encode("utf-8-sig"),
                           file_name="오후근무배정.txt", mime="text/plain")
