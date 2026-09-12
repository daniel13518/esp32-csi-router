# ESP32-S3 초기 세팅 가이드 (Windows + VS Code)

이 프로젝트(`esp32-csi-router`)를 빌드·플래시해서 CSI CSV를 뽑기까지의 처음 세팅.
따라 하면서 옆에 띄워두는 용도.

---

## 먼저 알아둘 개념 (안 헷갈리게)

### 1) ESP32 ≠ 라즈베리파이
- **라파** = 리눅스 도는 미니 PC. 화면(UI) 있고, 여러 프로그램 동시 실행, 소스가 칩(SD카드) 안에 있음.
- **ESP32** = OS 없는 마이크로컨트롤러 칩. **화면 없음, UI 없음.** 내가 구운 프로그램 **딱 1개**만 돎.
- 출력을 보려면 방법을 따로 만들어줘야 함 → 우리는 **시리얼(USB로 글자 뱉기)** 사용.

### 2) 코드는 내 PC에, 칩엔 결과물만
```
[내 PC] app_main.c 편집 → build(컴파일) → flash로 전송 → [칩] 실행
```
- **소스(`app_main.c`)는 칩 안에 없다. 내 노트북 프로젝트 폴더에 있다.** 편집도 내 PC에서.
- 칩엔 사람이 읽는 소스가 아니라 **컴파일된 기계어 덩어리**만 들어감.
- **USB는 칩 파일을 탐색기로 열어보는 통로가 아니다.** 역할은 딱 둘: ① 바이너리 굽기(flash) ② 글자 읽기(monitor).
- 코드 바꾸려면 → PC에서 수정 → **다시 build → 다시 flash** (이 왕복). 새로 구우면 이전 프로그램은 덮어써짐.

### 3) flash = 영구 저장, 전원만 있으면 혼자 돎
- flash하면 코드가 칩의 **비휘발성 메모리에 영구 저장**됨. 전원 꺼도 안 지워짐.
- 전원만 들어오면 자동 부팅 → `app_main()`부터 **혼자 계속 실행.**
- **`monitor`는 옆에서 구경하는 창문일 뿐.** 안 봐도, 노트북 없어도 프로그램은 상관없이 돌아감.

### 4) idf.py = 만능 명령 (SSH 아님)
- 모든 작업(`idf.py ...`)은 **내 노트북에서** 실행. ESP32 안에서 치는 게 아님. 접속·SSH 개념 없음.
  - `build` = 컴파일 / `flash` = 칩에 굽기 / `monitor` = 출력 보기 / `menuconfig` = 설정
- `idf.py flash`엔 **파일명 안 붙임.** "이 프로젝트의 빌드 결과물"을 알아서 구움. (실행 시작점은 항상 `app_main()` 함수 고정)
- **"ESP-IDF PowerShell" = 컴파일러 경로가 세팅된 평범한 PowerShell.** VS Code 상태바 버튼(🔨⚡🖥️)도 내부에서 이 idf.py를 대신 눌러주는 것.

### 5) USB 빼고 독립 동작시킬 때
USB가 주던 두 역할을 각각 대체해야 함:
- **전원** → 폰 충전기/보조배터리/벽 어댑터에 같은 USB-C 꽂으면 끝. (재플래시 불필요)
- **데이터 출구** → 지금은 CSV가 USB 시리얼로만 나옴. 노트북 없으면 갈 데가 없음.
  → **WiFi 전송 코드를 추가**해서 서버/PC로 쏴야 함 (칩이 이미 공유기에 붙어있으니 자연스러움). **이건 2단계 이후 작업.**
- **USB는 1단계 데이터 수집 내내 연결.** CSI CSV가 이 USB 선을 타고 노트북으로 온다.
  → 추후에 무선랜 통하여 서버로 보내면 USB는 빼도 됨(전원은 충전기로).

---

## 준비물

- ESP32-S3 개발보드 (USB-C 포트 2개짜리 정상)
- **데이터 전송 되는** USB-C 케이블 (충전 전용 X)
- 인터넷 (툴체인 ~2GB 다운로드)

### 보드의 USB-C 포트 2개 구분
```
[USB-C: UART] ← 여기 꽂기. 꽂으면 바로 COM 포트로 뜸 (플래시 제일 쉬움)
[USB-C: USB ] ← 네이티브 USB. 나중에
```
라벨 안 보이면: 두 포트 각각 꽂아보고 **장치 관리자에 COM 포트가 새로 뜨는 쪽**이 정답.

---

## STEP 1 — VS Code에 ESP-IDF 확장 설치

1. VS Code 왼쪽 확장 아이콘 → `Espressif IDF` 검색 → **ESP-IDF** 설치

## STEP 2 — 툴체인 자동 설치 (한 번만, 10~20분)

1. `Ctrl+Shift+P` → `ESP-IDF: Configure ESP-IDF Extension`
2. **EXPRESS** 선택
3. 버전 **v5.2** (또는 v5.x 최신 stable) 선택
4. 경로 기본값 두고 **Install**
5. "All settings have been configured" 뜨면 완료
   → 이걸로 아까 IntelliSense 빨간 줄 문제도 자동 해결됨

## STEP 3 — USB 연결 & 포트 확인

1. 케이블로 보드의 **UART** 포트 ↔ 노트북 연결
2. **장치 관리자** → **포트(COM & LPT)** 에 `COM?` 확인 (예: COM5)
3. 안 뜨면: 케이블(충전전용?) 또는 USB 드라이버(CP2102/CH340) 문제

## STEP 4 — 프로젝트 열기

1. VS Code → `File → Open Folder` → `Desktop/esp32-csi-router`
2. 맨 아래 파란 상태바에 아이콘들이 생김:

| 아이콘 | 역할 |
|---|---|
| 🎯 칩 | 타깃 설정 → **esp32s3** |
| 🔌 플러그 | 포트 → **본인 COM** |
| 🔨 망치 | 빌드 |
| ⚡ 번개 | 플래시 |
| 🖥️ 모니터 | 시리얼 출력 |

## STEP 5 — WiFi 정보 입력 (빌드 전 필수)

1. `Ctrl+Shift+P` → `ESP-IDF: SDK Configuration Editor (menuconfig)`
2. **`Example Connection Configuration`** 메뉴 → WiFi SSID / Password 입력 → 저장

## STEP 6 — 타깃 → 빌드 → 플래시 → 모니터

상태바 버튼 순서대로:
1. 🎯 → **esp32s3** 선택
2. 🔌 → **COM 포트** 선택
3. 🔨 빌드 (첫 빌드 5~10분, 이후 빠름)
4. ⚡ 플래시
5. 🖥️ 모니터

**터미널로 하려면** (ESP-IDF PowerShell 또는 확장 터미널에서):
```bash
idf.py set-target esp32s3
idf.py menuconfig          # 창에서 Example Connection Configuration → WiFi 입력
idf.py -p COM5 flash monitor
```

---

## 성공 신호 ✅

모니터 화면에 이게 좌르륵 흐르면 1단계 완료:
```
type,seq,mac,rssi,...,data
CSI_DATA,0,94:d9:b3:80:8c:81,-30,...,"[67,48,4,0,...]"
CSI_DATA,1,...
```

---

## 자주 막히는 지점

| 증상 | 해결 |
|---|---|
| `idf.py 없음` | ESP-IDF 환경 안 켜짐. 확장 버튼 쓰거나 "ESP-IDF PowerShell"에서 실행 |
| COM 포트 안 뜸 | 충전전용 케이블 / 드라이버 / 다른 USB-C 포트 시도 |
| 첫 빌드 오래 걸림 | 정상. 툴체인 전체 컴파일. 두 번째부터 빠름 |
| 플래시 실패 / 접속 안 됨 | 보드 **BOOT 버튼 누른 채** 플래시 |
| IntelliSense 빨간 줄 | 컴파일 에러 아님. 확장 설치하면 잡힘 (급하면 무시하고 빌드) |

---

## 다음 (오늘 목표 이후)

CSV가 나오면 → `tools/csi_data_read_parse.py`로 저장 + 실시간 그래프:
```bash
pip install -r tools/requirements.txt
python tools/csi_data_read_parse.py -p COM5 -s csi_data.csv
```
(monitor랑 포트 동시 사용 불가 → monitor 끄고 실행)
