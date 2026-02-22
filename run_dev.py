"""Run backend + frontend dev servers together."""
import subprocess
import sys
import signal
import os

def main():
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--reload", "--port", "8000"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend"),
    )

    try:
        backend.wait()
        frontend.wait()
    except KeyboardInterrupt:
        backend.terminate()
        frontend.terminate()


if __name__ == "__main__":
    main()
