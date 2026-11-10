#!/usr/bin/env python3
"""Encrypt the Shirley public data so only a person with the username and password can read it.
Usage: HAPS_USER=name HAPS_PW=password python3 tools/shirley_encrypt.py data.json OUT_DIR/data.enc.json
The password is read from the environment and never written to any file."""
import sys, os, json, base64, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
ITER = 600000
here = os.path.dirname(os.path.abspath(__file__))
salt = open(os.path.join(here, 'salt.txt')).read().strip()
user, pw = os.environ.get('HAPS_USER', ''), os.environ.get('HAPS_PW', '')
if not user or not pw:
    sys.exit('Set HAPS_USER and HAPS_PW')
src, dst = sys.argv[1], sys.argv[2]
raw = open(src, 'rb').read()
json.loads(raw)  # must be valid JSON
key = hashlib.pbkdf2_hmac('sha256', pw.encode(), (user.strip().lower() + ':' + salt).encode(), ITER, 32)
iv = os.urandom(12)
ct = AESGCM(key).encrypt(iv, raw, None)
b = lambda x: base64.b64encode(x).decode()
json.dump({'v': 1, 'salt': salt, 'iter': ITER, 'iv': b(iv), 'ct': b(ct)}, open(dst, 'w'))
print('encrypted', len(raw), 'bytes ->', dst)
