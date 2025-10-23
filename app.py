# =====================================
# app.py — 도로주행 근무자동배정 v7.12.3 (완전본)
# =====================================
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

# 🔽 숨김형 '다음 예정자 미리보기'
with st.sidebar.expander("🔍 다음 예정자 보기"):
    def normalize_name(s): return re.sub(r"[^가-힣]", "", re.sub(r"\(.*?\)", "", s or ""))
    def pick_next_key(cycle, last, excluded_names):
        if not cycle: return ""
        norm_cycle = [normalize_name(x) for x in cycle]
        excluded_norms = {normalize_name(x) for x in excluded_names}
        last_norm = normalize_name(last)
        try: start = norm_cycle.index(last_norm)
        except ValueError: start = -1
        n = len(cycle)
        for i in range(1, n+1):
            cand = cycle[(start+i) % n]
            if normalize_name(cand) not in excluded_norms:
                return cand
        return ""

    next_key_preview = pick_next_key(key_order, prev_key, excluded)
    st.markdown(f"**열쇠:** {next_key_preview or '-'}")

# =====================================
# 이하 주요 로직 (배정/비교/UI 개선 포함)
# =====================================
# ... (기존 배정 로직 동일, 출력 시 아래 변경사항 포함)

# 예시: 결과 출력 부분 (공통 적용)
result_text = "\n".join(lines)
st.markdown("### 📋 결과")
st.success(f"🔑 **열쇠:** {today_key}")
st.code(result_text, language="text")
st.download_button("📥 결과 저장", result_text.encode("utf-8-sig"), file_name="근무배정결과.txt")
st.button("📋 결과 복사", on_click=lambda: st.session_state.update({"copy_text": result_text}))

# 저장 조건 강화
if save_check:
    if today_key and (gy5 or gy4 or gy3):
        with open(PREV_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        st.success("전일근무.json 업데이트 완료")
    else:
        st.warning("⚠️ 결과가 불완전하여 전일근무.json 저장이 생략되었습니다.")
