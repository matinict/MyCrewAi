# get_tiktok_token.py
import os
import webbrowser
import http.server
import socketserver
import urllib.parse
import requests
import secrets
import hashlib
import base64
from dotenv import load_dotenv, set_key

# --- CONFIGURATION ---
# ⚠️ REPLACE THESE WITH YOUR ACTUAL KEYS FROM TIKTOK DEVELOPER PORTAL
CLIENT_KEY = "YOUR_CLIENT_KEY_HERE" 
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"
REDIRECT_URI = "http://localhost:8080/callback"
SCOPE = "user.info.basic,video.upload,video.publish"

def generate_pkce_pair():
    """Generates a code_verifier and code_challenge for PKCE"""
    # 1. Generate a random code_verifier (32-128 chars)
    code_verifier = secrets.token_urlsafe(32)
    
    # 2. Create code_challenge = SHA256(code_verifier) then Base64URL encode
    sha256_hash = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_hash).rstrip(b'=').decode('utf-8')
    
    return code_verifier, code_challenge

def get_auth_code(code_challenge):
    """Opens browser to get authorization code"""
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&state=random_state_string"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(SCOPE)}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    print(f"🌐 Opening browser to: {auth_url}")
    webbrowser.open(auth_url)
    
    received_code = None
    
    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/callback'):
                query_components = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                code = query_components.get("code", [None])[0]
                error = query_components.get("error", [None])[0]
                
                if code:
                    self.send_response(200)
                    self.end_headers()
                    # ✅ FIX: Removed emoji from byte string
                    self.wfile.write(b"<h1>Success! You can close this window.</h1>")
                    global received_code
                    received_code = code
                    return
                elif error:
                    self.send_response(400)
                    self.end_headers()
                    # ✅ FIX: Removed emoji from byte string
                    msg = f"<h1>Error: {error}</h1>".encode