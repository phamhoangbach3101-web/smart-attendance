"""Offline evaluation of the recognition pipeline (open-set identification).

Data layout (see docs/EVALUATION.md):

    eval_data/
      enroll/<person>/*.jpg              enrollment session(s)
      test/<condition>/<person>/*.jpg    a DIFFERENT session; <person> not in
                                         enroll/ is treated as an unknown person

Usage:
    python evaluate.py --data ../eval_data --out ../results/baseline
    python evaluate.py --data ../eval_data --out ../results/k1 --enroll-samples 1
    python evaluate.py --data ../eval_data --out ../results/confirm3 --confirm-frames 3

Only aggregate numbers and per-probe scores are written; no face images.
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import defaultdict

import cv2
import numpy as np

from config import (CLAHE_CLIP, CLAHE_GRID, DETECTION_SCORE_THRESHOLD,
                    FACE_SIZE, GAUSSIAN_KERNEL,
                    RECOGNITION_MIN_MARGIN)
from functions.adaface_service import DEFAULT_COSINE_THRESHOLD as ADAFACE_THRESHOLD
from functions.matching import decide, identity_scores

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp')


def list_images(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(IMAGE_EXTS))


def load_layout(data_dir):
    enroll_dir = os.path.join(data_dir, 'enroll')
    test_dir = os.path.join(data_dir, 'test')
    enroll = {p: list_images(os.path.join(enroll_dir, p))
              for p in sorted(os.listdir(enroll_dir))
              if os.path.isdir(os.path.join(enroll_dir, p))}
    probes = []
    for condition in sorted(os.listdir(test_dir)):
        cdir = os.path.join(test_dir, condition)
        if not os.path.isdir(cdir):
            continue
        for person in sorted(os.listdir(cdir)):
            for path in list_images(os.path.join(cdir, person)):
                probes.append({'path': path, 'condition': condition,
                               'person': person, 'known': person in enroll})
    return enroll, probes


class Embedder:
    """Primary-face embedding with an on-disk cache so threshold sweeps are fast."""

    def __init__(self, cache_path, preprocess=False):
        from functions.adaface_service import get_adaface_service
        from functions.face_recognizer import get_insight_app
        self.app = get_insight_app()
        self.adaface = get_adaface_service()      # same embedding model as the app
        self.preprocess = preprocess
        self.cache_path = cache_path
        self.cache = {}
        if os.path.exists(cache_path):
            with np.load(cache_path, allow_pickle=True) as data:
                self.cache = data['cache'].item()
        self._clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_GRID)

    def _enhance(self, img):
        img = cv2.GaussianBlur(img, GAUSSIAN_KERNEL, 0)
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        return cv2.cvtColor(cv2.merge([self._clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)

    def embed(self, path):
        key = f'{os.path.abspath(path)}|{int(self.preprocess)}|{os.path.getmtime(path)}|adaface'
        if key in self.cache:
            return self.cache[key]
        img = cv2.imread(path)
        result = {'embedding': None, 'det_score': 0.0, 'latency_ms': None}
        if img is not None:
            if self.preprocess:
                img = self._enhance(img)
            from functions.adaface_service import embed_detected_face
            t0 = time.perf_counter()
            faces = self.app.get(img)
            faces = [f for f in faces if f.det_score >= DETECTION_SCORE_THRESHOLD]
            if faces:
                # Largest face = primary face, same rule as the app.
                face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                result['embedding'] = embed_detected_face(self.adaface, img, face)
                result['det_score'] = float(face.det_score)
            result['latency_ms'] = (time.perf_counter() - t0) * 1000
        self.cache[key] = result
        return result

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        np.savez_compressed(self.cache_path, cache=np.array(self.cache, dtype=object))


def build_gallery(enroll, embedder, k):
    gallery, missing = {}, []
    for person, paths in enroll.items():
        embs = []
        for path in paths:
            e = embedder.embed(path)['embedding']
            if e is not None:
                embs.append(e)
            if k and len(embs) >= k:
                break
        if embs:
            gallery[person] = np.vstack(embs)
        else:
            missing.append(person)
    return gallery, missing


def score_probes(probes, gallery, embedder):
    rows = []
    for p in probes:
        r = embedder.embed(p['path'])
        scores = identity_scores(r['embedding'], gallery) if r['embedding'] is not None else {}
        rows.append({**p, 'detected': r['embedding'] is not None,
                     'latency_ms': r['latency_ms'], 'scores': scores})
    return rows


def frame_decisions(rows, threshold, margin):
    out = []
    for r in rows:
        d = decide(r['scores'], threshold, margin) if r['detected'] else \
            {'matched': False, 'identity': None, 'best_identity': None, 'score': 0.0, 'margin': 0.0}
        out.append({**r, **{k: d.get(k) for k in ('matched', 'identity', 'best_identity', 'score', 'margin')}})
    return out


def confirm_windows(decisions, n):
    """Multi-frame confirmation: accept an identity only if N consecutive frames agree."""
    if n <= 1:
        return decisions
    groups = defaultdict(list)
    for d in decisions:
        groups[(d['condition'], d['person'])].append(d)
    windows = []
    for (_, _), seq in groups.items():
        seq = sorted(seq, key=lambda d: d['path'])
        for i in range(len(seq) - n + 1):
            win = seq[i:i + n]
            ids = {d['identity'] for d in win}
            agreed = len(ids) == 1 and win[0]['matched']
            windows.append({**win[-1], 'matched': agreed,
                            'identity': win[0]['identity'] if agreed else None,
                            'detected': all(d['detected'] for d in win)})
    return windows


def compute_metrics(decisions):
    c = defaultdict(int)
    for d in decisions:
        if d['known']:
            c['known'] += 1
            if not d['detected']:
                c['known_not_detected'] += 1
            if d['matched'] and d['identity'] == d['person']:
                c['correct'] += 1
            elif d['matched']:
                c['misidentified'] += 1
            else:
                c['rejected_known'] += 1
        else:
            c['unknown'] += 1
            if d['matched']:
                c['unknown_accepted'] += 1
            else:
                c['unknown_rejected'] += 1
    known, unknown = c['known'], c['unknown']
    total = known + unknown

    def rate(a, b):
        return round(a / b, 4) if b else None

    return {
        'counts': dict(c),
        'identification_rate': rate(c['correct'], known),           # nhận đúng
        'misidentification_rate': rate(c['misidentified'], known),  # nhận nhầm người khác
        'false_reject_rate': rate(c['rejected_known'], known),      # từ chối nhầm
        'unknown_reject_rate': rate(c['unknown_rejected'], unknown),  # chặn người lạ
        'unknown_accept_rate': rate(c['unknown_accepted'], unknown),
        # Any wrong acceptance = attendance given to the wrong identity.
        'false_accept_rate': rate(c['misidentified'] + c['unknown_accepted'], total),
        'detection_failure_rate': rate(c['known_not_detected'], known),
    }


def latency_stats(rows):
    lat = sorted(r['latency_ms'] for r in rows if r['latency_ms'] is not None)
    if not lat:
        return {}
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    mean = statistics.mean(lat)
    return {'n': len(lat), 'mean_ms': round(mean, 1), 'p50_ms': round(statistics.median(lat), 1),
            'p95_ms': round(p95, 1), 'throughput_fps': round(1000 / mean, 1)}


def sweep(rows, margin, confirm, lo=0.2, hi=0.9, step=0.01):
    out = []
    t = lo
    while t <= hi + 1e-9:
        m = compute_metrics(confirm_windows(frame_decisions(rows, t, margin), confirm))
        out.append({'threshold': round(t, 2), **{k: v for k, v in m.items() if k != 'counts'}})
        t += step
    return out


def recommend(sweep_rows, far_target):
    ok = [r for r in sweep_rows if r['false_accept_rate'] is not None
          and r['false_accept_rate'] <= far_target and r['identification_rate'] is not None]
    if not ok:
        return None
    return max(ok, key=lambda r: (r['identification_rate'], -r['threshold']))


def pct(x):
    return '–' if x is None else f'{x * 100:.1f}%'


def write_report(out_dir, cfg, overall, per_condition, latency, rec, missing):
    lines = [
        '# Evaluation report', '',
        f"- Data: `{cfg['data']}`  ·  enrolled identities: {cfg['n_identities']}"
        f"  ·  enroll samples per person: {cfg['enroll_samples'] or 'all'}",
        f"- Decision: threshold {cfg['threshold']}, margin {cfg['margin']}, "
        f"confirm frames {cfg['confirm_frames']}, preprocessing {cfg['preprocess']}",
        f"- Hardware: {cfg['hardware']}", '',
        '| Condition | Known probes | Unknown probes | Identification | Misidentified | False reject | Unknown rejected | False accept |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for name, m in [*per_condition.items(), ('**all**', overall)]:
        c = m['counts']
        lines.append(f"| {name} | {c.get('known', 0)} | {c.get('unknown', 0)} | {pct(m['identification_rate'])} | "
                     f"{pct(m['misidentification_rate'])} | {pct(m['false_reject_rate'])} | "
                     f"{pct(m['unknown_reject_rate'])} | {pct(m['false_accept_rate'])} |")
    lines += ['', f"Detection failures on known probes: {pct(overall['detection_failure_rate'])}", '']
    if latency:
        lines += [f"Latency (detect + embed, per image): mean {latency['mean_ms']} ms, "
                  f"p50 {latency['p50_ms']} ms, p95 {latency['p95_ms']} ms "
                  f"(≈ {latency['throughput_fps']} images/s)", '']
    if rec:
        lines += [f"Recommended threshold for false-accept ≤ {pct(cfg['far_target'])}: **{rec['threshold']}** "
                  f"→ identification {pct(rec['identification_rate'])}, "
                  f"false reject {pct(rec['false_reject_rate'])}", '']
    else:
        lines += [f"No threshold reaches false-accept ≤ {pct(cfg['far_target'])} with this margin.", '']
    if missing:
        lines += [f"Identities with no usable enrollment face: {', '.join(missing)}", '']
    with open(os.path.join(out_dir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def try_plot(out_dir, sweep_rows, threshold):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return
    t = [r['threshold'] for r in sweep_rows]
    fig, ax = plt.subplots(figsize=(7, 4))
    for key, label in [('identification_rate', 'Identification'),
                       ('false_reject_rate', 'False reject'),
                       ('false_accept_rate', 'False accept')]:
        ax.plot(t, [r[key] or 0 for r in sweep_rows], label=label)
    ax.axvline(threshold, color='gray', linestyle='--', linewidth=1, label=f'current = {threshold}')
    ax.set_xlabel('Cosine threshold')
    ax.set_ylabel('Rate')
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'threshold_sweep.png'), dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--threshold', type=float, default=ADAFACE_THRESHOLD)
    ap.add_argument('--margin', type=float, default=RECOGNITION_MIN_MARGIN)
    ap.add_argument('--enroll-samples', type=int, default=0, help='0 = use all enrollment images')
    ap.add_argument('--confirm-frames', type=int, default=1)
    ap.add_argument('--preprocess', action='store_true', help='Gaussian + CLAHE before detection')
    ap.add_argument('--far-target', type=float, default=0.01)
    ap.add_argument('--hardware', default='not specified', help='e.g. "i5-1135G7, CPU only"')
    args = ap.parse_args()

    enroll, probes = load_layout(args.data)
    if not enroll or not probes:
        sys.exit('No data found. Expected <data>/enroll/<person>/ and <data>/test/<condition>/<person>/')
    os.makedirs(args.out, exist_ok=True)
    embedder = Embedder(os.path.join(args.data, '.embedding_cache.npz'), preprocess=args.preprocess)
    gallery, missing = build_gallery(enroll, embedder, args.enroll_samples)
    rows = score_probes(probes, gallery, embedder)
    embedder.save()

    decisions = confirm_windows(frame_decisions(rows, args.threshold, args.margin), args.confirm_frames)
    overall = compute_metrics(decisions)
    per_condition = {cond: compute_metrics([d for d in decisions if d['condition'] == cond])
                     for cond in sorted({d['condition'] for d in decisions})}
    latency = latency_stats(rows)
    sweep_rows = sweep(rows, args.margin, args.confirm_frames)
    rec = recommend(sweep_rows, args.far_target)

    cfg = {'data': args.data, 'threshold': args.threshold, 'margin': args.margin,
           'enroll_samples': args.enroll_samples, 'confirm_frames': args.confirm_frames,
           'preprocess': args.preprocess, 'far_target': args.far_target,
           'hardware': args.hardware, 'n_identities': len(gallery)}
    with open(os.path.join(args.out, 'metrics.json'), 'w', encoding='utf-8') as f:
        json.dump({'config': cfg, 'overall': overall, 'per_condition': per_condition,
                   'latency': latency, 'recommended': rec, 'missing_enrollment': missing},
                  f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.out, 'sweep.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(sweep_rows[0].keys()))
        w.writeheader()
        w.writerows(sweep_rows)
    with open(os.path.join(args.out, 'probes.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['file', 'condition', 'person', 'known', 'detected', 'decided', 'best_identity', 'score', 'margin'])
        for d in frame_decisions(rows, args.threshold, args.margin):
            w.writerow([os.path.relpath(d['path'], args.data), d['condition'], d['person'], d['known'],
                        d['detected'], d['identity'] or 'REJECT', d['best_identity'], d['score'], d['margin']])
    write_report(args.out, cfg, overall, per_condition, latency, rec, missing)
    try_plot(args.out, sweep_rows, args.threshold)
    print(open(os.path.join(args.out, 'report.md'), encoding='utf-8').read())


if __name__ == '__main__':
    main()
