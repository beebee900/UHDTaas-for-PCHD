"""Device simulators for every class of design 04, 4.1.1, driven by a `TruthStream`.

| Device class | Simulator | Wire format |
|---|---|---|
| smartwatch | `ble.Smartwatch` | GATT 0x2A37 with RR intervals |
| ecg_patch | `mqtt.EcgPatch` | MQTT JSON, 250 Hz ADC samples |
| bp_cuff | `ble.BpCuff`, `phd.bp_cuff` | GATT 0x2A35; 11073-20601 config 0x02BC |
| glucometer | `ble.Glucometer`, `phd.glucometer` | GATT 0x2A18; 11073-20601 config 0x06A4 |
| cgm | `cloud.DexcomCloud` | Dexcom API v3 EGV JSON |
| pulse_oximeter | `ble.PulseOximeter` | GATT 0x2A5F |
| spirometer | `phd.spirometer` | 11073-20601 extended config 0x4001 |
| smart_scale | `ble.Scale`, `phd.scale` | GATT 0x2A9D; 11073-20601 extended config 0x4000 |
| thermometer | `ble.Thermometer` | GATT 0x2A1C |
| insulin_pump | `mqtt.InsulinPump` | MQTT JSON |
| lab_analyser | `clinical.LabAnalyser` | HL7 v2.5 ORU^R01 |
| ecg_machine | `clinical.EcgMachine` | WFDB header + format 16 |
| imaging | `clinical.ImagingModality` | DICOM Part 10 in a STOW-RS multipart body |
| genomics | `clinical.Sequencer` | VCF 4.2 |
| imu | `mqtt.Imu` | MQTT JSON, 50 Hz |
| pressure_insoles | `mqtt.Insoles` | MQTT JSON, 100 Hz, 8 sensors per foot |
| phone sensors | `mqtt.PhoneSensors` | MQTT JSON accelerometer + GPS |
| phone microphone | `phone.Microphone` | 16-bit PCM WAV |
| phone camera | `phone.Camera` | PNG |
| phone video | `phone.Video` | recorded walking clip, or the pose track of one |
| screen and app use | `phone.UsageLog` | Android UsageStats JSON |
| self-report | `phone.SelfReport` | FHIR QuestionnaireResponse; ODK XForm instance |
| environmental, NB-IoT | `environment.CoapAirSensor` | CoAP POST, application/json |
| environmental, LoRaWAN | `environment.LoraAirSensor` | ChirpStack v4 uplink JSON over MQTT |
| environmental, DHT22 | `mqtt.Dht22` | MQTT JSON |
| records | `clinical.RecordsExport` | FHIR R4 Bundle (OpenMRS export) |
"""

from edge.devices.sim.base import Simulator, TruthStream, seed_of

__all__ = ["Simulator", "TruthStream", "seed_of"]
