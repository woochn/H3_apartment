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


def fetch_molit_openapi_fallback(target: Dict[str, Any], service_key: str, deal_ymd: str = "202610") -> Dict[str, Any]:
    """github_config.json에 저장된 공공데이터포털 OpenAPI(RTMSDataSvcAptTradeDev) 인증키를 사용한 조회"""
    lawd_cd = target["molit_led"][:5]
    url = (
        f"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev?"
        f"serviceKey={service_key}&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&pageNo=1&numOfRows=1000"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    xml_data = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
    root = ET.fromstring(xml_data)

    amin, amax = target["area_min"], target["area_max"]
    short_name = target["name"].split()[0][:4]
    history = []
    for item in root.findall(".//item"):
        apt_nm = (item.findtext("aptNm") or "").strip()
        cdeal = (item.findtext("cdealType") or "").strip()
        if cdeal == "O" or short_name not in apt_nm:
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
            res = fetch_molit_transactions(opener, t, year="2026")
            if not res.get("latestDeal") and openapi_key:
                res = fetch_molit_openapi_fallback(t, openapi_key, deal_ymd="202610")
            molit_results[t["id"]] = res
        except Exception as e:
            print(f"  [경고] {t['name']} 웹 조회 실패({e}), OpenAPI 폴백 시도...")
            if openapi_key:
                try:
                    molit_results[t["id"]] = fetch_molit_openapi_fallback(t, openapi_key, deal_ymd="202610")
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
