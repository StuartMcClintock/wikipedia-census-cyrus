import os, time

time.sleep(60*60*2)
os.system("python3 poster.py --municipality-type city --model gpt-5.1-codex-mini --skip-should-update-check --skip-logged-successes --state-postal TX")
