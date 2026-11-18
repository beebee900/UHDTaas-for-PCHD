// Board identity and stream settings. Override with -D build flags per board.
#pragma once

#ifndef ATRA_HDT_ID
#define ATRA_HDT_ID "hdt-000000000000"
#endif
#ifndef ATRA_DEVICE_ID
#define ATRA_DEVICE_ID "esp32-board-1"
#endif
#ifndef ATRA_MQTT_HOST
#define ATRA_MQTT_HOST "edge.local"
#endif
#ifndef ATRA_MQTT_PORT
#define ATRA_MQTT_PORT 8883
#endif

// AD8232 output on GPIO34 (ADC1 channel 6), sampled at 250 Hz and sent once per second.
#define ECG_PIN 34
#define ECG_FS_HZ 250
// ADC counts per millivolt at the electrodes: 4095 counts over about 3.3 V at 11 dB
// attenuation, times the AD8232 front-end gain of the board (1100). Calibrate per board.
#define ECG_GAIN_COUNTS_PER_MV 1365.0
#define ECG_BASELINE_COUNTS 2048

#define I2C_SDA 21
#define I2C_SCL 22
#define IMU_FS_HZ 50
#define PPG_FS_HZ 100
#define PPG_REPORT_S 5
#define DHT22_PIN 4
#define DHT22_REPORT_S 30
