from decimal import Decimal
import json
import re
from os.path import join

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from Jobs.models import Jobs
from Skills.models import Skills

APP_NAME = 'Planner'


def _normalize_scalar(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _normalize_series(value):
    if not value or value == 'None':
        return []

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return _normalize_series(parsed)

    if isinstance(value, (list, tuple, set)):
        return [_normalize_scalar(v) for v in value]

    return [_normalize_scalar(value)]


def imcFormatRemover(string):
    string = string.split('{nl}')
    s2 = []
    for i in string:
        s2.append(re.sub(r'\{(.*?)\}', '', i))
    return s2

# def parseToJSfriendly(string):
#     specialvar= [
#         '{CaptionRatio}', '{CaptionRatio2}', '{CaptionRatio3}',
#         '{SkillSR}', '{SpendItemCount}', '{SkillFactor}','{CaptionTime}',
#         '{SpendItemCount}', '{SpendPoison}', '{SpendSP}' 
#         ]
#     new_string = ''
#     new_words = ''
#     words = string.split('#')
#     for word in words:
#         if word in specialvar:
#             word = word.replace('{','').replace('}','')
#             word = " <span class='{}'> </span> ".format(word)
#         new_words+= word
#     new_string+=new_words

#     return imcFormatRemover(new_string)



def parseEffect(effect, obj):
    specialvar= {
        'CaptionRatio'  : 'captionratio1', 
        'CaptionRatio2' : 'captionratio2', 
        'CaptionRatio3' : 'captionratio3',
        'SkillSR'       : 'skillsr', 
        'SpendItemCount': 'spenditemcount' , 
        'SkillFactor'   : 'sfr',
        'CaptionTime'   : 'captiontime',
        'SpendItemCount': 'spenditemcount', 
        'SpendPoison'   : 'spendpoison',   
        'SpendSP'       : 'spendsp'
    }
    effect = effect.replace('{#339999}{ol}','').split('{nl}')
    ef = []
    for lines in effect:
        lines = lines.replace('{','').replace('}','').replace('//','').split('#')
        # new_lines = []
        # for word in lines:
        #     if word in specialvar:
        #         if (obj[specialvar[word]] == None):
        #             continue
        #         word = obj[specialvar[word]][0]
        #     new_lines.append(word)
        ef.append(lines)
    return ef

def _serialize_attribute(attribute):
    descriptions = attribute.descriptions or ''
    return {
        'name': attribute.name,
        'descriptions': descriptions.split("{nl}") if descriptions else [],
        'ids': attribute.ids,
        'icon': attribute.icon,
    }


def _serialize_skill(skill, counter):
    return {
        'counter': counter,
        'ids': skill.ids,
        'icon': skill.icon,
        'name': skill.name,
        'cooldown': (skill.cooldown or 0) / 1000 if skill.cooldown is not None else None,
        'sp': _normalize_scalar(skill.sp),
        'sfr': _normalize_series(skill.sfr),
        'descriptions': imcFormatRemover(skill.descriptions) if skill.descriptions else [],
        'cooldown_lv': _normalize_series(skill.cooldown_lv),
        'max_lv': skill.max_lv,
        'overheat': skill.overheat,
        'captionratio1': _normalize_series(skill.captionratio1),
        'captionratio2': _normalize_series(skill.captionratio2),
        'captionratio3': _normalize_series(skill.captionratio3),
        'captiontime': _normalize_series(skill.captiontime),
        'skillsr': _normalize_series(skill.skillsr),
        'spenditemcount': _normalize_series(skill.spenditemcount),
        'spendsp': _normalize_series(skill.spendsp),
        'spendpoison': _normalize_series(skill.spendpoison),
        'other': _normalize_series(skill.other),
        'stance': skill.stance,
        'attributes_set': [_serialize_attribute(attr) for attr in skill.attributes_set.all()],
        'effect': parseEffect(skill.effect or '', {}),
    }


def _serialize_job(job, skills_queryset):
    return {
        'ids': job.ids,
        'name': job.name,
        'icon': job.icon,
        'is_starter': job.is_starter,
        'job_tree': job.job_tree,
        'skills': [
            _serialize_skill(skill, counter)
            for counter, skill in enumerate(skills_queryset)
        ],
    }


@cache_page(60 * 10)
def index(request):
    deprecatedClass = [1005, 2012, 9001, 4013]
    jobs_qs = Jobs.objects.exclude(ids__in=deprecatedClass).order_by('ids')
    job_ids = list(jobs_qs.values_list('ids', flat=True))

    bootstrap_payload = json.dumps({
        'jobIds': job_ids,
        'getJobUrl': reverse('Planner:getJob'),
        'lazyAssets': [
            '/staticfiles_itos/js/skillFunctions.js',
            '/staticfiles_itos/js/ColladaLoader.js',
        ],
    })

    context = {
        'jobs': jobs_qs,
        'bootstrap_payload': bootstrap_payload,
    }

    return render(request, join(APP_NAME, "index.html"), context)

def getTree(request):
    try:
        ids = request.GET['ids']
        tree = Jobs.objects.get(ids = ids).job_tree
        ret = {'tree' : tree}
        return JsonResponse(ret)
    except:
        ret = {} 
        ret = json.dumps(ret)
        return JsonResponse(ret)

def getTreeData(request):
    try:
        tree = request.GET['tree']
        tree = Jobs.objects.filter(job_tree = tree)
 
        ret = [{'name' : i.name, 'ids' : i.ids, 'icon':i.icon } for i in tree]
        return JsonResponse(ret)
    except:
        ret = {} 
        ret = json.dumps(ret)
        return JsonResponse(ret)
@require_GET
@cache_page(60 * 30)
def getJob(request):
    job_id = request.GET.get('ids')
    if not job_id:
        return JsonResponse({'error': 'ids parameter is required'}, status=400)

    job = get_object_or_404(Jobs.objects.all(), ids=job_id)
    skills_qs = (
        Skills.objects.filter(job=job)
        .select_related('job')
        .prefetch_related('attributes_set')
        .order_by('ids')
    )

    payload = _serialize_job(job, skills_qs)
    return JsonResponse(payload)

@require_GET
def pvp(request):
    """Render a client-only calculator; no model or importer access."""
    korean = getattr(settings, 'REGION', '') in ('ktos', 'ktest')
    en = {
        'title': 'PvP Calculator',
        'intro': 'Basic probabilities from your entered stats using the supplied revised PvP formulas. Separate card, buff and trait probability bonuses are not automatically added. This is not confirmation of a live game patch.',
        'defaults': 'Defaults: both levels 500 and all stats 20,000. Equal levels and stats give 90% hit, 10% opponent evasion, 10% critical and 30% your block.',
        'limits': 'Levels: integers from 0 to 10,000. Stats: 0 to 1,000,000,000,000 (decimals allowed). Use decimal numbers or scientific notation, without commas; at most 64 characters. Negative signs and values too small to represent are rejected. Inputs are never clamped.',
        'inputs': 'Levels and stats', 'results': 'Basic probabilities',
        'reset': 'Reset to defaults', 'factor': 'Level correction factor',
        'formula': 'Formulas',
        'note': 'Before level correction, probabilities vary smoothly with the stat ratio (including +10). Only a higher opponent level reduces hit: an opponent 50 or more levels above you makes hit 0%. A higher player level gives no bonus. Critical and block have no level correction. This tool does not calculate PvE or damage.',
        'noscript': 'Enable JavaScript to calculate probabilities. Results remain unavailable until JavaScript runs.',
        'invalid': 'Correct the marked inputs. All results are unavailable until every input is valid.',
        'error': 'Enter a finite, non-negative decimal within the stated range; levels must be integers. Do not use a minus sign, commas or more than 64 characters.',
    }
    ko = {
        'title': 'PvP 확률 계산기',
        'intro': '제공된 PvP 개편 공식으로 입력 스탯의 기본 확률을 계산합니다. 별도 카드·버프·특성의 확률 보너스는 자동 합산하지 않습니다. 실제 게임 패치 적용 완료를 뜻하지 않습니다.',
        'defaults': '기본값: 양쪽 레벨 500, 모든 스탯 20,000. 같은 레벨과 스탯이면 명중 90%, 상대 회피 10%, 치명타 10%, 내 블록 30%입니다.',
        'limits': '레벨: 0~10,000 정수. 스탯: 0~1,000,000,000,000 (소수 허용). 쉼표 없이 십진수 또는 지수 표기를 사용하세요. 최대 64자이며 음수 부호나 표현할 수 없을 만큼 작은 값은 거부합니다. 입력을 임의 보정하지 않습니다.',
        'inputs': '레벨 및 스탯', 'results': '기본 확률',
        'reset': '기본값으로 초기화', 'factor': '레벨 보정 계수',
        'formula': '사용 공식',
        'note': '레벨 보정 전 확률은 +10을 포함한 스탯 비율에 따라 부드럽게 변합니다. 상대 레벨이 높을 때만 명중이 감소하며, 상대가 50레벨 이상 높으면 명중은 0%입니다. 내 레벨이 더 높아도 보너스는 없습니다. 치명타·블록에는 레벨 보정을 적용하지 않습니다. PvE나 대미지를 계산하지 않습니다.',
        'noscript': '확률 계산에는 JavaScript가 필요합니다. JavaScript 실행 전에는 결과를 표시하지 않습니다.',
        'invalid': '표시된 입력을 수정하세요. 모든 입력이 유효해질 때까지 전체 결과를 표시하지 않습니다.',
        'error': '범위 내의 유한한 0 이상 십진수를 입력하세요. 레벨은 정수여야 합니다. 음수 부호·쉼표·64자 초과 입력은 허용하지 않습니다.',
    }
    labels = [
        ('myLevel', 'My level', '내 레벨', '500'),
        ('opponentLevel', 'Opponent level', '상대 레벨', '500'),
        ('accuracy', 'My accuracy', '내 명중', '20000'),
        ('evasion', 'Opponent evasion', '상대 회피', '20000'),
        ('critical', 'My critical occurrence', '내 치명타 발생', '20000'),
        ('criticalResistance', 'Opponent critical resistance', '상대 치명타 저항', '20000'),
        ('block', 'My block', '내 블록', '20000'),
        ('blockPenetration', 'Opponent block penetration', '상대 블록 관통', '20000'),
    ]
    outputs = [
        ('hit', 'My hit chance', '내 명중률'),
        ('evasion', 'Opponent evasion chance', '상대 회피율'),
        ('critical', 'My critical chance', '내 치명타 확률'),
        ('block', 'My block chance', '내 블록 확률'),
    ]
    return render(request, join(APP_NAME, 'pvp.html'), {
        'pvp_text': ko if korean else en,
        'pvp_language': 'ko' if korean else 'en',
        'pvp_inputs': [{'key': key, 'label': kr if korean else eng, 'default': default}
                       for key, eng, kr, default in labels],
        'pvp_outputs': [{'key': key, 'label': kr if korean else eng}
                        for key, eng, kr in outputs],
    })
