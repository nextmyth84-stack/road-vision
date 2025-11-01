# =====================================
# app.py — 도로주행 근무 자동 배정 v7.41+ (Dropbox 연동 완전본)
# =====================================
import streamlit as st
from openai import OpenAI
import base64, re, json, os, difflib, html, random
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import dropbox  # ✅ Dropbox 연동 추가

# -----------------------
# 🕓 공통 헤더
# -----------------------
def kst_result_header(period_label: str) -> str:
    """예: '25.10.21(화) 오전 교양순서 및 차량배정'"""
    dt = datetime.now(ZoneInfo("Asia/Seoul"))
    yoil = "월화수목금토일"[dt.weekday()]
    return f"{dt.strftime('%y.%m.%d')}({yoil}) {period_label} 교양순서 및 차량배정"


# -----------------------
# ⚙️ 기본 설정
# -----------------------
st.set_page_config(layout="wide")
st.markdown("""
<h3 style='text-align:center; color:#1e3a8a;'> 도로주행 근무 자동 배정 </h3>
<p style='text-align:center; font-size:6px; color:#64748b; margin-top:-6px;'>
    Developed by <b>wook</b>
</p>
""", unsafe_allow_html=True)


# -----------------------
# 🔑 OpenAI API 연결
# -----------------------
try:
    client = OpenAI(api_key=st.secrets["general"]["OPENAI_API_KEY"])
except Exception:
    st.error("⚠️ OPENAI_API_KEY 설정 필요 (Streamlit Secrets에 추가하세요)")
    st.stop()
MODEL_NAME = "gpt-4o"


# -----------------------
# ☁️ Dropbox 연결 (전일근무자 자동저장/복원)
# -----------------------
@st.cache_resource
def connect_dropbox():
    token = st.secrets["general"].get("DROPBOX_TOKEN")
    if not token:
        st.error("⚠️ DROPBOX_TOKEN이 누락되었습니다.\nStreamlit Secrets에 추가해야 합니다.")
        st.stop()
    try:
        dbx = dropbox.Dropbox(token)
        dbx.users_get_current_account()
        return dbx
    except Exception as e:
        st.error(f"Dropbox 연결 실패: {e}")
        st.stop()

dbx = connect_dropbox()


def dropbox_save_prev(data: dict):
    """Dropbox에 오늘 날짜 기준 전일근무자 파일 저장"""
    fname = f"/전일근무자_{date.today().strftime('%Y%m%d')}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        dbx.files_upload(content.encode("utf-8"), fname, mode=dropbox.files.WriteMode.overwrite)
        st.sidebar.success("✅ Dropbox 전일근무자 저장 완료")
    except Exception as e:
        st.sidebar.error(f"❌ Dropbox 저장 실패: {e}")


def dropbox_load_prev(days_ago=1):
    """Dropbox에서 어제자 전일근무자 자동 복원"""
    fname = f"/전일근무자_{(date.today() - timedelta(days=days_ago)).strftime('%Y%m%d')}.json"
    try:
        _, res = dbx.files_download(fname)
        data = json.loads(res.content)
        st.sidebar.info("📥 Dropbox 전일근무자 복원 완료")
        return data
    except Exception:
        return {"열쇠": "", "교양_5교시": "", "1종수동": "", "1종자동": ""}


# -----------------------
# 🧾 JSON 유틸
# -----------------------
def load_json(file, default=None):
    if not os.path.exists(file):
        return default
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default


def save_json(file, data):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"저장 실패: {e}")


# -----------------------
# 📋 클립보드 복사 버튼 (모바일 호환)
# -----------------------
def clipboard_copy_button(label, text):
    btn_id = f"btn_{abs(hash(label+text))}"
    safe = (text or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    html_js = f"""
    <button id='{btn_id}' style="background:#2563eb;color:white;border:none;
    padding:8px 14px;border-radius:8px;cursor:pointer;margin-top:8px;">
      {label}
    </button>
    <script>
    (function(){{
      var b=document.getElementById('{btn_id}');
      if(!b)return;
      b.addEventListener('click', async function(){{
        try{{
          await navigator.clipboard.writeText("{safe}");
          var t=b.innerText; b.innerText="✅ 복사됨!";
          setTimeout(()=>b.innerText=t, 1800);
        }}catch(e){{
          alert('복사가 지원되지 않는 브라우저입니다. 텍스트를 길게 눌러 복사하세요.');
        }}
      }});
    }} )();
    </script>
    """
    st.components.v1.html(html_js, height=52)


# -----------------------
# ⚙️ 이름 정규화 / 차량 / 교정 / 순번
# -----------------------
def normalize_name(s):
    """괄호·공백·특수문자 제거 → 순수 한글 이름"""
    return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))


def get_vehicle(name, veh_map):
    nkey = normalize_name(name)
    for car, nm in veh_map.items():
        if normalize_name(nm) == nkey:
            return car
    return ""


def _norm_car_id(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", "", str(s)).strip()


def mark_car(car, repair_cars):
    if not car:
        return ""
    car_norm = _norm_car_id(car)
    repairs_norm = {_norm_car_id(x) for x in (repair_cars or [])}
    return f"{car}{' (정비중)' if car_norm in repairs_norm else ''}"


def car_num_key(car_id: str):
    m = re.search(r"(\d+)", car_id or "")
    return int(m.group(1)) if m else 10**9


def pick_next_from_cycle(cycle, last, allowed_norms: set):
    if not cycle:
        return None
    cycle_norm = [normalize_name(x) for x in cycle]
    last_norm = normalize_name(last)
    start = (cycle_norm.index(last_norm) + 1) % len(cycle) if last_norm in cycle_norm else 0
    for i in range(len(cycle) * 2):
        cand = cycle[(start + i) % len(cycle)]
        if normalize_name(cand) in allowed_norms:
            return cand
    return None


def correct_name_v2(name, employee_list, cutoff=0.6):
    """전체 근무자와 유사도 비교로 OCR 오타 교정"""
    name_norm = normalize_name(name)
    if not name_norm:
        return name
    best, best_score = None, 0.0
    for cand in employee_list:
        score = difflib.SequenceMatcher(None, normalize_name(cand), name_norm).ratio()
        if score > best_score:
            best_score, best = score, cand
    return best if best and best_score >= cutoff else name


# -----------------------
# 📥 전일 근무자 Dropbox에서 복원
# -----------------------
prev_data = dropbox_load_prev()
prev_key = prev_data.get("열쇠", "")
prev_gyoyang5 = prev_data.get("교양_5교시", "")
prev_sudong = prev_data.get("1종수동", "")
prev_auto1 = prev_data.get("1종자동", "")

# -----------------------
# 📦 JSON 기반 순번 / 차량 / 근무자 관리
# -----------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
files = {
    "열쇠": "열쇠순번.json",
    "교양": "교양순번.json",
    "1종": "1종순번.json",
    "veh1": "1종차량표.json",
    "veh2": "2종차량표.json",
    "employees": "전체근무자.json",
    "1종자동": "1종자동순번.json",
    "repair": "정비차량.json",
}
for k, v in files.items():
    files[k] = os.path.join(DATA_DIR, v)

default_data = {
    "열쇠": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조윤영","조정래"],
    "교양": ["권한솔","김남균","김면정","김병욱","김성연","김주현","김지은","안유미","이호석","조정래"],
    "1종":  ["권한솔","김남균","김성연","김주현","이호석","조정래"],
    "veh1": {"2호":"조정래","5호":"권한솔","7호":"김남균","8호":"이호석","9호":"김주현","10호":"김성연"},
    "veh2": {"4호":"김남균","5호":"김병욱","6호":"김지은","12호":"안유미","14호":"김면정","15호":"이호석","17호":"김성연","18호":"권한솔","19호":"김주현","22호":"조정래"},
    "employees": ["권한솔","김남균","김면정","김성연","김지은","안유미","윤여헌","윤원실","이나래","이호석","조정래","김병욱","김주현"],
    "1종자동": ["21호", "22호", "23호", "24호"],
    "repair": {"1종수동": [], "1종자동": [], "2종자동": []},
}
for k, v in files.items():
    if not os.path.exists(v):
        try:
            with open(v, "w", encoding="utf-8") as f:
                json.dump(default_data[k], f, ensure_ascii=False, indent=2)
        except Exception as e:
            st.error(f"{v} 초기화 실패: {e}")

# 로드
key_order     = load_json(files["열쇠"])
gyoyang_order = load_json(files["교양"])
sudong_order  = load_json(files["1종"])
veh1_map      = load_json(files["veh1"])
veh2_map      = load_json(files["veh2"])
employee_list = load_json(files["employees"])
auto1_order   = load_json(files["1종자동"])

# 정비 차량 로드 (하위호환: list ⇒ dict)
_repair_raw = load_json(files["repair"])
if isinstance(_repair_raw, dict):
    repair_saved = {
        "1종수동": _repair_raw.get("1종수동", []),
        "1종자동": _repair_raw.get("1종자동", []),
        "2종자동": _repair_raw.get("2종자동", []),
    }
elif isinstance(_repair_raw, list):
    repair_saved = {"1종수동": _repair_raw, "1종자동": _repair_raw, "2종자동": _repair_raw}
else:
    repair_saved = {"1종수동": [], "1종자동": [], "2종자동": []}
repair_union = sorted(set(repair_saved["1종수동"] + repair_saved["1종자동"] + repair_saved["2종자동"]), key=car_num_key)

# -----------------------
# 🎛 사이드바 디자인
# -----------------------
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"] {
    background-color: #f8fafc;
    padding: 10px;
    border-right: 1px solid #e5e7eb;
    min-width: 340px; width: 340px; flex: 0 0 340px;
}
@media (min-width: 1200px) {
  section[data-testid="stSidebar"] { width: 360px; flex: 0 0 360px; }
}
@media (min-width: 992px) and (max-width: 1199px) {
  section[data-testid="stSidebar"] { width: 340px; flex: 0 0 340px; }
}
@media (max-width: 991px) {
  section[data-testid="stSidebar"] { min-width: 280px; width: 85vw; flex: 0 0 auto; }
}
.streamlit-expanderHeader { font-weight: 700 !important; color: #1e3a8a !important; font-size: 15px !important; }
textarea, input { font-size: 14px !important; }
div.stButton > button { background-color: #2563eb; color: white; border: none; border-radius: 8px; padding: 6px 12px; margin-top: 6px; font-weight: 600; }
div.stButton > button:hover { background-color: #1d4ed8; }
.sidebar-subtitle { font-weight: 600; color: #334155; margin-top: 10px; margin-bottom: 4px; }
.repair-box { border: 1px solid #fdba74; background: #fff7ed; padding: 8px 10px; border-radius: 8px; color: #7c2d12; font-size: 13px; }
.btn-desc{ font-size: 13px; color: #475569; margin-top: 6px; line-height: 1.5; }
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("<h3 style='text-align:center; color:#1e3a8a;'>⚙️ 근무자 설정 </h3>", unsafe_allow_html=True)

# -----------------------
# 🗓 전일 근무자 (Dropbox 연동)
# -----------------------
with st.sidebar.expander("🗓 전일 근무자", expanded=True):
    prev_key = st.text_input("🔑 전일 열쇠 담당", prev_key)
    prev_gyoyang5 = st.text_input("🧑‍🏫 전일 교양(5교시)", prev_gyoyang5)
    prev_sudong = st.text_input("🚚 전일 1종 수동", prev_sudong)
    prev_auto1 = st.text_input("🚗 전일 1종 자동", prev_auto1)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Dropbox 저장", key="btn_prev_save"):
            dropbox_save_prev({
                "열쇠": prev_key,
                "교양_5교시": prev_gyoyang5,
                "1종수동": prev_sudong,
                "1종자동": prev_auto1,
            })
    with c2:
        if st.button("📥 Dropbox 복원", key="btn_prev_load"):
            restored = dropbox_load_prev()
            # UI 값 반영 후 리렌더
            prev_key = restored.get("열쇠", "")
            prev_gyoyang5 = restored.get("교양_5교시", "")
            prev_sudong = restored.get("1종수동", "")
            prev_auto1 = restored.get("1종자동", "")
            st.experimental_rerun()

# -----------------------
# 🌅 아침 열쇠 담당
# -----------------------
MORNING_KEY_FILE = os.path.join(DATA_DIR, "아침열쇠.json")
morning_key = load_json(MORNING_KEY_FILE, {})

with st.sidebar.expander("🌅 아침 열쇠 담당", expanded=False):
    mk_name = st.text_input("아침열쇠 담당자 이름", morning_key.get("name", ""))
    mk_start = st.date_input(
        "시작일",
        value=datetime.fromisoformat(morning_key.get("start")) if morning_key.get("start") else datetime.now().date(),
    )
    mk_end = st.date_input(
        "종료일",
        value=datetime.fromisoformat(morning_key.get("end")) if morning_key.get("end") else datetime.now().date(),
    )
    if st.button("💾 아침열쇠 저장", key="btn_morning_key_save"):
        data = {"name": mk_name, "start": str(mk_start), "end": str(mk_end)}
        save_json(MORNING_KEY_FILE, data)
        st.success("아침열쇠 담당자 저장 완료 ✅")

# -----------------------
# 📂 데이터 관리 (순번/차량/근무자)
# -----------------------
with st.sidebar.expander("📂 데이터 관리", expanded=False):

    # 🔢 순번표 관리
    with st.expander("🔢 순번표 관리", expanded=False):
        st.markdown("<div class='sidebar-subtitle'>열쇠 순번</div>", unsafe_allow_html=True)
        t1 = st.text_area("", "\n".join(key_order), height=150)
        st.markdown("<div class='sidebar-subtitle'>교양 순번</div>", unsafe_allow_html=True)
        t2 = st.text_area("", "\n".join(gyoyang_order), height=150)
        st.markdown("<div class='sidebar-subtitle'>1종 수동 순번</div>", unsafe_allow_html=True)
        t3 = st.text_area("", "\n".join(sudong_order), height=120)
        st.markdown("<div class='sidebar-subtitle'>1종 자동 순번</div>", unsafe_allow_html=True)
        t4 = st.text_area("", "\n".join(auto1_order or []), height=100)

        if st.button("💾 순번표 저장", key="btn_save_orders"):
            save_json(files["열쇠"], [x.strip() for x in t1.splitlines() if x.strip()])
            save_json(files["교양"], [x.strip() for x in t2.splitlines() if x.strip()])
            save_json(files["1종"], [x.strip() for x in t3.splitlines() if x.strip()])
            save_json(files["1종자동"], [x.strip() for x in (t4.splitlines() if t4 else []) if x.strip()])

            key_order[:]     = load_json(files["열쇠"])
            gyoyang_order[:] = load_json(files["교양"])
            sudong_order[:]  = load_json(files["1종"])
            auto1_order[:]   = load_json(files["1종자동"])

            st.session_state["key_order"] = key_order
            st.session_state["gyoyang_order"] = gyoyang_order
            st.session_state["sudong_order"] = sudong_order
            st.session_state["auto1_order"] = auto1_order

            st.success("순번표 저장 완료 ✅ (오후 탭 즉시 반영)")

    # 🚘 차량 담당 관리
    with st.expander("🚘 차량 담당 관리", expanded=False):
        st.markdown("<div class='sidebar-subtitle'>1종 수동 차량표</div>", unsafe_allow_html=True)
        t1v = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh1_map.items()]), height=130)
        st.markdown("<div class='sidebar-subtitle'>2종 자동 차량표</div>", unsafe_allow_html=True)
        t2v = st.text_area("", "\n".join([f"{car} {nm}" for car, nm in veh2_map.items()]), height=160)

        if st.button("💾 차량표 저장", key="btn_save_veh"):
            veh1_new, veh2_new = {}, {}
            for line in t1v.splitlines():
                p = line.strip().split()
                if len(p) >= 2: veh1_new[p[0]] = " ".join(p[1:])
            for line in t2v.splitlines():
                p = line.strip().split()
                if len(p) >= 2: veh2_new[p[0]] = " ".join(p[1:])
            save_json(files["veh1"], veh1_new)
            save_json(files["veh2"], veh2_new)
            veh1_map = load_json(files["veh1"])
            veh2_map = load_json(files["veh2"])
            st.success("차량표 저장 완료 ✅")

    # 👥 전체 근무자
    with st.expander("👥 전체 근무자", expanded=False):
        st.markdown("<div class='sidebar-subtitle'>근무자 목록</div>", unsafe_allow_html=True)
        t_emp = st.text_area("", "\n".join(employee_list), height=180)
        if st.button("💾 근무자 저장", key="btn_save_emp"):
            save_json(files["employees"], [x.strip() for x in t_emp.splitlines() if x.strip()])
            employee_list = load_json(files["employees"])
            st.success("근무자 명단 저장 완료 ✅")

# -----------------------
# ⚙️ 추가 설정 + 정비차량 그룹
# -----------------------
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 추가 설정")
sudong_count = st.sidebar.radio("1종 수동 인원 수", [1, 2], index=0)
st.sidebar.caption("정비차량 추가/삭제는 아래 ‘정비 차량 목록’에서 관리하세요.")

opt_1s = sorted(list((veh1_map or {}).keys()), key=car_num_key)
opt_1a = sorted(list((st.session_state.get("auto1_order") or auto1_order or [])), key=car_num_key)
opt_2a = sorted(list((veh2_map or {}).keys()), key=car_num_key)

def _defaults(saved_list, opts):
    s = set(saved_list or [])
    return [x for x in opts if x in s]

with st.sidebar.expander("🛠 정비 차량 목록", expanded=False):
    with st.expander(" 1종 수동 정비", expanded=False):
        sel_1s = st.multiselect("정비 차량 (1종 수동)", options=opt_1s,
                                default=_defaults(repair_saved["1종수동"], opt_1s), key="repair_sel_1s")
    with st.expander(" 1종 자동 정비", expanded=False):
        sel_1a = st.multiselect("정비 차량 (1종 자동)", options=opt_1a,
                                default=_defaults(repair_saved["1종자동"], opt_1a), key="repair_sel_1a")
    with st.expander(" 2종 자동 정비", expanded=False):
        sel_2a = st.multiselect("정비 차량 (2종 자동)", options=opt_2a,
                                default=_defaults(repair_saved["2종자동"], opt_2a), key="repair_sel_2a")

    payload = {
        "1종수동": sorted(set(sel_1s or []), key=car_num_key),
        "1종자동": sorted(set(sel_1a or []), key=car_num_key),
        "2종자동": sorted(set(sel_2a or []), key=car_num_key),
    }
    if st.button("💾 정비 차량 저장", key="repair_save_btn"):
        save_json(files["repair"], payload)
        repair_saved = payload
        st.session_state["repair_1s"] = payload["1종수동"]
        st.session_state["repair_1a"] = payload["1종자동"]
        st.session_state["repair_2a"] = payload["2종자동"]
        st.session_state["repair_cars"] = sorted(
            set(payload["1종수동"] + payload["1종자동"] + payload["2종자동"]), key=car_num_key
        )
        st.success("정비 차량 저장 완료 ✅")

    st.markdown(
        f"""<div class="repair-box">
        <b>현재 정비 차량</b><br>
        [1종 수동] {", ".join(repair_saved["1종수동"]) if repair_saved["1종수동"] else "없음"}<br>
        [1종 자동] {", ".join(repair_saved["1종자동"]) if repair_saved["1종자동"] else "없음"}<br>
        [2종 자동] {", ".join(repair_saved["2종자동"]) if repair_saved["2종자동"] else "없음"}
        </div>""",
        unsafe_allow_html=True
    )

# -----------------------
# 📝 메모장
# -----------------------
MEMO_FILE = os.path.join(DATA_DIR, "메모장.json")
memo_text = ""
if os.path.exists(MEMO_FILE):
    try:
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            memo_text = json.load(f).get("memo", "")
    except:
        memo_text = ""

with st.sidebar.expander("📝 메모장", expanded=False):
    st.markdown("<div class='sidebar-subtitle'>운영 메모 / 특이사항 기록</div>", unsafe_allow_html=True)
    memo_input = st.text_area("", memo_text, height=140, placeholder="예: 10월 27일 - 5호차 브레이크 경고등 점등")
    if st.button("💾 메모 저장", key="btn_save_memo"):
        try:
            with open(MEMO_FILE, "w", encoding="utf-8") as f:
                json.dump({"memo": memo_input}, f, ensure_ascii=False, indent=2)
            st.success("메모 저장 완료 ✅")
        except Exception as e:
            st.error(f"메모 저장 실패: {e}")

# -----------------------
# 🔤 컷오프 슬라이더 + 푸터 + 세션 반영
# -----------------------
cutoff = st.sidebar.slider("OCR 오타교정 컷오프 (낮을수록 공격적 교정)", 0.4, 0.9, 0.6, 0.05)
st.sidebar.markdown("<p style='text-align:center; font-size:8px; color:#94a3b8;'>powered by <b>wook</b></p>", unsafe_allow_html=True)

st.session_state.update({
    "key_order": key_order, "gyoyang_order": gyoyang_order, "sudong_order": sudong_order,
    "veh1": veh1_map, "veh2": veh2_map, "employee_list": employee_list,
    "sudong_count": sudong_count,
    "repair_1s": repair_saved["1종수동"],
    "repair_1a": repair_saved["1종자동"],
    "repair_2a": repair_saved["2종자동"],
    "repair_cars": repair_union,
    "cutoff": cutoff,
    "auto1_order": auto1_order,
})
# -----------------------
# 📊 GPT OCR (이름/코스/제외자/지각/조퇴)
# -----------------------
def gpt_extract(img_bytes, want_early=False, want_late=False, want_excluded=False):
    """
    반환: names, course_records, excluded, early_leave, late_start
    """
    b64 = base64.b64encode(img_bytes).decode()
    user = (
        "이 이미지는 운전면허시험 근무표입니다.\n"
        "1) '학과','기능','PC','초소'는 제외하고 도로주행 근무자만 추출.\n"
        "2) 이름 옆 괄호의 'A-합','B-불' 등은 코스점검 결과.\n"
        "3) '휴가, 교육, 출장, 연가' 표시는 excluded.\n"
        "4) '지각/10시 출근'은 late_start, '조퇴'는 early_leave.\n"
        "JSON 형식으로 반환하세요."
    )

    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "도로주행 근무표 분석 JSON 출력"},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
        )
        raw = res.choices[0].message["content"] if isinstance(res.choices[0].message, dict) else res.choices[0].message.content
        js = json.loads(re.search(r"\{[\s\S]*\}", raw).group(0)) if re.search(r"\{[\s\S]*\}", raw) else {}
        raw_names = js.get("names", [])
        names, course_records = [], []
        for n in raw_names:
            m = re.search(r"([가-힣]+)\s*\(([^)]*)\)", n)
            if m:
                nm = m.group(1); detail = m.group(2).upper()
                course = "A" if "A" in detail else ("B" if "B" in detail else None)
                result = "합격" if "합" in detail else ("불합격" if "불" in detail else None)
                if course and result:
                    course_records.append({"name": nm, "course": f"{course}코스", "result": result})
                names.append(nm)
            else:
                names.append(n.strip())
        excluded = js.get("excluded", []) if want_excluded else []
        early_leave = js.get("early_leave", []) if want_early else []
        late_start = js.get("late_start", []) if want_late else []
        return names, course_records, excluded, early_leave, late_start
    except Exception as e:
        st.error(f"OCR 실패: {e}")
        return [], [], [], [], []

# -----------------------
# ⏰ 교양 시간 제한 규칙
# -----------------------
def can_attend_period_morning(name_pure: str, period:int, late_list):
    """10시 이후 출근자는 1교시 불가"""
    tmap = {1: 9.0, 2: 10.5}
    nn = normalize_name(name_pure)
    for e in late_list or []:
        if normalize_name(e.get("name","")) == nn:
            try:
                return float(e.get("time", 99)) <= tmap[period]
            except:
                return True
    return True


def can_attend_period_afternoon(name_pure: str, period:int, early_list):
    """조퇴자 오후 제한"""
    tmap = {3: 13.0, 4: 14.5, 5: 16.0}
    nn = normalize_name(name_pure)
    for e in early_list or []:
        if normalize_name(e.get("name","")) == nn:
            try:
                return float(e.get("time", 0)) > tmap[period]
            except:
                return True
    return True

# -----------------------
# 🌞 탭 UI 구성 (오전/오후)
# -----------------------
tab1, tab2 = st.tabs([" 오전 근무", " 오후 근무"])
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] { display: flex; justify-content: center; gap: 12px; }
.stTabs [data-baseweb="tab"] { font-size: 20px; padding: 16px 40px; border-radius: 10px 10px 0 0; background-color: #d1d5db; }
.stTabs [aria-selected="true"] { background-color: #2563eb !important; color: white !important; font-weight: 700; }
.result-pre { white-space: pre-wrap; font-family: ui-monospace, Consolas, monospace; background: #0b1021; color: #e5e7eb; border-radius: 8px; padding: 12px; border: 1px solid #1f2937; }
.repair-tag { color: #ef4444; font-weight: 700; }
.btn-desc{ font-size: 13px; color: #475569; margin-top: 6px; line-height: 1.5; }
</style>
""", unsafe_allow_html=True)

def render_result_with_repair_color(text: str) -> str:
    esc = html.escape(text or "")
    esc = esc.replace("(정비중)", "<span class='repair-tag'>(정비중)</span>")
    return f"<pre class='result-pre'>{esc}</pre>"

# -----------------------
# 🌅 오전 근무 탭
# -----------------------
with tab1:
    st.markdown(
        "<p style='font-size:16px; color:#2563eb; margin-top:-8px;'>※ 전일근무자 확인 후 진행하세요.</p>",
        unsafe_allow_html=True
    )
    col1, col2 = st.columns(2)
    with col1:
        m_file = st.file_uploader("📸 오전 근무표 업로드", type=["png","jpg","jpeg"], key="m_upload")
    with col2:
        pass

    col_btn, col_desc = st.columns([1, 4])
    with col_btn:
        run_m = st.button("오전 GPT 인식", key="btn_m_ocr")
    with col_desc:
        st.markdown(
            """<div class='btn-desc'>
            GPT 인식 버튼을 누르고 <b>실제 근무자와 비교</b>하세요.<br>
            품질이 낮은 이미지는 인식이 잘 안될 수 있습니다.
            </div>""",
            unsafe_allow_html=True
        )
        if m_file is not None:
            st.image(m_file, caption="오전 근무표 미리보기", use_container_width=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    if run_m:
        if not m_file:
            st.warning("오전 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 분석 중..."):
                names, course, excluded, early, late = gpt_extract(m_file.read(), True, True, True)
                fixed = [correct_name_v2(n, employee_list) for n in names]
                excluded_fixed = [correct_name_v2(n, employee_list) for n in excluded]
                st.session_state["m_names_raw"] = fixed
                st.session_state["excluded_auto"] = excluded_fixed
                st.session_state["early_leave"] = early
                st.session_state["late_start"] = late
                st.success(f"오전 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    excluded_text = st.text_area("🚫 근무 제외자", "\n".join(st.session_state.get("excluded_auto", [])), height=120)
    morning_text = st.text_area("☀️ 오전 근무자", "\n".join(st.session_state.get("m_names_raw", [])), height=220)

    m_list = [x.strip() for x in morning_text.splitlines() if x.strip()]
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}
    m_norms = {normalize_name(x) for x in m_list} - excluded_set

    if st.button("📋 오전 배정 생성"):
        try:
            key_order     = st.session_state.get("key_order", [])
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            sudong_count  = st.session_state.get("sudong_count", 1)
            repair_1s     = st.session_state.get("repair_1s", [])
            repair_1a     = st.session_state.get("repair_1a", [])
            repair_2a     = st.session_state.get("repair_2a", [])
            auto1_order   = st.session_state.get("auto1_order", [])

            # 🔑 열쇠 배정
            today_key = pick_next_from_cycle(key_order, prev_key, m_norms)
            # 교양
            gy1 = pick_next_from_cycle(gyoyang_order, prev_gyoyang5, m_norms)
            gy2 = pick_next_from_cycle(gyoyang_order, gy1, m_norms)
            # 수동
            sud_m, last = [], prev_sudong
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, m_norms)
                if not pick: break
                sud_m.append(pick); last = pick
            # 자동
            sud_norms = {normalize_name(x) for x in sud_m}
            auto_m = [x for x in m_list if normalize_name(x) in (m_norms - sud_norms)]
            # 1종자동 순번
            today_auto1 = pick_next_from_cycle(auto1_order, prev_auto1, set(auto1_order))

            # === 결과 출력 ===
            lines = [kst_result_header("오전"), ""]
            if today_key: lines.append(f"열쇠: {today_key}\n")
            if gy1: lines.append(f"1교시: {gy1}")
            if gy2: lines.append(f"2교시: {gy2}\n")
            for nm in sud_m:
                lines.append(f"1종수동: {mark_car(get_vehicle(nm, veh1_map), repair_1s)} {nm}")
            if today_auto1:
                lines.append(f"\n1종자동: {mark_car(today_auto1, repair_1a)}")
            if auto_m:
                lines.append("\n2종자동:")
                for nm in auto_m:
                    car = mark_car(get_vehicle(nm, veh2_map), repair_2a)
                    lines.append(f" • {car} {nm}" if car else f" • {nm}")

            am_text = "\n".join(lines)
            st.markdown("#### 📋 오전 결과")
            st.code(am_text, language="text")
            clipboard_copy_button("📋 복사", am_text)

            # 오전결과 저장
            morning_data = {
                "today_key": today_key,
                "gyoyang_base_for_pm": gy2 or prev_gyoyang5,
                "sudong_base_for_pm": sud_m[-1] if sud_m else prev_sudong,
                "today_auto1": today_auto1,
                "timestamp": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%y.%m.%d %H:%M"),
            }
            save_json(os.path.join(DATA_DIR, "오전결과.json"), morning_data)
            st.info("✅ 오전 결과 저장 완료")

        except Exception as e:
            st.error(f"오전 오류: {e}")
# =====================================
# 🌇 오후 근무 탭
# =====================================
with tab2:
    # ✅ 오전결과 자동 복원
    MORNING_FILE = os.path.join(DATA_DIR, "오전결과.json")
    if os.path.exists(MORNING_FILE):
        morning_cache = load_json(MORNING_FILE, {})
        st.session_state["today_key"] = morning_cache.get("today_key", prev_key)
        st.session_state["gyoyang_base_for_pm"] = morning_cache.get("gyoyang_base_for_pm", prev_gyoyang5)
        st.session_state["sudong_base_for_pm"] = morning_cache.get("sudong_base_for_pm", prev_sudong)
        st.session_state["today_auto1"] = morning_cache.get("today_auto1", prev_auto1)
        if morning_cache.get("timestamp"):
            st.caption(f"🕒 오전 결과 복원 완료 ({morning_cache['timestamp']})")

    # === OCR 업로드 ===
    col1, col2 = st.columns(2)
    with col1:
        a_file = st.file_uploader("📸 오후 근무표 업로드", type=["png","jpg","jpeg"], key="a_upload")
    with col2:
        pass

    col_btn, col_desc = st.columns([1, 4])
    with col_btn:
        run_a = st.button("오후 GPT 인식", key="btn_a_ocr")
    with col_desc:
        st.markdown(
            """<div class='btn-desc'>
            GPT 인식 버튼을 누르고 <b>실제 근무자와 비교</b>하세요.<br>
            품질이 낮은 이미지는 인식이 잘 안될 수 있습니다.
            </div>""",
            unsafe_allow_html=True
        )
        if a_file is not None:
            st.image(a_file, caption="오후 근무표 미리보기", use_container_width=True)

    if run_a:
        if not a_file:
            st.warning("오후 이미지를 업로드하세요.")
        else:
            with st.spinner("🧩 GPT 분석 중..."):
                names, _, excluded, early, late = gpt_extract(a_file.read(), True, True, True)
                fixed = [correct_name_v2(n, employee_list) for n in names]
                excluded_fixed = [correct_name_v2(n, employee_list) for n in excluded]
                st.session_state["a_names_raw"] = fixed
                st.session_state["excluded_auto_pm"] = excluded_fixed
                st.session_state["early_leave_pm"] = early
                st.session_state["late_start_pm"] = late
                st.success(f"오후 인식 완료 → 근무자 {len(fixed)}명, 제외자 {len(excluded_fixed)}명")

    afternoon_text = st.text_area("🌥️ 오후 근무자", "\n".join(st.session_state.get("a_names_raw", [])), height=220)
    excluded_text = st.text_area("🚫 제외자", "\n".join(st.session_state.get("excluded_auto_pm", [])), height=100)
    a_list = [x.strip() for x in afternoon_text.splitlines() if x.strip()]
    excluded_set = {normalize_name(x) for x in excluded_text.splitlines() if x.strip()}
    a_norms = {normalize_name(x) for x in a_list} - excluded_set

    if st.button("📋 오후 배정 생성"):
        try:
            gyoyang_order = st.session_state.get("gyoyang_order", [])
            sudong_order  = st.session_state.get("sudong_order", [])
            veh1_map      = st.session_state.get("veh1", {})
            veh2_map      = st.session_state.get("veh2", {})
            repair_1s     = st.session_state.get("repair_1s", [])
            repair_1a     = st.session_state.get("repair_1a", [])
            repair_2a     = st.session_state.get("repair_2a", [])
            sudong_count  = st.session_state.get("sudong_count", 1)

            today_key = st.session_state.get("today_key", prev_key)
            gy_start = st.session_state.get("gyoyang_base_for_pm", prev_gyoyang5)
            sud_base = st.session_state.get("sudong_base_for_pm", prev_sudong)
            today_auto1 = st.session_state.get("today_auto1", prev_auto1)
            early_leave = st.session_state.get("early_leave_pm", [])

            # === 교양 ===
            used = set()
            gy3 = pick_next_from_cycle(gyoyang_order, gy_start, a_norms - used)
            gy4 = pick_next_from_cycle(gyoyang_order, gy3, a_norms - used)
            gy5 = pick_next_from_cycle(gyoyang_order, gy4, a_norms - used)
            # === 수동 ===
            sud_a, last = [], sud_base
            for _ in range(sudong_count):
                pick = pick_next_from_cycle(sudong_order, last, a_norms)
                if not pick: break
                sud_a.append(pick); last = pick
            sud_a_norms = {normalize_name(x) for x in sud_a}
            auto_a = [x for x in a_list if normalize_name(x) in (a_norms - sud_a_norms)]

            # === 결과 생성 ===
            lines = [kst_result_header("오후"), ""]
            if today_key: lines.append(f"열쇠: {today_key}\n")
            if gy3: lines.append(f"3교시: {gy3}")
            if gy4: lines.append(f"4교시: {gy4}")
            if gy5: lines.append(f"5교시: {gy5}\n")
            for nm in sud_a:
                lines.append(f"1종수동: {mark_car(get_vehicle(nm, veh1_map), repair_1s)} {nm}")
            if today_auto1:
                lines.append(f"\n1종자동: {mark_car(today_auto1, repair_1a)}")
            if auto_a:
                lines.append("\n2종자동:")
                for nm in auto_a:
                    car = mark_car(get_vehicle(nm, veh2_map), repair_2a)
                    lines.append(f" • {car} {nm}" if car else f" • {nm}")

            pm_result_text = "\n".join(lines)
            st.markdown("#### 🌇 오후 근무 결과")
            st.code(pm_result_text, language="text")
            clipboard_copy_button("📋 복사", pm_result_text)

            # === Dropbox 전일근무자 저장용 데이터 ===
            st.session_state["pm_save_ready"] = {
                "열쇠": today_key,
                "교양_5교시": gy5 or gy4 or gy3 or prev_gyoyang5,
                "1종수동": (sud_a[-1] if sud_a else prev_sudong),
                "1종자동": today_auto1 or prev_auto1,
            }

        except Exception as e:
            st.error(f"오후 오류: {e}")

    # === 전일근무자 Dropbox 자동저장 ===
    st.markdown("<h4 style='font-size:18px;'>💾 전일근무자 Dropbox 저장</h4>", unsafe_allow_html=True)
    if st.button("💾 Dropbox에 저장", key="btn_save_prev_pm"):
        data = st.session_state.get("pm_save_ready")
        if not data:
            st.warning("❌ 먼저 ‘오후 근무 배정 생성’을 실행하세요.")
        else:
            dropbox_save_prev(data)
            st.success("✅ Dropbox 전일근무자 저장 완료")
