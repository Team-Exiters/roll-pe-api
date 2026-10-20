"""Common browser OAuth primitives."""

import base64
import hashlib


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def no_store(response):
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


