"""스킬 렌더 계획(skill_plan.py 출력) → WebM 일괄 렌더. 윈도우·맥·리눅스 공통, 코어 수만큼 병렬.

준비: Python 3.8+, `pip install numpy pillow`, ffmpeg(libvpx-vp9 포함 빌드). ffmpeg 가 PATH 에 없으면 --ffmpeg 로 경로 지정.

  python batch_render.py --plans plans/ktos_m.json
  python batch_render.py --plans plans/ktos_m.json --limit 10                 # 시험 삼아 10개
  python batch_render.py --plans plans/ktos_m.json --only Priest_Blessing     # 쉼표로 여러 개

- 결과: <out>/<스킬 ClassName>.webm, <out>/status/<ClassName>.json(ok/error, 걸린 시간, 크기, 오류)
- 다시 실행하면 끝난 스킬은 건너뛴다. 실패한 것만 다시 하려면 --retry-errors.
- 모두 끝나면 <out>/manifest.json(사이트 반영 목록)을 쓴다. 옮길 것은 <out> 폴더의 .webm 과 manifest.json.
- 에셋은 패치 CDN 에서 필요한 부분만 받아 --cache 에 쌓는다(처음 한 번만 네트워크 사용).
"""
import os

# 워커마다 numpy/BLAS 가 코어를 다시 나눠 쓰지 않도록 import 전에 1스레드로 고정
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
             'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_key, '1')

import argparse  # noqa: E402
import json  # noqa: E402
import multiprocessing as mp  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_assets = None


def _init(index_path, cache_dir, ffmpeg):
    global _assets
    sys.path.insert(0, HERE)
    import render_motion
    render_motion.FFMPEG = ffmpeg
    render_motion.CACHE = cache_dir
    _assets = render_motion.Assets(index_path)


def motion_spec(plan):
    return ','.join(name if rep == 1 else '%s*%s' % (name, rep) for name, rep in plan['segments'])


def _write_json(path, data):
    tmp = '%s.%d.tmp' % (path, os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _render(task):
    plan, opts = task
    import render_motion
    name = plan['skill']
    final = os.path.join(opts['out'], name + '.webm')
    tmp = os.path.join(opts['out'], 'tmp', '%s.%d.webm' % (name, os.getpid()))
    ns = argparse.Namespace(
        job=plan['motion_job'], motion=motion_spec(plan), index=None, size=opts['size'], fps=opts['fps'],
        yaw=plan.get('yaw', 215.0), mirror_head=False, pitch=18.0, distance=None, target_y=None, loops=1,
        # 이펙트 유무와 상관없이 같은 어두운 배경(사이트 영상 틀 색과 같게)
        codec='vp9', crf=opts['crf'], background='1d2026', no_effects=False, skill=None, no_weapons=False,
        max_duration=opts['max_duration'], alpha=False, supersample=opts['supersample'], frames_dir=None,
        out=tmp, preview=None, time=None, weapons=plan['weapons'], events=plan['events'],
        main_index=plan.get('main_index'), threads=opts['ffmpeg_threads'])
    t0 = time.time()
    try:
        info = render_motion.render(ns, assets=_assets, log=lambda *a, **k: None)
        os.replace(tmp, final)
        status = dict(skill=name, status='ok', seconds=round(time.time() - t0, 1), file=name + '.webm', **info)
    except Exception as e:  # 한 스킬 실패가 전체를 멈추지 않게 기록만 한다
        status = dict(skill=name, status='error', seconds=round(time.time() - t0, 1),
                      error='%s: %s' % (type(e).__name__, e), trace=traceback.format_exc()[-3000:])
        if os.path.exists(tmp):
            os.remove(tmp)
    _write_json(os.path.join(opts['out'], 'status', name + '.json'), status)
    return status


def check_ffmpeg(ffmpeg):
    try:
        out = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, check=True).stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit('ffmpeg 실행 실패(%s). --ffmpeg 로 ffmpeg 경로를 지정하세요.' % e)
    if 'libvpx-vp9' not in out:
        raise SystemExit('이 ffmpeg 에 libvpx-vp9 인코더가 없습니다. full 빌드를 쓰세요.')


def load_status(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def fmt_secs(s):
    s = int(s)
    return '%dh%02dm' % (s // 3600, s % 3600 // 60) if s >= 3600 else '%dm%02ds' % (s // 60, s % 60)


def write_manifest(plans, out_dir):
    items, errors = [], []
    for p in plans:
        st = load_status(os.path.join(out_dir, 'status', p['skill'] + '.json'))
        if st and st['status'] == 'ok' and os.path.exists(os.path.join(out_dir, st['file'])):
            items.append(dict(skill=p['skill'], id=p['id'], name=p['name'], tree=p['tree'],
                              stance=p['stance'], file=st['file'], bytes=st['bytes'], seconds=st['total']))
        elif st:
            errors.append(dict(skill=p['skill'], error=st.get('error')))
    _write_json(os.path.join(out_dir, 'manifest.json'), dict(items=items, errors=errors))
    return items, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plans', default=os.path.join(HERE, 'plans', 'ktos_m.json'))
    ap.add_argument('--index', default=os.path.join(HERE, 'cache', 'index_ktos_render.json'))
    ap.add_argument('--cache', default=os.path.join(HERE, 'cache'))
    ap.add_argument('--out', default=os.path.join(HERE, 'out_batch'))
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2),
                    help='동시 렌더 수(기본: 논리 코어 - 2)')
    ap.add_argument('--ffmpeg', default=os.environ.get('FFMPEG', 'ffmpeg'))
    ap.add_argument('--ffmpeg-threads', type=int, default=1)
    ap.add_argument('--size', default='360x480')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--crf', type=int, default=40)
    ap.add_argument('--supersample', type=int, default=2)
    ap.add_argument('--max-duration', type=float, default=3.5)
    ap.add_argument('--only', help='쉼표로 구분한 스킬 ClassName 만')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--retry-errors', action='store_true')
    ap.add_argument('--passes', type=int, default=2, help='실패한 스킬을 같은 실행 안에서 다시 시도할 횟수(첫 시도 포함)')
    args = ap.parse_args()

    check_ffmpeg(args.ffmpeg)
    with open(args.plans, encoding='utf-8') as f:
        plans = [p for p in json.load(f) if p['status'] == 'ok']
    if args.only:
        wanted = {s.strip() for s in args.only.split(',')}
        plans = [p for p in plans if p['skill'] in wanted]
    for sub in ('status', 'tmp'):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)

    todo = []
    for p in plans:
        st = load_status(os.path.join(args.out, 'status', p['skill'] + '.json'))
        if st and st['status'] == 'ok' and os.path.exists(os.path.join(args.out, p['skill'] + '.webm')):
            continue
        if st and st['status'] == 'error' and not args.retry_errors:
            continue
        todo.append(p)
    if args.limit:
        todo = todo[:args.limit]

    opts = dict(out=args.out, size=args.size, fps=args.fps, crf=args.crf, supersample=args.supersample,
                max_duration=args.max_duration, ffmpeg_threads=args.ffmpeg_threads)
    print('plans %d, to render %d, workers %d' % (len(plans), len(todo), args.workers), flush=True)
    t0, failed = time.time(), 0
    pending = todo
    ctx = mp.get_context('spawn')
    for pass_no in range(max(1, args.passes)):
        if not pending:
            break
        if pass_no:
            print('실패 %d개 재시도(%d번째)' % (len(pending), pass_no + 1), flush=True)
        done, pass_t0, errs = 0, time.time(), set()
        with ctx.Pool(args.workers, initializer=_init, initargs=(args.index, args.cache, args.ffmpeg),
                      maxtasksperchild=40) as pool:
            for st in pool.imap_unordered(_render, [(p, opts) for p in pending]):
                done += 1
                if st['status'] != 'ok':
                    errs.add(st['skill'])
                elapsed = time.time() - pass_t0
                eta = elapsed / done * (len(pending) - done)
                detail = '%dKB' % (st['bytes'] // 1024) if st['status'] == 'ok' else st['error'][-120:]
                print('[%4d/%d] %-5s %-40s %6.1fs %s  경과 %s 남은 %s' % (
                    done, len(pending), st['status'], st['skill'], st['seconds'], detail,
                    fmt_secs(time.time() - t0), fmt_secs(eta)), flush=True)
        pending = [p for p in pending if p['skill'] in errs]
    failed = len(pending)
    items, errors = write_manifest(plans, args.out)
    print('완료: 성공 %d, 실패 %d (이번 실행 실패 %d), 걸린 시간 %s → %s' % (
        len(items), len(errors), failed, fmt_secs(time.time() - t0), os.path.join(args.out, 'manifest.json')))


if __name__ == '__main__':
    main()
