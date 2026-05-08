from os import path as opath, getenv
from logging import FileHandler, StreamHandler, INFO, basicConfig, error as log_error, info as log_info
from logging.handlers import RotatingFileHandler
from subprocess import run as srun
from dotenv import load_dotenv

# Clear old log file content
if opath.exists("log.txt"):
    with open("log.txt", 'r+') as f:
        f.truncate(0)

# Setup logging
basicConfig(
    format="[%(asctime)s] [%(name)s | %(levelname)s] - %(message)s [%(filename)s:%(lineno)d]",
    datefmt="%m/%d/%Y, %H:%M:%S %p",
    handlers=[FileHandler('log.txt'), StreamHandler()],
    level=INFO
)

# Load environment variables from config.env
load_dotenv('config.env', override=True)

# Get repo and branch from env
UPSTREAM_REPO = getenv('UPSTREAM_REPO')
UPSTREAM_BRANCH = getenv('UPSTREAM_BRANCH', 'main')  # default to main if not set

# Git update process
if UPSTREAM_REPO is not None:
    if opath.exists('.git'):
        srun(["rm", "-rf", ".git"])

    update = srun([f"""
        git init -q &&
        git config --global user.email "mdaquibjawed1106@gmail.com" &&
        git config --global user.name "aquib4040" &&
        git add . &&
        git commit -sm update -q || echo "No changes to commit" &&
        git remote add origin {UPSTREAM_REPO} &&
        git fetch origin -q &&
        git checkout -B {UPSTREAM_BRANCH} origin/{UPSTREAM_BRANCH} -q
    """], shell=True)

    if update.returncode == 0:
        log_info('✅ Successfully updated with latest commit from UPSTREAM_REPO')
    else:
        log_error('❌ Something went wrong while updating. Check UPSTREAM_REPO and UPSTREAM_BRANCH!')
