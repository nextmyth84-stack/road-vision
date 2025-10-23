# app.py — 도로주행 근무자동배정 v7.5 완전본
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# =====================================
# 기본 설정
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
# 전일 기준 로드
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
# 사이드바 설정
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
        if len(p) >= 2: m[" ".join(p[1:])] = p[0]
    return m

veh1 = parse_vehicle_map(st.sidebar.text_area("1종 수동 차량표", default_cha1, height=120))
veh2 = parse_vehicle_map(st.sidebar.text_area("2종 자동 차량표", default_cha2, height=180))

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
excluded = {x.strip() for x in st.sidebar.text_area("휴가/교육자 (한 줄당 한 명)", height=100).splitlines() if x.strip()}
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일값 확인/수정")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gyoyang5 = st.sidebar.text_input("전일 교양5", value=prev_gyoyang5)
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_sudong)
if st.sidebar.button("💾 전일값 저장"):
    with open(PREV_FILE, "w", encoding="utf-8") as f:
        json.dump({"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong}, f, ensure_ascii=False, indent=2)
    st.sidebar.success("저장 완료")

# =====================================
# 유틸 함수
# =====================================
def normalize_name(s): return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """정규화 기준 순환"""
    if not cycle: return None
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

def mark_car(car): return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

# =====================================
# GPT OCR
# =====================================
def gpt_extract(img_bytes, want_early=False):
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과', '기능장', '초소'를 제외한 도로주행 근무자 이름만 추출하세요.\n"
        "2) 괄호안 정보(A-합 등)는 유지하지만 반환할 때 괄호 전체를 제거한 이름으로 주세요.\n"
        "3) 괄호에 '지원','인턴','연수' 포함자는 제외하세요.\n"
        + ("4) '조퇴:' 항목이 있다면 이름과 시간을 함께 JSON으로 반환하세요.\n" if want_early else "") +
        ('반환 예시: {"names":["김면정","김성연"]' + (',"early_leave":[{"name":"김병욱","time":14}]' if want_early else '') + "}"
        )
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
        return names, early
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], []

# =====================================
# 1️⃣ 이미지 업로드 & OCR 버튼
# =====================================
st.markdown("<h4 style='font-size:18px;'>1️⃣ 근무표 이미지 업로드 & OCR</h4>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1: m_file = st.file_uploader("📸 오전 근무표", type=["png","jpg","jpeg"])
with col2: a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"])

# 오전 전용
if st.button("🧠 오전 GPT 인식"):
    if not m_file: st.warning("오전 이미지를 업로드하세요.")
    else:
        with st.spinner("오전 GPT 분석 중..."):
            m_names, _ = gpt_extract(m_file.read())
            st.session_state.m_names_raw = m_names
            st.success(f"오전 인식: {len(m_names)}명")
        st.rerun()

# 오후 전용
if st.button("🧠 오후 GPT 인식"):
    if not a_file: st.warning("오후 이미지를 업로드하세요.")
    else:
        with st.spinner("오후 GPT 분석 중..."):
            a_names, early = gpt_extract(a_file.read(), want_early=True)
            st.session_state.a_names_raw = a_names
            st.session_state.early_leave = early
            st.success(f"오후 인식: {len(a_names)}명, 조퇴 {len(early)}명")
        st.rerun()

# =====================================
# 2️⃣ 인식 결과 확인/수정
# =====================================
st.markdown("<h4 style='font-size:18px;'>2️⃣ 인식 결과 확인/수정</h4>", unsafe_allow_html=True)
c3, c4 = st.columns(2)
with c3: morning = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=150)
with c4: afternoon = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=150)
m_list = [x.strip() for x in morning.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]
early_leave = st.session_state.get("early_leave", [])

m_norms = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}
a_norms = {normalize_name(x) for x in a_list} - {normalize_name(x) for x in excluded}

# =====================================
# 3️⃣ 오전 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>3️⃣ 오전 근무 배정</h4>", unsafe_allow_html=True)
if st.button("📋 오전 배정 생성"):
    try:
        # 🔑 열쇠
        key_filtered = [x for x in key_order if normalize_name(x) not in {normalize_name(e) for e in excluded}]
        today_key = key_filtered[(key_filtered.index(prev_key)+1)%len(key_filtered)] if prev_key in key_filtered else key_filtered[0]

        # 교양
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_norms - {normalize_name(gy1)})

        # 1종 수동
        sud_m, last = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick); last = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # 2종 자동 (교양 포함)
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in m_norms - sud_norms]

        # 출력
        out = [
            f"열쇠: {today_key}",
            f"교양1: {gy1 or '-'}",
            f"교양2: {gy2 or '-'}",
        ]
        if sud_m:
            for x in sud_m:
                out.append(f"1종수동: {x} {mark_car(veh1.get(x,''))}")
        else:
            out.append("1종수동: (배정자 없음)")
        if auto_m:
            out.append("2종 자동:")
            for x in auto_m: out.append(f" • {x} {mark_car(veh2.get(x,''))}")
        st.code("\n".join(out))
    except Exception as e: st.error(f"오전 오류: {e}")

# =====================================
# 4️⃣ 오후 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
if st.button("📋 오후 배정 생성"):
    try:
        today_key = st.session_state.get("today_key", prev_key)
        base_sud = st.session_state.get("sudong_base_for_pm", prev_sudong)
        gy_start = gyoyang_order[0] if not prev_gyoyang5 else prev_gyoyang5
        # 교양
        gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_norms)
        gy4 = pick_next_from_cycle(gyoyang_order, gy3, a_norms - {normalize_name(gy3)})
        gy5 = pick_next_from_cycle(gyoyang_order, gy4, a_norms - {normalize_name(gy3), normalize_name(gy4)})
        # 1종
        sud_a = pick_next_from_cycle(sudong_order, base_sud, a_norms)
        sud_norms = {normalize_name(sud_a)} if sud_a else set()
        auto_a = [x for x in a_list if normalize_name(x) in a_norms - sud_norms]

        out = [
            f"열쇠: {today_key}",
            f"교양3: {gy3 or '-'}",
            f"교양4: {gy4 or '-'}",
            f"교양5: {gy5 or '-'}",
        ]
        if sud_a:
            out.append(f"1종수동(오후): {sud_a} {mark_car(veh1.get(sud_a,''))}")
        else:
            out.append("1종수동(오후): (배정자 없음)")
        if auto_a:
            out.append("2종 자동:")
            for x in auto_a: out.append(f" • {x} {mark_car(veh2.get(x,''))}")

        if early_leave:
            out.append("조퇴자:")
            for e in early_leave:
                out.append(f" • {e['name']}({e['time']}시~)")

        st.code("\n".join(out))
    except Exception as e:
        st.error(f"오후 오류: {e}")
