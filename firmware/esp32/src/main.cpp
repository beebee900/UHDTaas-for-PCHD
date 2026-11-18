// ATRA ESP32 sensor board (design 04, 4.1.3): AD8232 ECG, MPU-6050 IMU, MAX30102 pulse
// oximeter and DHT22, published as the streams.py JSON shapes on dev/{hdt_id}/{device_id}/
// {class} over MQTT/TLS with the board's client certificate.
//
// Framing, payloads and filtering are in lib/atra_wire, which the native tests cover. This file
// holds the hardware access only. Register addresses follow the MPU-6050 register map and the
// MAX30102 data sheet; they are checked on the bench with the boards (person action P8).
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <sys/time.h>

#include "atra_wire.h"
#include "config.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

namespace {

constexpr uint8_t kMpuAddr = 0x68;
constexpr uint8_t kMpuPwrMgmt1 = 0x6B;
constexpr uint8_t kMpuAccelXoutH = 0x3B;

constexpr uint8_t kMaxAddr = 0x57;
constexpr uint8_t kMaxFifoWrPtr = 0x04;
constexpr uint8_t kMaxOvfCounter = 0x05;
constexpr uint8_t kMaxFifoRdPtr = 0x06;
constexpr uint8_t kMaxFifoData = 0x07;
constexpr uint8_t kMaxFifoConfig = 0x08;
constexpr uint8_t kMaxModeConfig = 0x09;
constexpr uint8_t kMaxSpo2Config = 0x0A;
constexpr uint8_t kMaxLed1Pa = 0x0C;
constexpr uint8_t kMaxLed2Pa = 0x0D;

constexpr uint16_t kKeepAliveS = 60;

WiFiClientSecure net;
TaskHandle_t ecg_task = nullptr;
hw_timer_t* ecg_timer = nullptr;
portMUX_TYPE ecg_mux = portMUX_INITIALIZER_UNLOCKED;
// Double buffer: the sampler fills one half while loop() sends the other.
int ecg_buf[2][ECG_FS_HZ];
int ecg_fill = 0, ecg_n = 0, ecg_ready = -1;
int64_t ecg_t0[2] = {0, 0};

atra::PpgProcessor ppg(PPG_FS_HZ);
atra::ImuFrame imu{0, IMU_FS_HZ, {}, {}};
uint32_t last_imu_us = 0, last_ppg_report = 0, last_dht = 0, last_ping = 0;

int64_t now_ms() {
    timeval tv;
    gettimeofday(&tv, nullptr);
    return static_cast<int64_t>(tv.tv_sec) * 1000 + tv.tv_usec / 1000;
}

void write_reg(uint8_t addr, uint8_t reg, uint8_t value) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

size_t read_regs(uint8_t addr, uint8_t reg, uint8_t* out, size_t n) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return 0;
    size_t got = Wire.requestFrom(addr, static_cast<uint8_t>(n));
    for (size_t i = 0; i < got; ++i) out[i] = Wire.read();
    return got;
}

bool mqtt_send(const std::vector<uint8_t>& packet) {
    return !packet.empty() && net.write(packet.data(), packet.size()) == packet.size();
}

bool mqtt_connect() {
    net.setCACert(MQTT_CA_PEM);
    net.setCertificate(MQTT_CLIENT_CERT_PEM);
    net.setPrivateKey(MQTT_CLIENT_KEY_PEM);
    if (!net.connect(ATRA_MQTT_HOST, ATRA_MQTT_PORT)) return false;
    if (!mqtt_send(atra::mqtt_connect(ATRA_DEVICE_ID, kKeepAliveS))) return false;
    uint8_t ack[4];
    uint32_t start = millis();
    size_t got = 0;
    while (got < sizeof ack && millis() - start < 5000) {
        if (net.available()) ack[got++] = net.read();
    }
    return atra::mqtt_connack_code(ack, got) == 0;
}

void publish(const char* device_class, const std::string& payload) {
    if (!net.connected() && !mqtt_connect()) return;
    mqtt_send(atra::mqtt_publish(atra::device_topic(ATRA_HDT_ID, ATRA_DEVICE_ID, device_class),
                                 payload));
}

void IRAM_ATTR on_ecg_timer() {
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(ecg_task, &woken);
    if (woken) portYIELD_FROM_ISR();
}

void ecg_sampler(void*) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        int v = analogRead(ECG_PIN);
        if (ecg_n == 0) ecg_t0[ecg_fill] = now_ms();
        ecg_buf[ecg_fill][ecg_n++] = v;
        if (ecg_n == ECG_FS_HZ) {
            portENTER_CRITICAL(&ecg_mux);
            ecg_ready = ecg_fill;
            portEXIT_CRITICAL(&ecg_mux);
            ecg_fill ^= 1;
            ecg_n = 0;
        }
    }
}

void setup_sensors() {
    Wire.begin(I2C_SDA, I2C_SCL, 400000);
    write_reg(kMpuAddr, kMpuPwrMgmt1, 0x00);
    write_reg(kMaxAddr, kMaxModeConfig, 0x40);
    delay(10);
    write_reg(kMaxAddr, kMaxFifoConfig, 0x10);
    write_reg(kMaxAddr, kMaxSpo2Config, 0x27);
    write_reg(kMaxAddr, kMaxLed1Pa, 0x24);
    write_reg(kMaxAddr, kMaxLed2Pa, 0x24);
    write_reg(kMaxAddr, kMaxFifoWrPtr, 0);
    write_reg(kMaxAddr, kMaxOvfCounter, 0);
    write_reg(kMaxAddr, kMaxFifoRdPtr, 0);
    write_reg(kMaxAddr, kMaxModeConfig, 0x03);

    analogReadResolution(12);
    analogSetPinAttenuation(ECG_PIN, ADC_11db);
    xTaskCreatePinnedToCore(ecg_sampler, "ecg", 4096, nullptr, configMAX_PRIORITIES - 1,
                            &ecg_task, 1);
    ecg_timer = timerBegin(0, 80, true);
    timerAttachInterrupt(ecg_timer, &on_ecg_timer, true);
    timerAlarmWrite(ecg_timer, 1000000 / ECG_FS_HZ, true);
    timerAlarmEnable(ecg_timer);
}

int16_t be16(const uint8_t* r, int i) { return static_cast<int16_t>((r[i] << 8) | r[i + 1]); }

void poll_imu() {
    uint32_t now = micros();
    if (now - last_imu_us < 1000000 / IMU_FS_HZ) return;
    last_imu_us = now;
    uint8_t r[14];
    if (read_regs(kMpuAddr, kMpuAccelXoutH, r, sizeof r) != sizeof r) return;
    if (imu.acc.empty()) imu.t0_ms = now_ms();
    imu.acc.push_back(atra::mpu6050_accel(be16(r, 0), be16(r, 2), be16(r, 4)));
    imu.gyro.push_back(atra::mpu6050_gyro(be16(r, 8), be16(r, 10), be16(r, 12)));
    if (imu.acc.size() >= IMU_FS_HZ) {
        publish("imu", atra::imu_payload(imu));
        imu.acc.clear();
        imu.gyro.clear();
    }
}

void poll_ppg() {
    uint8_t wr = 0, rd = 0;
    read_regs(kMaxAddr, kMaxFifoWrPtr, &wr, 1);
    read_regs(kMaxAddr, kMaxFifoRdPtr, &rd, 1);
    int samples = (wr - rd) & 0x1F;
    for (int i = 0; i < samples; ++i) {
        uint8_t d[6];
        if (read_regs(kMaxAddr, kMaxFifoData, d, sizeof d) != sizeof d) return;
        uint32_t red = ((d[0] << 16) | (d[1] << 8) | d[2]) & 0x3FFFF;
        uint32_t ir = ((d[3] << 16) | (d[4] << 8) | d[5]) & 0x3FFFF;
        ppg.add(red, ir);
    }
    if (millis() - last_ppg_report >= PPG_REPORT_S * 1000u) {
        last_ppg_report = millis();
        if (ppg.pulse_rate() > 0) {
            publish("pulse_oximeter",
                    atra::pulse_oximeter_payload(now_ms(), ppg.spo2(), ppg.pulse_rate()));
        }
        ppg.reset_window();
    }
}

// DHT22 single-wire read: 1.1 ms start pulse, the sensor's 80 us low and high reply, then 40
// bits whose high time is about 27 us for 0 and 70 us for 1.
bool read_dht22(uint8_t frame[5]) {
    pinMode(DHT22_PIN, OUTPUT);
    digitalWrite(DHT22_PIN, LOW);
    delayMicroseconds(1100);
    pinMode(DHT22_PIN, INPUT_PULLUP);
    auto wait_level = [](int level, uint32_t timeout_us) {
        uint32_t start = micros();
        while (digitalRead(DHT22_PIN) != level) {
            if (micros() - start > timeout_us) return false;
        }
        return true;
    };
    noInterrupts();
    bool ok = wait_level(LOW, 100) && wait_level(HIGH, 100) && wait_level(LOW, 100);
    for (int i = 0; ok && i < 40; ++i) {
        ok = wait_level(HIGH, 80);
        uint32_t rise = micros();
        ok = ok && wait_level(LOW, 100);
        uint32_t high = micros() - rise;
        frame[i / 8] = static_cast<uint8_t>((frame[i / 8] << 1) | (high > 48 ? 1 : 0));
    }
    interrupts();
    return ok;
}

void poll_dht22() {
    if (millis() - last_dht < DHT22_REPORT_S * 1000u) return;
    last_dht = millis();
    uint8_t frame[5] = {0, 0, 0, 0, 0};
    if (!read_dht22(frame)) return;
    atra::Dht22Reading r = atra::dht22_decode(frame);
    if (r.ok) {
        publish("environmental",
                atra::dht22_payload(now_ms(), r.temperature_c, r.humidity_pct));
    }
}

void poll_ecg() {
    portENTER_CRITICAL(&ecg_mux);
    int half = ecg_ready;
    ecg_ready = -1;
    portEXIT_CRITICAL(&ecg_mux);
    if (half < 0) return;
    atra::EcgFrame f{ecg_t0[half], ECG_FS_HZ, ECG_GAIN_COUNTS_PER_MV, ECG_BASELINE_COUNTS,
                     std::vector<int>(ecg_buf[half], ecg_buf[half] + ECG_FS_HZ)};
    publish("ecg_patch", atra::ecg_payload(f));
}

}  // namespace

void setup() {
    Serial.begin(115200);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) delay(250);
    configTime(0, 0, "pool.ntp.org");
    while (now_ms() < 1700000000000LL) delay(100);
    setup_sensors();
    mqtt_connect();
}

void loop() {
    poll_ecg();
    poll_imu();
    poll_ppg();
    poll_dht22();
    if (millis() - last_ping >= kKeepAliveS * 500u) {
        last_ping = millis();
        if (net.connected()) mqtt_send(atra::mqtt_pingreq());
    }
    while (net.available()) net.read();
}
