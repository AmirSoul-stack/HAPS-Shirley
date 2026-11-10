# Shirley public page

Each run: build the plain data with `shirley_publish.py build RAW OUT.json --voice-read yes|no`,
then encrypt it into the live folder:

    HAPS_USER=<username> HAPS_PW=<password> python3 tools/shirley_encrypt.py OUT.json <live folder>/data.enc.json

Only `data.enc.json` is committed. Never commit OUT.json or the password.
