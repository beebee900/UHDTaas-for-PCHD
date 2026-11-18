// Native unit tests of lib/atra_wire. The JSON fixtures in test/fixtures are also decoded by
// the Python edge decoder (tests/unit/edge/devices/test_firmware_payloads.py), so both sides
// agree on every byte.
#include <unity.h>

#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "atra_wire.h"

using namespace atra;

namespace {

constexpr int64_t kNoon = 1791633600000;  // 2026-10-10T12:00:00Z

std::string fixture(const char* name) {
    std::string here = __FILE__;
    std::string dir = here.substr(0, here.find_last_of('/'));
    std::ifstream in(dir + "/../fixtures/" + name);
    std::stringstream s;
    s << in.rdbuf();
    std::string text = s.str();
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r')) text.pop_back();
    return text;
}

std::string hex(const std::vector<uint8_t>& bytes) {
    std::string out;
    char b[3];
    for (uint8_t v : bytes) {
        std::snprintf(b, sizeof b, "%02x", v);
        out += b;
    }
    return out;
}

}  // namespace

void setUp() {}
void tearDown() {}

void test_iso8601() {
    TEST_ASSERT_EQUAL_STRING("1970-01-01T00:00:00.000+00:00", iso8601(0).c_str());
    TEST_ASSERT_EQUAL_STRING("2026-10-10T12:00:00.000+00:00", iso8601(kNoon).c_str());
    TEST_ASSERT_EQUAL_STRING("2024-02-29T23:59:59.999+00:00",
                             iso8601(1709251199999).c_str());
    TEST_ASSERT_EQUAL_STRING("1969-12-31T23:59:59.500+00:00", iso8601(-500).c_str());
}

void test_remaining_length_boundaries() {
    TEST_ASSERT_EQUAL_STRING("00", hex(remaining_length(0)).c_str());
    TEST_ASSERT_EQUAL_STRING("7f", hex(remaining_length(127)).c_str());
    TEST_ASSERT_EQUAL_STRING("8001", hex(remaining_length(128)).c_str());
    TEST_ASSERT_EQUAL_STRING("ff7f", hex(remaining_length(16383)).c_str());
    TEST_ASSERT_EQUAL_STRING("808001", hex(remaining_length(16384)).c_str());
    TEST_ASSERT_EQUAL_STRING("ffffff7f", hex(remaining_length(268435455u)).c_str());
    TEST_ASSERT_EQUAL(0, remaining_length(268435456u).size());
}

void test_publish_matches_the_edge_codec() {
    // Bytes from edge.devices.transport.mqtt.encode_publish for the same topic and payload.
    std::string topic = device_topic("hdt-0123456789ab", "esp-1", "environmental");
    TEST_ASSERT_EQUAL_STRING(
        "302c00286465762f6864742d3031323334353637383961622f6573702d312f656e7669726f6e6d656e74"
        "616c7b7d",
        hex(mqtt_publish(topic, "{}")).c_str());
    std::string head = hex(mqtt_publish("a/b", std::string(200, 'x'))).substr(0, 16);
    TEST_ASSERT_EQUAL_STRING("30cd010003612f62", head.c_str());
}

void test_connect_packet() {
    std::vector<uint8_t> p = mqtt_connect("esp-1", 60);
    TEST_ASSERT_EQUAL_STRING("101100044d5154540402003c00056573702d31", hex(p).c_str());
    std::vector<uint8_t> u = mqtt_connect("e", 30, "dev");
    TEST_ASSERT_EQUAL_HEX8(0x82, u[9]);
    TEST_ASSERT_EQUAL_STRING("0003646576", hex(std::vector<uint8_t>(u.end() - 5, u.end())).c_str());
}

void test_connack_and_ping() {
    const uint8_t ok[] = {0x20, 0x02, 0x00, 0x00};
    const uint8_t refused[] = {0x20, 0x02, 0x00, 0x05};
    const uint8_t other[] = {0x30, 0x02, 0x00, 0x00};
    TEST_ASSERT_EQUAL(0, mqtt_connack_code(ok, 4));
    TEST_ASSERT_EQUAL(5, mqtt_connack_code(refused, 4));
    TEST_ASSERT_EQUAL(-1, mqtt_connack_code(other, 4));
    TEST_ASSERT_EQUAL(-1, mqtt_connack_code(ok, 3));
    TEST_ASSERT_EQUAL_STRING("c000", hex(mqtt_pingreq()).c_str());
}

void test_ecg_payload_matches_fixture() {
    EcgFrame f{kNoon, 250, 1365, 2048, {2048, 2100, 3413, 1990}};
    TEST_ASSERT_EQUAL_STRING(fixture("ecg_patch.json").c_str(), ecg_payload(f).c_str());
}

void test_imu_payload_matches_fixture() {
    ImuFrame f{kNoon, 50, {}, {}};
    for (int i = 0; i < 2; ++i) {
        f.acc.push_back(mpu6050_accel(0, 0, 16384));
        f.gyro.push_back(mpu6050_gyro(131, -262, 0));
    }
    TEST_ASSERT_EQUAL_STRING(fixture("imu.json").c_str(), imu_payload(f).c_str());
}

void test_dht22_decode_and_payload() {
    const uint8_t frame[5] = {0x02, 0x8C, 0x80, 0x65, 0x73};
    Dht22Reading r = dht22_decode(frame);
    TEST_ASSERT_TRUE(r.ok);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, -10.1, r.temperature_c);
    TEST_ASSERT_DOUBLE_WITHIN(1e-9, 65.2, r.humidity_pct);
    TEST_ASSERT_EQUAL_STRING(fixture("environmental.json").c_str(),
                             dht22_payload(kNoon, r.temperature_c, r.humidity_pct).c_str());
    const uint8_t bad[5] = {0x02, 0x8C, 0x80, 0x65, 0x74};
    TEST_ASSERT_FALSE(dht22_decode(bad).ok);
}

void test_pulse_oximeter_payload_matches_fixture() {
    TEST_ASSERT_EQUAL_STRING(fixture("pulse_oximeter.json").c_str(),
                             pulse_oximeter_payload(kNoon, 97, 72).c_str());
}

void test_non_finite_numbers_are_null() {
    std::string p = pulse_oximeter_payload(kNoon, NAN, 72);
    TEST_ASSERT_NOT_EQUAL(std::string::npos, p.find("\"spo2_pct\":null"));
}

// A PPG of `bpm` beats per minute: infrared and red pulses over large DC levels, with the red
// AC/DC ratio `ratio` times the infrared one.
void run_ppg(PpgProcessor& p, double fs, double bpm, double seconds, double ratio, int* beats) {
    const double pi = 3.14159265358979;
    for (int i = 0; i < static_cast<int>(seconds * fs); ++i) {
        double t = i / fs;
        double phase = std::fmod(t * bpm / 60.0, 1.0);
        double pulse = std::exp(-std::pow((phase - 0.2) / 0.08, 2)) +
                       0.3 * std::exp(-std::pow((phase - 0.5) / 0.1, 2));
        double ir = 50000 + 500 * pulse + 20 * std::sin(2 * pi * 0.25 * t);
        double red = 30000 + 300 * ratio * pulse;
        if (p.add(red, ir)) ++*beats;
    }
}

void test_ppg_pulse_rate() {
    for (double bpm : {48.0, 72.0, 120.0, 150.0}) {
        PpgProcessor p(100);
        int beats = 0;
        run_ppg(p, 100, bpm, 20, 0.6, &beats);
        TEST_ASSERT_DOUBLE_WITHIN(2.0, bpm, p.pulse_rate());
        TEST_ASSERT_INT_WITHIN(2, static_cast<int>(bpm / 3), beats);
    }
}

void test_ppg_spo2_follows_ratio_of_ratios() {
    PpgProcessor high(100), low(100);
    int b = 0;
    run_ppg(high, 100, 72, 10, 0.5, &b);
    run_ppg(low, 100, 72, 10, 1.0, &b);
    TEST_ASSERT_TRUE(high.spo2() > low.spo2());
    TEST_ASSERT_DOUBLE_WITHIN(1.5, 110 - 25 * 0.5, high.spo2());
    high.reset_window();
    TEST_ASSERT_EQUAL_DOUBLE(0, high.spo2());
}

void test_ppg_flat_signal_has_no_beats() {
    PpgProcessor p(100);
    int beats = 0;
    for (int i = 0; i < 1000; ++i) beats += p.add(30000, 50000);
    TEST_ASSERT_EQUAL(0, beats);
    TEST_ASSERT_EQUAL_DOUBLE(0, p.pulse_rate());
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_iso8601);
    RUN_TEST(test_remaining_length_boundaries);
    RUN_TEST(test_publish_matches_the_edge_codec);
    RUN_TEST(test_connect_packet);
    RUN_TEST(test_connack_and_ping);
    RUN_TEST(test_ecg_payload_matches_fixture);
    RUN_TEST(test_imu_payload_matches_fixture);
    RUN_TEST(test_dht22_decode_and_payload);
    RUN_TEST(test_pulse_oximeter_payload_matches_fixture);
    RUN_TEST(test_non_finite_numbers_are_null);
    RUN_TEST(test_ppg_pulse_rate);
    RUN_TEST(test_ppg_spo2_follows_ratio_of_ratios);
    RUN_TEST(test_ppg_flat_signal_has_no_beats);
    return UNITY_END();
}
