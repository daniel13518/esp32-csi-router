#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSI 신호 품질 눈으로 확인용. csi_data_read_parse.py 가 저장한 CSV를 읽어
subcarrier별 진폭/시간변동을 그린다. 목적: 재실감지 모델이 배울 게 있는지 판단.

  python csi_quality.py empty.csv occupied.csv --labels 빈방 사람있음
  python csi_quality.py one.csv            # 파일 하나만 봐도 됨
  python csi_quality.py --selfcheck        # 데이터 없이 파싱 로직만 검증
"""
import sys, json, argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def load_amplitude(csv_path):
    """CSV -> (진폭행렬 [패킷 x subcarrier], 원본 df). 'data'열은 [im,re,im,re,...] JSON."""
    df = pd.read_csv(csv_path)
    rows = []
    for s in df['data']:
        try:
            arr = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            continue  # 시리얼 손상 줄(,, 등) 건너뜀
        n = len(arr) // 2
        # subcarrier i = complex(real=arr[2i+1], imag=arr[2i])  <- 원본 파서와 동일
        c = np.array([complex(arr[2 * i + 1], arr[2 * i]) for i in range(n)])
        rows.append(np.abs(c))
    # 길이 다른 패킷은 버림(모드/대역폭 섞이면 발생). ponytail: 최빈 길이만, 필요하면 대역별 분리
    lens = [len(r) for r in rows]
    keep_len = max(set(lens), key=lens.count)
    amp = np.array([r for r in rows if len(r) == keep_len])
    return amp, df


def analyze(paths, labels):
    amps = [load_amplitude(p)[0] for p in paths]

    # subcarrier별: 평균진폭(=신호 유무=해상도), 시간변동 std(=움직임 감지 여지)
    fig, ax = plt.subplots(2, len(paths), figsize=(6 * len(paths), 8), squeeze=False)
    for j, (amp, lab) in enumerate(zip(amps, labels)):
        ax[0, j].imshow(amp.T, aspect='auto', origin='lower', cmap='viridis')
        ax[0, j].set_title(f'{lab}: amplitude heatmap (x=time, y=subcarrier)')
        ax[0, j].set_xlabel('packet'); ax[0, j].set_ylabel('subcarrier')
        ax[1, j].plot(amp.mean(0), label='mean amp')
        ax[1, j].plot(amp.std(0), label='temporal std', color='r')
        ax[1, j].set_title(f'{lab}: per-subcarrier mean / temporal std')
        ax[1, j].set_xlabel('subcarrier'); ax[1, j].legend()
    fig.tight_layout(); fig.savefig('csi_quality.png', dpi=110)

    # 분리 가능성: 빈방 vs 사람 의 subcarrier별 시간변동을 겹쳐 그림 (모델 feasibility의 핵심)
    if len(paths) >= 2:
        plt.figure(figsize=(9, 4))
        for amp, lab in zip(amps, labels):
            plt.plot(amp.std(0), label=lab)
        plt.title('per-subcarrier temporal std (empty vs occupied) - wider gap = easier to detect')
        plt.xlabel('subcarrier'); plt.ylabel('temporal std'); plt.legend()
        plt.tight_layout(); plt.savefig('csi_separability.png', dpi=110)

    # 시간축 직관: 전체 활성 subcarrier 진폭을 시간에 따라 그림 (두 칸 y축 공유해 공정 비교)
    fig2, ax2 = plt.subplots(len(paths), 1, figsize=(11, 3 * len(paths)), squeeze=False, sharey=True)
    for j, (amp, lab) in enumerate(zip(amps, labels)):
        active = np.where(amp.mean(0) > 0.5)[0]  # null(가운데 27~37 등) 제외
        for sc in active:
            ax2[j, 0].plot(amp[:, sc], lw=0.5, alpha=0.35)
        ax2[j, 0].set_title(f'{lab}: amplitude over time (all {len(active)} active subcarriers)')
        ax2[j, 0].set_xlabel('packet (time)'); ax2[j, 0].set_ylabel('amplitude')
    fig2.tight_layout(); fig2.savefig('csi_timeseries.png', dpi=110)

    # 숫자 요약
    for amp, lab in zip(amps, labels):
        print(f'{lab:>10}: packets {amp.shape[0]:5d}, subcarriers {amp.shape[1]:3d}, '
              f'mean_amp {amp.mean():6.1f}, mean_temporal_std {amp.std(0).mean():6.2f}')
    print('saved: csi_quality.png, csi_timeseries.png' + (', csi_separability.png' if len(paths) >= 2 else ''))


def selfcheck():
    # arr=[im0,re0, im1,re1] -> subcarrier0=3+? : re=arr[1]=4, im=arr[0]=3 -> |4+3j|=5
    df = pd.DataFrame({'data': [json.dumps([3, 4, -12, 5])]})
    df.to_csv('_sc.csv', index=False)
    amp, _ = load_amplitude('_sc.csv')
    assert np.allclose(amp[0], [5.0, 13.0]), amp  # |4+3j|=5, |5-12j|=13
    print('selfcheck OK')


if __name__ == '__main__':
    if '--selfcheck' in sys.argv:
        selfcheck(); sys.exit()
    ap = argparse.ArgumentParser()
    ap.add_argument('csv', nargs='+')
    ap.add_argument('--labels', nargs='*', default=None)
    a = ap.parse_args()
    labels = a.labels or [p.rsplit('/', 1)[-1].rsplit('\\', 1)[-1] for p in a.csv]
    analyze(a.csv, labels)
