from django.shortcuts import render
from os.path import join
from datetime import datetime, timedelta
from django.utils import timezone
import pytz
from django.core.cache import cache
import json

APP_NAME = 'Challenge'
CACHE_VERSION = 'v2'


def _load_challenge_data():
    with open('/home/ubuntu/bot/challenge.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def _split_multilang(name_raw: str):
    # 입력 예: "한글명,(English Name),(日本語名)" 혹은 줄바꿈 포함 케이스
    import re
    text = (name_raw or '').replace('\n', '')
    # 괄호 안의 텍스트 추출
    inner = re.findall(r'\((.*?)\)', text)
    # 첫 '(' 앞의 문자열을 한글로 간주
    ko = re.split(r'\(', text, 1)[0].strip().rstrip(',')
    en = inner[0].strip() if len(inner) > 0 else ko
    ja = inner[1].strip() if len(inner) > 1 else en
    return ko, en, ja


def _get_today_group():
    # 짝수달: em, 홀수달: om
    current = timezone.localtime(timezone.now())
    month = current.month
    return 'em' if month % 2 == 0 else 'om'


def _get_today_index():
    # 날짜를 DD 기반으로 0-index로 사용 (1~31 -> 0~30)
    current = timezone.localtime(timezone.now())
    day = current.day
    return (day - 1)


def _seconds_until_kst_midnight(now) -> int:
    # 기준: Asia/Seoul 자정까지 남은 초 계산
    kst = pytz.timezone('Asia/Seoul')
    now_kst = now.astimezone(kst)
    tomorrow = (now_kst + timedelta(days=1)).date()
    midnight = kst.localize(datetime.combine(tomorrow, datetime.min.time()))
    return int((midnight - now_kst).total_seconds())


def index(request):
    # 캐시 키: 도메인별 언어 + 그룹키 + 날짜
    current_kst = timezone.now().astimezone(pytz.timezone('Asia/Seoul'))
    cache_key = f"challenge:{CACHE_VERSION}:{request.get_host()}:{current_kst.strftime('%Y-%m-%d')}"
    cached = cache.get(cache_key)
    if cached:
        return render(request, join(APP_NAME, 'index.html'), cached)

    data = _load_challenge_data()
    group_key = _get_today_group()
    items = data.get(group_key, [])

    # 일수보다 아이템 수가 적을 때를 대비해 모듈러 사용
    idx = _get_today_index() % len(items) if items else 0
    today = items[idx] if items else None

    # 언어 선택
    host = request.get_host()
    ko, en, ja = _split_multilang(today['name']) if today else ('', '', '')
    if 'itos' in host:
        display_name = en
        title_label = "Today's Challenge"
        refresh_notice = "Updates at 00:00 (KST)."
    elif 'jtos' in host:
        display_name = ja
        title_label = "本日のチャレンジ"
        refresh_notice = "韓国時間の午前0時（KST）に更新されます。"
    else:
        display_name = ko
        title_label = "오늘의 챌린지"
        refresh_notice = "한국시간 기준 00시(KST)에 갱신됩니다."

    current = timezone.localtime(timezone.now())
    # 남은 TTL(초): 한국 자정까지
    ttl_seconds = _seconds_until_kst_midnight(timezone.now())
    context = {
        'today': today,
        'group_key': group_key,
        'today_str': current.strftime('%y-%m-%d'),
        'display_name': display_name,
        'title_label': title_label,
        'ttl_seconds': ttl_seconds,
        'refresh_notice': refresh_notice,
    }
    cache.set(cache_key, context, ttl_seconds if ttl_seconds > 0 else 60)
    return render(request, join(APP_NAME, 'index.html'), context)


