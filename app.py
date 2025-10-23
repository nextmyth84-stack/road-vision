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
# 1️⃣ 이미지 업로드 & OCR
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
# 2️⃣ 인식 결과 확인/수정
# =====================================
st.markdown("<h4 style='font-size:18px;'>2️⃣ 인식 결과 확인/수정</h4>", unsafe_allow_html=True)
c3, c4 = st.columns(2)
with c3:
    morning = st.text_area("오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=150)
with c4:
    afternoon = st.text_area("오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=150)

m_list = [x.strip() for x in morning.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon.splitlines() if x.strip()]
early_leave = st.session_state.get("early_leave", [])
late_start = st.session_state.get("late_start", [])

m_norms = {normalize_name(x) for x in m_list} - {normalize_name(x) for x in excluded}
a_norms = {normalize_name(x) for x in a_list} - {normalize_name(x) for x in excluded}

# =====================================
# 3️⃣ 오전 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>3️⃣ 오전 근무 배정</h4>", unsafe_allow_html=True)
if st.button("📋 오전 배정 생성"):
    try:
        # 🔑 열쇠 (휴가/교육 제외, 하루 1회)
        key_filtered = [x for x in key_order if normalize_name(x) not in {normalize_name(e) for e in excluded}]
        today_key = key_filtered[(key_filtered.index(prev_key)+1) % len(key_filtered)] if (key_filtered and prev_key in key_filtered) else (key_filtered[0] if key_filtered else "")
        st.session_state.today_key = today_key

        # 🧑‍🏫 교양 1·2교시 (오전 외출 10시 반영)
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
        if gy1 and not can_attend_period_morning(gy1, 1, late_start):
            gy1 = pick_next_from_cycle(gyoyang_order, gy1, m_norms)
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gyoyang5, m_norms - {normalize_name(gy1)})
        st.session_state.gyoyang_base_for_pm = gy2 if gy2 else prev_gyoyang5

        # 🔧 1종 수동 (인원수 반영)
        sud_m, last = [], prev_sudong
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick)
            last = pick
        st.session_state["sudong_base_for_pm"] = sud_m[-1] if sud_m else prev_sudong

        # 🚗 2종 자동 (교양 포함, 1종 제외)
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

        # 오전 2종 차량 저장(미배정 차량 계산용)
        st.session_state.morning_cars = [get_vehicle(x, veh2) for x in auto_m if get_vehicle(x, veh2)]
        st.session_state.morning_auto_names = auto_m

        # 출력
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy1: lines.append(f"1교시: {gy1}")
        if gy2: lines.append(f"2교시: {gy2}")
        if sud_m:
            for nm in sud_m:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        else:
            lines.append("1종수동: (배정자 없음)")
        if auto_m:
            lines.append("2종 자동:")
            for nm in auto_m:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")

        st.markdown("<h5 style='font-size:16px;'>📋 오전 결과</h5>", unsafe_allow_html=True)
        st.code("\n".join(lines), language="text")
        st.download_button("📥 오전 결과 저장", "\n".join(lines).encode("utf-8-sig"), file_name="오전근무배정.txt")

    except Exception as e:
        st.error(f"오전 오류: {e}")

# =====================================
# 4️⃣ 오후 근무 배정
# =====================================
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정</h4>", unsafe_allow_html=True)
save_check = st.checkbox("이 결과를 '전일 기준'으로 저장 (전일근무.json 덮어쓰기)", value=True)

if st.button("📋 오후 배정 생성"):
    try:
        today_key = st.session_state.get("today_key", prev_key)
        gy_start = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5)
        if not gy_start: gy_start = gyoyang_order[0] if gyoyang_order else None

        # 🧑‍🏫 오후 교양 3·4·5교시 (조퇴 반영)
        used = set()
        gy3 = gy4 = gy5 = None
        last_ptr = gy_start
        for period in [3,4,5]:
            while True:
                pick = pick_next_from_cycle(gyoyang_order, last_ptr, a_norms - used)
                if not pick: break
                last_ptr = pick
                nm = pick
                if nm and can_attend_period(nm, period, early_leave):
                    if period == 3: gy3 = nm
                    elif period == 4: gy4 = nm
                    else: gy5 = nm
                    used.add(normalize_name(nm))
                    break

        # ✅ 오후 1종 수동 (1명/2명 반영, 교양과 중복 허용 = v7.6 동작)
        sud_a_list = []
        base_raw = st.session_state.get("sudong_base_for_pm", None) or prev_sudong
        last = base_raw
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, a_norms)  # used 제외하지 않음
            if not pick: break
            sud_a_list.append(pick)
            last = pick
            used.add(normalize_name(pick))

        # 🚗 2종 자동(오후): 1종 제외(교양 포함)
        sud_a_norms = {normalize_name(x) for x in sud_a_list}
        auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

        # 출력
        lines = []
        if today_key: lines.append(f"열쇠: {today_key}")
        if gy3: lines.append(f"3교시: {gy3}")
        if gy4: lines.append(f"4교시: {gy4}")
        if gy5: lines.append(f"5교시: {gy5}")
        if sud_a_list:
            for nm in sud_a_list:
                lines.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1))}")
        else:
            lines.append("1종수동: (배정자 없음)")
        if auto_a:
            lines.append("2종 자동:")
            for nm in auto_a:
                lines.append(f" • {nm} {mark_car(get_vehicle(nm, veh2))}")

        # 조퇴자 표기
        if early_leave:
            lines.append("조퇴자:")
            for e in early_leave:
                name = e.get("name","")
                try:
                    t = float(e.get("time", None))
                except:
                    t = None
                if t is None: continue
                t_str = "14시30분~" if abs(t-14.5) < 1e-6 else f"{int(t)}시~"
                lines.append(f" • {name}({t_str})")

        # === 오전 대비 비교 ===
        lines.append("오전 대비 비교:")
        morning_names = set(st.session_state.get("morning_auto_names", []))
        afternoon_names = set(auto_a)
        added = sorted(list(afternoon_names - morning_names))
        missing = sorted(list(morning_names - afternoon_names))
        if added:
            lines.append(" • 추가 인원: " + ", ".join(added))
        if missing:
            lines.append(" • 누락 인원: " + ", ".join(missing))

        # 미배정 차량: 오전 2종에 있었는데 오후 2종에 없는 차량 → “14호 마감”
        morning_cars = set(st.session_state.get("morning_cars", []))
        afternoon_cars = {get_vehicle(x, veh2) for x in auto_a if get_vehicle(x, veh2)}
        unassigned = [c for c in morning_cars if c and c not in afternoon_cars]
        if unassigned:
            lines.append("미배정 차량:")
            for c in sorted(unassigned):
                lines.append(f" • {c} 마감")

        st.markdown("<h5 style='font-size:16px;'>📋 오후 결과</h5>", unsafe_allow_html=True)
        st.code("\n".join(lines), language="text")
        st.download_button("📥 오후 결과 저장", "\n".join(lines).encode("utf-8-sig"), file_name="오후근무배정.txt")

        # ✅ 전일 저장(체크박스 ON일 때만)
        if save_check:
            data = {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                "1종수동": sud_a_list[-1] if sud_a_list else prev_sudong
            }
            try:
                with open(PREV_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                st.success("전일근무.json 업데이트 완료")
            except Exception as e:
                st.error(f"전일 저장 실패: {e}")

    except Exception as e:
        st.error(f"오후 오류: {e}")
