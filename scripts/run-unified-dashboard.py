"""Use the camera venv's existing FastAPI/httpx packages; no OCR model is loaded."""
import argparse
import os
from pathlib import Path
import sys

import uvicorn
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from unified_gateway import create_gateway


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--sensor-url', default='http://127.0.0.1:5001')
    parser.add_argument('--parking-url', default='http://127.0.0.1:8001')
    args = parser.parse_args()
    config = {**dotenv_values(ROOT / '.env'), **os.environ}
    app = create_gateway(args.sensor_url, args.parking_url,
        username=config.get('DASHBOARD_USERNAME', config.get('GRAFANA_USERNAME', 'parking-admin')),
        password=config.get('DASHBOARD_PASSWORD', config.get('GRAFANA_PASSWORD', '')),
        auth_required=config.get('DASHBOARD_AUTH_REQUIRED', 'yes') != 'no')
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
