# app.py — 도로주행 근무자동배정 (v7.2 완전본)
import streamlit as st
from openai import OpenAI
import base64, re, json, os

# =========================
# 기본 설정 (모바일 친화)
# =========================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown(
    "<h3 style='text-align:center; font-size:22px; margin:6px 0;'>🚗 도로주행 근무자동배정</h3>",
    unsafe_allow_html=True
)

# =========================
# OpenAI 초기화 (GPT-4o 고정)
# =========================
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY가 없습니다. Streamlit Secrets를 확인하세요.")
    st.stop()
MODEL_NAME = "gpt-4o"

# =========================
# 전일 데이터 불러오기
# =========================
PREV_FILE = "전일근무.json"
prev_key = prev_gyoyang5 = prev_sudong = ""
if os.path.exists(PREV_FILE):
    try:
        with open(PREV_FILE, "r", encoding="utf-8") as f:
            prev_js = json.load(f)
        prev_key = prev_js.get("열쇠", "")
        prev_gyoyang5 = prev_js.get("교양_5교시", "")
        prev_sudong = prev_js.get("1종수동", "")
        st.info(f"전일 불러옴 → 열쇠:{prev_key or '없음'}, 교양5:{prev_gyoyang5 or '없음'}, 1종:{prev_sudong or '없음'}")
    except Exception as e:
        st.warning(f"전일근무.json 불러오기 실패: {e}")

# =========================
# 사이드바: 순번/차량/옵션
# =========================
st.sidebar.header("순번 / 차량표 / 옵션")
def _list(s): return [x.strip() for x in s.splitlines() if x.strip()]

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

key_order = _list(st.sidebar.text_area("열쇠 순번", default_key_order, height=160))
gyoyang_order = _list(st.sidebar.text_area("교양 순번", default_gyoyang_order, height=160))
sudong_order = _list(st.sidebar.text_area("1종 수동 순번", default_sudong_order, height=160))

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            car, name = parts[0], " ".join(parts[1:])
            m[name] = car
    return m

veh1 = parse_vehicle_map(st.sidebar.text_area("1종 수동 차량표", default_cha1, height=140))
veh2 = parse_vehicle_map(st.sidebar.text_area("2종 자동 차량표", default_cha2, height=200))

sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
absent_text = st.sidebar.text_area("휴가/교육자 (한 줄에 한 명)", height=90, value="")
repair_cars_text = st.sidebar.text_input("정비 차량(쉼표, 예: 12호,6호)", value="")
excluded_set = {x.strip() for x in absent_text.splitlines() if x.strip()}
repair_cars = [x.strip() for x in repair_cars_text.split(",") if x.strip()]

# 전일값 수정/저장
st.sidebar.markdown("---")
st.sidebar.subheader("🗓 전일값 확인/수정")
prev_key = st.sidebar.text_input("전일 열쇠", value=prev_key)
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value=prev_gyoyang5)
prev_sudong = st.sidebar.text_input("전일 1종 수동", value=prev_sudong)
if st.sidebar.button("💾 전일값 저장"):
    try:
        with open(PREV_FILE, "w", encoding="utf-8") as f:
            json.dump({"열쇠": prev_key, "교양_5교시": prev_gyoyang5, "1종수동": prev_sudong}, f, ensure_ascii=False, indent=2)
        st.sidebar.success("저장 완료")
    except Exception as e:
        st.sidebar.error(f"저장 실패: {e}")

# =========================
# 유틸 함수
# =========================
def normalize_name(s):
    if not isinstance(s, str): return ""
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[-_·•‧‵′\s]", "", s)
    return re.sub(r"[^\uAC00-\uD7A3]", "", s)

def strip_to_pure_korean(s):
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^가-힣]", "", s).strip()

def build_present_map(name_list):
    """
    입력 리스트(괄호 포함)를 매칭용 맵으로 변환.
    key = 정규화 이름, value = (원본문자열, 출력용 순수이름)
    """
    m = {}
    for x in name_list:
        k = normalize_name(x)
        if k and k not in m:
            m[k] = (x, strip_to_pure_korean(x))
    return m

def pick_next_from_cycle(cycle, last, allowed_norms: set):
    """cycle(원본 이름 리스트)에서 last 다음으로 돌며 allowed_norms(정규화)에 포함된 첫 원본 이름 반환"""
    if not cycle: return None
    start = 0 if not last or last not in cycle else (cycle.index(last) + 1) % len(cycle)
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None

def get_vehicle(name, veh_map):
    """name은 순수 이름 기준; 차량표 key도 정규화 비교"""
    kp = normalize_name(name)
    for k, v in veh_map.items():
        if normalize_name(k) == kp:
            return v
    return ""

def mark_car(car):
    return f"{car}{' (정비)' if car in repair_cars else ''}" if car else ""

def extract_course_check(names):
    """괄호 내용은 코스점검으로 모음 (중복 제거)"""
    result, seen = [], set()
    for n in names:
        base = strip_to_pure_korean(n)
        m = re.search(r"\((.*?)\)", n)
        if base and m:
            s = f"{base} ({m.group(1).strip()})"
            if s not in seen:
                seen.add(s); result.append(s)
    return result

# 조퇴
def can_attend_period(name_pure: str, period:int, early_list):
    """3=13:00, 4=14:30, 5=16:00 이전 조퇴면 해당 교시 불가"""
    tmap = {3:13.0, 4:14.5, 5:16.0}
    leave = None
    for e in early_list:
        if normalize_name(e.get("name","")) == normalize_name(name_pure):
            leave = e.get("time", None)
            break
    if leave is None: return True
    return float(leave) > tmap[period]

# =========================
# GPT OCR
# =========================
def gpt_extract(image_bytes, want_early=False):
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과', '기능장', '초소'를 제외한 **도로주행 근무자 이름**만 추출하세요.\n"
        "2) 이름 옆 괄호(A-합, B-불 등)는 그대로 둡니다.\n"
        "3) 괄호에 '지원','인턴','연수'가 포함된 항목은 제외하세요.\n"
        + ("4) 이미지 상단의 '조퇴 :' 항목에서 조퇴자 이름과 시간을 함께 추출하세요.\n" if want_early else "") +
        ('반환 예시: {"names":["김면정(A-합)","김성연(B-불)"]' + (',"early_leave":[{"name":"김병욱","time":14}]' if want_early else '') + "}"
        )
    )
    try:
        r = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "표에서 이름을 JSON으로 추출하는 도구"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = r.choices[0].message.content
        m = re.search(r"\{.*\}", raw, re.S)
        js = json.loads(m.group(0)) if m else {}
        names = [n for n in js.get("names", []) if not re.search(r"(지원|인턴|연수)", n)]
        names = [re.sub(r"\(.*?\)", "", n).strip() for n in names]  # 👈 괄호 제거 핵심
        early = js.get("early_leave", []) if want_early else []
        return names, early
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], []

# =========================
# 1) OCR 이미지 업로드 & 실행
# =========================
st.markdown("<h4 style='font-size:18px;'>1️⃣ 근무표 이미지 업로드 & OCR</h4>", unsafe_allow_html=True)
c1, c2 = st.columns(2)
with c1:
    m_file = st.file_uploader("📸 오전 근무표", type=["png", "jpg", "jpeg"])
with c2:
    a_file = st.file_uploader("📸 오후 근무표", type=["png", "jpg", "jpeg"])

if st.button("🧠 GPT로 인식"):
    if not m_file and not a_file:
        st.warning("오전 또는 오후 이미지를 업로드하세요.")
    else:
        with st.spinner("GPT 분석 중..."):
            if m_file:
                m_names, _ = gpt_extract(m_file.read())
                st.session_state.m_names_raw = m_names
                st.success(f"오전 인식: {len(m_names)}명")
            if a_file:
                a_names, early = gpt_extract(a_file.read(), want_early=True)
                st.session_state.a_names_raw = a_names
                st.session_state.early_leave = early
                st.success(f"오후 인식: {len(a_names)}명, 조퇴 {len(early)}명")
        st.rerun()

# =========================
# 2) 인식 결과 확인/수정
# =========================
st.markdown("<h4 style='font-size:18px;'>2️⃣ 인식 결과 확인/수정</h4>", unsafe_allow_html=True)
c3, c4 = st.columns(2)
morning_txt = "\n".join(st.session_state.get("m_names_raw", []))
afternoon_txt = "\n".join(st.session_state.get("a_names_raw", []))
with c3:
    m_edit = st.text_area("오전 근무자", value=morning_txt, height=150)
with c4:
    a_edit = st.text_area("오후 근무자", value=afternoon_txt, height=150)
morning_list_raw = [x.strip() for x in m_edit.splitlines() if x.strip()]
afternoon_list_raw = [x.strip() for x in a_edit.splitlines() if x.strip()]
early_leave_list = st.session_state.get("early_leave", [])

present_m = build_present_map(morning_list_raw)   # {norm: (orig, pure)}
present_a = build_present_map(afternoon_list_raw)
excluded_norm = {normalize_name(x) for x in excluded_set}

# =========================
# 3) 오전 배정 (열쇠/교양1·2/1종/2종)
# =========================
st.markdown("<h4 style='font-size:18px;'>3️⃣ 오전 근무 배정 생성</h4>", unsafe_allow_html=True)
# 안전 기본값
today_key = st.session_state.get("today_key", "")
gy1 = gy2 = None
sud_m = []
auto_m = []

if st.button("📋 오전 배정 생성"):
    try:
        allow_m = set(present_m.keys()) - excluded_norm

        # 🔑 열쇠 (하루 1회): 전체 근무자에서 휴가/교육 제외
        key_cycle_filtered = [x for x in key_order if normalize_name(x) not in excluded_norm]
        if key_cycle_filtered:
            if prev_key in key_cycle_filtered:
                idx = (key_cycle_filtered.index(prev_key) + 1) % len(key_cycle_filtered)
                today_key = key_cycle_filtered[idx]
            else:
                today_key = key_cycle_filtered[0]
            st.session_state.today_key = today_key

        # 🧑‍🏫 교양 1·2교시: prev_gyoyang5 → gy1 → gy2
        gy1_cand = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, allow_m)
        gy1 = present_m.get(normalize_name(gy1_cand), (None, None))[1] if gy1_cand else None

        base_for_gy2 = gy1_cand if gy1_cand else prev_gyoyang5
        allow_m2 = allow_m - ({normalize_name(gy1)} if gy1 else set())
        gy2_cand = pick_next_from_cycle(gyoyang_order, base_for_gy2, allow_m2)
        gy2 = present_m.get(normalize_name(gy2_cand), (None, None))[1] if gy2_cand else None
        st.session_state.m_gy2_source = gy2_cand  # 오후 시작 포인터

        # 🔧 1종 수동
        sud_m = []
        last = prev_sudong if prev_sudong in sudong_order else None
        allow_for_sud = set(allow_m)
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, allow_for_sud)
            if not pick: break
            pure = present_m.get(normalize_name(pick), (None, None))[1]
            if pure:
                sud_m.append(pure)
                allow_for_sud -= {normalize_name(pure)}
                last = pick
        # 오전 1종 수동 마지막 선택자를 오후 기준으로 넘김
        if sud_m:
            st.session_state["sudong_base_for_pm"] = sud_m[-1]   # 예: '권한솔'
        else:
        # 오전에 1종이 없으면 전일값을 그대로 사용 (없으면 None)
            st.session_state["sudong_base_for_pm"] = prev_sudong if prev_sudong in sudong_order else None
    
        # 🚗 2종 자동 (오전): 전체 - 1종 (교양 포함)
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [v[1] for k, v in present_m.items() if (k in allow_m) and (k not in sud_norms)]

        # === 출력 ===
        out = []
        if today_key: out.append(f"열쇠: {today_key}")
        if gy1: out.append(f"교양 1교시: {gy1}")
        if gy2: out.append(f"교양 2교시: {gy2}")
        if sud_m:
            for nm in sud_m:
                car = get_vehicle(nm, veh1)
                out.append(f"1종수동: {nm}{(' ' + mark_car(car)) if car else ''}")
        else:
            out.append("1종수동: (배정자 없음)")
        if auto_m:
            out.append("2종 자동:")
            for nm in auto_m:
                car = get_vehicle(nm, veh2)
                out.append(f" • {nm}{(' ' + mark_car(car)) if car else ''}")

        st.markdown("<h5 style='font-size:16px;'>📋 오전 결과</h5>", unsafe_allow_html=True)
        st.code("\n".join(out), language="text")
        st.download_button("📥 오전 결과 저장", "\n".join(out).encode("utf-8-sig"), file_name="오전근무배정.txt")

    except Exception as e:
        st.error(f"오전 배정 오류: {e}")

# =========================
# 4) 오후 배정 (교양3·4·5/1종/2종 + 조퇴 반영)
# =========================
st.markdown("<h4 style='font-size:18px;'>4️⃣ 오후 근무 배정 생성</h4>", unsafe_allow_html=True)

if st.button("📋 오후 배정 생성"):
    try:
        allow_a = set(present_a.keys()) - excluded_norm

        # 🔑 열쇠: 오전에서 정해진 값 사용, 없으면 여기서 계산
        afternoon_key = st.session_state.get("today_key", "")
        if not afternoon_key:
            key_cycle_filtered = [x for x in key_order if normalize_name(x) not in excluded_norm]
            if key_cycle_filtered:
                afternoon_key = key_cycle_filtered[(key_cycle_filtered.index(prev_key)+1) % len(key_cycle_filtered)] if prev_key in key_cycle_filtered else key_cycle_filtered[0]
                st.session_state.today_key = afternoon_key

        # 🧑‍🏫 오후 교양 시작 포인터 = 오전 2교시 교양자(원형) → 없으면 prev_gyoyang5
        gy_start_cand = st.session_state.get("m_gy2_source", None)
        if not gy_start_cand or gy_start_cand not in gyoyang_order:
            gy_start_cand = prev_gyoyang5 if prev_gyoyang5 in gyoyang_order else None

        used = set()  # 오후 배정에서 '이미 선택된 사람' 추적(교양과 1종 간 중복 방지 목적)
        gy3 = gy4 = gy5 = None
        last_ptr = gy_start_cand

        # 교시별 차례 유지, 조퇴로 불가하면 "건너뜀"
        for period in [3, 4, 5]:
            while True:
                pick = pick_next_from_cycle(gyoyang_order, last_ptr, allow_a - used)
                if not pick: break
                nm_pure = present_a.get(normalize_name(pick), (None, None))[1]
                last_ptr = pick
                if nm_pure and can_attend_period(nm_pure, period, early_leave_list):
                    if period == 3: gy3 = nm_pure
                    elif period == 4: gy4 = nm_pure
                    else: gy5 = nm_pure
                    used.add(normalize_name(nm_pure))
                    break
        # 🔧 1종 수동(오후): 오전 마지막 1종 다음 사람을 선택 (없으면 전일값 기준)
        sud_a = []
        # 오전 결과에서 넘겨받은 기준(없으면 전일값)
        base_last = st.session_state.get("sudong_base_for_pm", None)
        if base_last not in sudong_order:
            base_last = prev_sudong if prev_sudong in sudong_order else None

        pick = pick_next_from_cycle(sudong_order, base_last, allow_a - used)
        if pick:
            nm_pure = present_a.get(normalize_name(pick), (None, None))[1]
            if nm_pure:
                sud_a.append(nm_pure)
                used.add(normalize_name(nm_pure))


        # 🚗 2종 자동(오후): 전체 - 1종 (교양자는 포함)
        sud_a_norms = {normalize_name(x) for x in sud_a}
        auto_a = [v[1] for k, v in present_a.items() if (k in allow_a) and (k not in sud_a_norms)]

        # === 출력 ===
        out = []
        if afternoon_key: out.append(f"열쇠: {afternoon_key}")
        if gy3: out.append(f"교양 3교시: {gy3}")
        if gy4: out.append(f"교양 4교시: {gy4}")
        if gy5: out.append(f"교양 5교시: {gy5}")
        if sud_a:
            for nm in sud_a:
                car = get_vehicle(nm, veh1)
                out.append(f"1종수동(오후): {nm}{(' ' + mark_car(car)) if car else ''}")
        else:
            out.append("1종수동(오후): (배정자 없음)")
        if auto_a:
            out.append("2종 자동:")
            for nm in auto_a:
                car = get_vehicle(nm, veh2)
                out.append(f" • {nm}{(' ' + mark_car(car)) if car else ''}")

        # 조퇴자 표기(있을 때만)
        if early_leave_list:
            out.append("조퇴자:")
            for e in early_leave_list:
                name_pure = strip_to_pure_korean(e.get("name",""))
                t = e.get("time", None)
                if t is None: continue
                if isinstance(t, float):
                    t_str = "14시30분~" if abs(t-14.5) < 1e-6 else f"{t}시~"
                else:
                    t_str = f"{int(t)}시~"
                out.append(f" • {name_pure}({t_str})")

        st.markdown("<h5 style='font-size:16px;'>📋 오후 결과</h5>", unsafe_allow_html=True)
        st.code("\n".join(out), language="text")
        st.download_button("📥 오후 결과 저장", "\n".join(out).encode("utf-8-sig"), file_name="오후근무배정.txt")

        # ✅ 오늘 결과를 전일 기준으로 저장 (선택)
        if st.checkbox("이 결과를 '전일 기준'으로 저장", value=True):
            to_store = {
                "열쇠": afternoon_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                "1종수동": (sud_a[0] if sud_a else prev_sudong)
            }
            try:
                with open(PREV_FILE, "w", encoding="utf-8") as f:
                    json.dump(to_store, f, ensure_ascii=False, indent=2)
                st.success("전일근무.json 업데이트 완료")
            except Exception as e:
                st.error(f"전일 저장 실패: {e}")

    except Exception as e:
        st.error(f"오후 배정 오류: {e}")

# =========================
# 5) 코스점검 (괄호내용 모음)
# =========================
st.markdown("<h4 style='font-size:18px;'>5️⃣ 코스점검</h4>", unsafe_allow_html=True)
course_check = extract_course_check(morning_list_raw + afternoon_list_raw)
if course_check:
    st.text("\n".join(course_check))
else:
    st.caption("표시할 코스점검 항목이 없습니다.")
