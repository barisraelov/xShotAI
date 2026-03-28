"""
Serve the xShot AI prototype at http://localhost:8080

Run from this directory:
    python serve.py

Then open http://localhost:8080 in the browser.
The backend must also be running:
    cd ../backend && uvicorn main:app --reload --port 8000
"""
import http.server
import os
import webbrowser

PORT = 8080

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print(f"  xShot AI prototype  →  http://localhost:{PORT}")
print("  Press Ctrl+C to stop.\n")

try:
    webbrowser.open(f"http://localhost:{PORT}")
except Exception:
    pass

with http.server.HTTPServer(("", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
    httpd.serve_forever()
