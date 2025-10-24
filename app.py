import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib

# =====================================
# 페이지 설정
# =====================================
st.set_page_config(page_title="도로주행 근무자동배정", layout="wide")
st.markdown("<h3 style='text-align:center;'>🚗 도로주행 근무자동배정 v7.33</h3>", unsafe_allow_html=True)

# =====================================
# OpenAI 초기화
# =====================================
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 누락됨.")
    st.stop()
MODEL_NAME = "gpt-4o"

# =====================================
# JSON 파일 로드 및 저장 유틸
# =====================================
def load_json(file, default=None):
    if os.path.exists(file):
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default or {}
    return default or {}

def save_json(file, data):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"저장 실패: {e}")

# =====================================
# 전일 데이터
# =====================================
PREV_FILE = "전일근무.json"
prev_data = load_json(PREV_FILE, {"열쇠": "", "교양_5교시": "", "1종수동": ""})
prev_key, prev_gy5, prev_sud = prev_data["열쇠"], prev_data["교양_5교시"], prev_data["1종수동"]

# =====================================
# 문자열 유틸
# =====================================
def normalize_name(s): return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))

def mark_car(car, repair_list): return f"{car}{' (정비)' if car in repair_list else ''}" if car else ""

def get_vehicle(name, mapping):
    n = normalize_name(name)
    for k, v in mapping.items():
        if normalize_name(k) == n:
            return v
    return ""

def pick_next_from_cycle(cycle, last, allowed):
    if not cycle: return None
    norm_cycle = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = norm_cycle.index(last_norm) + 1 if last_norm in norm_cycle else 0
    for i in range(len(cycle)):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed:
            return cand
    return None

# =====================================
# OCR 이름 교정기
# =====================================
def correct_name_v2(name, all_staff, cutoff=0.5):
    """전체 근무자 기반 오타 교정"""
    name_norm = normalize_name(name)
    if not name_norm: return name
    candidates = difflib.get_close_matches(name_norm, [normalize_name(x) for x in all_staff], n=1, cutoff=cutoff)
    if candidates:
        for real in all_staff:
            if normalize_name(real) == candidates[0]:
                return real
    return name
# =====================================
# 사이드바 구성 (순번표 / 차량표 / 전체근무자)
# =====================================
st.sidebar.header("⚙️ 설정 메뉴")

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        p = line.strip().split()
        if len(p) >= 2:
            m[" ".join(p[1:])] = p[0]
    return m

with st.sidebar.expander("🔑 열쇠 / 교양 / 1종 수동 순번표", expanded=False):
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
    default_gy = """권한솔
김남균
김면정
김병욱
김성연
김주현
김지은
안유미
이호석
조정래"""
    default_sd = """권한솔
김남균
김성연
김주현
이호석
조정래"""

    key_order = st.text_area("열쇠 순번", default_key, height=160).splitlines()
    gyoyang_order = st.text_area("교양 순번", default_gy, height=160).splitlines()
    sudong_order = st.text_area("1종 수동 순번", default_sd, height=120).splitlines()

with st.sidebar.expander("🚘 차량표 (1종 / 2종)", expanded=False):
    default_veh1 = """2호 조정래
5호 권한솔
7호 김남균
8호 이호석
9호 김주현
10호 김성연"""
    default_veh2 = """4호 김남균
5호 김병욱
6호 김지은
12호 안유미
14호 김면정
15호 이호석
17호 김성연
18호 권한솔
19호 김주현
22호 조정래"""
    veh1_map = parse_vehicle_map(st.text_area("1종 수동 차량표", default_veh1, height=120))
    veh2_map = parse_vehicle_map(st.text_area("2종 자동 차량표", default_veh2, height=160))

with st.sidebar.expander("👥 전체 근무자 목록", expanded=False):
    default_staff = """권한솔
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
조정래
김병욱
김주현"""
    all_staff = st.text_area("전체 근무자", default_staff, height=150).splitlines()

sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)
repair_cars = [x.strip() for x in st.sidebar.text_input("정비 차량 (쉼표로 구분)", "").split(",") if x.strip()]
# =====================================
# 시간 제약 함수 (지각/조퇴 반영)
# =====================================
def can_attend_period_morning(name, period, late_list):
    """오전 교양: 1=9:00~10:30, 2=10:30~12:00. 10시 이후 출근자는 1교시 불가."""
    tmap = {1: 9.0, 2: 10.5}
    nn = normalize_name(name)
    for e in late_list or []:
        if normalize_name(e.get("name", "")) == nn:
            try:
                t = float(e.get("time", 99))
            except:
                t = 99
            return t <= tmap[period]
    return True

def can_attend_period_afternoon(name, period, early_list):
    """오후 교양: 3=13:00, 4=14:30, 5=16:00. 해당 시각 이전 조퇴면 해당 교시 불가."""
    tmap = {3: 13.0, 4: 14.5, 5: 16.0}
    nn = normalize_name(name)
    for e in early_list or []:
        if normalize_name(e.get("name", "")) == nn:
            try:
                t = float(e.get("time", 0))
            except:
                t = 0
            return t > tmap[period]
    return True

# =====================================
# OCR (오전/오후별 1회 호출로: 근무자 + 코스 + 제외자 + 조퇴/외출)
# =====================================
def gpt_extract(img_bytes, want_early=False, want_late=False):
    b64 = base64.b64encode(img_bytes).decode()
    prompt = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과','기능','PC','초소' 등은 제외하고 '도로주행' 근무자만 추출.\n"
        "2) 이름 뒤 괄호의 A/B와 합/불은 코스점검 결과로 인식.\n"
        "3) 표 상단(또는 별도 항목)의 '휴가','교육','출장','공가','연차','돌봄' 등은 excluded로 추출.\n"
        "4) '조퇴:'는 early_leave, '외출:'/'10시 출근:'은 late_start로 추출(시간은 숫자: 14 또는 14.5 등).\n"
        "정확히 '하나의 JSON'만 출력하고, 설명은 쓰지 마세요.\n"
        "예시: {\"names\":[\"김성연(B합)\"],\"excluded\":[\"안유미\"],"
        "\"early_leave\":[{\"name\":\"김병욱\",\"time\":14.5}],"
        "\"late_start\":[{\"name\":\"김지은\",\"time\":10}]}"
    )
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role":"system","content":"근무표를 JSON 하나로만 변환"},
                {"role":"user","content":[
                    {"type":"text","text":prompt},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
                ]}
            ]
        )
        raw = (res.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return [], [], [], [], []
        # JSON 파싱 (여분 텍스트 섞임 대비)
        try:
            js = json.loads(m.group(0))
        except json.JSONDecodeError:
            parts = re.findall(r"\{[^\}]*\}", raw)
            js = json.loads(parts[0]) if parts else {}

        raw_names = js.get("names", []) or []
        excluded = js.get("excluded", []) or []
        early = js.get("early_leave", []) if want_early else []
        late  = js.get("late_start",  []) if want_late  else []

        # 이름·코스 분리 (괄호 내용은 코스 결과로만 사용)
        names, course_records = [], []
        for n in raw_names:
            m2 = re.search(r"([가-힣]+)\s*\(([^)]*)\)", n)
            if m2:
                nm = m2.group(1).strip()
                det = re.sub(r"[^A-Za-z가-힣]", "", m2.group(2)).upper()
                crs = "A" if "A" in det else ("B" if "B" in det else None)
                res_txt = "합격" if "합" in det else ("불합격" if "불" in det else None)
                if crs and res_txt:
                    course_records.append({"name": nm, "course": f"{crs}코스", "result": res_txt})
                names.append(nm)
            else:
                names.append((n or "").strip())

        # 시간 숫자형
        def to_f(x):
            try: return float(x)
            except: return None
        for e in early or []: e["name"]=e.get("name",""); e["time"]=to_f(e.get("time"))
        for l in late  or []: l["name"]=l.get("name",""); l["time"]=to_f(l.get("time"))

        return names, course_records, excluded, (early or []), (late or [])

    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []

# =====================================
# 업로드 + OCR 실행 (오전/오후) + 이름교정 + 상태저장
# =====================================
st.markdown("<h4 style='font-size:18px;'>📸 근무표 이미지 업로드</h4>", unsafe_allow_html=True)
c1, c2 = st.columns(2)
with c1:
    m_file = st.file_uploader("오전 근무표", type=["png","jpg","jpeg"])
with c2:
    a_file = st.file_uploader("오후 근무표", type=["png","jpg","jpeg"])

col = st.columns(2)
with col[0]:
    if st.button("🧠 오전 인식"):
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            names, courses, excluded, _, late = gpt_extract(m_file.read(), want_late=True)
            # 이름 교정
            names = [correct_name_v2(n, all_staff, cutoff=0.5) for n in names]
            courses = [{"name": correct_name_v2(r["name"], all_staff, cutoff=0.5),
                        "course": r["course"], "result": r["result"]} for r in courses]
            excluded = [correct_name_v2(x, all_staff, cutoff=0.5) for x in excluded]
            for l in late: l["name"] = correct_name_v2(l.get("name",""), all_staff, cutoff=0.5)

            st.session_state.m_names_raw = names
            st.session_state.m_course_records = courses
            st.session_state.excluded_auto = excluded
            st.session_state.late_start = [l for l in late if l.get("time") is not None]
            st.success(f"오전 인식 완료: 근무자 {len(names)} / 제외자 {len(excluded)} / 외출 {len(st.session_state.late_start)}")

with col[1]:
    if st.button("🧠 오후 인식"):
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            names, courses_pm, excluded_pm, early, _ = gpt_extract(a_file.read(), want_early=True)
            names = [correct_name_v2(n, all_staff, cutoff=0.5) for n in names]
            excluded_pm = [correct_name_v2(x, all_staff, cutoff=0.5) for x in excluded_pm]
            for e in early: e["name"] = correct_name_v2(e.get("name",""), all_staff, cutoff=0.5)

            st.session_state.a_names_raw = names
            # 제외자는 오전/오후 합집합으로 유지(오전값이 없으면 오후 것만)
            st.session_state.excluded_auto = sorted(
                set(st.session_state.get("excluded_auto", [])) | set(excluded_pm),
                key=lambda x: x
            )
            st.session_state.early_leave = [e for e in early if e.get("time") is not None]
            st.success(f"오후 인식 완료: 근무자 {len(names)} / 제외자 누적 {len(st.session_state.excluded_auto)} / 조퇴 {len(st.session_state.early_leave)}")

# =====================================
# 인식 결과 확인/수정 UI (스크롤)
# =====================================
st.markdown("<h4 style='font-size:18px;'>📝 인식 결과 확인 / 수정</h4>", unsafe_allow_html=True)
e1, e2, e3 = st.columns(3)
with e1:
    excluded_text = st.text_area("근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=160)
with e2:
    morning_text = st.text_area("🌅 오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=160)
with e3:
    afternoon_text = st.text_area("🌇 오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=160)

excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}
m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]
a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
m_norms = {normalize_name(x) for x in m_list} - excluded_set
a_norms = {normalize_name(x) for x in a_list} - excluded_set

late_start = st.session_state.get("late_start", [])
early_leave = st.session_state.get("early_leave", [])
course_records = st.session_state.get("m_course_records", [])
veh1_map = veh1_map  # from sidebar
veh2_map = veh2_map  # from sidebar
# =====================================
# 📋 오전 배정 생성
# =====================================
st.markdown("<h4 style='font-size:18px;'>📋 오전 근무 배정</h4>", unsafe_allow_html=True)
if st.button("✅ 오전 배정 생성"):
    try:
        # 🔑 열쇠 순번 (제외자 반영)
        key_filtered = [x for x in key_order if normalize_name(x) not in excluded_set]
        if key_filtered:
            norm_list = [normalize_name(x) for x in key_filtered]
            prev_norm = normalize_name(prev_key)
            if prev_norm in norm_list:
                idx = (norm_list.index(prev_norm) + 1) % len(key_filtered)
                today_key = key_filtered[idx]
            else:
                today_key = key_filtered[0]
        else:
            today_key = ""
        st.session_state.today_key = today_key

        # 🧑‍🏫 교양 1·2교시 (지각 반영)
        gy1 = pick_next_from_cycle(gyoyang_order, prev_gy5, m_norms)
        if gy1 and not can_attend_period_morning(gy1, 1, late_start):
            gy1 = pick_next_from_cycle(gyoyang_order, gy1, m_norms)
        used = {normalize_name(gy1)} if gy1 else set()
        gy2 = pick_next_from_cycle(gyoyang_order, gy1 or prev_gy5, m_norms - used)
        st.session_state.gy_base_pm = gy2 if gy2 else prev_gy5

        # 🔧 1종 수동
        sud_m, last = [], prev_sud
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, m_norms - {normalize_name(x) for x in sud_m})
            if not pick: break
            sud_m.append(pick); last = pick
        st.session_state.sud_base_pm = sud_m[-1] if sud_m else prev_sud

        # 🚘 2종 자동 (오전: 1종 제외)
        sud_norms = {normalize_name(x) for x in sud_m}
        auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]

        # 오전 차량 기록 (오후 비교용)
        st.session_state.morning_assigned_cars_1 = [get_vehicle(x, veh1_map) for x in sud_m if get_vehicle(x, veh1_map)]
        st.session_state.morning_assigned_cars_2 = [get_vehicle(x, veh2_map) for x in auto_m if get_vehicle(x, veh2_map)]
        st.session_state.morning_auto_names = auto_m + sud_m

        # === 출력 구성 ===
        out = []
        if today_key: out.append(f"열쇠: {today_key}")
        if gy1: out.append(f"1교시: {gy1}")
        if gy2: out.append(f"2교시: {gy2}")

        if sud_m:
            for nm in sud_m:
                out.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
            if sudong_count == 2 and len(sud_m) < 2:
                out.append("※ 수동 가능 인원이 1명입니다.")
        else:
            out.append("1종수동: (배정자 없음)")
            if sudong_count >= 1:
                out.append("※ 수동 가능 인원이 0명입니다.")

        if auto_m:
            out.append("2종자동:")
            for nm in auto_m:
                out.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # 🧭 코스점검 (오전만 출력)
        if course_records:
            out.append("")
            out.append("🧭 코스점검 결과:")
            for c in ["A","B"]:
                passed = [r["name"] for r in course_records if r["course"] == f"{c}코스" and r["result"] == "합격"]
                failed = [r["name"] for r in course_records if r["course"] == f"{c}코스" and r["result"] == "불합격"]
                if passed: out.append(f" • {c}코스 합격: {', '.join(passed)}")
                if failed: out.append(f" • {c}코스 불합격: {', '.join(failed)}")

        am_text = "\n".join(out)
        st.markdown("#### 🧾 오전 결과", unsafe_allow_html=True)
        st.code(am_text, language="text")

        # ✅ 결과 복사 (HTML 노출 없이 실제 복사)
        if st.button("📋 오전 결과 복사하기"):
            st.toast("✅ 복사 완료")
            st.write(f"<script>navigator.clipboard.writeText({json.dumps(am_text)});</script>", unsafe_allow_html=True)

    except Exception as e:
        st.error(f"오전 오류: {e}")
# =====================================
# 🌇 오후 배정 생성
# =====================================
st.markdown("<h4 style='font-size:18px;'>🌇 오후 근무 배정</h4>", unsafe_allow_html=True)
save_check = st.checkbox("이 결과를 전일 기준으로 저장", value=True)

if st.button("✅ 오후 배정 생성"):
    try:
        today_key = st.session_state.get("today_key", prev_key)
        gy_start = st.session_state.get("gy_base_pm", prev_gy5) or prev_gy5
        sud_base = st.session_state.get("sud_base_pm", prev_sud)

        # 🧑‍🏫 교양 3·4·5교시 (조퇴 반영)
        used=set(); gy3=gy4=gy5=None; last=gy_start
        for period in [3,4,5]:
            while True:
                pick = pick_next_from_cycle(gyoyang_order, last, a_norms - used)
                if not pick: break
                last = pick
                if can_attend_period_afternoon(pick, period, early_leave):
                    if period==3: gy3=pick
                    elif period==4: gy4=pick
                    else: gy5=pick
                    used.add(normalize_name(pick))
                    break

        # 🔧 오후 1종 수동
        sud_a, last = [], sud_base
        for _ in range(sudong_count):
            pick = pick_next_from_cycle(sudong_order, last, a_norms)  # 교양과 중복 허용
            if not pick: break
            sud_a.append(pick); last = pick
        used.update(normalize_name(x) for x in sud_a)

        # 🚘 오후 2종 자동 (1종 제외)
        sud_a_norms = {normalize_name(x) for x in sud_a}
        auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

        # === 출력 ===
        out=[]
        if today_key: out.append(f"열쇠: {today_key}")
        if gy3: out.append(f"3교시: {gy3}")
        if gy4: out.append(f"4교시: {gy4}")
        if gy5: out.append(f"5교시: {gy5}")

        if sud_a:
            for nm in sud_a:
                out.append(f"1종수동: {nm} {mark_car(get_vehicle(nm, veh1_map), repair_cars)}")
            if sudong_count==2 and len(sud_a)<2:
                out.append("※ 수동 가능 인원이 1명입니다.")
        else:
            out.append("1종수동: (배정자 없음)")

        if auto_a:
            out.append("2종자동:")
            for nm in auto_a:
                out.append(f" • {nm} {mark_car(get_vehicle(nm, veh2_map), repair_cars)}")

        # === 오전 대비 비교 ===
        out.append("")
        out.append("🔍 오전 대비 비교:")
        morning_auto_names = set(st.session_state.get("morning_auto_names", []))
        afternoon_auto_names = set(auto_a)
        afternoon_sud_norms = {normalize_name(x) for x in sud_a}

        added = sorted(list(afternoon_auto_names - morning_auto_names))
        morning_only = []
        for nm in morning_auto_names:
            nn = normalize_name(nm)
            if nn not in {normalize_name(x) for x in auto_a} and nn not in afternoon_sud_norms:
                morning_only.append(nm)
        missing = sorted(morning_only)

        # 신규 도로주행(오전엔 아니었는데 오후엔 도로주행)
        newly_joined = sorted([
            x for x in a_list
            if normalize_name(x) not in {normalize_name(y) for y in st.session_state.get("morning_auto_names", [])}
        ])

        if added:        out.append(" • 추가 인원: " + ", ".join(added))
        if missing:      out.append(" • 빠진 인원: " + ", ".join(missing))
        if newly_joined: out.append(" • 신규 도로주행 인원: " + ", ".join(newly_joined))

        # === 미배정 차량 (오전에 있었는데 오후에 빠진 차량만)
        am_c1 = set(st.session_state.get("morning_assigned_cars_1", []))
        am_c2 = set(st.session_state.get("morning_assigned_cars_2", []))
        pm_c1 = {get_vehicle(x, veh1_map) for x in sud_a if get_vehicle(x, veh1_map)}
        pm_c2 = {get_vehicle(x, veh2_map) for x in auto_a if get_vehicle(x, veh2_map)}
        un1 = sorted([c for c in am_c1 if c and c not in pm_c1])
        un2 = sorted([c for c in am_c2 if c and c not in pm_c2])
        if un1 or un2:
            out.append("")
            out.append("🚫 미배정 차량:")
            if un1:
                out.append(" [1종 수동]")
                for c in un1: out.append(f"  • {c} 마감")
            if un2:
                out.append(" [2종 자동]")
                for c in un2: out.append(f"  • {c} 마감")

        pm_text = "\n".join(out)
        st.markdown("#### 🧾 오후 결과", unsafe_allow_html=True)
        st.code(pm_text, language="text")

        # ✅ 결과 복사
        if st.button("📋 오후 결과 복사하기"):
            st.toast("✅ 복사 완료")
            st.write(f"<script>navigator.clipboard.writeText({json.dumps(pm_text)});</script>", unsafe_allow_html=True)

        # ✅ 전일 저장
        if save_check:
            best_gy = gy5 or gy4 or gy3 or prev_gy5
            save_json(PREV_FILE, {"열쇠": today_key, "교양_5교시": best_gy, "1종수동": (sud_a[-1] if sud_a else prev_sud)})
            st.success("전일근무.json 업데이트 완료")

    except Exception as e:
        st.error(f"오후 오류: {e}")
