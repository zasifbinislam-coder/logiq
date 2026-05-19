"""
LogIQ — Component catalog.

Curated database of common UAV components (motors, ESCs, props, batteries,
flight controllers, etc.) with spec sheets. Used by the hardware-profile
feature and the compatibility analyzer.

The catalog is a hand-rolled subset of widely-used parts in the BD market.
A future version can pull from a live datasheet API.
"""
from __future__ import annotations

# Each spec follows a normalized schema per type.

MOTORS = [
    # racing / freestyle 5"
    {"id": "tmotor_f60_pro_v_1750",   "brand": "T-Motor",       "model": "F60 Pro V 1750KV",   "kv": 1750, "max_current_a": 38.5, "weight_g": 33,  "shaft_mm": 5, "prop_recommended_min_in": 5, "prop_recommended_max_in": 6, "battery_cells_min": 4, "battery_cells_max": 6, "type": "outrunner"},
    {"id": "tmotor_f40_pro_iv_2400",  "brand": "T-Motor",       "model": "F40 Pro IV 2400KV",  "kv": 2400, "max_current_a": 36.0, "weight_g": 30,  "shaft_mm": 5, "prop_recommended_min_in": 5, "prop_recommended_max_in": 5, "battery_cells_min": 4, "battery_cells_max": 4, "type": "outrunner"},
    {"id": "iflight_xing_2207_1855",  "brand": "iFlight",       "model": "XING 2207 1855KV",   "kv": 1855, "max_current_a": 32.0, "weight_g": 32,  "shaft_mm": 5, "prop_recommended_min_in": 5, "prop_recommended_max_in": 6, "battery_cells_min": 4, "battery_cells_max": 6, "type": "outrunner"},
    {"id": "emax_mt2204_2300",        "brand": "Emax",          "model": "MT2204 2300KV",      "kv": 2300, "max_current_a": 20.0, "weight_g": 23,  "shaft_mm": 3, "prop_recommended_min_in": 5, "prop_recommended_max_in": 5, "battery_cells_min": 3, "battery_cells_max": 4, "type": "outrunner"},
    {"id": "brotherhobby_r6_2306",    "brand": "BrotherHobby",  "model": "R6 2306 2450KV",     "kv": 2450, "max_current_a": 36.0, "weight_g": 33,  "shaft_mm": 5, "prop_recommended_min_in": 5, "prop_recommended_max_in": 5, "battery_cells_min": 4, "battery_cells_max": 6, "type": "outrunner"},
    {"id": "lumenier_rx2206_2450",    "brand": "Lumenier",      "model": "RX2206 2450KV",      "kv": 2450, "max_current_a": 30.0, "weight_g": 28,  "shaft_mm": 5, "prop_recommended_min_in": 5, "prop_recommended_max_in": 5, "battery_cells_min": 3, "battery_cells_max": 4, "type": "outrunner"},
    # photography
    {"id": "dji_2212_920",            "brand": "DJI",           "model": "2212 920KV",         "kv": 920,  "max_current_a": 15.0, "weight_g": 60,  "shaft_mm": 4, "prop_recommended_min_in": 9, "prop_recommended_max_in": 11, "battery_cells_min": 3, "battery_cells_max": 4, "type": "outrunner"},
    {"id": "sunnysky_v2806_740",      "brand": "SunnySky",      "model": "V2806 740KV",        "kv": 740,  "max_current_a": 22.0, "weight_g": 81,  "shaft_mm": 5, "prop_recommended_min_in": 9, "prop_recommended_max_in": 12, "battery_cells_min": 4, "battery_cells_max": 6, "type": "outrunner"},
    {"id": "tmotor_mn5008_400",       "brand": "T-Motor",       "model": "MN5008 400KV",       "kv": 400,  "max_current_a": 28.0, "weight_g": 187, "shaft_mm": 6, "prop_recommended_min_in": 15, "prop_recommended_max_in": 17, "battery_cells_min": 6, "battery_cells_max": 6, "type": "outrunner"},
    # heavy lift / industrial
    {"id": "tmotor_u8ii_100",         "brand": "T-Motor",       "model": "U8II 100KV",         "kv": 100,  "max_current_a": 42.0, "weight_g": 240, "shaft_mm": 8, "prop_recommended_min_in": 28, "prop_recommended_max_in": 30, "battery_cells_min": 12, "battery_cells_max": 12, "type": "outrunner"},
    {"id": "eaglepower_6215_240",     "brand": "Eaglepower",    "model": "6215 240KV",         "kv": 240,  "max_current_a": 40.0, "weight_g": 195, "shaft_mm": 8, "prop_recommended_min_in": 22, "prop_recommended_max_in": 24, "battery_cells_min": 6, "battery_cells_max": 12, "type": "outrunner"},
    # toy / sub-250g
    {"id": "happymodel_se1404_2900",  "brand": "HappyModel",    "model": "SE1404 2900KV",      "kv": 2900, "max_current_a": 16.0, "weight_g": 9,   "shaft_mm": 1.5, "prop_recommended_min_in": 3, "prop_recommended_max_in": 3.5, "battery_cells_min": 3, "battery_cells_max": 4, "type": "outrunner"},
]


ESCS = [
    {"id": "hobbywing_xrotor_40a",    "brand": "Hobbywing",     "model": "XRotor 40A",          "max_current_a": 40, "burst_a": 50, "voltage_cells_min": 3, "voltage_cells_max": 6, "weight_g": 11,  "bec_v": None, "fw": "BLHeli_32"},
    {"id": "holybro_tekko32_65a",     "brand": "Holybro",       "model": "Tekko32 F3 65A",      "max_current_a": 65, "burst_a": 80, "voltage_cells_min": 3, "voltage_cells_max": 6, "weight_g": 16,  "bec_v": None, "fw": "BLHeli_32"},
    {"id": "tmotor_f45a_v2",          "brand": "T-Motor",       "model": "F45A V2",             "max_current_a": 45, "burst_a": 55, "voltage_cells_min": 3, "voltage_cells_max": 6, "weight_g": 8,   "bec_v": None, "fw": "BLHeli_32"},
    {"id": "tmotor_alpha_60a_hv",     "brand": "T-Motor",       "model": "ALPHA 60A HV",        "max_current_a": 60, "burst_a": 75, "voltage_cells_min": 6, "voltage_cells_max": 14, "weight_g": 40, "bec_v": 5.5, "fw": "ALPHA"},
    {"id": "blheli_s_20a",            "brand": "Generic",       "model": "BLHeli_S 20A",        "max_current_a": 20, "burst_a": 25, "voltage_cells_min": 2, "voltage_cells_max": 4, "weight_g": 6,   "bec_v": None, "fw": "BLHeli_S"},
    {"id": "aikon_ak32_35a",          "brand": "Aikon",         "model": "AK32 35A",            "max_current_a": 35, "burst_a": 45, "voltage_cells_min": 3, "voltage_cells_max": 6, "weight_g": 8,   "bec_v": None, "fw": "BLHeli_32"},
    {"id": "hobbywing_skywalker_40a", "brand": "Hobbywing",     "model": "Skywalker 40A",       "max_current_a": 40, "burst_a": 55, "voltage_cells_min": 2, "voltage_cells_max": 4, "weight_g": 39,  "bec_v": 5.0, "fw": "SimonK"},
    {"id": "tmotor_70a_6s",           "brand": "T-Motor",       "model": "70A 6S Multi-Rotor",  "max_current_a": 70, "burst_a": 80, "voltage_cells_min": 3, "voltage_cells_max": 6, "weight_g": 32,  "bec_v": 5.5, "fw": "BLHeli_32"},
]


PROPS = [
    {"id": "hqprop_5x4_3x3",        "brand": "HQProp",   "model": "5x4.3x3 V1S",       "diameter_in": 5.0,  "pitch_in": 4.3, "blades": 3, "weight_g": 4.5,  "material": "PC"},
    {"id": "gemfan_5152s",          "brand": "Gemfan",   "model": "5152S Hurricane",   "diameter_in": 5.1,  "pitch_in": 5.2, "blades": 3, "weight_g": 4.8,  "material": "PC"},
    {"id": "dal_cyclone_t5046",     "brand": "DAL",      "model": "Cyclone T5046C",    "diameter_in": 5.0,  "pitch_in": 4.6, "blades": 3, "weight_g": 4.2,  "material": "PC"},
    {"id": "hq_t3x3x3",             "brand": "HQProp",   "model": "T3x3x3",            "diameter_in": 3.0,  "pitch_in": 3.0, "blades": 3, "weight_g": 1.4,  "material": "PC"},
    {"id": "dji_1045",              "brand": "DJI",      "model": "1045 (10x4.5)",     "diameter_in": 10.0, "pitch_in": 4.5, "blades": 2, "weight_g": 13,   "material": "Nylon"},
    {"id": "tmotor_p15x5",          "brand": "T-Motor",  "model": "P15x5 CF",          "diameter_in": 15.0, "pitch_in": 5.0, "blades": 2, "weight_g": 23,   "material": "Carbon"},
    {"id": "tmotor_carbon_22x66",   "brand": "T-Motor",  "model": "22x66 Carbon",      "diameter_in": 22.0, "pitch_in": 6.6, "blades": 2, "weight_g": 58,   "material": "Carbon"},
    {"id": "gemfan_2030",           "brand": "Gemfan",   "model": "2030 4-blade",      "diameter_in": 2.0,  "pitch_in": 3.0, "blades": 4, "weight_g": 0.4,  "material": "PC"},
]


BATTERIES = [
    {"id": "tattu_rline_1300_4s_95c",      "brand": "Tattu",        "model": "R-Line 1300mAh 4S 95C",         "cells": 4, "capacity_mah": 1300,  "c_rating": 95,  "weight_g": 165,  "connector": "XT60",  "chemistry": "LiPo"},
    {"id": "cnhl_black_1500_4s_100c",      "brand": "CNHL",         "model": "Black Series 1500mAh 4S 100C",  "cells": 4, "capacity_mah": 1500,  "c_rating": 100, "weight_g": 175,  "connector": "XT60",  "chemistry": "LiPo"},
    {"id": "gnb_1300_6s_120c",             "brand": "GNB",          "model": "6S 1300mAh 120C",               "cells": 6, "capacity_mah": 1300,  "c_rating": 120, "weight_g": 220,  "connector": "XT60",  "chemistry": "LiPo"},
    {"id": "tattu_5200_4s_15c",            "brand": "Tattu",        "model": "5200mAh 4S 15C",                "cells": 4, "capacity_mah": 5200,  "c_rating": 15,  "weight_g": 470,  "connector": "XT60",  "chemistry": "LiPo"},
    {"id": "tattu_plus_22000_6s_25c",      "brand": "Tattu Plus",   "model": "22000mAh 6S 25C",               "cells": 6, "capacity_mah": 22000, "c_rating": 25,  "weight_g": 2680, "connector": "AS150", "chemistry": "LiPo"},
    {"id": "tattu_plus_62000_6s2p_15c",    "brand": "Tattu Plus",   "model": "62000mAh 6S2P 15C",             "cells": 6, "capacity_mah": 62000, "c_rating": 15,  "weight_g": 7800, "connector": "AS150", "chemistry": "LiPo"},
    {"id": "dji_intelligent_4s_5200",      "brand": "DJI",          "model": "Phantom 4S 5200mAh",            "cells": 4, "capacity_mah": 5200,  "c_rating": 10,  "weight_g": 365,  "connector": "Custom", "chemistry": "LiPo"},
]


FLIGHT_CONTROLLERS = [
    {"id": "pixhawk_cube_orange",   "brand": "CubePilot", "model": "Pixhawk Cube Orange",    "mcu": "STM32H7", "voltage_v": 5, "weight_g": 73, "compass": True, "barometer": True, "imu_count": 3},
    {"id": "pixhawk_6c",            "brand": "Holybro",   "model": "Pixhawk 6C",             "mcu": "STM32H743", "voltage_v": 5, "weight_g": 35, "compass": True, "barometer": True, "imu_count": 2},
    {"id": "matek_h743_wing",       "brand": "Matek",     "model": "H743-WING",              "mcu": "STM32H743", "voltage_v": 5, "weight_g": 9, "compass": False, "barometer": True, "imu_count": 1},
    {"id": "speedybee_f7v3",        "brand": "SpeedyBee", "model": "F7 V3",                  "mcu": "STM32F745", "voltage_v": 5, "weight_g": 8, "compass": False, "barometer": True, "imu_count": 1},
]


CATALOG = {
    "motor":   MOTORS,
    "esc":     ESCS,
    "prop":    PROPS,
    "battery": BATTERIES,
    "fc":      FLIGHT_CONTROLLERS,
}


def search(component_type: str, query: str = "", limit: int = 50) -> list[dict]:
    items = CATALOG.get(component_type, [])
    if not query:
        return items[:limit]
    q = query.lower()
    return [c for c in items if q in c["brand"].lower() or q in c["model"].lower() or q in c["id"].lower()][:limit]


def get_by_id(component_type: str, item_id: str) -> dict | None:
    for c in CATALOG.get(component_type, []):
        if c["id"] == item_id:
            return c
    return None
