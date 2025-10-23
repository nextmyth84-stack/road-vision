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
        st.info(f"전일 불러옴 → 열쇠:{prev_key or '-'}, 5교시:{prev_gyoyang5 or '-'}, 1종:{prev_sudong or '-'}")
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

# 접힘 구조 적용
with st.sidebar.expander("🔑 열쇠 순번 보기 / 수정", expanded=False):
    key_order = _list(st.text_area("열쇠 순번", default_key, height=160))

with st.sidebar.expander("📚 교양 순번 보기 / 수정", expanded=False):
    gyoyang_order = _list(st.text_area("교양 순번", default_gyoyang, height=160))

with st.sidebar.expander("🧰 1종 수동 순번 보기 / 수정", expanded=False):
    sudong_order = _list(st.text_area("1종 수동 순번", default_sudong, height=160))

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            car = p[0]
            name = " ".join(p[1:])
            m[name] = car
    return m

with st.sidebar.expander("🚗 1종 수동 차량표 보기 / 수정", expanded=False):
    veh1 = parse_vehicle_map(st.text_area("1종 수동 차량표", default_cha1, height=120))

with st.sidebar.expander("🚙 2종 자동 차량표 보기 / 수정", expanded=False):
    veh2 = parse_vehicle_map(st.text_area("2종 자동 차량표", default_cha2, height=180))

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
excluded = {x.strip() for x in st.sidebar.text_area("휴가/교육자 (한 줄당 한 명)", height=100).splitlines() if x.strip()}
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", value="").split(",") if x.strip()]

# 전일값 수정/저장
st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일값 확인/수정")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gyoyang5 = st.sidebar.text_input("전일 교양5", value=prev_gyoyang5)
prev_sudong = st.sidebar.text_input("전일 1종수동", value=prev_sudong)
if st.sidebar.button("💾 전일값 저장"):
    try:
        with open(PREV_FILE, "w", encoding="utf-8") as f:
            json.dump({"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong}, f, ensure_ascii=False, indent=2)
        st.sidebar.success("저장 완료")
    except Exception as e:
        st.sidebar.error(f"저장 실패: {e}")

# =====================================
# 유틸 함수
# =====================================
def normalize_name(s):
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def pick_next_from_cycle(cycle, last, allowed_norms: set):
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
# 클립보드 복사(JS)
# =====================================
def clipboard_copy_button(text: str, label="📋 결과 복사"):
    clipboard_script = f"""
        <script>
        async function copyText() {{
            await navigator.clipboard.writeText(`{text}`);
            alert("복사 완료!");
        }}
        </script>
        <button onclick="copyText()" style="background-color:#4CAF50;color:white;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;">{label}</button>
    """
    st.markdown(clipboard_script, unsafe_allow_html=True)
# =====================================
# GPT OCR
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
# 1) 이미지 업로드 & OCR
# =====================================
st.markdown("<h4 style='font-size:18px;'>1️⃣ 근무표 이미지 업로드 & OCR</h4>", unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1: m_file = st.file_uploader("📸 오전 근무표", type=["png","jpg","jpeg"])
with col2: a_file = st.file_uploader("📸 오후 근무표", type=["png","jpg","jpeg"])

b1, b2 = st.columns(2)
with b1:
    if st.button("🧠 오전 GPT 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("오전 GPT 분석 중..."):
                m_names, _, late = gpt_extract(m_file.read(), want_late=True)
                st.session_state.m_names_raw = m_names
                st.session_state.late_start = late
                st.success(f"오전 인식: {len(m_names)}명, 외출 {len(late)}명")
            st.rerun()
with b2:
    if st.button("🧠 오후 GPT 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("오후 GPT 분석 중..."):
                a_names, early, _ = gpt_extract(a_file.read(), want_early=True)
                st.session_state.a_names_raw = a_names
                st.session_state.early_leave = early
                st.success(f"오후 인식: {len(a_names)}명, 조퇴 {len(early)}명")
            st.rerun()


# =====================================
# 2️⃣ 인식 결과 입력 (수동 또는 GPT 후 수정)
# =====================================
st.markdown("<h4 style='font-size:18px;'>2️⃣ 인식 결과 확인/수정</h4>", unsafe_allow_html=True)
c3, c4 = st.columns(2)
with c3:
    morning = st.text_area("오전 근무자", "", height=150)
with c4:
    afternoon = st.text_area("오후 근무자", "", height=150)
m_list = [x.strip() for x in morning.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]

# =====================================
# 3️⃣ 오전 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>3️⃣ 오전 근무 배정</h4>", unsafe_allow_html=True)
if st.button("📋 오전 배정 생성"):
    try:
        lines = []
        # 🔑 열쇠 순번
        available = [x for x in key_order if normalize_name(x) not in {normalize_name(e) for e in excluded}]
        today_key = pick_next_from_cycle(available, prev_key, {normalize_name(x) for x in m_list})

        # 🔧 1종 수동
        sud_m, last = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, {normalize_name(x) for x in m_list})
            if pick:
                sud_m.append(pick)
                last = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # 🚗 2종 자동
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) not in sud_norms]

        # 차량 저장
        st.session_state.morning_cars_1 = [get_vehicle(x, veh1) for x in sud_m if get_vehicle(x, veh1)]
        st.session_state.morning_cars_2 = [get_vehicle(x, veh2) for x in auto_m if get_vehicle(x, veh2)]
        st.session_state.morning_auto_names = auto_m + sud_m

        lines.append(f"열쇠: {today_key}")
        for nm in sud_m:
            lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        lines.append("2종 자동:")
        for nm in auto_m:
            lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")

        result_text = "\n".join(lines)
        st.markdown("### 📋 오전 결과")
        st.code(result_text, language="text")
        st.download_button("📥 오전 결과 저장", result_text.encode("utf-8-sig"), file_name="오전근무배정.txt")
        clipboard_copy_button(result_text)
        st.session_state.today_key = today_key
    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 4️⃣ 오후 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
save_check = st.checkbox("이 결과를 '전일 기준'으로 저장", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        lines = []
        today_key = st.session_state.get("today_key", prev_key)
        sudong_prev = st.session_state.get("sudong_base_for_pm", prev_sudong)

        # 🔧 오후 1종 수동
        sud_a_list, last = [], sudong_prev
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, {normalize_name(x) for x in a_list})
            if pick:
                sud_a_list.append(pick)
                last = pick

        # 🚗 오후 2종 자동
        sud_a_norms = {normalize_name(x) for x in sud_a_list}
        auto_a = [x for x in a_list if normalize_name(x) not in sud_a_norms]

        # 비교
        morning_auto = set(st.session_state.get("morning_auto_names", []))
        afternoon_auto = set(auto_a)
        afternoon_sud = {normalize_name(x) for x in sud_a_list}

        morning_only = []
        for nm in morning_auto:
            n_norm = normalize_name(nm)
            if n_norm not in {normalize_name(x) for x in afternoon_auto} and n_norm not in afternoon_sud:
                morning_only.append(nm)
        added = sorted(list(afternoon_auto - morning_auto))
        missing = sorted(morning_only)

        # 차량 비교
        m1 = set(st.session_state.get("morning_cars_1", []))
        m2 = set(st.session_state.get("morning_cars_2", []))
        a1 = {get_vehicle(x, veh1) for x in sud_a_list if get_vehicle(x, veh1)}
        a2 = {get_vehicle(x, veh2) for x in auto_a if get_vehicle(x, veh2)}
        unassigned_1 = sorted([c for c in m1 if c not in a1])
        unassigned_2 = sorted([c for c in m2 if c not in a2])

        lines.append(f"열쇠: {today_key}")
        for nm in sud_a_list:
            lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        lines.append("2종 자동:")
        for nm in auto_a:
            lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")

        lines.append("오전 대비 비교:")
        if added:
            lines.append(" • 추가 인원: " + ", ".join(added))
        if missing:
            lines.append(" • 빠진 인원: " + ", ".join(missing))

        if unassigned_1 or unassigned_2:
            lines.append("미배정 차량:")
            if unassigned_1:
                lines.append(" [1종 수동]")
                for c in unassigned_1: lines.append(f"  • {c} 마감")
            if unassigned_2:
                lines.append(" [2종 자동]")
                for c in unassigned_2: lines.append(f"  • {c} 마감")

        result_text = "\n".join(lines)
        st.markdown("### 📋 오후 결과")
        st.code(result_text, language="text")
        st.download_button("📥 오후 결과 저장", result_text.encode("utf-8-sig"), file_name="오후근무배정.txt")
        clipboard_copy_button(result_text)

        # ✅ 전일 저장
        if save_check:
            if today_key:
                with open(PREV_FILE, "w", encoding="utf-8") as f:
                    json.dump({"열쇠": today_key, "교양_5교시": prev_gyoyang5, "1종수동": last}, f, ensure_ascii=False, indent=2)
                st.success("전일근무.json 업데이트 완료")
            else:
                st.warning("⚠️ 결과가 불완전하여 전일근무.json 저장이 생략되었습니다.")
    except Exception as e:
        st.error(f"오후 오류: {e}")
