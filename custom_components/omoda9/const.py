"""Costanti del custom component Omoda 9 / Jaecoo."""

DOMAIN = "omoda9"
PLATFORMS = ["sensor", "binary_sensor", "button", "device_tracker", "text"]

# Chiavi del config_entry (dati per-account, inseriti nel config flow)
CONF_EMAIL = "email"
CONF_PIN = "pin"
CONF_VIN = "vin"
CONF_TUSERID = "tuserid"

# Parametri di REGIONE (default = Europa). Esposti come options per supportare altre regioni.
CONF_BFF = "bff"
CONF_TSP_HOST = "tsp_host"
CONF_CAR_MQTT_HOST = "car_mqtt_host"
CONF_CAR_MQTT_PORT = "car_mqtt_port"
CONF_CHANNEL_ID = "channel_id"

# Provisioning certificati mutual-TLS MQTT (FASE 3c). Cartella (dentro il filesystem di HA)
# da cui importare i 4 cert nella certs_dir per-entry. Vuoto = i cert si mettono a mano.
CONF_CERTS_SRC = "certs_src"

# I 4 file mutual-TLS attesi nella certs_dir per-entry (= quelli del bridge certs_eu/).
CERT_FILES = ("ca.pem", "client.pem", "client.key", "eu_prd_cheryinternational.cer")

DEFAULTS = {
    CONF_BFF: "https://legend-oj.omodaauto.nl/api",
    CONF_TSP_HOST: "https://tspconsole-eu.cheryinternational.com",
    CONF_CAR_MQTT_HOST: "tspemqx-app-eu.cheryinternational.com",
    CONF_CAR_MQTT_PORT: 8083,
    CONF_CHANNEL_ID: "1",
}

# Costante app condivisa (non un segreto utente): seed per derivare la password MQTT
CAR_SEED = "fa89db3abe8045919d70c6ed3cc65bc5"

# Intervalli (secondi)
DEFAULT_SESSION_EVERY = 900
DEFAULT_AWAKE_WINDOW = 300
