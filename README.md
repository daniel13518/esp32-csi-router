# ESP32-S3 Router-based CSI 수집 — 실내 재실(사람 유무) 감지

ESP32-S3의 WiFi **CSI(Channel State Information)** 로 **빈방 vs 사람 있음**을 구분하는 종합설계 프로젝트.
현재 단계: **데이터 수집 파이프라인 + 신호 품질/feasibility 검증**까지 완료.
최종 목표: 데이터 → 서버 → 학습 모델 → UI.

Espressif 공식 [esp-csi](https://github.com/espressif/esp-csi) 의
`examples/get-started/csi_recv_router` 예제를 기반으로 함(자세한 원리는
[`README_official.md`](README_official.md)). 라우터에 STA로 접속 → 게이트웨이로
주기적 ping → 응답 패킷의 CSI를 콜백에서 CSV로 시리얼 출력하는 방식.

---

## 저장소 구조

| 경로 | 내용 |
|---|---|
| `main/app_main.c` | 펌웨어 본체. WiFi 접속·ping·CSI 콜백. **설정 상수도 여기.** |
| `sdkconfig.defaults` | 커밋되는 기본 설정. **WiFi SSID/PW는 여기서 각자 입력.** |
| `sdkconfig` | 빌드가 자동 생성(커밋 안 됨, 실제 WiFi 비번 들어감). |
| `SETUP.md` | 처음 세팅(Windows + VS Code + ESP-IDF 설치)부터 첫 빌드까지. |
| `README_official.md` | 원본 Espressif 예제 설명(영문, 참고용). |
| `tools/csi_record.py` | **헤드리스 녹화기.** N초간 CSI를 CSV로 저장(권장 수집 방법). |
| `tools/csi_quality.py` | 저장한 CSV를 그래프로 분석(재실감지 feasibility 확인). |
| `tools/csi_data_read_parse.py` | 실시간 PyQt 그래프 뷰어(원본 파서, 저장은 불안정). |
| `tools/csi_viewer.html` | 원본 esp-csi 웹 뷰어(브라우저에서 열어 확인). |
| `tools/empty.csv`, `tools/occupied.csv` | 샘플 데이터(빈방/사람 있음). 하드웨어 없이 분석 테스트용. |
| `tools/requirements.txt` | 파이썬 도구 의존성. |

---

## 처음 한 번 (팀에 새로 합류했다면)

1. **ESP-IDF 설치 & 보드 연결**: [`SETUP.md`](SETUP.md) 그대로 따라오면 됨(툴체인 설치 ~20분).
2. **WiFi 정보 입력**: `sdkconfig.defaults` 의 두 줄을 본인 공유기로 수정 (2.4GHz만, ESP32는 5GHz 불가).
   ```
   CONFIG_EXAMPLE_WIFI_SSID="여기에_공유기이름"
   CONFIG_EXAMPLE_WIFI_PASSWORD="여기에_비밀번호"
   ```
   또는 `idf.py menuconfig` → *Example Connection Configuration* 에서 입력.
   > `sdkconfig`(자동 생성)에는 실제 비번이 저장되지만 `.gitignore`로 커밋 안 됨. 팀원 각자 자기 공유기 정보로 설정.
3. **포트 확인**: 장치 관리자 → 포트(COM & LPT) → 보드의 COM 번호(예: `COM5`). 아래 명령의 `COM5`를 본인 번호로 바꿔 쓰기.

> 아래 `idf.py` 명령은 **ESP-IDF 환경이 켜진** 터미널("ESP-IDF PowerShell" 또는 VS Code ESP-IDF 확장 터미널)에서 실행. 파이썬 도구는 일반 터미널이면 됨.

---

## 상황별 명령어

### A. 펌웨어 빌드 / 플래시 / 모니터

```bash
idf.py set-target esp32s3            # 처음 한 번(타깃 지정)
idf.py build                         # 컴파일만
idf.py -p COM5 flash                 # 칩에 굽기
idf.py -p COM5 monitor               # 시리얼 출력 보기 (종료: Ctrl+])
idf.py -p COM5 flash monitor         # 굽고 바로 모니터 (제일 자주 씀)
idf.py fullclean                     # 빌드 꼬였을 때 build/ 통째로 정리
```
- 첫 빌드는 5~10분(툴체인 전체 컴파일), 이후 빠름.
- 플래시 안 되면 보드 **BOOT 버튼 누른 채** 재시도.

### B. 데이터 수집 (녹화) — 권장 방법

`monitor`와 포트를 동시에 못 쓰니, 녹화 중엔 `idf.py monitor`는 꺼두기.

```bash
cd tools
pip install -r requirements.txt      # 처음 한 번

python csi_record.py -p COM5 -s empty.csv    -t 30   # 빈 방: 실행하고 방 밖으로
python csi_record.py -p COM5 -s occupied.csv -t 30   # 사람: 방 안에서 걸어다니기
```
- `-p` 포트 / `-s` 저장 파일명 / `-t` 녹화 시간(초).
- 콘솔에 `12s  240 rows (0 bad)` 처럼 실시간 카운트. `done: ~600 rows`면 성공(20Hz×30s).
- 유효한 JSON 줄만 저장하고 손상된 시리얼 줄은 버림 → CSV가 항상 깨끗함.

### C. 신호 품질 / 분석 (그래프)

```bash
cd tools
python csi_quality.py empty.csv occupied.csv --labels empty occupied   # 두 상태 비교(핵심)
python csi_quality.py empty.csv                                         # 파일 하나만 봐도 됨
python csi_quality.py --selfcheck                                       # 데이터 없이 파싱 로직만 검증
```
출력 PNG 3장:
- **`csi_separability.png`** — subcarrier별 시간변동을 두 상태 겹쳐 그림. 선이 벌어질수록 구분 쉬움. **feasibility의 핵심.**
- **`csi_timeseries.png`** — 시간축 진폭. empty=안정된 줄무늬 / occupied=출렁임.
- **`csi_quality.png`** — 히트맵 + subcarrier별 평균/변동.

### D. 실시간 눈으로 보기 (선택)

```bash
cd tools
python csi_data_read_parse.py -p COM5 -s x.csv   # PyQt 실시간 그래프
```
- 눈으로 확인하는 용도. **저장은 불안정하니 데이터 수집은 `csi_record.py` 사용.**
- 웹 뷰어: `tools/csi_viewer.html` 을 브라우저로 열어도 됨.

### E. 설정 바꾸기

| 바꿀 것 | 방법 |
|---|---|
| **ping 주파수(샘플레이트)** | `main/app_main.c:38` 의 `#define CONFIG_SEND_FREQUENCY 20` (Hz). 값만 수정 후 다시 flash. |
| **WiFi SSID/PW** | `sdkconfig.defaults` 두 줄 수정, 또는 `idf.py menuconfig`. |
| **시리얼 baud** | `sdkconfig.defaults` 의 `921600`. 파이썬 도구도 921600 고정이니 바꾸면 양쪽 맞추기. |

> ping 주파수를 100Hz까지 올리면 라우터 ICMP throttle로 ~1.5초 뒤 응답이 끊길 수 있음. 재실감지엔 20Hz로 충분.

---

## CSV 출력 형식

부팅 시 헤더 1회, 이후 샘플마다 한 줄 (`main/app_main.c` 의 `wifi_csi_rx_cb`):
```
type,id,mac,rssi,rate,...,channel,...,sig_len,rx_format,len,first_word,data
CSI_DATA,0,AA:BB:CC:DD:EE:FF,-30,11,...,13,...,67,0,128,1,"[67,48,4,0,...]"
```
- `data` = `"[콤마로 구분된 int8 배열]"`, subcarrier별 `[허수, 실수]` 쌍. subcarrier `i` = `complex(re=arr[2i+1], im=arr[2i])`.
- **공유기 BSSID와 일치하는 CSI만** 출력(콜백에서 MAC 필터링).
- S3는 `esp_csi_gain_ctrl`로 AGC/FFT 게인 보정을 곱한 값이 나옴(원시값 아님).
- 20MHz·LLTF 기준 `len`은 128 부근. 대역폭/칩에 따라 달라지니 파싱 전 실제 `len` 확인.

---

## 지금까지 결과 (feasibility: **성립**)

- 샘플레이트 약 20Hz, 유효 subcarrier 52개(가운데 27-37은 null/guard).
- 전체 시간변동: empty **1.16** vs occupied **2.29** (약 2배).
- 모든 활성 subcarrier에서 occupied > empty, 교차 없음. 저대역·고대역 ratio 모두 ~2.0.
- **결론: 빈방 vs 걷는 사람 구분 명확. 단순 threshold ~ 작은 모델로 충분.**

## 다음 단계

1. 여러 클립 수집(각 상태를 위치·시간 바꿔가며 여러 번) → 라벨링.
2. feature = subcarrier별 sliding-window std/energy. 특정 subcarrier 하드코딩 금지(방 바뀌면 fading 봉우리 이동) → 전 대역 또는 상위 SNR 자동선택.
3. 간단 모델(threshold / logistic / 작은 NN)부터 → 서버 → UI.

---

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| CSI 값이 전부 0 | COM 포트 틀림 or WiFi 미접속. 올바른 포트 + `menuconfig`/`sdkconfig.defaults` WiFi 확인. |
| `idf.py` 없음 | ESP-IDF 환경 안 켜짐. "ESP-IDF PowerShell" 또는 확장 터미널에서 실행. |
| COM 포트 안 뜸 | 충전전용 케이블 / 드라이버(CP210x·CH340) / 다른 USB-C 포트 시도. |
| 첫 빌드 오래 걸림 | 정상. 툴체인 전체 컴파일, 두 번째부터 빠름. |
| 플래시 실패 | 보드 **BOOT 버튼 누른 채** 플래시. |
| 실효 샘플레이트가 설정값보다 낮음 | `esp_ping`이 응답/타임아웃 대기 후 다음 ping. 공유기 응답 느리면 발생. |
| 뷰어가 1~10초 뒤 멈춤/CSV 깨짐 | `csi_data_read_parse.py`의 921600 잘린 줄 크래시. 수집은 `csi_record.py` 사용. |
