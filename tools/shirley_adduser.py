#!/usr/bin/env python3
"""Add (or replace) an extra sign-in for the public page.
Usage: HAPS_USER=Rhys HAPS_PW=<main password> NEW_USER=Kyle NEW_PW=<new password> \
       python3 tools/shirley_adduser.py hp-46fd9621c309/data.enc.json
The extra user's key wraps the main data key; the data file stays encrypted once.
Passwords come from the environment and are never written to any file.
Daily runs keep using only the main password: shirley_encrypt.py preserves 'wraps'."""
import sys, os, json, base64, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
here = os.path.dirname(os.path.abspath(__file__))
dst = sys.argv[1]
enc = json.load(open(dst))
def key(u, p): return hashlib.pbkdf2_hmac('sha256', p.encode(), (u.strip().lower() + ':' + enc['salt']).encode(), enc['iter'], 32)
main = key(os.environ['HAPS_USER'], os.environ['HAPS_PW'])
AESGCM(main).decrypt(base64.b64decode(enc['iv']), base64.b64decode(enc['ct']), None)  # proves main password
nu, npw = os.environ['NEW_USER'], os.environ['NEW_PW']
iv = os.urandom(12)
w = base64.b64encode(iv).decode(), base64.b64encode(AESGCM(key(nu, npw)).encrypt(iv, main, None)).decode()
wraps = [x for x in enc.get('wraps', []) if x.get('u') != nu.strip().lower()]
wraps.append({'u': nu.strip().lower(), 'iv': w[0], 'wk': w[1]})
enc['wraps'] = wraps
json.dump(enc, open(dst, 'w'))
print('added sign-in for', nu, '- total extra sign-ins:', len(wraps))
