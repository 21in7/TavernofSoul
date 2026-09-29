from decimal import Decimal
import json
import re
from os.path import join

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