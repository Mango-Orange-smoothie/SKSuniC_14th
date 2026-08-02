"""공통 설정 - 분석 대상 데이터셋을 인자로 바꿔 끼울 수 있게 한다.

사용:
    python 01_screen.py            # 기본(구 데이터)
    python 01_screen.py r1         # R1 데이터
    python 01_screen.py both       # 두 표본 합치고 Source 열 추가
"""
import os
import sys
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 데이터 위치 : --data 인자 > 환경변수 DP_DATA_DIR > 스크립트 상위 폴더
def _data_dir():
    argv = sys.argv
    if "--data" in argv:
        return Path(argv[argv.index("--data") + 1]).expanduser()
    if os.environ.get("DP_DATA_DIR"):
        return Path(os.environ["DP_DATA_DIR"]).expanduser()
    return ROOT.parent


DATA = _data_dir()

FILES = {
    "base": DATA / "DP_HealthIndex_Dataset.csv",
    "r1": DATA / "DP_HealthIndex_Dataset_r1.csv",
}

# 설비 인자 (파라미터 설명서 2. FDC + 환경센서). 응답/ID/시간은 원인인자에서 제외.
FDC = [
    "Laser_Power", "Power_Efficiency", "Laser_Centering_Position",
    "Laser_Current", "Laser_Voltage", "Beam_Diameter",
    "Feed_Speed", "Frequency", "Alignment_Time", "Process_Time",
    "Cutting_X_Index", "Cutting_Y_Index",
    "Head_Temp", "Cooling_Flow", "Cooling_Water_Temp", "Focus",
    "CLN_Flow", "CLN_Pressure", "CLN_Time", "Coating_Flow",
    "Laser_Head_Remain_Time", "Vibration",
    "PLC_CPU_Load", "PLC_Memory", "Network_Latency", "LED_Brightness",
    "Room_Noise", "Door_Open_Count", "Fan_RPM", "Vision_Exposure",
    "Maintenance_Count", "Factory_Power",
]

DEFECTS = ["Chipping", "Remain_Coat", "Particle", "Micro_Crack", "Laser_Paim", "Edge_Burn"]

RESPONSES = [
    "Kerf_Width_Profile", "Top_Kerf", "Bottom_Kerf", "Kerf_Angle", "Groove_Depth",
    "Package_Size_1", "Package_Size_2", "Package_Size_3", "Package_Size_4",
    "Coating_Thickness", "Coating_Uniformity", "Cutting_Offset", "Surface_Roughness",
]


def which(argv=None):
    a = (argv or sys.argv)[1:]
    return a[0].lower() if a and a[0].lower() in ("base", "r1", "both") else "base"


def load(tag=None):
    tag = tag or which()
    if tag == "both":
        parts = []
        for k in ("base", "r1"):
            d = pd.read_csv(FILES[k], encoding="utf-8-sig")
            d["Source"] = k
            parts.append(d)
        df = pd.concat(parts, ignore_index=True)
    else:
        df = pd.read_csv(FILES[tag], encoding="utf-8-sig")
        df["Source"] = tag
    df["Freq_dev"] = (df.Frequency - 100.0).abs()
    return df


def outdir(tag=None):
    tag = tag or which()
    p = ROOT / "out" / tag
    p.mkdir(parents=True, exist_ok=True)
    return p
