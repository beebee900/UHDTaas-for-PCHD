"""Device wire formats: Bluetooth GATT characteristics, IEEE 11073-20601 APDUs, the MQTT
JSON device payloads (`streams`), environmental CoAP and LoRaWAN payloads (`environment`),
WFDB records, phone media and app-use logs, and self-report forms.

Every format has an encoder and a decoder. The simulators in `edge/devices/sim` use the encoders,
and the edge service uses the decoders and `observations` to build ingestion payloads.
"""
