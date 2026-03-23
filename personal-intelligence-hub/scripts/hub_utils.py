from pathlib import Path
import sys

# Reference the SHARED LIB explicitly
LIB_DIR = Path(r"C:\Users\shich\.gemini\scripts\lib")
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

import utils

HUB_DIR = utils.HUB_DIR
PROJECT_ROOT = utils.PROJECT_ROOT
NEWS_DIR = utils.NEWS_DIR
clean_json_output = utils.clean_json_output

if __name__ == "__main__":
    print(f"HUB_DIR: {HUB_DIR}")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"NEWS_DIR: {NEWS_DIR}")
