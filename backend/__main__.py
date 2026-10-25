"""Run the web app:  python -m backend  [--host 127.0.0.1] [--port 8000]"""
import argparse
import os
import warnings

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)


def main():
    parser = argparse.ArgumentParser(description='Smart Attendance web app')
    parser.add_argument('--host', default=os.environ.get('SA_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('SA_PORT', '8000')))
    args = parser.parse_args()

    import onnxruntime  # noqa: F401  (load before other native libs, as in main.py)
    import uvicorn
    from backend.app import create_app

    print('=' * 60)
    print(f'  Smart Attendance đang chạy tại:  http://{args.host}:{args.port}')
    print('  Nhấn Ctrl+C để dừng.')
    print('=' * 60)
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
