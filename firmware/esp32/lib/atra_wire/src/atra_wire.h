// Hardware-independent framing, encoding and filtering of the ATRA ESP32 board
// (design 04, 4.1.3). Built for the board and for PlatformIO's `native` test environment.
//
// Payloads are the JSON shapes of edge/devices/decode/streams.py; times are ISO 8601 UTC with
// an explicit "+00:00" offset, as the edge decoder requires.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace atra {

// ---- Time ------------------------------------------------------------------

// "YYYY-MM-DDTHH:MM:SS.mmm+00:00" for milliseconds since the Unix epoch.
std::string iso8601(int64_t unix_ms);

// ---- MQTT 3.1.1 (OASIS standard, 29 October 2014) --------------------------

// Remaining Length, section 2.2.3: seven bits per byte, bit 7 continues. Empty when n is out of
// range.
std::vector<uint8_t> remaining_length(uint32_t n);

// CONNECT, section 3.1: protocol "MQTT", level 4, clean session, optional user name.
std::vector<uint8_t> mqtt_connect(const std::string& client_id, uint16_t keep_alive_s,
                                  const std::string& username = "");

// PUBLISH at QoS 0, section 3.3.
std::vector<uint8_t> mqtt_publish(const std::string& topic, const std::string& payload,
                                  bool retain = false);

std::vector<uint8_t> mqtt_pingreq();

// CONNACK, section 3.2: the return code, or -1 when the bytes are not a CONNACK.
int mqtt_connack_code(const uint8_t* data, size_t len);

// "dev/{hdt_id}/{device_id}/{device_class}"
std::string device_topic(const std::string& hdt_id, const std::string& device_id,
                         const std::string& device_class);

// ---- Stream payloads ---------------------------------------------------------

struct EcgFrame {
    int64_t t0_ms;
    double fs;
    double gain;       // ADC counts per millivolt at the electrodes
    int baseline;      // ADC count at 0 mV
    std::vector<int> adc;
};

struct Vec3 {
    double x, y, z;
};

struct ImuFrame {
    int64_t t0_ms;
    double fs;
    std::vector<Vec3> acc;   // m/s2
    std::vector<Vec3> gyro;  // deg/s
};

std::string ecg_payload(const EcgFrame& f);
std::string imu_payload(const ImuFrame& f);
std::string dht22_payload(int64_t time_ms, double temperature_c, double humidity_pct);
std::string pulse_oximeter_payload(int64_t time_ms, double spo2_pct, double pulse_rate);

// ---- Sensors ---------------------------------------------------------------

// MPU-6050 at its reset full-scale ranges: +-2 g (16384 LSB/g) and +-250 deg/s (131 LSB per
// deg/s).
constexpr double kGravity = 9.80665;
Vec3 mpu6050_accel(int16_t x, int16_t y, int16_t z);
Vec3 mpu6050_gyro(int16_t x, int16_t y, int16_t z);

// DHT22 40-bit frame: humidity (x10), temperature (x10, bit 15 = negative), checksum = low byte
// of the sum of the first four bytes.
struct Dht22Reading {
    bool ok;
    double temperature_c;
    double humidity_pct;
};
Dht22Reading dht22_decode(const uint8_t frame[5]);

// Photoplethysmogram processing for the MAX3010x red and infrared channels.
//
// Each channel is split into DC (exponential mean, `kDcAlpha`) and AC (signal minus DC). Beats
// are maxima of the low-passed infrared AC above `kBeatFraction` of the recent peak, at least
// `kRefractoryS` apart. SpO2 uses the ratio of ratios R = (ACrms_red/DC_red) /
// (ACrms_ir/DC_ir) with the linear approximation 110 - 25 R; it is uncalibrated, so readings
// are a device estimate until a calibration table for the sensor is applied.
class PpgProcessor {
public:
    static constexpr double kDcAlpha = 0.02;
    static constexpr double kLowpassAlpha = 0.3;
    static constexpr double kBeatFraction = 0.5;
    static constexpr double kRefractoryS = 0.3;

    explicit PpgProcessor(double fs);

    // Adds one sample; returns true when it completes a beat.
    bool add(double red, double ir);

    // Beats per minute from the mean of the last beat intervals; 0 before two beats.
    double pulse_rate() const;

    // SpO2 percent over the samples since the last `reset_window`; 0 when undefined.
    double spo2() const;

    void reset_window();

private:
    double fs_;
    double dc_red_ = 0, dc_ir_ = 0, lp_ = 0, prev_lp_ = 0, prev2_lp_ = 0, peak_ = 0;
    double sq_red_ = 0, sq_ir_ = 0, sum_dc_red_ = 0, sum_dc_ir_ = 0;
    long n_ = 0, window_n_ = 0, last_beat_ = -1;
    std::vector<double> intervals_;
};

}  // namespace atra
