# app.py
import streamlit as st
from google.cloud import vision
from google.oauth2 import service_account
import re
import json
from PIL import Image
from io import BytesIO

st.set_page_config(page_title="근무표 자동 배정 (한글 OCR 버전)", layout="wide")

st.title("🚦 근무표 자동 배정 — (Google Vision OCR + 한글 텍스트 출력)")

########################################################################
# 1) Google Vision API 인증 설정
########################################################################
try:
    cred_data = json.loads(st.secrets["general"]["GOOGLE_APPLICATION_CREDENTIALS"])
    creds = service_account.Credentials.from_service_account_info(cred_data)
    client = vision.ImageAnnotatorClient(credentials=creds)
except Exception as e:
    st.error("⚠️ Google Vision API 인증 실패: Secrets 설정을 다시 확인하세요.")
    st.stop()

########################################################################
# 2) 순번표 및 차량 매핑 설정
########################################################################

st.sidebar.header("초기 데이터 입력 (필요 시 수정)")

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
김면정
김성연
김주현
김지은
안유미
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

st.sidebar.markdown("**순번표 / 차량표 (필요 시 수정하세요)**")
key_order_text = st.sidebar.text_area("열쇠 순번 (위→아래 순환)", default_key_order, height=160)
gyoyang_order_text = st.sidebar.text_area("교양 순번 (위→아래 순환)", default_gyoyang_order, height=160)
sudong_order_text = st.sidebar.text_area("1종 수동 순번 (위→아래 순환)", default_sudong_order, height=160)

st.sidebar.markdown("**차량 매핑 (한 줄에 `호수 이름`)**")
cha1_text = st.sidebar.text_area("1종 수동 차량표", default_cha1, height=140)
cha2_text = st.sidebar.text_area("2종 자동 차량표", default_cha2, height=200)

def parse_list(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def parse_vehicle_map(text):
    m = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            car = parts[0]
            name = " ".join(parts[1:])
            m[name] = car
    return m

key_order = parse_list(key_order_text)
gyoyang_order = parse_list(gyoyang_order_text)
sudong_order = parse_list(sudong_order_text)
veh1 = parse_vehicle_map(cha1_text)
veh2 = parse_vehicle_map(cha2_text)

########################################################################
# 3) Vision API OCR 함수
########################################################################

def extract_text_from_image(uploaded_file):
    if not uploaded_file:
        return ""
    try:
        image = vision.Image(content=uploaded_file.read())
        response = client.text_detection(image=image)
        texts = response.text_annotations
        if response.error.message:
            st.error(f"Vision API 오류: {response.error.message}")
            return ""
        return texts[0].description if texts else ""
    except Exception as e:
        st.error(f"OCR 중 오류 발생: {e}")
        return ""

name_regex = re.compile(r'[가-힣]{2,3}')

def extract_names(text):
    found = name_regex.findall(text)
    seen, ordered = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered

########################################################################
# 4) 사용자 입력: 전일 근무자, 정비차량 등
########################################################################

st.sidebar.markdown("---")
st.sidebar.header("전일(기준) 입력 — 꼭 채워주세요")
prev_key = st.sidebar.text_input("전일 열쇠", value="")
prev_gyoyang5 = st.sidebar.text_input("전일 5교시 교양", value="")
prev_sudong = st.sidebar.text_input("전일 1종수동", value="")

st.sidebar.markdown("---")
st.sidebar.header("옵션")
sudong_count = st.sidebar.radio("1종 수동 인원수", [1, 2], index=0)
repair_cars = st.sidebar.text_input("정비중 차량 (쉼표로 구분)", value="")

########################################################################
# 5) 오전/오후 이미지 업로드 및 분석
########################################################################

st.markdown("## ① 오전/오후 근무표 이미지 업로드")
col1, col2 = st.columns(2)
with col1:
    morning_file = st.file_uploader("오전 근무표 이미지 업로드", type=["png", "jpg", "jpeg"], key="morning")
with col2:
    afternoon_file = st.file_uploader("오후 근무표 이미지 업로드", type=["png", "jpg", "jpeg"], key="afternoon")

if st.button("분석 시작"):
    st.markdown("### ⏳ Google Vision API로 OCR 중... 잠시만 기다려주세요.")

    morning_text = extract_text_from_image(morning_file)
    afternoon_text = extract_text_from_image(afternoon_file)

    morning_names = extract_names(morning_text)
    afternoon_names = extract_names(afternoon_text)

    st.markdown("### OCR 추출 결과 (오전)")
    st.text_area("오전 OCR 텍스트", morning_text, height=180)
    st.markdown("이름 추출: " + ", ".join(morning_names))

    st.markdown("### OCR 추출 결과 (오후)")
    st.text_area("오후 OCR 텍스트", afternoon_text, height=180)
    st.markdown("이름 추출: " + ", ".join(afternoon_names))

    # 이후 근무자 자동 배정 로직은 기존 코드와 동일하게 유지
    st.success("✅ OCR 완료! 다음 단계에서 근무자 자동 배정이 가능합니다.")
else:
    st.info("이미지를 업로드한 후 '분석 시작' 버튼을 눌러주세요.")

# 2) 유틸리티: OCR 추출, 이름 추출, 다음 순번 계산 등
########################################################################

########################################################################
# 3) 업로드 UI: 오전, 오후 이미지
########################################################################


st.markdown("옵션을 확인한 뒤 **분석 시작** 버튼을 눌러주세요.")
if st.button("분석 시작"):
    # OCR
    morning_text = extract_text_from_image(morning_file) if morning_file else ""
    afternoon_text = extract_text_from_image(afternoon_file) if afternoon_file else ""

    # extract names from images
    morning_names = extract_names(morning_text)
    afternoon_names = extract_names(afternoon_text)

    # 양식: present_set is union of morning_names (if morning) or afternoon_names
    # we treat morning analysis (오전 전용) and afternoon separately
    present_morning = set(morning_names)
    present_afternoon = set(afternoon_names)

    # If 전산병행 체크되어 있으면 exclude them from 교양 assignment
    # But we need to detect which names are 전산병행 from OCR: we'll ask user to mark if any
    # For now, if has_computer True: show a small input to list names that are 전산병행
    st.markdown("### OCR 추출된 이름 (오전 이미지에서 발견)")
    st.text_area("오전 OCR 원문", morning_text, height=180)
    st.markdown("추출된 이름(오전 순서대로): " + ", ".join(morning_names))

    st.markdown("### OCR 추출된 이름 (오후 이미지에서 발견)")
    st.text_area("오후 OCR 원문", afternoon_text, height=180)
    st.markdown("추출된 이름(오후 순서대로): " + ", ".join(afternoon_names))

    # 사용자에게 전산병행자 직접 입력(콤마 구분)
    computer_names_input = st.text_input("전산병행자 이름(콤마 구분, 빈칸 가능) — OCR 인식 후 정확히 입력하세요", value="")
    computer_names = [n.strip() for n in computer_names_input.split(",") if n.strip()]

    # 선택: 이미지에서 도로주행 근무자 컬럼만 쓰는 경우 사용자 확인
    st.markdown("**주의**: OCR은 완벽하지 않습니다. 위 추출 결과를 확인하고, '도로주행 근무자'만 포함되도록 아래 입력란에 근무자 리스트를 수정해주세요.")
    morning_list_str = st.text_area("오전 근무자(확정 — 한 줄에 하나씩 입력)", value="\n".join(morning_names), height=160)
    afternoon_list_str = st.text_area("오후 근무자(확정 — 한 줄에 하나씩 입력)", value="\n".join(afternoon_names), height=160)
    morning_list = [x.strip() for x in morning_list_str.splitlines() if x.strip()]
    afternoon_list = [x.strip() for x in afternoon_list_str.splitlines() if x.strip()]

    # parse repair cars
    repair_list = [x.strip() for x in repair_cars.split(",") if x.strip()]

    # compute morning assignment based on rules:
    # - 열쇠: next of prev_key in key_order
    # - 교양(오전1,2): start from next after prev_gyoyang5 in gyoyang_order, take two in present_morning excluding 전산병행
    # - 1종수동 (오전): next after prev_sudong in sudong_order, but must be present_morning; default sudong_count persons if available
    # - 2종 자동: present_morning MINUS assigned 1종 persons; map to veh2 (if missing, leave blank); exclude repair cars from mapping
    present_set_morning = set(morning_list)
    present_set_afternoon = set(afternoon_list)

    # 열쇠
    today_key = next_in_cycle(prev_key, key_order) if prev_key else next_in_cycle(key_order[0], key_order)

    # 교양 오전 (2명)
    gy_start = next_in_cycle(prev_gyoyang5, gyoyang_order) if prev_gyoyang5 else gyoyang_order[0]
    # find two valid (exclude 전산병행)
    gy_candidates = []
    idx = gyoyang_order.index(gy_start) if gy_start in gyoyang_order else 0
    i = 0
    while len(gy_candidates) < 2 and i < len(gyoyang_order):
        cand = gyoyang_order[(idx + i) % len(gyoyang_order)]
        if cand in present_set_morning and cand not in computer_names:
            gy_candidates.append(cand)
        i += 1
    gy1 = gy_candidates[0] if len(gy_candidates) >= 1 else None
    gy2 = gy_candidates[1] if len(gy_candidates) >= 2 else None

    # 1종 수동 오전: choose sudong_count people by next_valid_after from prev_sudong
    sudong_assigned = []
    cur = prev_sudong if prev_sudong else sudong_order[0]
    i = 0
    while len(sudong_assigned) < sudong_count and i < len(sudong_order):
        cand = next_in_cycle(cur, sudong_order)
        cur = cand  # move forward
        if cand in present_set_morning:
            if cand not in sudong_assigned:
                sudong_assigned.append(cand)
        i += 1
    # If none found, leave empty

    # 2종자동 morning: all present minus sudong_assigned and minus computer-only? (전산병행은 2종으로만 배정 가능)
    morning_2jong = [p for p in morning_list if p not in sudong_assigned]
    # map vehicles: use veh2 where possible; skip repair cars mapping
    morning_2jong_map = []
    for name in morning_2jong:
        car = veh2.get(name, "")
        # if car in repair_list, mark (정비중) next to it
        note = ""
        if car and car in repair_list:
            note = "(정비중)"
        morning_2jong_map.append((name, car, note))

    # Build morning result text
    morning_lines = []
    morning_lines.append(f"📅 {st.session_state.get('date', '')} 오전 근무 배정 결과")
    morning_lines.append(f"열쇠: {today_key}")
    if gy1 or gy2:
        morning_lines.append("교양 (오전)")
        morning_lines.append(f"  1교시: {gy1 if gy1 else '-'}")
        morning_lines.append(f"  2교시: {gy2 if gy2 else '-'}")
    else:
        morning_lines.append("교양 (오전): 지정 불가(근무자 부족)")

    if sudong_assigned:
        for idx, name in enumerate(sudong_assigned, start=1):
            car = veh1.get(name, "")
            morning_lines.append(f"1종 수동 #{idx}: {name}" + (f" ({car})" if car else ""))
    else:
        morning_lines.append("1종 수동: 배정 불가")

    morning_lines.append("2종 자동 (도로주행 근무자 — 1종 담당자 제외)")
    for name, car, note in morning_2jong_map:
        morning_lines.append(f"  {name} → {car if car else '-'} {note}")

    # Now compute afternoon results following rules:
    # - 열쇠 same as morning_key
    # - 교양 afternoon starts from next after morning's last gy candidate (i.e., gy2) and continues, skipping non-present and those excluded by 전산병행.
    # - 1종 afternoon: next after last assigned 1종 (we used sudong_assigned[-1]) in sudong_order, find 1 person present in afternoon_list
    # - 2종 afternoon: afternoon_list minus 1종 assigned
    # Determine last gy in morning: the last 교양 assigned in morning is gy2 if present else gy1
    last_gy = gy2 if gy2 else gy1

    # afternoon key same as morning
    afternoon_key = today_key

    # afternoon 교양: start from next after last_gy
    aft_gy_candidates = []
    if last_gy:
        start_gy = next_in_cycle(last_gy, gyoyang_order)
    else:
        start_gy = gyoyang_order[0]
    idx = gyoyang_order.index(start_gy) if start_gy in gyoyang_order else 0
    i = 0
    # want up to 3 교시 (3,4,5) but consider 5교시 skipping rule: if candidate not present or 16:00 퇴근, skip to next
    aft_needed = 3
    while len(aft_gy_candidates) < aft_needed and i < len(gyoyang_order):
        cand = gyoyang_order[(idx + i) % len(gyoyang_order)]
        # skip 전산병행 for 교양
        if cand in present_set_afternoon and cand not in computer_names:
            aft_gy_candidates.append(cand)
        i += 1
    # apply 5교시 rule: if 5교시 candidate is person who cannot do 5교시 (we don't have explicit 16:00 flag, ask user)
    # we will display and allow user to correct after seeing text.

    # afternoon 1종: next after last morning 1종 assigned (last_sudong)
    last_sudong = sudong_assigned[-1] if sudong_assigned else prev_sudong
    aft_sudong = None
    if last_sudong:
        # find next valid present in afternoon_set
        aft_sudong = next_valid_after(last_sudong, sudong_order, present_set_afternoon)
    # if none found, leave None

    # afternoon 2종 mapping
    aft_2jong = [p for p in afternoon_list if p != aft_sudong]
    aft_2jong_map = []
    for name in aft_2jong:
        car = veh2.get(name, "")
        note = ""
        if car and car in repair_list:
            note = "(정비중)"
        aft_2jong_map.append((name, car, note))

    # Build afternoon result text
    afternoon_lines = []
    afternoon_lines.append(f"📅 {st.session_state.get('date', '')} 오후 근무 배정 결과")
    afternoon_lines.append(f"열쇠: {afternoon_key}")
    if aft_gy_candidates:
        afternoon_lines.append("교양 (오후)")
        # only show up to 3 교시
        for i, c in enumerate(aft_gy_candidates[:3], start=3):
            afternoon_lines.append(f"  {i}교시: {c}")
    else:
        afternoon_lines.append("교양 (오후): 지정 불가")

    if aft_sudong:
        car = veh1.get(aft_sudong, "")
        afternoon_lines.append(f"1종 수동 (오후): {aft_sudong}" + (f" ({car})" if car else ""))
    else:
        afternoon_lines.append("1종 수동 (오후): 배정 불가")

    afternoon_lines.append("2종 자동 (도로주행 근무자 — 1종 담당자 제외)")
    for name, car, note in aft_2jong_map:
        afternoon_lines.append(f"  {name} → {car if car else '-'} {note}")

    # Final: show text outputs
    st.markdown("## 결과 (한글 텍스트 출력)")
    st.text_area("오전 결과 (텍스트)", "\n".join(morning_lines), height=300)
    st.text_area("오후 결과 (텍스트)", "\n".join(afternoon_lines), height=300)

    # Offer download as .txt
    all_text = "== 오전 ==\n" + "\n".join(morning_lines) + "\n\n== 오후 ==\n" + "\n".join(afternoon_lines)
    st.download_button("결과 텍스트 다운로드 (.txt)", data=all_text, file_name="근무배정결과.txt", mime="text/plain")

    # Save '오늘' as 전일근무.json if user confirms
    if st.checkbox("이 결과를 '전일 기준'으로 저장 (전일근무.json 덮어쓰기)", value=False):
        today_record = {
            "열쇠": afternoon_key,
            "교양_5교시": aft_gy_candidates[2] if len(aft_gy_candidates) >= 3 else (aft_gy_candidates[-1] if aft_gy_candidates else ""),
            "1종수동": aft_sudong if aft_sudong else ""
        }
        with open("전일근무.json", "w", encoding="utf-8") as f:
            json.dump(today_record, f, ensure_ascii=False, indent=2)
        st.success("전일근무.json에 저장했습니다.")

else:
    st.info("이미지 업로드 후 '분석 시작' 버튼을 눌러주세요. OCR 결과를 확인하고 근무자 목록을 보정한 뒤 최종 결과를 생성합니다.")
