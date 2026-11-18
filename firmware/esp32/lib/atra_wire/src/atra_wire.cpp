#include "atra_wire.h"

#include <cmath>
#include <cstdio>

namespace atra {

namespace {

// Days from 1970-01-01 to a civil date (H. Hinnant, "chrono-Compatible Low-Level Date
// Algorithms", civil_from_days).
void civil_from_days(int64_t z, int& y, unsigned& m, unsigned& d) {
    z += 719468;
    const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    const unsigned doe = static_cast<unsigned>(z - era * 146097);
    const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const unsigned mp = (5 * doy + 2) / 153;
    d = doy - (153 * mp + 2) / 5 + 1;
    m = mp < 10 ? mp + 3 : mp - 9;
    y = static_cast<int>(yoe + era * 400 + (m <= 2));
}

std::string number(double v) {
    if (!std::isfinite(v)) return "null";
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.6g", v);
    return buf;
}

std::string quoted(const std::string& s) {
    std::string out = "\"";
    for (char c : s) {
        if (c == '"' || c == '\\') out += '\\';
        out += c;
    }
    return out + "\"";
}

std::string vec3_list(const std::vector<Vec3>& v) {
    std::string out = "[";
    for (size_t i = 0; i < v.size(); ++i) {
        if (i) out += ",";
        out += "[" + number(v[i].x) + "," + number(v[i].y) + "," + number(v[i].z) + "]";
    }
    return out + "]";
}

void put_string(std::vector<uint8_t>& out, const std::string& s) {
    out.push_back(static_cast<uint8_t>(s.size() >> 8));
    out.push_back(static_cast<uint8_t>(s.size() & 0xFF));
    out.insert(out.end(), s.begin(), s.end());
}

std::vector<uint8_t> packet(uint8_t first, const std::vector<uint8_t>& body) {
    std::vector<uint8_t> out{first};
    std::vector<uint8_t> len = remaining_length(static_cast<uint32_t>(body.size()));
    if (len.empty()) return {};
    out.insert(out.end(), len.begin(), len.end());
    out.insert(out.end(), body.begin(), body.end());
    return out;
}

}  // namespace

std::string iso8601(int64_t unix_ms) {
    int64_t s = unix_ms >= 0 ? unix_ms / 1000 : (unix_ms - 999) / 1000;
    const int ms = static_cast<int>(unix_ms - s * 1000);
    int64_t days = s >= 0 ? s / 86400 : (s - 86399) / 86400;
    const int64_t sod = s - days * 86400;
    int y;
    unsigned m, d;
    civil_from_days(days, y, m, d);
    char buf[40];
    std::snprintf(buf, sizeof buf, "%04d-%02u-%02uT%02d:%02d:%02d.%03d+00:00", y, m, d,
                  static_cast<int>(sod / 3600), static_cast<int>(sod / 60 % 60),
                  static_cast<int>(sod % 60), ms);
    return buf;
}

std::vector<uint8_t> remaining_length(uint32_t n) {
    if (n > 268435455u) return {};
    std::vector<uint8_t> out;
    do {
        uint8_t byte = n % 128;
        n /= 128;
        if (n) byte |= 0x80;
        out.push_back(byte);
    } while (n);
    return out;
}

std::vector<uint8_t> mqtt_connect(const std::string& client_id, uint16_t keep_alive_s,
                                  const std::string& username) {
    std::vector<uint8_t> body;
    put_string(body, "MQTT");
    body.push_back(4);
    body.push_back(static_cast<uint8_t>(0x02 | (username.empty() ? 0 : 0x80)));
    body.push_back(static_cast<uint8_t>(keep_alive_s >> 8));
    body.push_back(static_cast<uint8_t>(keep_alive_s & 0xFF));
    put_string(body, client_id);
    if (!username.empty()) put_string(body, username);
    return packet(0x10, body);
}

std::vector<uint8_t> mqtt_publish(const std::string& topic, const std::string& payload,
                                  bool retain) {
    std::vector<uint8_t> body;
    put_string(body, topic);
    body.insert(body.end(), payload.begin(), payload.end());
    return packet(static_cast<uint8_t>(0x30 | (retain ? 1 : 0)), body);
}

std::vector<uint8_t> mqtt_pingreq() { return {0xC0, 0x00}; }

int mqtt_connack_code(const uint8_t* data, size_t len) {
    if (len != 4 || data[0] != 0x20 || data[1] != 0x02) return -1;
    return data[3];
}

std::string device_topic(const std::string& hdt_id, const std::string& device_id,
                         const std::string& device_class) {
    return "dev/" + hdt_id + "/" + device_id + "/" + device_class;
}

std::string ecg_payload(const EcgFrame& f) {
    std::string adc = "[";
    for (size_t i = 0; i < f.adc.size(); ++i) {
        if (i) adc += ",";
        adc += std::to_string(f.adc[i]);
    }
    adc += "]";
    return "{\"t0\":" + quoted(iso8601(f.t0_ms)) + ",\"fs\":" + number(f.fs) +
           ",\"gain\":" + number(f.gain) + ",\"baseline\":" + std::to_string(f.baseline) +
           ",\"units\":\"mV\",\"adc\":" + adc + "}";
}

std::string imu_payload(const ImuFrame& f) {
    return "{\"t0\":" + quoted(iso8601(f.t0_ms)) + ",\"fs\":" + number(f.fs) +
           ",\"acc\":" + vec3_list(f.acc) + ",\"gyro\":" + vec3_list(f.gyro) + "}";
}

std::string dht22_payload(int64_t time_ms, double temperature_c, double humidity_pct) {
    return "{\"time\":" + quoted(iso8601(time_ms)) + ",\"temperature_c\":" +
           number(temperature_c) + ",\"humidity_pct\":" + number(humidity_pct) + "}";
}

std::string pulse_oximeter_payload(int64_t time_ms, double spo2_pct, double pulse_rate) {
    return "{\"time\":" + quoted(iso8601(time_ms)) + ",\"spo2_pct\":" + number(spo2_pct) +
           ",\"pulse_rate\":" + number(pulse_rate) + "}";
}

Vec3 mpu6050_accel(int16_t x, int16_t y, int16_t z) {
    const double k = kGravity / 16384.0;
    return {x * k, y * k, z * k};
}

Vec3 mpu6050_gyro(int16_t x, int16_t y, int16_t z) {
    const double k = 1.0 / 131.0;
    return {x * k, y * k, z * k};
}

Dht22Reading dht22_decode(const uint8_t frame[5]) {
    const uint8_t sum = static_cast<uint8_t>(frame[0] + frame[1] + frame[2] + frame[3]);
    if (sum != frame[4]) return {false, NAN, NAN};
    const double humidity = ((frame[0] << 8) | frame[1]) / 10.0;
    const int raw_t = ((frame[2] & 0x7F) << 8) | frame[3];
    const double temperature = (frame[2] & 0x80 ? -raw_t : raw_t) / 10.0;
    return {true, temperature, humidity};
}

PpgProcessor::PpgProcessor(double fs) : fs_(fs) {}

bool PpgProcessor::add(double red, double ir) {
    if (n_ == 0) {
        dc_red_ = red;
        dc_ir_ = ir;
    }
    dc_red_ += kDcAlpha * (red - dc_red_);
    dc_ir_ += kDcAlpha * (ir - dc_ir_);
    const double ac_red = red - dc_red_;
    const double ac_ir = ir - dc_ir_;
    sq_red_ += ac_red * ac_red;
    sq_ir_ += ac_ir * ac_ir;
    sum_dc_red_ += dc_red_;
    sum_dc_ir_ += dc_ir_;
    ++window_n_;

    prev2_lp_ = prev_lp_;
    prev_lp_ = lp_;
    lp_ += kLowpassAlpha * (ac_ir - lp_);
    peak_ *= 1.0 - 1.0 / fs_;
    bool beat = false;
    const long candidate = n_ - 1;
    const bool is_max = prev_lp_ > prev2_lp_ && prev_lp_ >= lp_ && prev_lp_ > 0;
    if (is_max) {
        if (prev_lp_ > peak_) peak_ = prev_lp_;
        const bool tall = prev_lp_ >= kBeatFraction * peak_;
        const bool apart = last_beat_ < 0 || (candidate - last_beat_) >= kRefractoryS * fs_;
        if (tall && apart) {
            if (last_beat_ >= 0) {
                intervals_.push_back((candidate - last_beat_) / fs_);
                if (intervals_.size() > 8) intervals_.erase(intervals_.begin());
            }
            last_beat_ = candidate;
            beat = true;
        }
    }
    ++n_;
    return beat;
}

double PpgProcessor::pulse_rate() const {
    if (intervals_.empty()) return 0;
    double sum = 0;
    for (double v : intervals_) sum += v;
    return 60.0 * intervals_.size() / sum;
}

double PpgProcessor::spo2() const {
    if (window_n_ < 2 || sum_dc_red_ <= 0 || sum_dc_ir_ <= 0 || sq_ir_ <= 0) return 0;
    const double n = static_cast<double>(window_n_);
    const double r = (std::sqrt(sq_red_ / n) / (sum_dc_red_ / n)) /
                     (std::sqrt(sq_ir_ / n) / (sum_dc_ir_ / n));
    const double s = 110.0 - 25.0 * r;
    return s > 100.0 ? 100.0 : (s < 0 ? 0 : s);
}

void PpgProcessor::reset_window() {
    sq_red_ = sq_ir_ = sum_dc_red_ = sum_dc_ir_ = 0;
    window_n_ = 0;
}

}  // namespace atra
