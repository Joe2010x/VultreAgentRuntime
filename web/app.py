from base64 import b64encode
from collections import deque
import csv
from io import BytesIO, TextIOWrapper
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from .inference import generate_chart_code

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "runner" / "run.sh"
MAX_CSV_BYTES = 1024 * 1024
run_lock = Lock()
PUBLIC_DEMO = os.getenv("VULTRE_PUBLIC_DEMO") == "1"
if PUBLIC_DEMO and (
    os.getenv("VULTRE_SANDBOX_RUNTIME") != "runsc" or os.getenv("VULTRE_PREBUILT") != "1"
):
    raise RuntimeError("Public demo mode requires VULTRE_SANDBOX_RUNTIME=runsc and VULTRE_PREBUILT=1.")

attempts = deque()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def claim_run():
    if not run_lock.acquire(blocking=False):
        raise HTTPException(429, "A sandbox run is already underway. Try again shortly.")

    if PUBLIC_DEMO:
        now = monotonic()
        while attempts and attempts[0] <= now - 86400:
            attempts.popleft()
        if len(attempts) >= 100 or (len(attempts) >= 6 and attempts[-6] > now - 60):
            run_lock.release()
            raise HTTPException(429, "The demo has reached its run limit. Try again later.")
        attempts.append(now)


def invoke_runner(command, workspace):
    allowed = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR",
               "VULTRE_PREBUILT", "VULTRE_SANDBOX_RUNTIME")
    runner_env = {name: os.environ[name] for name in allowed if name in os.environ}
    return subprocess.run(
        command, cwd=workspace, env=runner_env, capture_output=True, text=True, errors="replace"
    )


def runner_log(result):
    return (result.stdout + result.stderr).strip()[-12000:]


def check_origin(request):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin requests are disabled.")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


def run_chart(upload, question=""):
    claim_run()
    try:
        with TemporaryDirectory(prefix="vultre-chart-") as workspace:
            task = Path(workspace)
            command = [str(RUNNER), "chart"]
            code = (ROOT / "runner" / "chart.py").read_text()
            if upload or question:
                data = upload or (ROOT / "runner" / "sample-sales.csv").read_bytes()
                csv_file = task / "input.csv"
                csv_file.write_bytes(data)
                csv_file.chmod(0o644)
                command.append(str(csv_file))
                if question:
                    try:
                        with TextIOWrapper(BytesIO(data), encoding="utf-8-sig", newline="") as source:
                            columns = next(csv.reader(source))
                    except (UnicodeError, csv.Error, StopIteration):
                        raise HTTPException(400, "Provide a UTF-8 CSV with a header row.") from None
                    if not columns or len(columns) > 100 or any(not name or len(name) > 120 for name in columns):
                        raise HTTPException(400, "Use 1–100 named columns, each at most 120 characters.")
                    code = generate_chart_code(question, columns)
                    script = task / "generated.py"
                    script.write_text(code, encoding="utf-8")
                    script.chmod(0o644)
                    command = [str(RUNNER), "generated", str(csv_file), str(script)]

            result = invoke_runner(command, task)
            response = {
                "log": runner_log(result),
                "code": code,
            }
            if result.returncode:
                response["error"] = "The chart run failed. Check the run log."
                return JSONResponse(response, status_code=500)

            chart = (task / "sales-chart.png").read_bytes()
            if not chart.startswith(b"\x89PNG\r\n\x1a\n"):
                response["error"] = "The script did not produce a PNG chart."
                return JSONResponse(response, status_code=502)
            response["chart"] = b64encode(chart).decode()
            return response
    finally:
        run_lock.release()


@app.post("/api/chart")
async def chart(request: Request):
    check_origin(request)

    question = unquote(request.headers.get("x-analysis-question", "")).strip()
    if len(question) > 500:
        raise HTTPException(400, "The analysis question must be 500 characters or fewer.")

    upload = bytearray()
    async for chunk in request.stream():
        if len(upload) + len(chunk) > MAX_CSV_BYTES:
            raise HTTPException(413, "CSV files must be 1 MiB or smaller.")
        upload.extend(chunk)

    if request.headers.get("content-type") == "text/csv" and not upload:
        raise HTTPException(400, "The uploaded CSV is empty.")

    return await run_in_threadpool(run_chart, upload, question)


@app.post("/api/containment")
def containment(request: Request):
    check_origin(request)
    claim_run()
    try:
        with TemporaryDirectory(prefix="vultre-probe-") as workspace:
            result = invoke_runner([str(RUNNER), "timeout-test"], workspace)
            response = {"log": runner_log(result)}
            if result.returncode:
                response["error"] = "The containment check failed. See the run log."
                return JSONResponse(response, status_code=500)
            return response
    finally:
        run_lock.release()
