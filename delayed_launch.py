import os, time

time.sleep(60*60*24*4+60*60*5)
os.system("python poster.py --model gpt-5.1-codex-mini --state-postal TX --municipality-type city --skip-logged-successes")
