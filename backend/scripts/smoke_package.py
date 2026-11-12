"""在独立目录和仅运行依赖环境中检查部署包。"""

from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.request import build_opener, HTTPCookieProcessor, Request
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    report = ROOT / "reports/release"
    uv = shutil.which("uv")
    assert uv
    with tempfile.TemporaryDirectory(
        prefix="package-smoke-", dir=ROOT / "tmp"
    ) as folder:
        target = Path(folder).resolve()
        assert target.is_relative_to((ROOT / "tmp").resolve())
        with zipfile.ZipFile(ROOT / "output/reading-practice-1.0.0-rc1.zip") as archive:
            for member in archive.infolist():
                assert (target / member.filename).resolve().is_relative_to(target)
            archive.extractall(target)
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env.pop("PUBLIC_ORIGIN", None)
        env.pop("APP_DATABASE", None)
        env.pop("APP_ENV", None)
        install = subprocess.run(
            [uv, "sync", "--locked", "--no-dev", "--offline"],
            cwd=target,
            env=env,
            capture_output=True,
            text=True,
        )
        (report / "package-install.log").write_text(
            install.stdout + install.stderr, encoding="utf8"
        )
        assert install.returncode == 0, install.stderr
        python = (
            target / ".venv/Scripts/python.exe"
            if os.name == "nt"
            else target / ".venv/bin/python"
        )
        log = (report / "package-server.log").open("w", encoding="utf8")
        process = subprocess.Popen(
            [
                str(python),
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8020",
            ],
            cwd=target,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            csrf = ""

            def call(path, method="GET", body=None):
                headers = {"Content-Type": "application/json"}
                if method != "GET":
                    headers["X-CSRF-Token"] = csrf
                r = opener.open(
                    Request(
                        "http://127.0.0.1:8020" + path,
                        data=json.dumps(body).encode() if body is not None else None,
                        method=method,
                        headers=headers,
                    ),
                    timeout=10,
                )
                return r.read(), r.headers

            for _ in range(60):
                try:
                    call("/api/health")
                    break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("部署包未启动")
            raw, headers = call("/")
            assert (
                b'id="app"' in raw
                and "frame-ancestors" in headers["Content-Security-Policy"]
            )
            script = re.search(r'src="([^"]+\.js)"', raw.decode())[1]
            assert call(script)[0]
            csrf = json.loads(call("/api/visitor")[0])["csrf"]
            a = json.loads(
                call(
                    "/api/attempts", "POST", dict(exam_id=1, mode="practice", scope=6)
                )[0]
            )
            aid = a["id"]
            q = json.loads(call(f"/api/attempts/{aid}/questions/31")[0])
            assert "answer" not in q and len(a["questions"]) == 16
            assert call(q["passage"]["assets"][0]["url"])[0].startswith(b"\xff\xd8")
            a = json.loads(
                call(
                    f"/api/attempts/{aid}/questions/31/answer",
                    "PUT",
                    dict(selection="D", revision=a["revision"]),
                )[0]
            )
            call(f"/api/attempts/{aid}/questions/31/reveal", "POST")
            q = json.loads(call(f"/api/attempts/{aid}/questions/31")[0])
            assert q["answer"] == "D" and q["explanation"]
            result = json.loads(call(f"/api/attempts/{aid}/submit", "POST")[0])[
                "result"
            ]
            assert result["independent_correct"] == 1 and result["total"] == 16
            output = dict(
                status="passed",
                fresh_runtime_only_environment=True,
                node_required=False,
                offline_locked_install=True,
                checks=[
                    "health",
                    "static_html_and_js",
                    "cookie_csrf",
                    "create_practice",
                    "hidden_answer",
                    "original_image",
                    "save_answer",
                    "reveal_explanation",
                    "submit_result",
                ],
            )
            (report / "package-smoke.json").write_text(
                json.dumps(output, ensure_ascii=False, indent=2), encoding="utf8"
            )
            print(json.dumps(output, ensure_ascii=False))
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.close()


if __name__ == "__main__":
    main()
