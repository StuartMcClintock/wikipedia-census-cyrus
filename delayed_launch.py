import os, time

time.sleep(60*10)

while True:
    time.sleep(60*60*1 + 60*0 + 0)
    os.system("python3 poster.py --municipality-type city --model gpt-5.3-codex --skip-logged-successes --state-postal ALL --skip-should-update-check --min-muni-population 10000 --max-muni-population 100000")
