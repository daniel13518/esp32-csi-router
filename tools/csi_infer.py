#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSI 재실감지 추론 모듈 — 서버/UI 쪽이 쓰는 인터페이스. 모델을 바꿔도 입출력은 그대로.

환경(방, 공유기/보드 위치)이 바뀌면 먼저 '빈방 보정'을 1번 한다. 특징을 그 환경의 빈방 대비
비율로 바꿔 판단하므로, 방마다 다른 신호 세기·페이딩 기준이 같이 따라간다.

  1) 빈방 보정 (설치 때 / 환경 바뀔 때, 방 비우고 30초)
     python csi_infer.py -p COM5 --calibrate baseline.json
  2) 실행
     python csi_infer.py -p COM5 --baseline baseline.json
     python csi_infer.py --replay empty.csv occupied.csv --loop   # 보드 없이 20Hz 재생 (UI 개발용)
     python csi_infer.py --selfcheck

입력: ESP32 시리얼 한 줄  CSI_DATA,...,"[im0,re0,im1,re1,...]"  (csi_record.py CSV 의 한 줄과 동일)
출력: 윈도우마다 dict 1개 (CLI 는 JSON 한 줄씩 stdout)
  {"ts": 1761700000.123, "state": "occupied", "confidence": 0.93,
   "probs": {"empty": 0.07, "occupied": 0.93}, "model": "rf-20261029-1env2sess"}
  - 첫 결과는 win 패킷 쌓인 뒤, 이후 step 패킷마다 1개 (모델에 들어 있음. 지금 모델 = 10초 창, 5초마다).
  - 손상 줄/길이 다른 패킷은 조용히 버림. state 값 = 학습 때 라벨.
  - 시리얼 포트를 열면 보드가 재부팅되고 첫 5초는 게인이 안정되기 전이라 보정/판정 둘 다 버림.

파이썬 서버에서:
  from csi_infer import Detector, calibrate
  json.dump(calibrate(lines_30s), open('baseline.json', 'w'))   # UI '빈방 보정' 버튼
  det = Detector('csi_model.pkl', 'baseline.json')
  r = det.feed(line)        # 대부분 None, 윈도우 찰 때만 dict
  if r: push_to_ui(r)

모델 교체: csi_model.pkl (+특징이 바뀌었으면 이 파일도) 덮어쓰기. 특징이 바뀌면 보정도 다시.
설치: pip install numpy scikit-learn joblib pyserial   (모델 만든 sklearn 버전과 맞추기, 다르면 경고)
"""
import sys, csv, json, time, argparse
from collections import deque
import numpy as np

MODEL = 'csi_model.pkl'
BASELINE = 'baseline.json'
BAUD = 921600
FS = 20.0  # 펌웨어 ping 주파수. ponytail: 실제 패킷 간격 흔들림(18-77ms) 무시, Doppler 정밀도 필요하면 local_timestamp로 리샘플링
SKIP = 100  # 부팅 직후 패킷 100개(5초)는 게인 기준 잡기 전 상태(app_main.c CONFIG_GAIN_CONTROL) -> 버림
FEATURES = ['amp_std', 'amp_cv', 'fade_decorr', 'rician_k', 'doppler_hz', 'dop_0-2', 'dop_2-5', 'dop_5-10']


def parse_line(line):
    """시리얼/CSV 한 줄 -> data 배열(list[int]), CSI 줄이 아니거나 손상이면 None."""
    i = line.find('CSI_DATA')
    if i == -1:
        return None
    try:
        arr = json.loads(next(csv.reader([line[i:]]))[-1])
    except (json.JSONDecodeError, IndexError, StopIteration):
        return None
    return arr if isinstance(arr, list) else None


def to_complex(data):
    """[im0,re0,im1,re1,...] -> subcarrier별 복소 CSI (csi_quality.load_amplitude 와 같은 규칙)."""
    a = np.asarray(data, float)
    return a[1::2] + 1j * a[0::2]


def load_csi(lines, n_sc=None):
    """줄들(파일/리스트/제너레이터) -> 복소 CSI [패킷 x n_sc]. 손상 줄 버림, n_sc 없으면 최빈 길이."""
    rows = [d for d in map(parse_line, lines) if d is not None]
    if not rows:
        return np.empty((0, n_sc or 0), complex)
    L = 2 * n_sc if n_sc else max(set(map(len, rows)), key=[len(r) for r in rows].count)
    return np.array([to_complex(d) for d in rows if len(d) == L]).reshape(-1, L // 2)


def phys_k(idx, n_sc=64):
    """FFT 순서 인덱스(0..31, 32..63) -> 물리 subcarrier 번호(0..31, -32..-1)."""
    idx = np.asarray(idx)
    return np.where(idx < n_sc // 2, idx, idx - n_sc)


def active_sc(csi):
    """평균 진폭 > 0.5 인 칸(DC·보호대역 제외)을 물리 순서로 정렬한 인덱스."""
    idx = np.where(np.abs(csi).mean(0) > 0.5)[0]
    return idx[np.argsort(phys_k(idx, csi.shape[1]))]


def sanitize(h, k):
    """패킷마다 CFO(공통 위상)와 STO(주파수에 비례하는 위상 기울기) 제거.
    unwrap 대신 이웃 칸 복소곱의 진폭가중 각도로 기울기 추정 -> 깊은 페이딩 칸에 덜 흔들림.
    ESP32 데이터는 음/양 대역 절반 사이에 ~180도 고정 오프셋이 있어(샘플에서 확인) 공통 위상은 절반마다 따로 뺌."""
    adj = np.diff(k) == 1  # 바로 옆 칸 쌍만 (DC 틈 제외)
    slope = np.angle((h[:, 1:] * h[:, :-1].conj())[:, adj].sum(1))
    h = h * np.exp(-1j * slope[:, None] * k[None])
    for half in (k < 0, k > 0):
        h[:, half] *= np.exp(-1j * np.angle(h[:, half].sum(1)))[:, None]
    return h


def features(csi, active, fs=FS):
    """[win x n_sc] 복소 CSI -> FEATURES 순서 특징 8개. 학습/추론 공용, 바꾸면 모델 재학습.
    진폭 = 다중경로 페이딩, 위상 = Doppler. 대역 전체 요약값이라 subcarrier 하드코딩 없음(방 바뀌어도 의미 유지)."""
    k = phys_k(active, csi.shape[1])
    h = csi[:, active]
    amp = np.abs(h)
    z = (amp - amp.mean(1, keepdims=True)) / (amp.std(1, keepdims=True) + 1e-9)
    p = amp ** 2
    s = np.sqrt(np.clip(1 - p.var(0) / (p.mean(0) ** 2 + 1e-9), 0, 1))  # 모멘트법 Rician K: K = s/(1-s)
    hs = sanitize(h, k)
    dphi = np.angle(hs[1:] * hs[:-1].conj())  # 패킷 간 위상 회전 (wrap 안전)
    S = (np.abs(np.fft.fft(hs - hs.mean(0), axis=0)) ** 2).mean(1)  # 정지 경로(평균) 뺀 Doppler 스펙트럼
    f = np.abs(np.fft.fftfreq(len(hs), 1 / fs))
    tot = S[f > 0.25].sum() + 1e-9
    return np.array([
        amp.std(0).mean(),                                    # amp_std: 시간 흔들림 크기
        (amp.std(0) / (amp.mean(0) + 1e-9)).mean(),           # amp_cv: 게인(스케일) 무관 버전
        1 - (z[1:] * z[:-1]).mean(),                          # fade_decorr: 주파수축 페이딩 모양이 패킷마다 바뀌는 정도
        np.log1p(np.median(s / (1 - s + 1e-9))),              # rician_k: 고정 경로 우세(빈방)일수록 큼
        np.median(np.abs(dphi).mean(0)) * fs / (2 * np.pi),   # doppler_hz: 평균 위상 회전 속도
        *[S[(f > a) & (f <= b)].sum() / tot for a, b in ((0.25, 2), (2, 5), (5, fs / 2))],  # Doppler 대역 에너지 비율
    ])


def windows(csi, active, win, step):
    """[패킷 x n_sc] -> 윈도우별 특징 [n_win x len(FEATURES)]. Detector 와 같은 정렬(0, step, 2step..)."""
    return np.array([features(csi[i:i + win], active)
                     for i in range(0, len(csi) - win + 1, step)]).reshape(-1, len(FEATURES))


def baseline(csi, m):
    """빈방 CSI -> 보정값 dict (특징별 중앙값). m = 모델 dict (active/win/step)."""
    W = windows(csi, m['active'], m['win'], 10)  # 보정은 0.5초 간격으로 촘촘히 -> 10초 창 모델도 30초면 충분
    if len(W) < 10:
        raise ValueError(f'보정 데이터 부족: 창 {len(W)}개 < 10 (빈방 30초 이상 필요)')
    return {'median': np.median(W, 0).tolist(), 'features': FEATURES, 'n_windows': len(W)}


def normalize(f, base):
    """특징 -> 빈방 보정 대비 log 비율 (0 = 빈방과 같음). 방·공유기 거리·게인이 달라도 기준이 같이 따라감."""
    return np.log((np.asarray(f) + 1e-3) / (np.asarray(base) + 1e-3))


def load_model(model=MODEL):
    if isinstance(model, dict):
        return model
    import joblib, sklearn
    m = joblib.load(model)
    if m.get('sklearn') not in (None, sklearn.__version__):
        print(f'[경고] 모델은 sklearn {m["sklearn"]}로 만들어짐, 현재 {sklearn.__version__}', file=sys.stderr)
    return m


def calibrate(lines, model=MODEL):
    """빈방 30초 이상의 줄들 -> 보정 dict (json 저장해서 Detector 에 넘김)."""
    m = load_model(model)
    return baseline(load_csi(lines, m['n_sc'])[SKIP:], m)


class Detector:
    """줄을 하나씩 넣으면 step 패킷마다 판정 dict 반환. baseline = 보정 파일 경로/dict/리스트."""

    def __init__(self, model=MODEL, baseline=BASELINE, skip=SKIP):
        m = load_model(model)
        self.skip = skip
        self.clf, self.win, self.step = m['clf'], m['win'], m['step']
        self.n_sc, self.active = m['n_sc'], np.asarray(m['active'])
        self.name = m.get('name', 'unknown')
        self.labels = [str(c) for c in self.clf.classes_]
        if isinstance(baseline, str):
            try:
                with open(baseline, encoding='utf-8') as f:
                    baseline = json.load(f)
            except FileNotFoundError:
                raise FileNotFoundError(f'{baseline} 없음 -> 빈방에서 먼저: python csi_infer.py -p COM5 --calibrate {baseline}') from None
        if isinstance(baseline, dict):
            if baseline.get('features', FEATURES) != FEATURES:
                raise ValueError('보정 파일의 특징 목록이 이 모듈과 다름 -> --calibrate 다시')
            baseline = baseline['median']
        self.base = np.asarray(baseline, float)
        self.buf = deque(maxlen=self.win)
        self.since = 0

    def feed(self, line):
        data = parse_line(line) if isinstance(line, str) else line
        if data is None or len(data) != 2 * self.n_sc:
            return None
        if self.skip > 0:
            self.skip -= 1
            return None
        self.buf.append(to_complex(data)); self.since += 1
        if len(self.buf) < self.win or self.since < self.step:
            return None
        self.since = 0
        x = normalize(features(np.array(self.buf), self.active), self.base)
        p = self.clf.predict_proba(x[None])[0]
        k = int(p.argmax())
        return {'ts': round(time.time(), 3), 'state': self.labels[k], 'confidence': round(float(p[k]), 3),
                'probs': {l: round(float(v), 3) for l, v in zip(self.labels, p)}, 'model': self.name}


def emit(r):
    if r:
        print(json.dumps(r, ensure_ascii=False), flush=True)


def read_serial(port, seconds=float('inf')):
    import serial
    with serial.Serial(port, BAUD, timeout=1) as ser:
        t0 = time.time()
        while time.time() - t0 < seconds:
            yield ser.readline().decode('latin1', 'ignore')


def read_files(paths, loop=False, fast=True):
    """녹화 CSV 줄을 흘려보냄. fast=False 면 20Hz 속도로 (보드가 있는 것처럼). 재생 파일은 stderr 로 알림."""
    while True:
        for p in paths:
            print(f'# replay {p}', file=sys.stderr, flush=True)
            with open(p, encoding='latin1') as f:
                for line in f:
                    yield line
                    if not fast:
                        time.sleep(1 / FS)
        if not loop:
            return


def selfcheck():
    line = 'CSI_DATA,1,00:00:00:00:00:00,-60,11,1,7,0,1,1,0,0,0,1,-96,0,11,0,123,0,83,1,4,0,"[3,4,-12,5]"'
    assert parse_line(line) == [3, 4, -12, 5]
    assert parse_line(line.replace('-12,', ',')) is None      # ,, 손상 줄
    assert parse_line('I (123) wifi: connected') is None      # 부팅 로그
    assert np.allclose(to_complex([3, 4, -12, 5]), [4 + 3j, 5 - 12j])
    assert load_csi([line, 'junk', line]).shape == (2, 2)

    # 합성 채널: 고정 다중경로 3개 (+ 사람 반사 경로 1개, 4Hz Doppler) x 패킷마다 랜덤 CFO/STO + 잡음
    rng = np.random.default_rng(0)
    k = phys_k(np.arange(64)); df = 312.5e3
    def sess(move, n=40):
        rows = []
        for i in range(n):
            H = sum(a * np.exp(-2j * np.pi * k * df * tau) for a, tau in [(1, 0), (0.6, 30e-9), (0.4, 70e-9)])
            if move:
                H = H + 0.5 * np.exp(2j * np.pi * (4 * i / FS - k * df * 40e-9))
            H = 10 * H * np.exp(1j * (rng.uniform(-np.pi, np.pi) + rng.normal(0, 0.1) * k))
            H[k > 0] *= -1  # 실제 ESP32처럼 양쪽 대역 절반 사이 180도 오프셋
            H = H + rng.normal(0, 0.1, 64) + 1j * rng.normal(0, 0.1, 64)
            H[(k == 0) | (np.abs(k) > 26)] = 0
            rows.append(H)
        return np.array(rows)
    still, walk = sess(False), sess(True)
    act = active_sc(still)
    assert len(act) == 52 and list(phys_k(act)[:2]) == [-26, -25], act
    F = dict(zip(FEATURES, zip(features(still, act), features(walk, act))))
    assert F['amp_std'][1] > F['amp_std'][0] and F['fade_decorr'][1] > F['fade_decorr'][0], F
    assert F['rician_k'][1] < F['rician_k'][0] and F['doppler_hz'][1] > F['doppler_hz'][0], F
    assert F['dop_2-5'][1] > 0.5, F  # 4Hz 경로 에너지는 2-5Hz 대역에 몰려야 (CFO/STO 제거가 되었다는 뜻)

    # 빈방 보정: 신호 세기가 3배인 다른 환경이어도 '빈방 대비' 값은 같아야
    m = {'active': act, 'win': 40, 'step': 20}
    calm = sess(False, 240)
    b1, b3 = baseline(calm, m)['median'], baseline(3 * calm, m)['median']
    assert np.allclose(normalize(features(walk, act), b1), normalize(features(3 * walk, act), b3), atol=0.05)
    assert abs(normalize(features(still, act), b1)).max() < 1.0  # 빈방은 0 근처

    class Dummy:  # predict_proba 흉내
        classes_ = np.array(['empty', 'occupied'])
        def predict_proba(self, X): return np.array([[0.2, 0.8]])
    det = Detector({'clf': Dummy(), 'win': 4, 'step': 2, 'n_sc': 64, 'active': act}, b1, skip=3)
    data = np.ravel(np.c_[still[0].imag, still[0].real]).round().astype(int).tolist()  # [im0,re0,...]
    out = [det.feed(data) for _ in range(11)][3:]             # 처음 3개는 부팅 직후라 버림
    assert [i for i, r in enumerate(out) if r] == [3, 5, 7]   # win 찬 뒤 첫 결과, 이후 step마다
    assert out[3]['state'] == 'occupied' and out[3]['probs'] == {'empty': 0.2, 'occupied': 0.8}
    assert det.feed(line) is None                             # 길이 다른 패킷 무시
    print('selfcheck OK')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('-p', '--port', help='시리얼 포트 (예: COM5)')
    ap.add_argument('--replay', nargs='+', metavar='CSV', help='녹화 파일 재생')
    ap.add_argument('--calibrate', metavar='OUT.json', help='빈방 보정 파일 만들기 (방 비우고 실행)')
    ap.add_argument('--baseline', default=BASELINE, help='빈방 보정 파일')
    ap.add_argument('--seconds', type=float, default=30, help='시리얼 보정 녹화 시간(초)')
    ap.add_argument('--loop', action='store_true', help='재생 무한 반복')
    ap.add_argument('--fast', action='store_true', help='재생 대기 없이 최대 속도')
    ap.add_argument('--model', default=MODEL)
    ap.add_argument('--selfcheck', action='store_true')
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck(); sys.exit()
    if not (a.port or a.replay):
        ap.error('-p 포트, --replay 파일, --selfcheck 중 하나 필요')
    if a.calibrate:
        if a.port:
            print(f'빈방 보정 {a.seconds:.0f}초: 방을 비워주세요', file=sys.stderr, flush=True)
        b = calibrate(read_serial(a.port, a.seconds) if a.port else read_files(a.replay), a.model)
        with open(a.calibrate, 'w', encoding='utf-8') as f:
            json.dump(b, f, indent=1)
        print(f'보정 저장: {a.calibrate} (창 {b["n_windows"]}개)', file=sys.stderr)
    else:
        try:
            det = Detector(a.model, a.baseline)
        except (FileNotFoundError, ValueError) as e:
            sys.exit(str(e))
        for line in (read_serial(a.port) if a.port else read_files(a.replay, a.loop, a.fast)):
            emit(det.feed(line))
