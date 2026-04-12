import os, time

time.sleep(60*10)

while True:
    time.sleep(60*60*6 + 60*0 + 0)
    os.system("python3 poster.py --municipality-type city --model gpt-5.1-codex-max --skip-logged-successes --state-postal ALL --skip-should-update-check --min-muni-population 18000 --max-muni-population 100000 --start-state CO")
