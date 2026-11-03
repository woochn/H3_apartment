#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
삼성전자 H3 화성캠퍼스 근거리 셔틀 아파트 실거래가 & 네이버 실시간 호가 수집기
-------------------------------------------------------------------------
1. 국토교통부 실거래가 공개시스템 (rt.molit.go.kr) -> 최근 실거래가, 계약일, 층수, 최근 거래이력 수집
2. 네이버 부동산 모바일 API (m.land.naver.com) -> 현재 매물 최저/최고 호가 및 매물 수 수집
3. prices.json 로컬 생성 + (선택) index.html 내장 스냅샷 자동 갱신 + (선택) GitHub Gist 자동 업로드

사용법:
  python3 update_prices.py                  # prices.json 생성 및 index.html 내장 데이터 동시 업데이트
  python3 update_prices.py --gist           # GitHub Gist까지 자동 업로드 (환경변수 GITHUB_TOKEN, GIST_ID 필요)
"""

import argparse
import base64
import datetime
import http.cookiejar
import json
import os
import re
import statistics
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# 16개 분석 대상 단지 메타데이터 매핑
# - molit_led: 국토부 법정동코드 (10자리)
# - molit_code: 국토부 단지 고유코드 (aprpnHsmpCode)
# - naver_hscp_no: 네이버 부동산 단지 번호 (hscpNo)
# - lat, lng: 단지 좌표
# - area_min, area_max: 타겟 전용면적(㎡) 필터 범위
APARTMENT_TARGETS = [
    {
        "id": "apt1",
        "name": "망포쌍용에듀파크",
        "molit_led": "4111710700",
        "molit_code": "253177",
        "naver_hscp_no": "11503",
        "lat": 37.2427,
        "lng": 127.0628,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt2",
        "name": "늘푸른벽산",
        "molit_led": "4111710700",
        "molit_code": "6146",
        "naver_hscp_no": "7965",
        "lat": 37.2410,
        "lng": 127.0575,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt3",
        "name": "망포현대아이파크2차",
        "molit_led": "4111710700",
        "molit_code": "6150",
        "naver_hscp_no": "3629",
        "lat": 37.2435,
        "lng": 127.0645,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt4",
        "name": "반달마을1단지 두산위브",
        "molit_led": "4159510500",
        "molit_code": "20073178",
        "naver_hscp_no": "22521",
        "lat": 37.2378,
        "lng": 127.0718,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt5",
        "name": "동수원자이 1차",
        "molit_led": "4111710700",
        "molit_code": "6147",
        "naver_hscp_no": "3632",
        "lat": 37.2392,
        "lng": 127.0588,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "34평 (전용 84㎡)",
    },
    {
        "id": "apt6",
        "name": "신동탄 SK뷰파크 2차",
        "molit_led": "4159510400",
        "molit_code": "20355949",
        "naver_hscp_no": "110459",
        "lat": 37.2245,
        "lng": 127.0468,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt7",
        "name": "신동탄 SK뷰파크 1차",
        "molit_led": "4159510500",
        "molit_code": "20312599",
        "naver_hscp_no": "105746",
        "lat": 37.2275,
        "lng": 127.0505,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "25평 (전용 59㎡)",
    },
    {
        "id": "apt8",
        "name": "e편한세상 반월나노시티역",
        "molit_led": "4159510500",
        "molit_code": "20348352",
        "naver_hscp_no": "109360",
        "lat": 37.2318,
        "lng": 127.0538,
        "area_min": 55.0,
        "area_max": 78.0,
        "target_pyeong": "24~30평 (전용 59·75㎡)",
    },
    {
        "id": "apt9",
        "name": "신영통 현대타운 4단지",
        "molit_led": "4159510500",
        "molit_code": "7421",
        "naver_hscp_no": "3728",
        "lat": 37.2365,
        "lng": 127.0628,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt10",
        "name": "동탄센트럴포레스트 (구 새강5단지)",
        "molit_led": "4159710200",
        "molit_code": "20123531",
        "naver_hscp_no": "127686",
        "lat": 37.1985,
        "lng": 127.0620,
        "area_min": 70.0,
        "area_max": 86.0,
        "target_pyeong": "30~33평 (전용 74·84㎡)",
    },
    {
        "id": "apt11",
        "name": "벽적골 9단지 롯데",
        "molit_led": "4111710500",
        "molit_code": "6130",
        "naver_hscp_no": "3638",
        "lat": 37.2450,
        "lng": 127.0622,
        "area_min": 55.0,
        "area_max": 62.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt12",
        "name": "벽적골 8단지 주공(두산우성한신)",
        "molit_led": "4111710500",
        "molit_code": "6110",
        "naver_hscp_no": "12045",
        "lat": 37.2468,
        "lng": 127.0630,
        "area_min": 55.0,
        "area_max": 62.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt13",
        "name": "영통 SK뷰",
        "molit_led": "4111710700",
        "molit_code": "20332556",
        "naver_hscp_no": "107825",
        "lat": 37.2428,
        "lng": 127.0595,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "25평 (전용 59㎡)",
    },
    {
        "id": "apt14",
        "name": "영통아이파크캐슬 2단지",
        "molit_led": "4111710700",
        "molit_code": "20383742",
        "naver_hscp_no": "115709",
        "lat": 37.2405,
        "lng": 127.0425,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt15",
        "name": "신동탄포레자이",
        "molit_led": "4159510500",
        "molit_code": "20442918",
        "naver_hscp_no": "131197",
        "lat": 37.2395,
        "lng": 127.0668,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt16",
        "name": "반정아이파크캐슬 4단지",
        "molit_led": "4159510600",
        "molit_code": "20441623",
        "naver_hscp_no": "137330",
        "lat": 37.2365,
        "lng": 127.0402,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    # -----------------------------------------------------------------
    # 수원권 일반 통근 셔틀 (R7 ~ R18: 아주대/인계동/광교/망포/화서/정자동 등) 연계 단지
    # -----------------------------------------------------------------
    {
        "id": "apt17",
        "name": "매탄위브하늘채",
        "molit_led": "4111710100",
        "molit_code": "",
        "molit_kw": "매탄위브하늘채",
        "naver_hscp_no": "22911",
        "lat": 37.2625,
        "lng": 127.0414,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt18",
        "name": "래미안노블클래스 1단지",
        "molit_led": "4111514100",
        "molit_code": "",
        "molit_kw": "래미안노블클래스1단지",
        "naver_hscp_no": "25771",
        "lat": 37.2694,
        "lng": 127.0365,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt19",
        "name": "인계 선경3차",
        "molit_led": "4111514100",
        "molit_code": "",
        "molit_kw": "선경",
        "naver_hscp_no": "2494",
        "lat": 37.2662,
        "lng": 127.0322,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt20",
        "name": "수원시청역 SK VIEW",
        "molit_led": "4111313700",
        "molit_code": "",
        "molit_kw": "수원시청역SKVIEW",
        "naver_hscp_no": "100374",
        "lat": 37.2582,
        "lng": 127.0315,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "34평 (전용 84㎡)",
    },
    {
        "id": "apt21",
        "name": "e편한세상 광교",
        "molit_led": "4111710300",
        "molit_code": "",
        "molit_kw": "광교e편한세상",
        "naver_hscp_no": "102091",
        "lat": 37.2918,
        "lng": 127.0547,
        "area_min": 98.0,
        "area_max": 105.0,
        "target_pyeong": "39평 (전용 100㎡)",
    },
    {
        "id": "apt22",
        "name": "광교 자연앤힐스테이트",
        "molit_led": "4111710300",
        "molit_code": "",
        "molit_kw": "자연앤힐스테이트",
        "naver_hscp_no": "101273",
        "lat": 37.2882,
        "lng": 127.0502,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt23",
        "name": "광교 푸르지오월드마크",
        "molit_led": "4111710300",
        "molit_code": "",
        "molit_kw": "광교푸르지오월드마크",
        "naver_hscp_no": "104517",
        "lat": 37.2920,
        "lng": 127.0480,
        "area_min": 80.0,
        "area_max": 108.0,
        "target_pyeong": "34~41평 (전용 84·106㎡)",
    },
    {
        "id": "apt24",
        "name": "광교 오드카운티",
        "molit_led": "4111710300",
        "molit_code": "",
        "molit_kw": "오드카운티",
        "naver_hscp_no": "100641",
        "lat": 37.2925,
        "lng": 127.0589,
        "area_min": 118.0,
        "area_max": 125.0,
        "target_pyeong": "45평 (전용 121㎡)",
    },
    {
        "id": "apt25",
        "name": "수원센트럴아이파크자이",
        "molit_led": "4111514100",
        "molit_code": "",
        "molit_kw": "수원센트럴아이파크자이",
        "naver_hscp_no": "133091",
        "lat": 37.2718,
        "lng": 127.0213,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "25평 (전용 59㎡)",
    },
    {
        "id": "apt26",
        "name": "영통아이파크캐슬 1단지",
        "molit_led": "4111710700",
        "molit_code": "",
        "molit_kw": "영통아이파크캐슬1단지",
        "naver_hscp_no": "115708",
        "lat": 37.2430,
        "lng": 127.0449,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt27",
        "name": "망포 그대가프리미어",
        "molit_led": "4111710700",
        "molit_code": "",
        "molit_kw": "그대가프리미어",
        "naver_hscp_no": "26762",
        "lat": 37.2444,
        "lng": 127.0544,
        "area_min": 55.0,
        "area_max": 103.0,
        "target_pyeong": "25~39평 (전용 59·101㎡)",
    },
    {
        "id": "apt28",
        "name": "광교 중흥S-클래스",
        "molit_led": "4111710200",
        "molit_code": "",
        "molit_kw": "광교중흥에스클래스",
        "naver_hscp_no": "111038",
        "lat": 37.2823,
        "lng": 127.0579,
        "area_min": 80.0,
        "area_max": 88.0,
        "target_pyeong": "34평 (전용 84㎡)",
    },
    {
        "id": "apt29",
        "name": "광교 호반베르디움",
        "molit_led": "4111710200",
        "molit_code": "",
        "molit_kw": "광교호반베르디움",
        "naver_hscp_no": "103682",
        "lat": 37.2730,
        "lng": 127.0568,
        "area_min": 55.0,
        "area_max": 86.0,
        "target_pyeong": "24~33평 (전용 59·84㎡)",
    },
    {
        "id": "apt30",
        "name": "광교 아이파크",
        "molit_led": "4111710200",
        "molit_code": "",
        "molit_kw": "광교아이파크",
        "naver_hscp_no": "110746",
        "lat": 37.2738,
        "lng": 127.0611,
        "area_min": 80.0,
        "area_max": 92.0,
        "target_pyeong": "34~35평 (전용 84·90㎡)",
    },
    {
        "id": "apt31",
        "name": "광교자이더클래스(구 광교상록자이)",
        "molit_led": "4146510700",
        "molit_code": "",
        "molit_kw": "광교자이더클래스",
        "naver_hscp_no": "102536",
        "lat": 37.2968,
        "lng": 127.0717,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "34평 (전용 84㎡)",
    },
    {
        "id": "apt32",
        "name": "광교 호반베르디움 트라엘",
        "molit_led": "4111710300",
        "molit_code": "",
        "molit_kw": "광교호반베르디움트라엘",
        "naver_hscp_no": "120759",
        "lat": 37.3049,
        "lng": 127.0518,
        "area_min": 80.0,
        "area_max": 102.0,
        "target_pyeong": "34~39평 (전용 84·100㎡)",
    },
    {
        "id": "apt33",
        "name": "매교역 푸르지오 SK VIEW",
        "molit_led": "4111513300",
        "molit_code": "",
        "molit_kw": "매교역푸르지오SKVIEW",
        "naver_hscp_no": "129264",
        "lat": 37.2676,
        "lng": 127.0207,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "25평 (전용 59㎡)",
    },
    {
        "id": "apt34",
        "name": "권선 자이 e편한세상",
        "molit_led": "4111313700",
        "molit_code": "",
        "molit_kw": "권선자이e편한세상",
        "naver_hscp_no": "102005",
        "lat": 37.2525,
        "lng": 127.0262,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "25평 (전용 59㎡)",
    },
    {
        "id": "apt35",
        "name": "수원 하늘채 더퍼스트 1·2단지",
        "molit_led": "4111313600",
        "molit_code": "",
        "molit_kw": "수원하늘채더퍼스트",
        "naver_hscp_no": "130135",
        "lat": 37.2412,
        "lng": 127.0338,
        "area_min": 55.0,
        "area_max": 63.0,
        "target_pyeong": "25평 (전용 59㎡)",
    },
    {
        "id": "apt36",
        "name": "서천 센트럴파크원",
        "molit_led": "4146311000",
        "molit_code": "",
        "molit_kw": "센트럴파크원",
        "naver_hscp_no": "103170",
        "lat": 37.2395,
        "lng": 127.0742,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt37",
        "name": "영통 신나무실 5단지 주공",
        "molit_led": "4111710500",
        "molit_code": "",
        "molit_kw": "신나무실휴먼시아5단지",
        "naver_hscp_no": "2588",
        "lat": 37.2522,
        "lng": 127.0633,
        "area_min": 55.0,
        "area_max": 62.0,
        "target_pyeong": "24평 (전용 59㎡)",
    },
    {
        "id": "apt38",
        "name": "화서역 파크푸르지오",
        "molit_led": "4111113000",
        "molit_code": "",
        "molit_kw": "화서역파크푸르지오",
        "naver_hscp_no": "121991",
        "lat": 37.2898,
        "lng": 126.9949,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "34평 (전용 84㎡)",
    },
    {
        "id": "apt39",
        "name": "화서역 블루밍푸른숲",
        "molit_led": "4111513800",
        "molit_code": "",
        "molit_kw": "화서역블루밍푸른숲",
        "naver_hscp_no": "24615",
        "lat": 37.2852,
        "lng": 126.9895,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "33평 (전용 84㎡)",
    },
    {
        "id": "apt40",
        "name": "수원 SK 스카이뷰",
        "molit_led": "4111113000",
        "molit_code": "",
        "molit_kw": "수원SKSKYVIEW",
        "naver_hscp_no": "102614",
        "lat": 37.2952,
        "lng": 126.9862,
        "area_min": 80.0,
        "area_max": 86.0,
        "target_pyeong": "34평 (전용 84㎡)",
    },
    {
            "id": "apt41",
            "name": "영통마젤란21(2단지)",
            "molit_led": "4111710700",
            "molit_code": "20057295",
            "molit_kw": "마젤란21(1101동)",
            "naver_hscp_no": "25483",
            "lat": 37.2417,
            "lng": 127.0625,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt42",
            "name": "센트럴하이츠",
            "molit_led": "4111710700",
            "molit_code": "20130910",
            "molit_kw": "센트럴하이츠",
            "naver_hscp_no": "26764",
            "lat": 37.2426,
            "lng": 127.0593,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt43",
            "name": "방죽마을영통뜨란채",
            "molit_led": "4111710700",
            "molit_code": "20009490",
            "molit_kw": "방죽마을영통뜨란채",
            "naver_hscp_no": "11236",
            "lat": 37.2424,
            "lng": 127.0655,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt44",
            "name": "영통라온프라이빗",
            "molit_led": "4111710500",
            "molit_code": "20357362",
            "molit_kw": "영통라온프라이빗",
            "naver_hscp_no": "109929",
            "lat": 37.2444,
            "lng": 127.0636,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt45",
            "name": "영통e-편한세상",
            "molit_led": "4111710500",
            "molit_code": "20071582",
            "molit_kw": "영통e-편한세상",
            "naver_hscp_no": "26008",
            "lat": 37.2459,
            "lng": 127.0682,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt46",
            "name": "행림마을삼성래미안1차",
            "molit_led": "4159510400",
            "molit_code": "51116",
            "molit_kw": "삼성래미안1차",
            "naver_hscp_no": "9329",
            "lat": 37.2226,
            "lng": 127.0488,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt47",
            "name": "동수원쌍용스윗닷홈2차",
            "molit_led": "4111710700",
            "molit_code": "253178",
            "molit_kw": "쌍용스윗닷홈2차",
            "naver_hscp_no": "11502",
            "lat": 37.2339,
            "lng": 127.0533,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt48",
            "name": "반월자이더파크",
            "molit_led": "4159510500",
            "molit_code": "20335890",
            "molit_kw": "반월자이더파크",
            "naver_hscp_no": "146651",
            "lat": 37.2281,
            "lng": 127.0477,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt49",
            "name": "행림마을LD삼성래미안2차",
            "molit_led": "4159510500",
            "molit_code": "52370",
            "molit_kw": "삼성래미안2차",
            "naver_hscp_no": "10384",
            "lat": 37.2233,
            "lng": 127.051,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt50",
            "name": "영통자이",
            "molit_led": "4111710700",
            "molit_code": "20439110",
            "molit_kw": "영통자이",
            "naver_hscp_no": "131810",
            "lat": 37.2343,
            "lng": 127.0549,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt51",
            "name": "신동탄푸르지오",
            "molit_led": "4159510400",
            "molit_code": "449210",
            "molit_kw": "신동탄푸르지오",
            "naver_hscp_no": "12681",
            "lat": 37.227,
            "lng": 127.0443,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt52",
            "name": "행복마을참누리에듀파크",
            "molit_led": "4159510400",
            "molit_code": "20061901",
            "molit_kw": "행복마을 참누리 에듀파크(101동-113동)",
            "naver_hscp_no": "23769",
            "lat": 37.2199,
            "lng": 127.0495,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt53",
            "name": "힐스테이트서천",
            "molit_led": "4146311000",
            "molit_code": "20140333",
            "molit_kw": "서천마을휴먼시아",
            "naver_hscp_no": "109211",
            "lat": 37.2381,
            "lng": 127.0713,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt54",
            "name": "e편한세상영통2차1단지",
            "molit_led": "4111710700",
            "molit_code": "20344903",
            "molit_kw": "e편한세상영통2차(2단지)",
            "naver_hscp_no": "109249",
            "lat": 37.2406,
            "lng": 127.0663,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt55",
            "name": "현대홈타운",
            "molit_led": "4146311000",
            "molit_code": "8492",
            "molit_kw": "현대홈타운",
            "naver_hscp_no": "9243",
            "lat": 37.2413,
            "lng": 127.0679,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt56",
            "name": "래미안영통마크원2단지",
            "molit_led": "4111710600",
            "molit_code": "20277469",
            "molit_kw": "래미안영통마크원1단지",
            "naver_hscp_no": "103518",
            "lat": 37.246,
            "lng": 127.0431,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt57",
            "name": "영통롯데캐슬엘클래스1단지",
            "molit_led": "4111710700",
            "molit_code": "20441486",
            "molit_kw": "영통롯데캐슬엘클래스2단지",
            "naver_hscp_no": "136398",
            "lat": 37.2401,
            "lng": 127.0391,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt58",
            "name": "반정아이파크캐슬5단지",
            "molit_led": "4159510600",
            "molit_code": "20441623",
            "molit_kw": "반정아이파크캐슬4단지",
            "naver_hscp_no": "137187",
            "lat": 37.2377,
            "lng": 127.041,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt59",
            "name": "영통푸르지오트레센츠",
            "molit_led": "4111710700",
            "molit_code": "20455765",
            "molit_kw": "영통푸르지오파인베르",
            "naver_hscp_no": "148799",
            "lat": 37.2355,
            "lng": 127.0479,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt60",
            "name": "망포마을벽산이빌리지",
            "molit_led": "4111710700",
            "molit_code": "6154",
            "molit_kw": "망포벽산이빌리지",
            "naver_hscp_no": "8491",
            "lat": 37.237,
            "lng": 127.0471,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt61",
            "name": "동탄시범다은마을월드메르디앙반도유보라",
            "molit_led": "4159710200",
            "molit_code": "20090525",
            "molit_kw": "동탄시범다은마을센트럴파크뷰",
            "naver_hscp_no": "22065",
            "lat": 37.2002,
            "lng": 127.0632,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt62",
            "name": "서동탄역더샵파크시티",
            "molit_led": "4137011100",
            "molit_code": "20393913",
            "molit_kw": "서동탄역더샵파크시티",
            "naver_hscp_no": "115677",
            "lat": 37.1921,
            "lng": 127.0637,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt63",
            "name": "동탄시범다은마을우남퍼스트빌",
            "molit_led": "4159710200",
            "molit_code": "20069760",
            "molit_kw": "시범다은마을우남퍼스트빌",
            "naver_hscp_no": "19208",
            "lat": 37.2001,
            "lng": 127.0664,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt64",
            "name": "동탄솔빛마을쌍용예가",
            "molit_led": "4159710200",
            "molit_code": "20073182",
            "molit_kw": "솔빛마을쌍용예가",
            "naver_hscp_no": "19672",
            "lat": 37.1947,
            "lng": 127.0723,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt65",
            "name": "동탄푸른마을모아미래도",
            "molit_led": "4159710100",
            "molit_code": "20095158",
            "molit_kw": "푸른마을모아미래도",
            "naver_hscp_no": "26219",
            "lat": 37.2004,
            "lng": 127.0576,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt66",
            "name": "동탄나루마을한화꿈에그린우림필유",
            "molit_led": "4159710200",
            "molit_code": "20073185",
            "molit_kw": "나루마을한화꿈에그린",
            "naver_hscp_no": "19675",
            "lat": 37.1913,
            "lng": 127.0724,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt67",
            "name": "삼성",
            "molit_led": "4111514100",
            "molit_code": "6005",
            "molit_kw": "삼성",
            "naver_hscp_no": "1832",
            "lat": 37.2723,
            "lng": 127.0367,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt68",
            "name": "우성",
            "molit_led": "4111710100",
            "molit_code": "6035",
            "molit_kw": "우성",
            "naver_hscp_no": "2584",
            "lat": 37.2732,
            "lng": 127.038,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt69",
            "name": "한화꿈에그린파크(주상복합)",
            "molit_led": "4111514100",
            "molit_code": "20126611",
            "molit_kw": "한화꿈에그린파크",
            "naver_hscp_no": "27677",
            "lat": 37.2602,
            "lng": 127.0345,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt70",
            "name": "신안풍림",
            "molit_led": "4111313700",
            "molit_code": "6080",
            "molit_kw": "신안풍림",
            "naver_hscp_no": "1763",
            "lat": 37.254,
            "lng": 127.0337,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt71",
            "name": "현대힐스테이트",
            "molit_led": "4111710100",
            "molit_code": "20022714",
            "molit_kw": "현대힐스테이트",
            "naver_hscp_no": "13698",
            "lat": 37.271,
            "lng": 127.0396,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt72",
            "name": "선경1차",
            "molit_led": "4111514100",
            "molit_code": "6007",
            "molit_kw": "선경1",
            "naver_hscp_no": "1833",
            "lat": 37.2762,
            "lng": 127.0365,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt73",
            "name": "수원인계동문굿모닝힐",
            "molit_led": "4111514100",
            "molit_code": "20414668",
            "molit_kw": "수원인계동동문굿모닝힐아파트",
            "naver_hscp_no": "120222",
            "lat": 37.2757,
            "lng": 127.039,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt74",
            "name": "수정",
            "molit_led": "4111514100",
            "molit_code": "6011",
            "molit_kw": "수정",
            "naver_hscp_no": "1834",
            "lat": 37.2733,
            "lng": 127.0307,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt75",
            "name": "한일베라체에코플러스",
            "molit_led": "4111514000",
            "molit_code": "20437507",
            "molit_kw": "한일베라체에코플러스",
            "naver_hscp_no": "127743",
            "lat": 37.2769,
            "lng": 127.0386,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt76",
            "name": "선경",
            "molit_led": "4111514000",
            "molit_code": "5995",
            "molit_kw": "선경",
            "naver_hscp_no": "1816",
            "lat": 37.2765,
            "lng": 127.04,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt77",
            "name": "광교에듀포레",
            "molit_led": "4111710300",
            "molit_code": "20294735",
            "molit_kw": "광교에듀포레",
            "naver_hscp_no": "140889",
            "lat": 37.2837,
            "lng": 127.0532,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt78",
            "name": "광교e편한세상2차",
            "molit_led": "4111710300",
            "molit_code": "20167295",
            "molit_kw": "광교e편한세상",
            "naver_hscp_no": "102119",
            "lat": 37.2917,
            "lng": 127.0542,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt79",
            "name": "광교센트럴뷰",
            "molit_led": "4111710300",
            "molit_code": "20277274",
            "molit_kw": "광교센트럴뷰",
            "naver_hscp_no": "138183",
            "lat": 37.2891,
            "lng": 127.059,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt80",
            "name": "래미안광교",
            "molit_led": "4111710300",
            "molit_code": "20150776",
            "molit_kw": "래미안광교",
            "naver_hscp_no": "100607",
            "lat": 37.2912,
            "lng": 127.0614,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt81",
            "name": "광교더포레스트",
            "molit_led": "4111710400",
            "molit_code": "20277325",
            "molit_kw": "광교더리브",
            "naver_hscp_no": "137233",
            "lat": 37.2893,
            "lng": 127.0634,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt82",
            "name": "힐스테이트광교중앙역퍼스트(주상복합)",
            "molit_led": "4111710300",
            "molit_code": "20452829",
            "molit_kw": "힐스테이트광교중앙역퍼스트",
            "naver_hscp_no": "143963",
            "lat": 37.2892,
            "lng": 127.0517,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt83",
            "name": "힐스테이트광교(주상복합)",
            "molit_led": "4111710400",
            "molit_code": "20367641",
            "molit_kw": "힐스테이트광교",
            "naver_hscp_no": "109525",
            "lat": 37.2855,
            "lng": 127.0641,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt84",
            "name": "한효",
            "molit_led": "4111313700",
            "molit_code": "6088",
            "molit_kw": "한효",
            "naver_hscp_no": "1772",
            "lat": 37.2545,
            "lng": 127.0248,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt85",
            "name": "망포역아이파크",
            "molit_led": "4111710700",
            "molit_code": "6153",
            "molit_kw": "망포역아이파크",
            "naver_hscp_no": "3628",
            "lat": 37.244,
            "lng": 127.057,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt86",
            "name": "인계한양수자인(주상복합)",
            "molit_led": "4111514100",
            "molit_code": "20386458",
            "molit_kw": "인계한양수자인",
            "naver_hscp_no": "115681",
            "lat": 37.276,
            "lng": 127.0255,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt87",
            "name": "신영통현대1단지",
            "molit_led": "4159510500",
            "molit_code": "7421",
            "molit_kw": "신영통현대4차",
            "naver_hscp_no": "3725",
            "lat": 37.2334,
            "lng": 127.0618,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt88",
            "name": "한양수자인에듀파크",
            "molit_led": "4111710700",
            "molit_code": "20278271",
            "molit_kw": "한양수자인",
            "naver_hscp_no": "105153",
            "lat": 37.2405,
            "lng": 127.0573,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt89",
            "name": "삼정라츠",
            "molit_led": "4111710700",
            "molit_code": "20100801",
            "molit_kw": "삼정라츠",
            "naver_hscp_no": "26625",
            "lat": 37.2385,
            "lng": 127.0612,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt90",
            "name": "힐스테이트영통",
            "molit_led": "4111710700",
            "molit_code": "20356741",
            "molit_kw": "힐스테이트영통",
            "naver_hscp_no": "109412",
            "lat": 37.2432,
            "lng": 127.049,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt91",
            "name": "수원성중흥S-클래스",
            "molit_led": "4111513900",
            "molit_code": "20459022",
            "molit_kw": "수원성중흥S-클래스",
            "naver_hscp_no": "155738",
            "lat": 37.2769,
            "lng": 127.0219,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt92",
            "name": "신명",
            "molit_led": "4111313700",
            "molit_code": "6079",
            "molit_kw": "신명",
            "naver_hscp_no": "1760",
            "lat": 37.254,
            "lng": 127.0216,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt93",
            "name": "삼천리권선2차",
            "molit_led": "4111313700",
            "molit_code": "6072",
            "molit_kw": "삼천리1차",
            "naver_hscp_no": "1759",
            "lat": 37.2519,
            "lng": 127.0241,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt94",
            "name": "성지",
            "molit_led": "4111313700",
            "molit_code": "6077",
            "molit_kw": "성지",
            "naver_hscp_no": "1761",
            "lat": 37.2523,
            "lng": 127.0223,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt95",
            "name": "인계극동스타클래스",
            "molit_led": "4111514100",
            "molit_code": "20119481",
            "molit_kw": "인계극동스타클래스아파트",
            "naver_hscp_no": "27120",
            "lat": 37.2733,
            "lng": 127.0299,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt96",
            "name": "권선한양",
            "molit_led": "4111313700",
            "molit_code": "6087",
            "molit_kw": "한양",
            "naver_hscp_no": "1771",
            "lat": 37.2525,
            "lng": 127.021,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt97",
            "name": "광교더샵(주상복합)",
            "molit_led": "4111710200",
            "molit_code": "20374305",
            "molit_kw": "광교더샵",
            "naver_hscp_no": "110726",
            "lat": 37.2715,
            "lng": 127.062,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt98",
            "name": "성일(1199)",
            "molit_led": "4111710100",
            "molit_code": "6036",
            "molit_kw": "원천성일",
            "naver_hscp_no": "1795",
            "lat": 37.271,
            "lng": 127.0562,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt99",
            "name": "원천레이크파크",
            "molit_led": "4111710200",
            "molit_code": "6050",
            "molit_kw": "원천레이크파크",
            "naver_hscp_no": "9075",
            "lat": 37.2682,
            "lng": 127.0613,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt100",
            "name": "매탄e-편한세상",
            "molit_led": "4111710100",
            "molit_code": "20128552",
            "molit_kw": "e-편한세상",
            "naver_hscp_no": "100273",
            "lat": 37.2697,
            "lng": 127.0535,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt101",
            "name": "한국1차",
            "molit_led": "4111710100",
            "molit_code": "6042",
            "molit_kw": "한국1",
            "naver_hscp_no": "1793",
            "lat": 37.2691,
            "lng": 127.0564,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt102",
            "name": "광교한양수자인",
            "molit_led": "4111710300",
            "molit_code": "20141517",
            "molit_kw": "광교한양수자인",
            "naver_hscp_no": "103072",
            "lat": 37.3045,
            "lng": 127.0489,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt103",
            "name": "광교호반베르디움(1184)",
            "molit_led": "4111710300",
            "molit_code": "20350121",
            "molit_kw": "광교호반베르디움트라엘",
            "naver_hscp_no": "102624",
            "lat": 37.3036,
            "lng": 127.0499,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt104",
            "name": "광교경남아너스빌",
            "molit_led": "4146510700",
            "molit_code": "20146660",
            "molit_kw": "광교경남아너스빌",
            "naver_hscp_no": "101239",
            "lat": 37.2976,
            "lng": 127.0671,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt105",
            "name": "광교해모로",
            "molit_led": "4111710300",
            "molit_code": "20144105",
            "molit_kw": "광교 해모로 아파트",
            "naver_hscp_no": "103034",
            "lat": 37.3071,
            "lng": 127.0533,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt106",
            "name": "광교더힐",
            "molit_led": "4146510700",
            "molit_code": "20285691",
            "molit_kw": "광교더힐",
            "naver_hscp_no": "137232",
            "lat": 37.2978,
            "lng": 127.0644,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt107",
            "name": "광교역참누리포레스트",
            "molit_led": "4111710300",
            "molit_code": "20323287",
            "molit_kw": "광교역참누리포레스트",
            "naver_hscp_no": "107650",
            "lat": 37.3023,
            "lng": 127.0393,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt108",
            "name": "광교호수마을호반써밋",
            "molit_led": "4111710400",
            "molit_code": "20143603",
            "molit_kw": "광교호수마을호반써밋",
            "naver_hscp_no": "101301",
            "lat": 37.2908,
            "lng": 127.0729,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt109",
            "name": "인계파밀리에",
            "molit_led": "4111514100",
            "molit_code": "20118648",
            "molit_kw": "인계파밀리에",
            "naver_hscp_no": "26276",
            "lat": 37.2705,
            "lng": 127.0227,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt110",
            "name": "현대(1240)",
            "molit_led": "4111313700",
            "molit_code": "6090",
            "molit_kw": "현대3",
            "naver_hscp_no": "11986",
            "lat": 37.2494,
            "lng": 127.0374,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt111",
            "name": "권선3주공1단지",
            "molit_led": "4111313700",
            "molit_code": "12143289",
            "molit_kw": "권선3지구주공1단지",
            "naver_hscp_no": "3625",
            "lat": 37.2484,
            "lng": 127.0341,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt112",
            "name": "대림",
            "molit_led": "4111313700",
            "molit_code": "6063",
            "molit_kw": "대림",
            "naver_hscp_no": "9284",
            "lat": 37.2477,
            "lng": 127.038,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt113",
            "name": "우남2차",
            "molit_led": "4111313700",
            "molit_code": "50180",
            "molit_kw": "우남2",
            "naver_hscp_no": "9676",
            "lat": 37.2478,
            "lng": 127.0366,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt114",
            "name": "권선대우",
            "molit_led": "4111313700",
            "molit_code": "6056",
            "molit_kw": "권선대우",
            "naver_hscp_no": "8843",
            "lat": 37.2491,
            "lng": 127.0387,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt115",
            "name": "벽산",
            "molit_led": "4111313700",
            "molit_code": "6074",
            "molit_kw": "삼호벽산",
            "naver_hscp_no": "1754",
            "lat": 37.2507,
            "lng": 127.033,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt116",
            "name": "권선3지구상록5단지",
            "molit_led": "4111313700",
            "molit_code": "6075",
            "molit_kw": "상록5단지",
            "naver_hscp_no": "3624",
            "lat": 37.2499,
            "lng": 127.0364,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt117",
            "name": "우남1차",
            "molit_led": "4111313700",
            "molit_code": "6083",
            "molit_kw": "우남1",
            "naver_hscp_no": "9675",
            "lat": 37.2473,
            "lng": 127.0336,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt118",
            "name": "권선상록3단지",
            "molit_led": "4111313700",
            "molit_code": "6076",
            "molit_kw": "상록3단지",
            "naver_hscp_no": "3623",
            "lat": 37.2508,
            "lng": 127.0384,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt119",
            "name": "매탄권선역리버파크",
            "molit_led": "4111313700",
            "molit_code": "6055",
            "molit_kw": "매탄권선역리버파크",
            "naver_hscp_no": "10594",
            "lat": 37.2502,
            "lng": 127.0396,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt120",
            "name": "벽산한성",
            "molit_led": "4111313700",
            "molit_code": "6069",
            "molit_kw": "벽산",
            "naver_hscp_no": "1755",
            "lat": 37.2499,
            "lng": 127.0303,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt121",
            "name": "수원아이파크시티7단지",
            "molit_led": "4111313700",
            "molit_code": "20354781",
            "molit_kw": "수원아이파크시티8단지",
            "naver_hscp_no": "109075",
            "lat": 37.2467,
            "lng": 127.0303,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt122",
            "name": "보성,유원",
            "molit_led": "4111313700",
            "molit_code": "6070",
            "molit_kw": "보성,유원",
            "naver_hscp_no": "1766",
            "lat": 37.2491,
            "lng": 127.0281,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt123",
            "name": "신우",
            "molit_led": "4111313700",
            "molit_code": "6081",
            "molit_kw": "신우",
            "naver_hscp_no": "1764",
            "lat": 37.2513,
            "lng": 127.0285,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt124",
            "name": "권선신일유토빌",
            "molit_led": "4111313600",
            "molit_code": "20174671",
            "molit_kw": "권선신일유토빌",
            "naver_hscp_no": "103565",
            "lat": 37.2402,
            "lng": 127.0299,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt125",
            "name": "곡반정현대아이파크",
            "molit_led": "4111313600",
            "molit_code": "6093",
            "molit_kw": "수원곡반정현대아이파크",
            "naver_hscp_no": "3622",
            "lat": 37.237,
            "lng": 127.0278,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt126",
            "name": "용인서천효성해링턴플레이스",
            "molit_led": "4146311000",
            "molit_code": "20358747",
            "molit_kw": "용인서천효성해링턴플레이스",
            "naver_hscp_no": "110641",
            "lat": 37.2445,
            "lng": 127.0749,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt127",
            "name": "서그내마을SK",
            "molit_led": "4146311000",
            "molit_code": "8491",
            "molit_kw": "SK",
            "naver_hscp_no": "3688",
            "lat": 37.2443,
            "lng": 127.0719,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt128",
            "name": "청명마을주공",
            "molit_led": "4111710500",
            "molit_code": "253176",
            "molit_kw": "청명마을삼성",
            "naver_hscp_no": "1809",
            "lat": 37.255,
            "lng": 127.0791,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt129",
            "name": "살구골진덕,서광,성지,동아",
            "molit_led": "4111710500",
            "molit_code": "6114",
            "molit_kw": "살구골마을진덕서광성지동아",
            "naver_hscp_no": "1800",
            "lat": 37.2482,
            "lng": 127.0705,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt130",
            "name": "영통로효성해링턴플레이스",
            "molit_led": "4146311000",
            "molit_code": "20354837",
            "molit_kw": "영통로효성해링턴플레이스1차",
            "naver_hscp_no": "109883",
            "lat": 37.2457,
            "lng": 127.0703,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt131",
            "name": "현대",
            "molit_led": "4111710500",
            "molit_code": "6136",
            "molit_kw": "현대",
            "naver_hscp_no": "1802",
            "lat": 37.2499,
            "lng": 127.0716,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt132",
            "name": "건영1차",
            "molit_led": "4111710500",
            "molit_code": "6107",
            "molit_kw": "건영1차",
            "naver_hscp_no": "2490",
            "lat": 37.2562,
            "lng": 127.078,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt133",
            "name": "대우",
            "molit_led": "4111710500",
            "molit_code": "20096150",
            "molit_kw": "대우월드마크",
            "naver_hscp_no": "12056",
            "lat": 37.255,
            "lng": 127.0756,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt134",
            "name": "벽적골9단지주공",
            "molit_led": "4111710500",
            "molit_code": "6130",
            "molit_kw": "벽적골롯데",
            "naver_hscp_no": "3991",
            "lat": 37.2474,
            "lng": 127.0625,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt135",
            "name": "삼성,태영",
            "molit_led": "4111710500",
            "molit_code": "50688",
            "molit_kw": "태영",
            "naver_hscp_no": "1803",
            "lat": 37.2493,
            "lng": 127.0638,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt136",
            "name": "화서주공3단지",
            "molit_led": "4111513800",
            "molit_code": "5877",
            "molit_kw": "화서주공3단지",
            "naver_hscp_no": "2727",
            "lat": 37.2859,
            "lng": 126.9923,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt137",
            "name": "꽃뫼노을마을대동",
            "molit_led": "4111113000",
            "molit_code": "5925",
            "molit_kw": "노을마을대동",
            "naver_hscp_no": "7973",
            "lat": 37.2923,
            "lng": 126.9941,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt138",
            "name": "화서주공4단지",
            "molit_led": "4111513800",
            "molit_code": "5878",
            "molit_kw": "화서주공4단지",
            "naver_hscp_no": "2728",
            "lat": 37.2843,
            "lng": 126.9926,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt139",
            "name": "화서주공5단지",
            "molit_led": "4111513800",
            "molit_code": "5882",
            "molit_kw": "화서주공5단지",
            "naver_hscp_no": "10398",
            "lat": 37.2843,
            "lng": 126.9926,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt140",
            "name": "수원화서역동문굿모닝힐",
            "molit_led": "4111513800",
            "molit_code": "20130267",
            "molit_kw": "수원화서역동문굿모닝힐",
            "naver_hscp_no": "26431",
            "lat": 37.2847,
            "lng": 126.9948,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt141",
            "name": "꽃뫼양지마을대우",
            "molit_led": "4111513800",
            "molit_code": "5879",
            "molit_kw": "꽃뫼양지마을현대",
            "naver_hscp_no": "3640",
            "lat": 37.2873,
            "lng": 126.9853,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt142",
            "name": "신미주",
            "molit_led": "4111113000",
            "molit_code": "5950",
            "molit_kw": "신미주",
            "naver_hscp_no": "2707",
            "lat": 37.2952,
            "lng": 126.9981,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt143",
            "name": "정자KTe-편한세상",
            "molit_led": "4111113000",
            "molit_code": "20090768",
            "molit_kw": "정자KTe-편한세상",
            "naver_hscp_no": "25066",
            "lat": 37.2961,
            "lng": 126.9978,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt144",
            "name": "현대",
            "molit_led": "4111113000",
            "molit_code": "5944",
            "molit_kw": "백설마을현대코오롱아파트",
            "naver_hscp_no": "8209",
            "lat": 37.2963,
            "lng": 126.9879,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt145",
            "name": "백설에듀빌",
            "molit_led": "4111113000",
            "molit_code": "5941",
            "molit_kw": "백설 에듀빌",
            "naver_hscp_no": "3641",
            "lat": 37.2962,
            "lng": 126.9906,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt146",
            "name": "화서역현대벽산",
            "molit_led": "4111113000",
            "molit_code": "5957",
            "molit_kw": "현대",
            "naver_hscp_no": "7967",
            "lat": 37.2941,
            "lng": 126.9987,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt147",
            "name": "청솔마을한라",
            "molit_led": "4111113000",
            "molit_code": "5955",
            "molit_kw": "청솔마을한라",
            "naver_hscp_no": "3650",
            "lat": 37.294,
            "lng": 126.9839,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt148",
            "name": "연꽃마을벽산",
            "molit_led": "4111113000",
            "molit_code": "5952",
            "molit_kw": "연꽃마을벽산",
            "naver_hscp_no": "7976",
            "lat": 37.2986,
            "lng": 126.9958,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt149",
            "name": "수원정자금강에스쁘아",
            "molit_led": "4111113000",
            "molit_code": "449034",
            "molit_kw": "수원정자금강에스쁘아",
            "naver_hscp_no": "17451",
            "lat": 37.2927,
            "lng": 127.0052,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt150",
            "name": "연꽃마을풍림",
            "molit_led": "4111113000",
            "molit_code": "5953",
            "molit_kw": "연꽃마을풍림",
            "naver_hscp_no": "2710",
            "lat": 37.2981,
            "lng": 126.9933,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt151",
            "name": "비단마을영풍마드레빌",
            "molit_led": "4111113300",
            "molit_code": "5914",
            "molit_kw": "비단마을영풍",
            "naver_hscp_no": "3648",
            "lat": 37.2985,
            "lng": 126.9835,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt152",
            "name": "꽃뫼노을마을한마루",
            "molit_led": "4111113000",
            "molit_code": "253098",
            "molit_kw": "꽃뫼노을마을한마루아파트",
            "naver_hscp_no": "13369",
            "lat": 37.2913,
            "lng": 126.9891,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt153",
            "name": "화서위브하늘채",
            "molit_led": "4111513800",
            "molit_code": "20108213",
            "molit_kw": "화서위브하늘채",
            "naver_hscp_no": "24672",
            "lat": 37.2885,
            "lng": 127.0006,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt154",
            "name": "비단마을베스트타운",
            "molit_led": "4111113300",
            "molit_code": "5910",
            "molit_kw": "비단마을베스트타운",
            "naver_hscp_no": "3646",
            "lat": 37.2981,
            "lng": 126.9809,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt155",
            "name": "북수원자이렉스비아",
            "molit_led": "4111113000",
            "molit_code": "5958",
            "molit_kw": "북수원리버파크",
            "naver_hscp_no": "141607",
            "lat": 37.3002,
            "lng": 126.986,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt156",
            "name": "동신2차",
            "molit_led": "4111113000",
            "molit_code": "5930",
            "molit_kw": "동신2단지",
            "naver_hscp_no": "17267",
            "lat": 37.3005,
            "lng": 126.9934,
            "area_min": 45.0,
            "area_max": 72.0,
            "target_pyeong": "24~25평 (전용 59㎡ 전후)"
    },
    {
            "id": "apt157",
            "name": "동신3차",
            "molit_led": "4111113000",
            "molit_code": "5931",
            "molit_kw": "동신3단지",
            "naver_hscp_no": "17269",
            "lat": 37.3011,
            "lng": 126.9957,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
    {
            "id": "apt158",
            "name": "백설마을5단지효성",
            "molit_led": "4111113000",
            "molit_code": "253086",
            "molit_kw": "효성",
            "naver_hscp_no": "2711",
            "lat": 37.2953,
            "lng": 127.0066,
            "area_min": 70.0,
            "area_max": 115.0,
            "target_pyeong": "33~34평 (전용 84㎡ 전후)"
    },
]


def parse_korean_price_to_eok(raw: Optional[str]) -> Optional[float]:
    """'6<em class=...>억</em> 8,500' 또는 '53,500' 형태를 억 단위 float(예: 6.85, 5.35)로 변환"""
    if not raw:
        return None
    clean = re.sub(r"<[^>]+>", "", str(raw)).strip()
    if not clean or clean == "0":
        return None

    if "억" in clean:
        parts = clean.split("억")
        eok = int(parts[0].replace(",", "").strip() or "0")
        man_str = parts[1].replace(",", "").strip() if len(parts) > 1 else ""
        man = int(man_str) if man_str.isdigit() else 0
        return round(eok + man / 10000.0, 2)
    else:
        num_str = clean.replace(",", "").strip()
        if num_str.isdigit():
            return round(int(num_str) / 10000.0, 2)
    return None


def format_eok(val: Optional[float]) -> str:
    if val is None:
        return "-"
    return f"{val:.2f}".rstrip("0").rstrip(".") + "억"


def create_molit_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        ("Referer", "https://rt.molit.go.kr/pt/gis/gis.do"),
        ("X-Requested-With", "XMLHttpRequest"),
    ]
    try:
        opener.open("https://rt.molit.go.kr/pt/gis/gis.do", timeout=10).read()
    except Exception as e:
        print(f"[경고] 국토부 세션 초기화 실패: {e}")
    return opener


def fetch_molit_transactions(opener, target: Dict[str, Any], year: str = "2026") -> Dict[str, Any]:
    """국토교통부 실거래가 공개시스템(rt.molit.go.kr)에서 단지별 실거래 내역 조회"""
    dtl_data = urllib.parse.urlencode({
        "srhThingSecd": "A",
        "srhDelngSecd": "1",
        "dtlLi": target["molit_led"],
        "dtlYear": year,
        "dtlMon": "",
        "dtlArea": "",
        "dtlAmount": "",
        "dtlLfstsMtht": "",
        "srhAprpnHsmpCode": target["molit_code"],
        "dtlGbn1": "1",
        "dtlGbn2": "1",
    }).encode("utf-8")

    resp = opener.open("https://rt.molit.go.kr/pt/gis/ptDtl.do", data=dtl_data, timeout=10)
    res = json.loads(resp.read().decode("utf-8"))
    raw_list = res.get("danjiList", [])

    # 취소(해제)되지 않은 정상 거래만 필터링
    valid_rows = [r for r in raw_list if r.get("relisDe", "-") == "-"]

    # 타겟 전용면적 필터링
    amin, amax = target["area_min"], target["area_max"]
    area_rows = [
        r for r in valid_rows
        if amin <= float(r.get("prvuseAr", 0.0)) <= amax
    ]

    # 만약 타겟 면적 거래가 올해 없으면 전체 면적 거래 사용
    use_rows = area_rows if area_rows else valid_rows

    history = []
    prices_eok = []
    for r in use_rows:
        p_eok = parse_korean_price_to_eok(r.get("thingAmount"))
        if p_eok is None:
            continue
        c_date = str(r.get("cntrctDe", ""))
        formatted_date = (
            f"{c_date[:4]}.{c_date[4:6]}.{c_date[6:8]}"
            if len(c_date) == 8 else c_date
        )
        item = {
            "date": formatted_date,
            "priceEok": p_eok,
            "priceText": format_eok(p_eok),
            "rawAmount": r.get("thingAmount"),
            "areaM2": round(float(r.get("prvuseAr", 0.0)), 1),
            "floor": str(r.get("floorCo", "-")),
            "dealType": r.get("brkrAt", "중개거래"),
        }
        history.append(item)
        prices_eok.append(p_eok)

    latest = history[0] if history else None
    recent_5 = history[:5]
    recent_prices = [h["priceEok"] for h in recent_5]

    return {
        "totalDealsYear": len(use_rows),
        "latestDeal": latest,
        "recentAvgEok": round(statistics.mean(recent_prices), 2) if recent_prices else None,
        "recentMinEok": min(recent_prices) if recent_prices else None,
        "recentMaxEok": max(recent_prices) if recent_prices else None,
        "recentDeals": recent_5,
    }


def fetch_molit_openapi_fallback(target: Dict[str, Any], service_key: str, deal_ymds: Optional[List[str]] = None) -> Dict[str, Any]:
    """github_config.json에 저장된 공공데이터포털 OpenAPI(RTMSDataSvcAptTradeDev) 인증키를 사용한 조회"""
    if deal_ymds is None:
        deal_ymds = ["202610", "202609", "202608"]
    lawd_cd = target["molit_led"][:5]
    amin, amax = target["area_min"], target["area_max"]
    kw = (target.get("molit_kw") or target["name"].split()[0][:4]).replace(" ", "").upper()
    history = []

    for deal_ymd in deal_ymds:
        url = (
            f"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?"
            f"serviceKey={service_key}&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&pageNo=1&numOfRows=1000"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        xml_data = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
        root = ET.fromstring(xml_data)

        for item in root.findall(".//item"):
            apt_nm = (item.findtext("aptNm") or "").strip().replace(" ", "").upper()
            cdeal = (item.findtext("cdealType") or "").strip()
            if cdeal == "O" or kw not in apt_nm:
                continue
            area = float(item.findtext("excluUseAr") or "0")
            if not (amin <= area <= amax):
                continue
            raw_amt = (item.findtext("dealAmount") or "").strip()
            p_eok = parse_korean_price_to_eok(raw_amt)
            if p_eok is None:
                continue
            y = (item.findtext("dealYear") or "").strip()
            m = (item.findtext("dealMonth") or "").strip().zfill(2)
            d = (item.findtext("dealDay") or "").strip().zfill(2)
            history.append({
                "date": f"{y}.{m}.{d}",
                "priceEok": p_eok,
                "priceText": format_eok(p_eok),
                "rawAmount": raw_amt,
                "areaM2": round(area, 1),
                "floor": (item.findtext("floor") or "-").strip(),
                "dealType": (item.findtext("dealingGbn") or "중개거래").strip(),
            })

    history.sort(key=lambda x: x["date"], reverse=True)
    recent_5 = history[:5]
    recent_prices = [h["priceEok"] for h in recent_5]
    return {
        "totalDealsYear": len(history),
        "latestDeal": history[0] if history else None,
        "recentAvgEok": round(statistics.mean(recent_prices), 2) if recent_prices else None,
        "recentMinEok": min(recent_prices) if recent_prices else None,
        "recentMaxEok": max(recent_prices) if recent_prices else None,
        "recentDeals": recent_5,
    }


def fetch_naver_asking_prices(targets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """네이버 부동산 모바일 클러스터 API를 통해 법정동별 단지 실시간 호가 및 매물 수 조회"""
    by_cortar: Dict[str, List[Dict[str, Any]]] = {}
    for t in targets:
        by_cortar.setdefault(t["molit_led"], []).append(t)

    naver_map: Dict[str, Dict[str, Any]] = {}
    for cortar, t_list in by_cortar.items():
        lat = t_list[0]["lat"]
        lon = t_list[0]["lng"]
        for page in range(1, 4):
            url = (
                f"https://m.land.naver.com/cluster/ajax/complexList?"
                f"rletTpCd=APT&tradTpCd=A1:B1&z=14&lat={lat}&lon={lon}"
                f"&btm={lat-0.03}&lft={lon-0.03}&top={lat+0.03}&rgt={lon+0.03}"
                f"&cortarNo={cortar}&page={page}"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
                    "Referer": "https://m.land.naver.com/",
                },
            )
            try:
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("result", []):
                    hscp_no = str(item.get("hscpNo", ""))
                    ask_min = parse_korean_price_to_eok(item.get("dealPrcMin"))
                    ask_max = parse_korean_price_to_eok(item.get("dealPrcMax"))
                    lease_min = parse_korean_price_to_eok(item.get("leasePrcMin"))
                    naver_map[hscp_no] = {
                        "hscpNo": hscp_no,
                        "hscpNm": item.get("hscpNm"),
                        "dealCnt": item.get("dealCnt", 0),
                        "leaseCnt": item.get("leaseCnt", 0),
                        "askingMinEok": ask_min,
                        "askingMaxEok": ask_max,
                        "askingMinText": format_eok(ask_min) if ask_min else None,
                        "askingMaxText": format_eok(ask_max) if ask_max else None,
                        "leaseMinEok": lease_min,
                        "leaseMinText": format_eok(lease_min) if lease_min else None,
                    }
                if not data.get("more"):
                    break
            except Exception as e:
                print(f"[경고] 네이버 호가 조회 실패 ({cortar} p.{page}): {e}")
                break

    return naver_map


def build_prices_payload(config_path: str = "github_config.json") -> Dict[str, Any]:
    print("1/2 국토교통부 실거래가 공개시스템(rt.molit.go.kr & OpenAPI) 조회 중...")
    cfg = load_github_config(config_path)
    openapi_key = cfg.get("molit_openapi", {}).get("service_key", "")
    opener = create_molit_opener()
    molit_results = {}
    for t in APARTMENT_TARGETS:
        try:
            res = fetch_molit_transactions(opener, t, year="2026") if t.get("molit_code") else {}
            if not res.get("latestDeal") and openapi_key:
                res = fetch_molit_openapi_fallback(t, openapi_key)
            molit_results[t["id"]] = res
        except Exception as e:
            print(f"  [경고] {t['name']} 웹 조회 실패({e}), OpenAPI 폴백 시도...")
            if openapi_key:
                try:
                    molit_results[t["id"]] = fetch_molit_openapi_fallback(t, openapi_key)
                except Exception as e2:
                    print(f"  [오류] {t['name']} OpenAPI 조회 실패: {e2}")
                    molit_results[t["id"]] = {}
            else:
                molit_results[t["id"]] = {}

    print("2/2 네이버 부동산 모바일 API(m.land.naver.com) 실시간 호가 조회 중...")
    naver_by_hscp = fetch_naver_asking_prices(APARTMENT_TARGETS)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    items: Dict[str, Any] = {}

    for t in APARTMENT_TARGETS:
        aid = t["id"]
        m_data = molit_results.get(aid, {})
        n_data = naver_by_hscp.get(t["naver_hscp_no"], {})

        latest = m_data.get("latestDeal")
        latest_eok = latest["priceEok"] if latest else None
        recent_avg = m_data.get("recentAvgEok")
        recent_min = m_data.get("recentMinEok")
        recent_max = m_data.get("recentMaxEok")

        ask_min = n_data.get("askingMinEok")
        ask_max = n_data.get("askingMaxEok")

        # 대표 기준 가격(priceNum): 최근 5건 평균 실거래가 우선 -> 없으면 직전 실거래가 -> 없으면 최저호가
        rep_price = recent_avg or latest_eok or ask_min or 0.0

        # 실거래 요약 텍스트
        if latest:
            real_price_text = f"{latest['priceText']} ({latest['date'][2:]} · {latest['floor']}층)"
            if recent_min and recent_max and recent_min != recent_max:
                real_range_text = f"{format_eok(recent_min)} ~ {format_eok(recent_max)}"
            else:
                real_range_text = latest["priceText"]
        else:
            real_price_text = "최근 거래 없음"
            real_range_text = "-"

        # 호가 요약 텍스트
        if ask_min:
            asking_text = f"최저 {format_eok(ask_min)}" + (
                f" ~ {format_eok(ask_max)}" if ask_max and ask_max != ask_min else ""
            )
        else:
            asking_text = "매물 없음"

        items[aid] = {
            "id": aid,
            "name": t["name"],
            "naverHscpNo": t["naver_hscp_no"],
            "targetPyeong": t["target_pyeong"],
            "priceNum": rep_price,
            "realPriceLatestEok": latest_eok,
            "realPriceLatestText": real_price_text,
            "realPriceAvgEok": recent_avg,
            "realPriceRangeText": real_range_text,
            "totalDealsYear": m_data.get("totalDealsYear", 0),
            "recentDeals": m_data.get("recentDeals", []),
            "askingMinEok": ask_min,
            "askingMaxEok": ask_max,
            "askingPriceText": asking_text,
            "dealArticleCount": n_data.get("dealCnt", 0),
            "leaseMinText": n_data.get("leaseMinText", "-"),
            "leaseArticleCount": n_data.get("leaseCnt", 0),
        }

    return {
        "updatedAt": now_str,
        "source": "국토교통부 실거래가 공개시스템(rt.molit.go.kr) & 네이버 부동산(m.land.naver.com)",
        "apartments": items,
    }


def upload_to_gist(payload: Dict[str, Any], token: str, gist_id: str) -> bool:
    url = f"https://api.github.com/gists/{gist_id}"
    body = json.dumps({
        "description": f"삼성전자 H3 아파트 실거래가 & 실시간 호가 ({payload['updatedAt']})",
        "files": {
            "prices.json": {
                "content": json.dumps(payload, ensure_ascii=False, indent=2)
            }
        }
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "H3-Apartment-Updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            raw_url = res["files"]["prices.json"]["raw_url"]
            print(f"[성공] GitHub Gist 업로드 완료! Raw URL: {raw_url}")
            return True
    except Exception as e:
        print(f"[오류] GitHub Gist 업로드 실패: {e}")
        return False


def inject_into_html(payload: Dict[str, Any], html_path: str = "index.html") -> bool:
    if not os.path.exists(html_path):
        return False
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"(/\* __PRICES_DATA_START__ \*/)(.*?)(/\* __PRICES_DATA_END__ \*/)"
    json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    replacement = f"\\1\n    const EMBEDDED_PRICES_DATA = {json_str};\n    \\3"

    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)
    if count > 0:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"[완료] '{html_path}' 내장 스냅샷(EMBEDDED_PRICES_DATA) 자동 갱신 완료!")
        return True
    return False


def load_github_config(config_path: str = "github_config.json") -> Dict[str, Any]:
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[경고] '{config_path}' 로드 실패: {e}")
        return {}


def push_to_github_repo(updated_at: str, config_path: str = "github_config.json") -> bool:
    """github_config.json의 토큰을 사용해 로컬에는 토큰을 남기지 않고 GitHub 저장소에 자동 커밋 & 푸시"""
    cfg = load_github_config(config_path)
    token = cfg.get("github_token") or os.environ.get("GITHUB_TOKEN", "")
    repo_url = cfg.get("repo_url", "https://github.com/woochn/H3_apartment.git")
    branch = cfg.get("branch", "main")

    if not token:
        print("[알림] GitHub 토큰이 설정되지 않아 자동 푸시를 건너뜁니다.")
        return False

    try:
        # git 저장소 초기화 확인
        if not os.path.exists(".git"):
            subprocess.run(["git", "init", "-b", branch], check=True)

        # 로컬 저장소 작성자 정보 설정 확인
        user_name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip()
        if not user_name:
            owner = cfg.get("owner", "woochn")
            subprocess.run(["git", "config", "user.name", owner], check=True)
            subprocess.run(["git", "config", "user.email", f"{owner}@users.noreply.github.com"], check=True)

        # remote origin 설정 (토큰이 포함되지 않은 순수 URL만 저장)
        remotes = subprocess.run(["git", "remote"], capture_output=True, text=True, check=True).stdout.split()
        if "origin" not in remotes:
            subprocess.run(["git", "remote", "add", "origin", repo_url], check=True)
        else:
            subprocess.run(["git", "remote", "set-url", "origin", repo_url], check=True)

        # 스테이징 (.gitignore에 의해 github_config.json은 절대 포함되지 않음)
        subprocess.run(["git", "add", ".gitignore", "prices.json", "index.html", "update_prices.py"], check=True)

        # 혹시라도 github_config.json이 추적 대상에 들어갔는지 이중 안전 검사
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True).stdout.splitlines()
        if any("github_config.json" in s or "secret" in s for s in staged):
            subprocess.run(["git", "reset", "HEAD", "github_config.json"], check=False)
            raise RuntimeError("보안 경고: github_config.json이 스테이징에 감지되어 푸시를 중단했습니다.")

        if not staged:
            print("[알림] 변경된 파일이 없어 Git 커밋을 건너뜁니다.")
        else:
            subprocess.run(
                ["git", "commit", "-m", f"chore: 실거래가 및 네이버 호가 업데이트 ({updated_at})"],
                check=True,
            )

        # HTTP Authorization 헤더를 일회성으로 주입하여 푸시 (.git/config에 토큰이 남지 않음)
        basic_auth = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        subprocess.run(
            [
                "git",
                "-c",
                f"http.extraheader=AUTHORIZATION: basic {basic_auth}",
                "push",
                "-u",
                "origin",
                branch,
            ],
            check=True,
        )
        raw_url = cfg.get("raw_prices_url", f"https://raw.githubusercontent.com/woochn/H3_apartment/{branch}/prices.json")
        print(f"[성공] GitHub 저장소({repo_url}) 푸시 완료!")
        print(f"       실시간 JSON URL: {raw_url}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[오류] Git 명령 실행 실패: {e}")
        return False
    except Exception as e:
        print(f"[오류] GitHub 푸시 실패: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="H3 아파트 실거래가 & 호가 업데이트 스크립트")
    parser.add_argument("--output", default="prices.json", help="출력 JSON 파일 경로")
    parser.add_argument("--html", default="index.html", help="내장 스냅샷을 갱신할 HTML 파일 경로")
    parser.add_argument("--config", default="github_config.json", help="GitHub 설정 JSON 파일 경로")
    parser.add_argument("--no-push", action="store_true", help="GitHub 저장소 자동 푸시 생략")
    parser.add_argument("--gist", action="store_true", help="GitHub Gist에 자동 업로드")
    args = parser.parse_args()

    payload = build_prices_payload()

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[완료] '{args.output}' 저장 완료 (기준일시: {payload['updatedAt']})")

    inject_into_html(payload, args.html)

    for aid, info in payload["apartments"].items():
        print(
            f" - {aid:5s} | {info['name']:22s} | "
            f"실거래(평균 {format_eok(info['realPriceAvgEok'])} / 직전 {info['realPriceLatestText']}) | "
            f"네이버호가({info['askingPriceText']}, 매물 {info['dealArticleCount']}건)"
        )

    if not args.no_push:
        push_to_github_repo(payload["updatedAt"], args.config)

    if args.gist:
        cfg = load_github_config(args.config)
        token = cfg.get("github_token") or os.environ.get("GITHUB_TOKEN", "").strip()
        gist_id = cfg.get("gist_id") or os.environ.get("GIST_ID", "").strip()
        if not token or not gist_id:
            print("[경고] --gist 옵션 사용 시 github_config.json 또는 환경변수에 토큰과 gist_id가 필요합니다.")
        else:
            upload_to_gist(payload, token, gist_id)


if __name__ == "__main__":
    main()
