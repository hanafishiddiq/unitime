"""
spatial_catalog.py - Spatial & Facility Topology Module for ITB Multi-Campus
============================================================================
Authoritative Python catalog modeling physical infrastructure across:
  - Kampus Ganesha (Bandung)
  - Kampus Jatinangor (Sumedang)

Total Buildings: Exactly 7
Total Rooms: Exactly 20

Strict Tiered Coordinate Distribution:
  - Tier 1: Exactly 8 rooms (40.0%) with room-level Cartesian/GPS coordinates.
  - Tier 2: Exactly 7 rooms (35.0%) with building-level coordinates only (room coords null).
  - Tier 3: Exactly 5 rooms (25.0%) with completely missing coordinates (building and room null).

Capacity Categories:
  - Seminar rooms (20 seats): e.g. 7603 (Cap 20)
  - Standard classrooms (40-60 seats): 13 rooms (Capacities 40, 45, 50, 60)
  - Computer & hardware labs (28-35 workstations): 4 rooms (Capacities 28, 30, 32)
  - Auditoriums & amphitheatres (150-200 seats): 2 rooms (Capacities 150, 200)

Equipment Flags:
  - GPU Workstations
  - Projector
  - Audio System
  - SmartBoard
  - ComputerLab
  - Hardware Stations

Distance Formula:
  Vincenty's inverse formula on WGS84 ellipsoid matching UniTime's DistanceMetric.java
  (a = 6378137.0 m, b = 6356752.3142 m, f = 1.0 / 298.257223563).
"""

from __future__ import annotations

import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ==============================================================================
# 1. WGS84 ELLIPSOID CONSTANTS (Matching UniTime DistanceMetric.java)
# ==============================================================================
WGS84_A: float = 6378137.0
WGS84_B: float = 6356752.3142
WGS84_F: float = 1.0 / 298.257223563

# Default UniTime fallback distance in meters when coordinates are missing
DEFAULT_NULL_DISTANCE_METERS: float = 10000.0

# Student / faculty walking speed in meters per minute (1000m / 15min)
DEFAULT_WALKING_SPEED_MPM: float = 1000.0 / 15.0  # 66.6667 m/min

# Minimum cross-campus travel time in minutes between Ganesha and Jatinangor (~27 km)
CROSS_CAMPUS_MIN_TRAVEL_MINUTES: float = 60.0

# Standard Equipment Flags
EQUIPMENT_FLAGS: List[str] = [
    "GPU Workstations",
    "Projector",
    "Audio System",
    "SmartBoard",
    "ComputerLab",
    "Hardware Stations",
]

# ==============================================================================
# 2. CAMPUS DEFINITIONS
# ==============================================================================
CAMPUSES: Dict[str, Dict[str, Any]] = {
    "Kampus Ganesha": {
        "code": "GANESHA",
        "name": "Kampus Ganesha",
        "city": "Bandung",
        "address": "Jl. Ganesha No. 10, Lebak Siliwangi, Coblong, Kota Bandung, Jawa Barat 40132",
        "reference_coordinates": {"latitude": -6.8915, "longitude": 107.6107},
        "buildings": ["LTV", "LTVIII", "LTIII", "GKUB"],
    },
    "Kampus Jatinangor": {
        "code": "JATINANGOR",
        "name": "Kampus Jatinangor",
        "city": "Sumedang",
        "address": "Jl. Letjen Purn. Dr. (HC) Mashudi No. 1, Jatinangor, Sumedang, Jawa Barat 45363",
        "reference_coordinates": {"latitude": -6.9312, "longitude": 107.7725},
        "buildings": ["GKU1J", "KOICA", "LABTJ"],
    },
}

# ==============================================================================
# 3. BUILDING DEFINITIONS (7 Buildings)
# ==============================================================================
BUILDINGS: Dict[str, Dict[str, Any]] = {
    # --- KAMPUS GANESHA BUILDINGS ---
    "LTV": {
        "abbreviation": "LTV",
        "name": "Labtek V Benny Subianto",
        "external_id": "BLD_GANESHA_LTV",
        "campus": "Kampus Ganesha",
        "coordinates": {"longitude": 107.61030, "latitude": -6.89040},
        "rooms": ["7601", "7602", "Lab-1", "7603"],
    },
    "LTVIII": {
        "abbreviation": "LTVIII",
        "name": "Labtek VIII Achmad Bakrie",
        "external_id": "BLD_GANESHA_LTVIII",
        "campus": "Kampus Ganesha",
        "coordinates": {"longitude": 107.60980, "latitude": -6.89060},
        "rooms": ["8201", "Lab-El", "8202"],
    },
    "LTIII": {
        "abbreviation": "LTIII",
        "name": "Labtek III Matthias Aroef",
        "external_id": "BLD_GANESHA_LTIII",
        "campus": "Kampus Ganesha",
        "coordinates": {"longitude": 107.60950, "latitude": -6.88980},
        "rooms": ["3101", "3102"],
    },
    "GKUB": {
        "abbreviation": "GKUB",
        "name": "Gedung Kuliah Umum Barat",
        "external_id": "BLD_GANESHA_GKUB",
        "campus": "Kampus Ganesha",
        "coordinates": {"longitude": 107.60990, "latitude": -6.89180},
        "rooms": ["9001", "9002"],
    },
    # --- KAMPUS JATINANGOR BUILDINGS ---
    "GKU1J": {
        "abbreviation": "GKU1J",
        "name": "Gedung Kuliah Umum 1 Jatinangor",
        "external_id": "BLD_JATINANGOR_GKU1J",
        "campus": "Kampus Jatinangor",
        "coordinates": {"longitude": 107.77280, "latitude": -6.93150},
        "rooms": ["101", "102"],
    },
    "KOICA": {
        "abbreviation": "KOICA",
        "name": "Gedung KOICA",
        "external_id": "BLD_JATINANGOR_KOICA",
        "campus": "Kampus Jatinangor",
        "coordinates": {"longitude": 107.77350, "latitude": -6.93220},
        "rooms": ["201", "202"],
    },
    "LABTJ": {
        "abbreviation": "LABTJ",
        "name": "Lab Terpadu Jatinangor",
        "external_id": "BLD_JATINANGOR_LABTJ",
        "campus": "Kampus Jatinangor",
        # Tier 3: Building coordinates are completely missing / null
        "coordinates": None,
        "rooms": ["Lab-01", "Lab-02", "301", "302", "303"],
    },
}

# ==============================================================================
# 4. ROOM DEFINITIONS (Exactly 20 Rooms)
# ==============================================================================
ALL_ROOMS: List[Dict[str, Any]] = [
    # --------------------------------------------------------------------------
    # KAMPUS GANESHA - Labtek V Benny Subianto (LTV)
    # --------------------------------------------------------------------------
    {
        "room_number": "7601",
        "display_name": "Labtek V - 7601",
        "external_id": "RM_LTV_7601",
        "building_abbreviation": "LTV",
        "building": "Labtek V Benny Subianto",
        "campus": "Kampus Ganesha",
        "capacity": 45,
        "exam_capacity": 25,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.61028, "latitude": -6.89038},
        "effective_coordinates": {"longitude": 107.61028, "latitude": -6.89038},
        "features": ["SmartBoard", "Projector"],
        "department": "IF",
        "department_name": "Teknik Informatika",
    },
    {
        "room_number": "7602",
        "display_name": "Labtek V - 7602",
        "external_id": "RM_LTV_7602",
        "building_abbreviation": "LTV",
        "building": "Labtek V Benny Subianto",
        "campus": "Kampus Ganesha",
        "capacity": 45,
        "exam_capacity": 25,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.61035, "latitude": -6.89042},
        "effective_coordinates": {"longitude": 107.61035, "latitude": -6.89042},
        "features": ["SmartBoard", "Projector"],
        "department": "IF",
        "department_name": "Teknik Informatika",
    },
    {
        "room_number": "Lab-1",
        "display_name": "Labtek V - Lab Komputer AI (Lab-1)",
        "external_id": "RM_LTV_LAB1",
        "building_abbreviation": "LTV",
        "building": "Labtek V Benny Subianto",
        "campus": "Kampus Ganesha",
        "capacity": 30,
        "exam_capacity": 30,
        "room_classification": "computingLab",
        "scheduled_room_type": "computingLab",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.61025, "latitude": -6.89045},
        "effective_coordinates": {"longitude": 107.61025, "latitude": -6.89045},
        "features": ["GPU Workstations", "Audio System", "ComputerLab"],
        "department": "IF",
        "department_name": "Teknik Informatika",
    },
    {
        "room_number": "7603",
        "display_name": "Labtek V - 7603 (Ruang Seminar)",
        "external_id": "RM_LTV_7603",
        "building_abbreviation": "LTV",
        "building": "Labtek V Benny Subianto",
        "campus": "Kampus Ganesha",
        "capacity": 20,
        "exam_capacity": 15,
        "room_classification": "seminar",
        "scheduled_room_type": "departmental",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.61030, "latitude": -6.89040},
        "features": ["SmartBoard", "Projector"],
        "department": "IF",
        "department_name": "Teknik Informatika",
    },
    # --------------------------------------------------------------------------
    # KAMPUS GANESHA - Labtek VIII Achmad Bakrie (LTVIII)
    # --------------------------------------------------------------------------
    {
        "room_number": "8201",
        "display_name": "Labtek VIII - 8201",
        "external_id": "RM_LTVIII_8201",
        "building_abbreviation": "LTVIII",
        "building": "Labtek VIII Achmad Bakrie",
        "campus": "Kampus Ganesha",
        "capacity": 50,
        "exam_capacity": 30,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.60982, "latitude": -6.89058},
        "effective_coordinates": {"longitude": 107.60982, "latitude": -6.89058},
        "features": ["Projector", "Audio System"],
        "department": "EL",
        "department_name": "Teknik Elektro",
    },
    {
        "room_number": "Lab-El",
        "display_name": "Labtek VIII - Lab Elektronika (Lab-El)",
        "external_id": "RM_LTVIII_LABEL",
        "building_abbreviation": "LTVIII",
        "building": "Labtek VIII Achmad Bakrie",
        "campus": "Kampus Ganesha",
        "capacity": 28,
        "exam_capacity": 28,
        "room_classification": "specialLab",
        "scheduled_room_type": "departmental",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.60975, "latitude": -6.89065},
        "effective_coordinates": {"longitude": 107.60975, "latitude": -6.89065},
        "features": ["Hardware Stations", "Projector"],
        "department": "EL",
        "department_name": "Teknik Elektro",
    },
    {
        "room_number": "8202",
        "display_name": "Labtek VIII - 8202",
        "external_id": "RM_LTVIII_8202",
        "building_abbreviation": "LTVIII",
        "building": "Labtek VIII Achmad Bakrie",
        "campus": "Kampus Ganesha",
        "capacity": 50,
        "exam_capacity": 30,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.60980, "latitude": -6.89060},
        "features": ["Projector"],
        "department": "EL",
        "department_name": "Teknik Elektro",
    },
    # --------------------------------------------------------------------------
    # KAMPUS GANESHA - Labtek III Matthias Aroef (LTIII)
    # --------------------------------------------------------------------------
    {
        "room_number": "3101",
        "display_name": "Labtek III - 3101",
        "external_id": "RM_LTIII_3101",
        "building_abbreviation": "LTIII",
        "building": "Labtek III Matthias Aroef",
        "campus": "Kampus Ganesha",
        "capacity": 60,
        "exam_capacity": 35,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.60952, "latitude": -6.88978},
        "effective_coordinates": {"longitude": 107.60952, "latitude": -6.88978},
        "features": ["Projector", "Audio System"],
        "department": "TI",
        "department_name": "Teknik Industri",
    },
    {
        "room_number": "3102",
        "display_name": "Labtek III - 3102",
        "external_id": "RM_LTIII_3102",
        "building_abbreviation": "LTIII",
        "building": "Labtek III Matthias Aroef",
        "campus": "Kampus Ganesha",
        "capacity": 60,
        "exam_capacity": 35,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.60950, "latitude": -6.88980},
        "features": ["Projector"],
        "department": "TI",
        "department_name": "Teknik Industri",
    },
    # --------------------------------------------------------------------------
    # KAMPUS GANESHA - Gedung Kuliah Umum Barat (GKUB)
    # --------------------------------------------------------------------------
    {
        "room_number": "9001",
        "display_name": "GKU Barat - 9001 (Auditorium)",
        "external_id": "RM_GKUB_9001",
        "building_abbreviation": "GKUB",
        "building": "Gedung Kuliah Umum Barat",
        "campus": "Kampus Ganesha",
        "capacity": 150,
        "exam_capacity": 80,
        "room_classification": "auditorium",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.60988, "latitude": -6.89175},
        "effective_coordinates": {"longitude": 107.60988, "latitude": -6.89175},
        "features": ["Projector", "Audio System"],
        "department": "TPB",
        "department_name": "Tahap Bersama",
    },
    {
        "room_number": "9002",
        "display_name": "GKU Barat - 9002 (Amphitheatre)",
        "external_id": "RM_GKUB_9002",
        "building_abbreviation": "GKUB",
        "building": "Gedung Kuliah Umum Barat",
        "campus": "Kampus Ganesha",
        "capacity": 200,
        "exam_capacity": 110,
        "room_classification": "auditorium",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 1,
        "coordinate_tier_description": "Room-level explicit coordinates",
        "room_coordinates": {"longitude": 107.60995, "latitude": -6.89182},
        "effective_coordinates": {"longitude": 107.60995, "latitude": -6.89182},
        "features": ["Projector", "Audio System"],
        "department": "TPB",
        "department_name": "Tahap Bersama",
    },
    # --------------------------------------------------------------------------
    # KAMPUS JATINANGOR - Gedung Kuliah Umum 1 Jatinangor (GKU1J)
    # --------------------------------------------------------------------------
    {
        "room_number": "101",
        "display_name": "GKU 1 Jatinangor - 101",
        "external_id": "RM_GKU1J_101",
        "building_abbreviation": "GKU1J",
        "building": "Gedung Kuliah Umum 1 Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 60,
        "exam_capacity": 35,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.77280, "latitude": -6.93150},
        "features": ["Projector", "Audio System"],
        "department": "TPB",
        "department_name": "Tahap Bersama",
    },
    {
        "room_number": "102",
        "display_name": "GKU 1 Jatinangor - 102",
        "external_id": "RM_GKU1J_102",
        "building_abbreviation": "GKU1J",
        "building": "Gedung Kuliah Umum 1 Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 50,
        "exam_capacity": 30,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.77280, "latitude": -6.93150},
        "features": ["Projector"],
        "department": "TPB",
        "department_name": "Tahap Bersama",
    },
    # --------------------------------------------------------------------------
    # KAMPUS JATINANGOR - Gedung KOICA (KOICA)
    # --------------------------------------------------------------------------
    {
        "room_number": "201",
        "display_name": "Gedung KOICA - 201 (Lab Komputer SI)",
        "external_id": "RM_KOICA_201",
        "building_abbreviation": "KOICA",
        "building": "Gedung KOICA",
        "campus": "Kampus Jatinangor",
        "capacity": 40,
        "exam_capacity": 25,
        "room_classification": "computingLab",
        "scheduled_room_type": "computingLab",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.77350, "latitude": -6.93220},
        "features": ["ComputerLab", "Projector"],
        "department": "SI",
        "department_name": "Sistem Informasi",
    },
    {
        "room_number": "202",
        "display_name": "Gedung KOICA - 202 (Lab Komputer)",
        "external_id": "RM_KOICA_202",
        "building_abbreviation": "KOICA",
        "building": "Gedung KOICA",
        "campus": "Kampus Jatinangor",
        "capacity": 40,
        "exam_capacity": 25,
        "room_classification": "computingLab",
        "scheduled_room_type": "computingLab",
        "instructional": True,
        "coordinate_tier": 2,
        "coordinate_tier_description": "Building-level inherited coordinates (room coords null)",
        "room_coordinates": None,
        "effective_coordinates": {"longitude": 107.77350, "latitude": -6.93220},
        "features": ["ComputerLab", "Projector"],
        "department": "SI",
        "department_name": "Sistem Informasi",
    },
    # --------------------------------------------------------------------------
    # KAMPUS JATINANGOR - Lab Terpadu Jatinangor (LABTJ) (Tier 3 - Completely Null)
    # --------------------------------------------------------------------------
    {
        "room_number": "Lab-01",
        "display_name": "Lab Terpadu - Lab Perangkat Keras (Lab-01)",
        "external_id": "RM_LABTJ_LAB01",
        "building_abbreviation": "LABTJ",
        "building": "Lab Terpadu Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 30,
        "exam_capacity": 30,
        "room_classification": "computingLab",
        "scheduled_room_type": "computingLab",
        "instructional": True,
        "coordinate_tier": 3,
        "coordinate_tier_description": "Completely missing/null coordinates (building and room null)",
        "room_coordinates": None,
        "effective_coordinates": None,
        "features": ["Hardware Stations", "ComputerLab"],
        "department": "EL",
        "department_name": "Teknik Elektro",
    },
    {
        "room_number": "Lab-02",
        "display_name": "Lab Terpadu - Lab Komputasi Terapan (Lab-02)",
        "external_id": "RM_LABTJ_LAB02",
        "building_abbreviation": "LABTJ",
        "building": "Lab Terpadu Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 32,
        "exam_capacity": 32,
        "room_classification": "computingLab",
        "scheduled_room_type": "computingLab",
        "instructional": True,
        "coordinate_tier": 3,
        "coordinate_tier_description": "Completely missing/null coordinates (building and room null)",
        "room_coordinates": None,
        "effective_coordinates": None,
        "features": ["ComputerLab", "Projector"],
        "department": "IF",
        "department_name": "Teknik Informatika",
    },
    {
        "room_number": "301",
        "display_name": "Lab Terpadu - 301",
        "external_id": "RM_LABTJ_301",
        "building_abbreviation": "LABTJ",
        "building": "Lab Terpadu Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 40,
        "exam_capacity": 25,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 3,
        "coordinate_tier_description": "Completely missing/null coordinates (building and room null)",
        "room_coordinates": None,
        "effective_coordinates": None,
        "features": ["Projector"],
        "department": "TI",
        "department_name": "Teknik Industri",
    },
    {
        "room_number": "302",
        "display_name": "Lab Terpadu - 302",
        "external_id": "RM_LABTJ_302",
        "building_abbreviation": "LABTJ",
        "building": "Lab Terpadu Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 40,
        "exam_capacity": 25,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 3,
        "coordinate_tier_description": "Completely missing/null coordinates (building and room null)",
        "room_coordinates": None,
        "effective_coordinates": None,
        "features": ["Projector"],
        "department": "TI",
        "department_name": "Teknik Industri",
    },
    {
        "room_number": "303",
        "display_name": "Lab Terpadu - 303",
        "external_id": "RM_LABTJ_303",
        "building_abbreviation": "LABTJ",
        "building": "Lab Terpadu Jatinangor",
        "campus": "Kampus Jatinangor",
        "capacity": 50,
        "exam_capacity": 30,
        "room_classification": "classroom",
        "scheduled_room_type": "genClassroom",
        "instructional": True,
        "coordinate_tier": 3,
        "coordinate_tier_description": "Completely missing/null coordinates (building and room null)",
        "room_coordinates": None,
        "effective_coordinates": None,
        "features": ["Projector"],
        "department": "SI",
        "department_name": "Sistem Informasi",
    },
]

# Fast index maps
ROOMS_BY_KEY: Dict[str, Dict[str, Any]] = {}
ROOMS_BY_EXTERNAL_ID: Dict[str, Dict[str, Any]] = {}

for r in ALL_ROOMS:
    key1 = f"{r['building_abbreviation']} {r['room_number']}"
    key2 = f"{r['building_abbreviation']}_{r['room_number']}"
    ROOMS_BY_KEY[key1.upper()] = r
    ROOMS_BY_KEY[key2.upper()] = r
    ROOMS_BY_EXTERNAL_ID[r["external_id"]] = r

# ==============================================================================
# 5. GEODESIC MATH (WGS-84 Vincenty's Formula matching UniTime)
# ==============================================================================
def deg2rad(deg: float) -> float:
    """Convert degrees to radians."""
    return deg * math.pi / 180.0


def vincenty_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    a: float = WGS84_A,
    b: float = WGS84_B,
    f: float = WGS84_F,
) -> float:
    """
    Compute geodesic distance in meters between two coordinates on the WGS84 ellipsoid
    using Vincenty's inverse formula.

    Directly matches org.cpsolver.ifs.util.DistanceMetric.java getDistanceInMeters().
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    L = deg2rad(lon2 - lon1)
    U1 = math.atan((1.0 - f) * math.tan(deg2rad(lat1)))
    U2 = math.atan((1.0 - f) * math.tan(deg2rad(lat2)))
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)

    lamb = L
    iter_limit = 100
    while iter_limit > 0:
        sinLambda = math.sin(lamb)
        cosLambda = math.cos(lamb)
        sinSigma = math.sqrt(
            (cosU2 * sinLambda) ** 2
            + (cosU1 * sinU2 - sinU1 * cosU2 * cosLambda) ** 2
        )
        if sinSigma == 0:
            return 0.0  # Coincident points

        cosSigma = sinU1 * sinU2 + cosU1 * cosU2 * cosLambda
        sigma = math.atan2(sinSigma, cosSigma)
        sinAlpha = cosU1 * cosU2 * sinLambda / sinSigma
        cosSqAlpha = 1.0 - sinAlpha * sinAlpha
        cos2SigmaM = (
            cosSigma - 2.0 * sinU1 * sinU2 / cosSqAlpha
            if cosSqAlpha != 0.0
            else 0.0
        )
        C = f / 16.0 * cosSqAlpha * (4.0 + f * (4.0 - 3.0 * cosSqAlpha))
        lambda_prev = lamb
        lamb = L + (1.0 - C) * f * sinAlpha * (
            sigma
            + C
            * sinSigma
            * (cos2SigmaM + C * cosSigma * (-1.0 + 2.0 * cos2SigmaM * cos2SigmaM))
        )
        if abs(lamb - lambda_prev) <= 1e-12:
            break
        iter_limit -= 1

    if iter_limit == 0:
        return float("nan")  # Formula failed to converge

    uSq = cosSqAlpha * (a * a - b * b) / (b * b)
    A = 1.0 + uSq / 16384.0 * (4096.0 + uSq * (-768.0 + uSq * (320.0 - 175.0 * uSq)))
    B = uSq / 1024.0 * (256.0 + uSq * (-128.0 + uSq * (74.0 - 47.0 * uSq)))
    deltaSigma = (
        B
        * sinSigma
        * (
            cos2SigmaM
            + B
            / 4.0
            * (
                cosSigma * (-1.0 + 2.0 * cos2SigmaM * cos2SigmaM)
                - B
                / 6.0
                * cos2SigmaM
                * (-3.0 + 4.0 * sinSigma * sinSigma)
                * (-3.0 + 4.0 * cos2SigmaM * cos2SigmaM)
            )
        )
    )

    return b * A * (sigma - deltaSigma)


# Compute reference inter-campus distance (between Ganesha and Jatinangor campus centroids)
INTER_CAMPUS_DISTANCE_METERS: float = vincenty_distance(
    CAMPUSES["Kampus Ganesha"]["reference_coordinates"]["latitude"],
    CAMPUSES["Kampus Ganesha"]["reference_coordinates"]["longitude"],
    CAMPUSES["Kampus Jatinangor"]["reference_coordinates"]["latitude"],
    CAMPUSES["Kampus Jatinangor"]["reference_coordinates"]["longitude"],
)

# ==============================================================================
# 6. LOOKUP & HELPER FUNCTIONS
# ==============================================================================
def get_campus(campus_name_or_code: str) -> Optional[Dict[str, Any]]:
    """Lookup a campus by name or code."""
    query = campus_name_or_code.strip().upper()
    for name, c in CAMPUSES.items():
        if name.upper() == query or c["code"].upper() == query:
            return c
    return None


def get_building(
    abbreviation_or_name: str, campus: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Lookup a building by abbreviation, externalId, or displayName."""
    query = abbreviation_or_name.strip().upper()
    for abbr, b in BUILDINGS.items():
        if (
            abbr.upper() == query
            or b["name"].upper() == query
            or b["external_id"].upper() == query
        ):
            if campus is None or b["campus"].upper() == campus.strip().upper():
                return b
    return None


def get_room(
    room_number: str,
    building: Optional[str] = None,
    campus: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Lookup a room by room number and optional building or campus.
    Accepts composite strings like 'LTV 7601', 'LTV_7601', or 'RM_LTV_7601'.
    """
    clean_room = room_number.strip()

    # Check external ID directly
    if clean_room in ROOMS_BY_EXTERNAL_ID:
        return ROOMS_BY_EXTERNAL_ID[clean_room]

    # Check composite key
    if clean_room.upper() in ROOMS_BY_KEY:
        return ROOMS_BY_KEY[clean_room.upper()]

    # If building is provided
    if building:
        bldg_obj = get_building(building, campus)
        if bldg_obj:
            composite = f"{bldg_obj['abbreviation']} {clean_room}".upper()
            if composite in ROOMS_BY_KEY:
                return ROOMS_BY_KEY[composite]

    # Ambiguity check across rooms
    matches = []
    for r in ALL_ROOMS:
        if r["room_number"].upper() == clean_room.upper():
            if building is None or (
                r["building_abbreviation"].upper() == building.strip().upper()
                or r["building"].upper() == building.strip().upper()
            ):
                if campus is None or r["campus"].upper() == campus.strip().upper():
                    matches.append(r)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        # Prefer matching building if specified
        return matches[0]

    return None


def get_effective_coordinates(
    room_or_identifier: Union[Dict[str, Any], str],
    building: Optional[str] = None,
) -> Optional[Tuple[float, float]]:
    """
    Resolve the effective coordinates (longitude, latitude) for a room.
    Implements UniTime's hierarchical coordinate inheritance:
      - If room has coordinates (Tier 1) -> use them.
      - If room coordinates are null (Tier 2) -> inherit parent building's coordinates.
      - If parent building coordinates are also null (Tier 3) -> return None.
    """
    if isinstance(room_or_identifier, dict):
        room_obj = room_or_identifier
    else:
        room_obj = get_room(room_or_identifier, building)
        if room_obj is None:
            return None

    if room_obj.get("effective_coordinates"):
        eff = room_obj["effective_coordinates"]
        return (eff["longitude"], eff["latitude"])

    # Manual fallback calculation
    if room_obj.get("room_coordinates"):
        rc = room_obj["room_coordinates"]
        return (rc["longitude"], rc["latitude"])

    bldg_obj = BUILDINGS.get(room_obj.get("building_abbreviation", ""))
    if bldg_obj and bldg_obj.get("coordinates"):
        bc = bldg_obj["coordinates"]
        return (bc["longitude"], bc["latitude"])

    return None


def list_rooms(
    campus: Optional[str] = None,
    tier: Optional[int] = None,
    feature: Optional[str] = None,
    min_capacity: Optional[int] = None,
    max_capacity: Optional[int] = None,
    scheduled_room_type: Optional[str] = None,
    department: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter rooms by various criteria."""
    results = []
    for r in ALL_ROOMS:
        if campus and r["campus"].upper() != campus.strip().upper():
            continue
        if tier is not None and r["coordinate_tier"] != tier:
            continue
        if feature and feature not in r["features"]:
            continue
        if min_capacity is not None and r["capacity"] < min_capacity:
            continue
        if max_capacity is not None and r["capacity"] > max_capacity:
            continue
        if scheduled_room_type and r["scheduled_room_type"] != scheduled_room_type:
            continue
        if department and r["department"].upper() != department.strip().upper():
            continue
        results.append(r)
    return results


def get_rooms_by_tier(tier: int) -> List[Dict[str, Any]]:
    """Get all rooms belonging to a specific coordinate tier (1, 2, or 3)."""
    return list_rooms(tier=tier)


def get_rooms_by_feature(feature: str) -> List[Dict[str, Any]]:
    """Get all rooms offering a specific equipment/facility feature."""
    return list_rooms(feature=feature)


def get_rooms_by_capacity_range(min_cap: int, max_cap: int) -> List[Dict[str, Any]]:
    """Get all rooms with capacity between min_cap and max_cap (inclusive)."""
    return list_rooms(min_capacity=min_cap, max_capacity=max_cap)


# ==============================================================================
# 7. DISTANCE & TRAVEL TIME COMPUTATION
# ==============================================================================
def get_distance_in_meters(
    room1: Union[Dict[str, Any], str],
    room2: Union[Dict[str, Any], str],
    null_distance: float = DEFAULT_NULL_DISTANCE_METERS,
) -> float:
    """
    Calculate the physical distance in meters between two rooms using Vincenty's WGS84 formula.
    Gracefully handles missing coordinates (Tier 3) by returning `null_distance`.
    """
    r1 = room1 if isinstance(room1, dict) else get_room(room1)
    r2 = room2 if isinstance(room2, dict) else get_room(room2)

    if r1 is None or r2 is None:
        return null_distance

    # Same room check
    if r1["external_id"] == r2["external_id"]:
        return 0.0

    c1 = get_effective_coordinates(r1)
    c2 = get_effective_coordinates(r2)

    if c1 is None or c2 is None:
        # Tier 3 null coordinates fallback
        return null_distance

    lon1, lat1 = c1
    lon2, lat2 = c2

    return vincenty_distance(lat1, lon1, lat2, lon2)


def get_travel_time_in_minutes(
    room1: Union[Dict[str, Any], str],
    room2: Union[Dict[str, Any], str],
    walking_speed_mpm: float = DEFAULT_WALKING_SPEED_MPM,
    cross_campus_minutes: float = CROSS_CAMPUS_MIN_TRAVEL_MINUTES,
    null_travel_time: float = 60.0,
) -> float:
    """
    Calculate travel time in minutes between two rooms.
      - If same room: 0.0 minutes.
      - If different campuses: enforces minimum cross-campus transit time (60 min).
      - If intra-campus: walking distance in meters divided by walking speed (m/min).
      - If either room lacks coordinates: falls back to null_travel_time.
    """
    r1 = room1 if isinstance(room1, dict) else get_room(room1)
    r2 = room2 if isinstance(room2, dict) else get_room(room2)

    if r1 is None or r2 is None:
        return null_travel_time

    if r1["external_id"] == r2["external_id"]:
        return 0.0

    # Cross-campus travel constraint
    if r1["campus"] != r2["campus"]:
        return cross_campus_minutes

    dist = get_distance_in_meters(r1, r2, null_distance=-1.0)
    if dist < 0:
        return null_travel_time

    return dist / walking_speed_mpm


# ==============================================================================
# 8. SELF-VERIFICATION ROUTINE
# ==============================================================================
def verify_spatial_topology(base_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """
    Comprehensive self-verification routine checking 100% compliance with
    Milestone M1 requirements:
      - 2 campuses, 7 buildings, exactly 20 rooms.
      - Exact coordinate tier distribution: Tier 1 (8, 40%), Tier 2 (7, 35%), Tier 3 (5, 25%).
      - Capacity categories: Seminar (20), Classrooms (40-60), Labs (28-35), Auditoriums (150-200).
      - All 6 equipment flags present and assigned.
      - Effective coordinate inheritance correctness.
      - WGS84 Vincenty formula and inter-campus distance (>15 km).
      - File validity for campus_topology.json and buildingRoomImport.xml.
    """
    checks: List[Dict[str, Any]] = []

    def record_check(name: str, passed: bool, details: str) -> None:
        checks.append({"check": name, "passed": passed, "details": details})
        if not passed:
            raise AssertionError(f"Verification FAILED: {name} - {details}")

    # Check 1: Campus count
    c_count = len(CAMPUSES)
    record_check("Campus Count", c_count == 2, f"Expected 2 campuses, found {c_count}")

    # Check 2: Building count
    b_count = len(BUILDINGS)
    record_check("Building Count", b_count == 7, f"Expected 7 buildings, found {b_count}")

    # Check 3: Room count
    r_count = len(ALL_ROOMS)
    record_check("Room Count", r_count == 20, f"Expected exactly 20 rooms, found {r_count}")

    # Check 4: Coordinate Tier Distribution
    t1_rooms = get_rooms_by_tier(1)
    t2_rooms = get_rooms_by_tier(2)
    t3_rooms = get_rooms_by_tier(3)

    t1_pct = len(t1_rooms) / r_count * 100.0
    t2_pct = len(t2_rooms) / r_count * 100.0
    t3_pct = len(t3_rooms) / r_count * 100.0

    record_check(
        "Tier 1 Distribution (40%)",
        len(t1_rooms) == 8 and abs(t1_pct - 40.0) < 1e-6,
        f"Tier 1: {len(t1_rooms)}/20 ({t1_pct:.1f}%), expected exactly 8 (40.0%)",
    )
    record_check(
        "Tier 2 Distribution (35%)",
        len(t2_rooms) == 7 and abs(t2_pct - 35.0) < 1e-6,
        f"Tier 2: {len(t2_rooms)}/20 ({t2_pct:.1f}%), expected exactly 7 (35.0%)",
    )
    record_check(
        "Tier 3 Distribution (25%)",
        len(t3_rooms) == 5 and abs(t3_pct - 25.0) < 1e-6,
        f"Tier 3: {len(t3_rooms)}/20 ({t3_pct:.1f}%), expected exactly 5 (25.0%)",
    )

    # Check 5: Capacity Categories
    seminar_rooms = [r for r in ALL_ROOMS if r["capacity"] == 20]
    standard_classrooms = [r for r in ALL_ROOMS if 40 <= r["capacity"] <= 60]
    labs = [r for r in ALL_ROOMS if 28 <= r["capacity"] <= 35]
    auditoriums = [r for r in ALL_ROOMS if 150 <= r["capacity"] <= 200]

    record_check(
        "Seminar Room (20 seats)",
        len(seminar_rooms) >= 1,
        f"Found {len(seminar_rooms)} seminar rooms (e.g. {[r['room_number'] for r in seminar_rooms]})",
    )
    record_check(
        "Standard Classrooms (40-60 seats)",
        len(standard_classrooms) >= 8,
        f"Found {len(standard_classrooms)} standard classrooms",
    )
    record_check(
        "Computer/Hardware Labs (28-35 workstations)",
        len(labs) >= 4,
        f"Found {len(labs)} specialized labs",
    )
    record_check(
        "Auditoriums/Amphitheatres (150-200 seats)",
        len(auditoriums) >= 2,
        f"Found {len(auditoriums)} auditoriums ({[r['room_number'] for r in auditoriums]})",
    )

    # Check 6: Equipment Flags
    for flag in EQUIPMENT_FLAGS:
        rooms_with_flag = get_rooms_by_feature(flag)
        record_check(
            f"Equipment Flag: {flag}",
            len(rooms_with_flag) > 0,
            f"Flag '{flag}' assigned to {len(rooms_with_flag)} rooms",
        )

    # Check 7: Effective Coordinate Inheritance
    for r in ALL_ROOMS:
        tier = r["coordinate_tier"]
        eff = get_effective_coordinates(r)
        if tier == 1:
            record_check(
                f"Effective Coords Tier 1 ({r['room_number']})",
                eff is not None and eff == (r["room_coordinates"]["longitude"], r["room_coordinates"]["latitude"]),
                f"Room {r['room_number']} has explicit coordinates {eff}",
            )
        elif tier == 2:
            bldg = BUILDINGS[r["building_abbreviation"]]
            expected_coords = (bldg["coordinates"]["longitude"], bldg["coordinates"]["latitude"])
            record_check(
                f"Effective Coords Tier 2 ({r['room_number']})",
                eff is not None and eff == expected_coords and r["room_coordinates"] is None,
                f"Room {r['room_number']} inherited building coordinates {eff}",
            )
        elif tier == 3:
            record_check(
                f"Effective Coords Tier 3 ({r['room_number']})",
                eff is None and r["room_coordinates"] is None,
                f"Room {r['room_number']} correctly has null coordinates",
            )

    # Check 8: Geodesic Math & Inter-Campus Distance
    d_same = get_distance_in_meters("LTV 7601", "LTV 7601")
    record_check("Distance: Same Room", d_same == 0.0, f"Same room distance is {d_same} m")

    d_intra = get_distance_in_meters("LTV 7601", "LTVIII 8201")
    record_check(
        "Distance: Intra-Campus (LTV to LTVIII)",
        20.0 < d_intra < 200.0,
        f"Intra-campus distance between LTV and LTVIII is {d_intra:.2f} m",
    )

    d_cross = get_distance_in_meters("LTV 7601", "GKU1J 101")
    record_check(
        "Distance: Cross-Campus (LTV to GKU1J)",
        15000.0 < d_cross < 25000.0,
        f"Cross-campus distance between Ganesha (LTV) and Jatinangor (GKU1J) is {d_cross/1000.0:.2f} km",
    )

    t_cross = get_travel_time_in_minutes("LTV 7601", "GKU1J 101")
    record_check(
        "Travel Time: Cross-Campus",
        t_cross >= CROSS_CAMPUS_MIN_TRAVEL_MINUTES,
        f"Cross-campus travel time is {t_cross} minutes (>= {CROSS_CAMPUS_MIN_TRAVEL_MINUTES} min)",
    )

    d_null = get_distance_in_meters("LTV 7601", "LABTJ Lab-01")
    record_check(
        "Distance: Null Coords Fallback",
        d_null == DEFAULT_NULL_DISTANCE_METERS,
        f"Missing coordinates fallback returned {d_null} m",
    )

    # Check 9: File Artifacts Validation
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent

    base_path = Path(base_dir)
    json_path = base_path / "campus_topology.json"
    xml_path = base_path / "buildingRoomImport.xml"

    record_check(
        "File Exists: campus_topology.json",
        json_path.exists(),
        f"Path: {json_path}",
    )
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
        json_rooms = [
            rm
            for c in json_data["campuses"]
            for b in c["buildings"]
            for rm in b["rooms"]
        ]
        record_check(
            "JSON Room Count Match",
            len(json_rooms) == 20,
            f"JSON contains {len(json_rooms)} rooms",
        )

    record_check(
        "File Exists: buildingRoomImport.xml",
        xml_path.exists(),
        f"Path: {xml_path}",
    )
    if xml_path.exists():
        tree = ET.parse(xml_path)
        root = tree.getroot()
        xml_bldgs = root.findall("building")
        xml_rooms = root.findall(".//room")
        record_check(
            "XML Building Count Match",
            len(xml_bldgs) == 7,
            f"XML contains {len(xml_bldgs)} buildings",
        )
        record_check(
            "XML Room Count Match",
            len(xml_rooms) == 20,
            f"XML contains {len(xml_rooms)} rooms",
        )

    return {
        "status": "PASSED",
        "total_checks": len(checks),
        "passed_checks": sum(1 for c in checks if c["passed"]),
        "campuses": c_count,
        "buildings": b_count,
        "rooms": r_count,
        "tier_1_rooms": len(t1_rooms),
        "tier_2_rooms": len(t2_rooms),
        "tier_3_rooms": len(t3_rooms),
        "inter_campus_distance_km": INTER_CAMPUS_DISTANCE_METERS / 1000.0,
        "checks": checks,
    }


# ==============================================================================
# 9. CLI ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    print("=" * 80)
    print("ITB Multi-Campus Spatial & Facility Topology Verification")
    print("=" * 80)

    try:
        report = verify_spatial_topology()
        print(f"Status: {report['status']}")
        print(f"Total Verification Checks Passed: {report['passed_checks']} / {report['total_checks']}")
        print(f"Campuses: {report['campuses']} | Buildings: {report['buildings']} | Rooms: {report['rooms']}")
        print(f"Tier 1 (Room X/Y): {report['tier_1_rooms']} (40.0%)")
        print(f"Tier 2 (Building X/Y): {report['tier_2_rooms']} (35.0%)")
        print(f"Tier 3 (Null coords): {report['tier_3_rooms']} (25.0%)")
        print(f"Inter-Campus Geodesic Distance: {report['inter_campus_distance_km']:.2f} km")
        print("=" * 80)
        print("All spatial topology constraints verified with 100% precision!")
        exit(0)
    except AssertionError as e:
        print(f"FAILED: {e}")
        exit(1)
