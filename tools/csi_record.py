#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""헤드리스 CSI 레코더: 시리얼에서 CSI_DATA 줄을 N초간 받아 CSV로. GUI 없음.
  python csi_record.py -p COM5 -s empty.csv -t 30
csi_quality.py 와 같은 컬럼(header)으로 저장하므로 바로 분석 가능."""
import time, argparse, csv, json, serial

# 원본 도구와 동일한 컬럼명 (위치 매칭). csi_quality 는 'local_timestamp','data' 만 이름으로 씀.
HEADER = ['type', 'id', 'mac', 'rssi', 'rate', 'sig_mode', 'mcs', 'bandwidth', 'smoothing',
          'not_sounding', 'aggregation', 'stbc', 'fec_coding', 'sgi', 'noise_floor', 'ampdu_cnt',
          'channel', 'secondary_channel', 'local_timestamp', 'ant', 'sig_len', 'rx_state', 'len',
          'first_word', 'data']


def record(port, out, seconds, baud=921600):
    ser = serial.Serial(port, baud, timeout=1)  # timeout=1: idle여도 readline이 풀려서 N초에 종료됨
    f = open(out, 'w', newline='', buffering=1)  # line-buffered: 닫아도 안 날아감
    w = csv.writer(f); w.writerow(HEADER)
    n = bad = 0; t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            line = ser.readline().decode('latin1', 'ignore').strip()
            i = line.find('CSI_DATA')
            if i == -1:
                continue
            row = next(csv.reader([line[i:]]))
            try:
                json.loads(row[-1])              # data가 완결+유효 JSON인 줄만 저장 (,, 손상줄 버림)
            except (json.JSONDecodeError, IndexError):
                bad += 1; continue
            w.writerow(row); n += 1
            if n % 20 == 0:
                print(f'\r{time.time()-t0:4.0f}s  {n} rows  ({bad} bad)', end='', flush=True)
    finally:
        ser.close(); f.close()
        print(f'\ndone: {n} rows, {bad} bad -> {out}  ({n/max(seconds,1):.0f} Hz avg)')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('-p', '--port', required=True)
    ap.add_argument('-s', '--store', default='csi.csv')
    ap.add_argument('-t', '--seconds', type=float, default=30)
    a = ap.parse_args()
    record(a.port, a.store, a.seconds)
