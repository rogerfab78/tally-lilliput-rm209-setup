import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import threading
import time
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

# Config bandeaux : IP par bandeau
BANDEAUX = {
    1: "192.168.1.109",  # Bandeau 1
    2: "192.168.1.110",  # Bandeau 2
    3: "192.168.1.111"   # Bandeau 3
}

UDP_PORT_DEST = 19523    # Port destination des écrans
UDP_PORT_SOURCE = 19522  # Port source
POLL_INTERVAL = 2.0      # Intervalle de polling en secondes

# États valides
VALID_STATES = {'off', 'rouge', 'vert', 'jaune'}
STATE_BYTES = {
    'off': 0x07,
    'rouge': 0x17,
    'vert': 0x27,
    'jaune': 0x37
}

# Sockets UDP par bandeau (un socket par IP)
udp_sockets = {}
for band, ip in BANDEAUX.items():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', UDP_PORT_SOURCE))
        udp_sockets[band] = sock
        logging.info(f"Socket UDP bandeau {band} créé pour {ip}:{UDP_PORT_DEST} (source port {UDP_PORT_SOURCE})")
    except Exception as e:
        logging.error(f"Erreur création socket bandeau {band}: {e}")
        raise

# États courants par bandeau/écran (défaut 'off' ; 2 écrans par bandeau)
current_states = {band: {1: 'off', 2: 'off'} for band in BANDEAUX}
state_lock = threading.Lock()  # Protection contre les accès concurrents


def build_payload(screen_id, state):
    """
    Construit le payload UDP de 28 bytes selon le protocole Lilliput.
    """
    if screen_id not in [1, 2]:
        raise ValueError(f"screen_id invalide: {screen_id}")
    if state not in STATE_BYTES:
        raise ValueError(f"État invalide: {state}")
    
    # Header (9 bytes) : 5A 1C 00 20 0[screen_id] FF 00 [7A si id=1, 00 si id=2] 05
    header = bytes([
        0x5A, 0x1C, 0x00, 0x20,
        0x00 + screen_id,  # 0x01 ou 0x02
        0xFF, 0x00,
        0x7A if screen_id == 1 else 0x00,
        0x05
    ])
    
    # Body (19 bytes) : [state_byte] + 16*0x00 + [checksum] + 0xDD
    state_byte = STATE_BYTES[state]
    zeros = bytes(16)  # 16 octets à zéro
    
    # Checksum (pattern sniffé Wireshark)
    checksum_offset = 0x15 if screen_id == 1 else 0x9C
    checksum = (state_byte + checksum_offset) & 0xFF
    
    body = bytes([state_byte]) + zeros + bytes([checksum, 0xDD])
    
    payload = header + body
    
    if len(payload) != 28:
        raise ValueError(f"Payload invalide: {len(payload)} bytes au lieu de 28")
    
    return payload


def send_tally_udp(band, screen_id, state):
    """
    Envoie un paquet UDP tally vers un bandeau/écran spécifique.
    """
    if band not in BANDEAUX:
        logging.error(f"Bandeau {band} non configuré")
        return False
    
    try:
        sock = udp_sockets[band]
        ip = BANDEAUX[band]
        payload = build_payload(screen_id, state)
        
        sock.sendto(payload, (ip, UDP_PORT_DEST))
        logging.debug(f"UDP → bandeau {band} écran {screen_id} : {state} ({ip}:{UDP_PORT_DEST})")
        return True
    except Exception as e:
        logging.error(f"Erreur envoi UDP bandeau {band} écran {screen_id}: {e}")
        return False


def poller():
    """
    Thread de polling : maintient l'état actif toutes les POLL_INTERVAL secondes.
    Ne réémet que les états non-'off' pour éviter le timeout des écrans.
    """
    logging.info(f"Poller démarré (intervalle: {POLL_INTERVAL}s)")
    
    while True:
        try:
            with state_lock:
                states_snapshot = {
                    band: screens.copy() 
                    for band, screens in current_states.items()
                }
            
            for band, screens in states_snapshot.items():
                for screen_id, state in screens.items():
                    if state != 'off':
                        send_tally_udp(band, screen_id, state)
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            logging.error(f"Erreur dans le poller: {e}")
            time.sleep(1)  # Évite une boucle rapide en cas d'erreur


# Lancement du poller en arrière-plan
poller_thread = threading.Thread(target=poller, daemon=True, name="TallyPoller")
poller_thread.start()


class TallyHandler(BaseHTTPRequestHandler):
    """
    Gère les requêtes HTTP GET pour contrôler les écrans tally.
    Format: /?state=rouge&band=1&id=2
    """
    
    def log_message(self, format, *args):
        """Override pour utiliser notre logging"""
        pass  # Désactivé car on log manuellement
    
    def do_GET(self):
        # Ignore les requêtes favicon
        if '/favicon' in self.path:
            self.send_response(204)
            self.end_headers()
            return
        
        try:
            # Parse des paramètres
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            
            state = params.get('state', ['off'])[0].lower()
            screen_id = int(params.get('id', ['1'])[0])
            band = int(params.get('band', ['1'])[0])
            
            # Validations
            if state not in VALID_STATES:
                logging.warning(f"État invalide: {state}")
                self.send_error(400, f"État invalide. Valeurs: {', '.join(VALID_STATES)}")
                return
            
            if screen_id not in [1, 2]:
                logging.warning(f"ID écran invalide: {screen_id}")
                self.send_error(400, "ID écran invalide. Valeurs: 1 ou 2")
                return
            
            if band not in BANDEAUX:
                logging.warning(f"Bandeau invalide: {band}")
                self.send_error(400, f"Bandeau invalide. Valeurs: {', '.join(map(str, BANDEAUX.keys()))}")
                return
            
            # Mise à jour de l'état (thread-safe)
            with state_lock:
                old_state = current_states[band][screen_id]
                current_states[band][screen_id] = state
            
            logging.info(f"Bandeau {band} écran {screen_id}: {old_state} → {state}")
            
            # Envoi immédiat pour réactivité
            success = send_tally_udp(band, screen_id, state)
            
            if success:
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                response = f"OK - Bandeau {band} écran {screen_id} : {state}\n"
                self.wfile.write(response.encode('utf-8'))
            else:
                self.send_error(500, "Erreur envoi UDP")
        
        except ValueError as e:
            logging.error(f"Erreur de paramètres: {e}")
            self.send_error(400, str(e))
        except Exception as e:
            logging.error(f"Erreur inattendue: {e}")
            self.send_error(500, "Erreur serveur")


def main():
    """Point d'entrée principal"""
    HOST = 'localhost'
    PORT = 8080
    
    server = HTTPServer((HOST, PORT), TallyHandler)
    
    logging.info("=" * 60)
    logging.info("PONT TALLY LILLIPUT RM209 - Multi-Bandeaux")
    logging.info("=" * 60)
    logging.info(f"Serveur HTTP: http://{HOST}:{PORT}")
    logging.info(f"Format requête: /?state=rouge&band=1&id=2")
    logging.info(f"États: {', '.join(VALID_STATES)}")
    logging.info(f"Bandeaux configurés: {len(BANDEAUX)}")
    for band, ip in BANDEAUX.items():
        logging.info(f"  - Bandeau {band}: {ip}:{UDP_PORT_DEST}")
    logging.info("Appuyez sur Ctrl+C pour arrêter")
    logging.info("=" * 60)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("\nArrêt du serveur... Envoi OFF à tous les tally...")
        # Envoi OFF à tous les bandeaux/écrans avant shutdown
        for band in BANDEAUX:
            for screen_id in [1, 2]:
                success = send_tally_udp(band, screen_id, 'off')
                if success:
                    logging.info(f"OFF envoyé à bandeau {band} écran {screen_id}")
                else:
                    logging.warning(f"Échec OFF bandeau {band} écran {screen_id}")
        
        # Fermeture sockets
        for band, sock in udp_sockets.items():
            sock.close()
            logging.info(f"Socket bandeau {band} fermé")
        logging.info("Pont arrêté proprement.")


if __name__ == '__main__':
    main()