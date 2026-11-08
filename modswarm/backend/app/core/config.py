import os
from pathlib import Path

from dotenv import load_dotenv

_backend_dir = Path(__file__).resolve().parent.parent.parent
_repo_root = _backend_dir.parent.parent
load_dotenv(_repo_root / ".env")
load_dotenv(_backend_dir / ".env.local")
load_dotenv(_backend_dir / ".env")

OPENAI_API_KEY = os.getenv("NVIDIA_API_KEY") or os.getenv("NEMOTRON_API_KEY") or os.getenv("OPENAI_API_KEY", "")
NVIDIA_API_KEY = OPENAI_API_KEY
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
VULTR_BASE_URL = os.getenv("VULTR_BASE_URL", "https://api.vultrinference.com/v1")
VULTR_API_KEY = os.getenv("VULTR_API_KEY", "")
VULTR_MODEL = os.getenv("VULTR_MODEL", "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
GRAPHDEV_API_SECRET = os.getenv("GRAPHDEV_API_SECRET", "")
ENV = os.getenv("ENV", "dev")
DATA_DIR = Path(os.getenv("DATA_DIR", str(_backend_dir / "data")))
REPOS_DIR = Path(os.getenv("REPOS_DIR", str(DATA_DIR / "repos")))
DB_PATH = Path(os.getenv("DB_PATH", str(_backend_dir / "graphdev.db")))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
