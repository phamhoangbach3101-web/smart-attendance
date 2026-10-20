"""Record evaluation images from a webcam into the layout evaluate.py expects.

    python -m tools.capture_eval --person P01 --split enroll
    python -m tools.capture_eval --person P01 --split test --condition low_light
    python -m tools.capture_eval --person X01 --split test --condition normal   # unknown person

Use anonymous codes (P01, P02, ... for enrolled people, X01, ... for unknown
people) instead of real names. Keep the code-to-name mapping offline.

Keys in the preview window: SPACE start/pause capture, Q quit.
"""
import argparse
import os
import time

import cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--person', required=True, help='anonymous code, e.g. P01 or X01')
    ap.add_argument('--split', choices=['enroll', 'test'], required=True)
    ap.add_argument('--condition', default='normal',
                    help='test condition: normal, low_light, pose, glasses, mask, distance ...')
    ap.add_argument('--data', default=os.path.join('..', 'eval_data'))
    ap.add_argument('--count', type=int, default=20, help='images to save')
    ap.add_argument('--interval', type=float, default=0.3, help='seconds between saved frames')
    ap.add_argument('--camera', default='0', help='webcam index or RTSP URL')
    ap.add_argument('--check-face', action='store_true',
                    help='save only frames with exactly one detected face (loads the detector)')
    args = ap.parse_args()

    if args.split == 'enroll':
        out_dir = os.path.join(args.data, 'enroll', args.person)
    else:
        out_dir = os.path.join(args.data, 'test', args.condition, args.person)
    os.makedirs(out_dir, exist_ok=True)
    start_idx = len([f for f in os.listdir(out_dir) if f.endswith('.jpg')])

    detector = None
    if args.check_face:
        from functions.face_detector import FaceDetector
        detector = FaceDetector()

    source = int(args.camera) if args.camera.isdigit() else args.camera
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f'Cannot open camera {args.camera}')

    saved, capturing, last = 0, False, 0.0
    print(f'Saving to {out_dir}. Press SPACE to start, Q to quit.')
    while saved < args.count:
        ok, frame = cap.read()
        if not ok:
            continue
        now = time.time()
        status = 'ready'
        if capturing and now - last >= args.interval:
            usable = True
            if detector is not None:
                n = len(detector.detect_faces(frame))
                usable = n == 1
                status = f'{n} faces' if not usable else status
            if usable:
                path = os.path.join(out_dir, f'{start_idx + saved + 1:04d}.jpg')
                cv2.imwrite(path, frame)
                saved += 1
                last = now
        view = frame.copy()
        label = f'{args.person} | {args.split}/{args.condition} | {saved}/{args.count} | ' + \
                ('CAPTURING' if capturing else 'PAUSED') + f' | {status}'
        cv2.putText(view, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow('capture_eval', view)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord(' '):
            capturing = not capturing
    cap.release()
    cv2.destroyAllWindows()
    print(f'Saved {saved} images to {out_dir}')


if __name__ == '__main__':
    main()
