"""
main.py

Entrée principale pour l'application.
Il lance le frontend web sur le port 5000.
"""

import os
from backend import app

if __name__ == "__main__":
    print("\n" + "="*55)

    print("  Samba Portal")
    print(f"  Serveur : {os.getenv('SAMBA_SERVER','10.0.1.10')}")
    print(f"  Admin   : {os.getenv('SSH_USER','?')}@{os.getenv('SSH_HOST','?')}")
    print("  URL : http://localhost:5000")
    print("="*55 + "\n")
    app.run(host="0.0.0.0", port=5000, threaded=True,
        debug=os.getenv("FLASK_DEBUG", "False") == "True")
