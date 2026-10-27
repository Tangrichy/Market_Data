// pybind11 wrapper for Guotai Junan UDP Market Data API (V3.7.x)
// Target: Python 3.9 + pybind11

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <dirent.h>
#include <memory>
#include <mutex>
#include <string.h>
#include <string>
#include <thread>
#include <vector>
#include <functional>
#include <sys/syscall.h>
#include <unistd.h>

#include "GtjaMdUserApi.h"

namespace py = pybind11;
using namespace GtjaMdV3;

// ---------------------------------------------------------------------------
// Helper: copy fixed-length char array to std::string (stops at '\0')
// ---------------------------------------------------------------------------
static std::string char_to_str(const char* s, size_t n) {
    if (!s) return "";
    size_t len = strnlen(s, n);
    return std::string(s, len);
}

// ---------------------------------------------------------------------------
// Python-facing SPI: stores std::function callbacks set from Python
// ---------------------------------------------------------------------------
class PySpi : public GtjaMdUserSpi {
public:
    std::function<void(int)> on_front_connected;
    std::function<void(int, int)> on_front_disconnected;
    std::function<void(const GtjaMdRspInfoField*, int, bool, int)> on_rsp_error;
    std::function<void(const GtjaMdRspUserLoginField*, const GtjaMdRspInfoField*, int, bool, int)> on_rsp_user_login;
    std::function<void(const GtjaMdInstrumentFieldV3*, const TGtjaDateTime*, const GtjaMdTradeInfoFieldV3*,
                       const GtjaMdBaseInfoFieldV3*, const GtjaMdStaticInfoFieldV3*, int,
                       const std::vector<GtjaMdMBLFieldV3>&, const GtjaMdInstrumentStatusV3*, int)> on_rtn_depth_snapshot;
    std::function<void(const GtjaDepthMarketDataField*, int)> on_rsp_last_snapshot;
    std::function<void(const GtjaMdSpecificInstrumentField*, const GtjaMdRspInfoField*, int, int)> on_rsp_sub_market_data;
    std::function<void(const GtjaMdSpecificInstrumentField*, const GtjaMdRspInfoField*, int, int)> on_rsp_unsub_market_data;

    void GTJAMDAPI OnFrontConnected(int nConnectID) override {
        if (on_front_connected) on_front_connected(nConnectID);
    }
    void GTJAMDAPI OnFrontDisconnected(int nReason, int nConnectID) override {
        if (on_front_disconnected) on_front_disconnected(nReason, nConnectID);
    }
    void GTJAMDAPI OnRspError(const GtjaMdRspInfoField* pRspInfo, int nRequestID, bool bIsLast, int nConnectID) override {
        if (on_rsp_error) on_rsp_error(pRspInfo, nRequestID, bIsLast, nConnectID);
    }
    void GTJAMDAPI OnRspUserLogin(const GtjaMdRspUserLoginField* pRspUserLogin, const GtjaMdRspInfoField* pRspInfo,
                                  int nRequestID, bool bIsLast, int nConnectID) override {
        if (on_rsp_user_login) on_rsp_user_login(pRspUserLogin, pRspInfo, nRequestID, bIsLast, nConnectID);
    }
    void GTJAMDAPI OnRtnDepthSnapshot(const GtjaMdInstrumentFieldV3* pInstrument, const TGtjaDateTime* pStamp,
                                      const GtjaMdTradeInfoFieldV3* pTradeInfo, const GtjaMdBaseInfoFieldV3* pBaseInfo,
                                      const GtjaMdStaticInfoFieldV3* pStaticInfo, int MBLLength,
                                      const GtjaMdMBLFieldV3* pMBL, const GtjaMdInstrumentStatusV3* pInstrumentStatus,
                                      int nConnectID) override {
        std::vector<GtjaMdMBLFieldV3> mbl_vec;
        if (pMBL && MBLLength > 0) {
            mbl_vec.assign(pMBL, pMBL + MBLLength);
        }
        if (on_rtn_depth_snapshot) on_rtn_depth_snapshot(pInstrument, pStamp, pTradeInfo, pBaseInfo, pStaticInfo,
                                                          MBLLength, mbl_vec, pInstrumentStatus, nConnectID);
    }
    void GTJAMDAPI OnRspLastSnapshot(const GtjaDepthMarketDataField* pDepthMarketData, int nConnectID) override {
        if (on_rsp_last_snapshot) on_rsp_last_snapshot(pDepthMarketData, nConnectID);
    }
    void GTJAMDAPI OnRspSubMarketData(const GtjaMdSpecificInstrumentField* pInstrument, const GtjaMdRspInfoField* pRspInfo,
                                      int nRequestID, int nConnectID) override {
        if (on_rsp_sub_market_data) on_rsp_sub_market_data(pInstrument, pRspInfo, nRequestID, nConnectID);
    }
    void GTJAMDAPI OnRspUnSubMarketData(const GtjaMdSpecificInstrumentField* pInstrument, const GtjaMdRspInfoField* pRspInfo,
                                        int nRequestID, int nConnectID) override {
        if (on_rsp_unsub_market_data) on_rsp_unsub_market_data(pInstrument, pRspInfo, nRequestID, nConnectID);
    }
};

// ---------------------------------------------------------------------------
// Binding helpers for fixed char arrays
// ---------------------------------------------------------------------------
#define BIND_CHAR_ARRAY(struct_, field_) \
    .def_property(#field_, \
        [](const struct_& f) { return char_to_str(f.field_, sizeof(f.field_)); }, \
        [](struct_& f, const std::string& s) { strncpy(f.field_, s.c_str(), sizeof(f.field_)); })

// ---------------------------------------------------------------------------
// Release wakeup helpers
//
// GtjaMdUserApi::Release() sets an internal stop flag and then joins the
// receive thread. That thread parks in a select()/pselect6() with no timeout,
// so the flag is only observed after select returns - which never happens when
// no market data arrives. Interrupting the thread makes select return EINTR,
// the receive loop re-checks the flag, and the join completes.
//
// SIGURG is used because its default disposition is "ignore": a stray delivery
// cannot terminate the process even if our handler is not installed.
// ---------------------------------------------------------------------------
namespace {

constexpr int kWakeSignal = SIGURG;
constexpr int kDestructorReleaseTimeoutMs = 2000;
constexpr int kWakeGraceMs = 1000;
constexpr int kRewakeIntervalMs = 100;

extern "C" void gtja_wake_signal_handler(int) {}

class ScopedWakeSignalHandler {
public:
    ScopedWakeSignalHandler() {
        struct sigaction sa;
        memset(&sa, 0, sizeof(sa));
        sa.sa_handler = gtja_wake_signal_handler;
        sigemptyset(&sa.sa_mask);
        sa.sa_flags = 0;  // select()/pselect6() are never restarted anyway
        installed_ = (sigaction(kWakeSignal, &sa, &old_) == 0);
    }
    ~ScopedWakeSignalHandler() {
        if (installed_) sigaction(kWakeSignal, &old_, nullptr);
    }
    bool installed() const { return installed_; }

private:
    struct sigaction old_;
    bool installed_ = false;
};

// The SDK never exposes its receive thread's pthread_t, but every thread of the
// process is listed in /proc/self/task, so tgkill() can address it directly.
// Threads that are not blocked in an interruptible syscall just run the no-op
// handler, which is harmless.
//
// The caller must keep ScopedWakeSignalHandler installed across the delivery:
// restoring the old disposition (SIG_DFL == ignore for SIGURG) before the
// signal is delivered makes the kernel discard it, and select() never returns.
int wake_blocked_threads() {
    DIR* dir = opendir("/proc/self/task");
    if (!dir) return 0;

    const pid_t self = getpid();
    const pid_t me = static_cast<pid_t>(syscall(SYS_gettid));
    int sent = 0;
    while (struct dirent* ent = readdir(dir)) {
        if (ent->d_name[0] < '0' || ent->d_name[0] > '9') continue;
        const pid_t tid = static_cast<pid_t>(std::atoi(ent->d_name));
        if (tid == me) continue;
        if (syscall(SYS_tgkill, self, tid, kWakeSignal) == 0) ++sent;
    }
    closedir(dir);
    return sent;
}

long long elapsed_ms(std::chrono::steady_clock::time_point t0) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now() - t0)
        .count();
}

}  // namespace

// Wrapper class to manage lifetime safely. The official API hides the
// destructor and requires calling Release() to destroy the object. We keep a
// raw pointer and null it after Release() to avoid double-free when the Python
// wrapper is garbage collected.
class GtjaMdApiWrapper {
public:
    explicit GtjaMdApiWrapper(const std::string& log_path)
        : api_(GtjaMdUserApi::CreateMdUserApi(log_path.c_str())) {}

    ~GtjaMdApiWrapper() { release_impl(kDestructorReleaseTimeoutMs); }

    // Blocking release, but without holding the GIL: the SDK callbacks that run
    // on its receive thread need the GIL to reach Python, and holding it here
    // while waiting for that very thread deadlocks the interpreter.
    void release() {
        py::gil_scoped_release no_gil;
        release_impl(0);
    }

    // Bounded release. Returns elapsed milliseconds. If the SDK has not returned
    // by `timeout_ms`, the receive thread is interrupted so its select() returns
    // and the internal stop flag is observed. timeout_ms <= 0 blocks forever.
    int ReleaseWithTimeout(int timeout_ms) {
        py::gil_scoped_release no_gil;
        return static_cast<int>(release_impl(timeout_ms));
    }

    int LastReleaseWakeups() const { return last_wakeups_.load(); }

    // True if the SDK never returned and the object was abandoned (leaked) so
    // that the caller could continue instead of blocking forever.
    bool LastReleaseAbandoned() const { return abandoned_.load(); }

    void RegisterSpi(PySpi* spi) {
        if (!api_) throw std::runtime_error("API already released");
        api_->RegisterSpi(spi);
    }

    int RegisterFront(const std::string& addr) {
        if (!api_) throw std::runtime_error("API already released");
        return api_->RegisterFront(addr.c_str());
    }

    void SetConfig(const std::string& key, const std::string& val) {
        if (!api_) throw std::runtime_error("API already released");
        api_->SetConfig(key.c_str(), val.c_str());
    }

    int Init() {
        if (!api_) throw std::runtime_error("API already released");
        return api_->Init();
    }

    int Join() {
        if (!api_) throw std::runtime_error("API already released");
        return api_->Join();
    }

    int ReqUserLogin(const GtjaMdReqUserLoginField& req, int request_id, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        return api_->ReqUserLogin(&req, request_id, conn_id);
    }

    int ReqUserLogin(const std::string& user, const std::string& pwd, int request_id, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        GtjaMdReqUserLoginField req{};
        strncpy(req.UserID, user.c_str(), sizeof(req.UserID) - 1);
        strncpy(req.Password, pwd.c_str(), sizeof(req.Password) - 1);
        return api_->ReqUserLogin(&req, request_id, conn_id);
    }

    bool QueryFunction(uint64_t function, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        return api_->QueryFunction(function, conn_id);
    }

    int ReqSubMarketData(const std::vector<GtjaMdSpecificInstrumentField>& insts, int request_id, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        return api_->ReqSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

    int ReqSubMarketData(const std::vector<std::string>& symbols, int request_id, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        std::vector<GtjaMdSpecificInstrumentField> insts(symbols.size());
        for (size_t i = 0; i < symbols.size(); ++i) {
            memset(&insts[i], 0, sizeof(insts[i]));
            insts[i].ExchangeType = _et_unset;
            insts[i].ProductType = _pt_unset;
            strncpy(insts[i].InstrumentID, symbols[i].c_str(), sizeof(insts[i].InstrumentID) - 1);
        }
        return api_->ReqSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

    int ReqUnSubMarketData(const std::vector<GtjaMdSpecificInstrumentField>& insts, int request_id, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        return api_->ReqUnSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

    int ReqUnSubMarketData(const std::vector<std::string>& symbols, int request_id, int conn_id) {
        if (!api_) throw std::runtime_error("API already released");
        std::vector<GtjaMdSpecificInstrumentField> insts(symbols.size());
        for (size_t i = 0; i < symbols.size(); ++i) {
            memset(&insts[i], 0, sizeof(insts[i]));
            insts[i].ExchangeType = _et_unset;
            insts[i].ProductType = _pt_unset;
            strncpy(insts[i].InstrumentID, symbols[i].c_str(), sizeof(insts[i].InstrumentID) - 1);
        }
        return api_->ReqUnSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

private:
    // Whoever takes the pointer owns the release; a second caller gets nullptr
    // and returns immediately instead of releasing the same object twice.
    GtjaMdUserApi* take_api() {
        std::lock_guard<std::mutex> lock(mu_);
        GtjaMdUserApi* api = api_;
        api_ = nullptr;
        return api;
    }

    long long release_impl(int timeout_ms) {
        GtjaMdUserApi* api = take_api();
        if (!api) return 0;

        const auto t0 = std::chrono::steady_clock::now();
        if (timeout_ms <= 0) {
            api->Release();
            return elapsed_ms(t0);
        }

        // The worker may outlive this scope if the SDK never returns, so the
        // flag is shared rather than a stack local.
        auto done = std::make_shared<std::atomic<bool>>(false);
        std::thread worker([api, done]() {
            api->Release();
            done->store(true, std::memory_order_release);
        });

        auto wait_until = [&](std::chrono::steady_clock::time_point deadline) {
            while (!done->load(std::memory_order_acquire) &&
                   std::chrono::steady_clock::now() < deadline) {
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
            }
        };

        wait_until(t0 + std::chrono::milliseconds(timeout_ms));
        if (!done->load(std::memory_order_acquire)) {
            ScopedWakeSignalHandler handler;
            const auto grace_end = std::chrono::steady_clock::now() +
                                   std::chrono::milliseconds(kWakeGraceMs);
            int wakeups = 0;
            while (!done->load(std::memory_order_acquire) &&
                   std::chrono::steady_clock::now() < grace_end && handler.installed()) {
                // A single shot can land while the thread is between selects,
                // so keep interrupting until it unwinds.
                wakeups += wake_blocked_threads();
                wait_until(std::chrono::steady_clock::now() +
                           std::chrono::milliseconds(kRewakeIntervalMs));
            }
            last_wakeups_.store(wakeups);
            // Let any in-flight signal be delivered before the disposition is
            // restored, otherwise it is silently dropped.
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }

        if (done->load(std::memory_order_acquire)) {
            worker.join();
            abandoned_.store(false);
            return elapsed_ms(t0);
        }

        // Still stuck after the interrupt. Never hang the caller: detach and
        // deliberately leak the SDK object so the process can still exit.
        abandoned_.store(true);
        worker.detach();
        return elapsed_ms(t0);
    }

    std::mutex mu_;
    GtjaMdUserApi* api_;
    std::atomic<int> last_wakeups_{0};
    std::atomic<bool> abandoned_{false};
};

PYBIND11_MODULE(gtja_udp_api, m) {
    m.doc() = "Guotai Junan UDP Market Data API V3 Python Binding";

    // -----------------------------------------------------------------------
    // Enums
    // -----------------------------------------------------------------------
    py::enum_<TExchangeType>(m, "TExchangeType")
        .value("_et_unset", _et_unset)
        .value("_et_czce", _et_czce)
        .value("_et_dce", _et_dce)
        .value("_et_shfe", _et_shfe)
        .value("_et_cffex", _et_cffex)
        .value("_et_ine", _et_ine)
        .value("_et_sse", _et_sse)
        .value("_et_szse", _et_szse)
        .value("_et_sge", _et_sge)
        .export_values();

    py::enum_<TProductType>(m, "TProductType")
        .value("_pt_unset", _pt_unset)
        .value("_pt_futures", _pt_futures)
        .value("_pt_options", _pt_options)
        .value("_pt_stock", _pt_stock)
        .value("_pt_stock_options", _pt_stock_options)
        .value("_pt_index", _pt_index)
        .value("_pt_etf", _pt_etf)
        .value("_pt_bonds", _pt_bonds)
        .value("_pt_convertible_bonds", _pt_convertible_bonds)
        .export_values();

    py::enum_<RtnCode>(m, "RtnCode")
        .value("_rc_succ", _rc_succ)
        .value("_rc_invalid_connid", _rc_invalid_connid)
        .value("_rc_not_connected", _rc_not_connected)
        .value("_rc_send_request_error", _rc_send_request_error)
        .value("_rc_wrong_param", _rc_wrong_param)
        .value("_rc_not_login", _rc_not_login)
        .value("_rc_not_support", _rc_not_support)
        .export_values();

    m.attr("_FF_SUPPORT_SUB_MD") = (uint64_t)1;

    // -----------------------------------------------------------------------
    // Date/Time unions (expose computed fields because inner struct is anonymous)
    // -----------------------------------------------------------------------
    py::class_<TGtjaTime>(m, "TGtjaTime")
        .def(py::init<>())
        .def_readwrite("Time", &TGtjaTime::Time)
        .def_property_readonly("Seccond", [](const TGtjaTime* p) { return (uint16_t)(p->Time & 0x3F); })
        .def_property_readonly("MilliSec", [](const TGtjaTime* p) { return (uint16_t)((p->Time >> 6) & 0x3FF); })
        .def_property_readonly("Minite", [](const TGtjaTime* p) { return (uint8_t)((p->Time >> 16) & 0xFF); })
        .def_property_readonly("Hour", [](const TGtjaTime* p) { return (uint8_t)((p->Time >> 24) & 0xFF); });

    py::class_<TGtjaDate>(m, "TGtjaDate")
        .def(py::init<>())
        .def_readwrite("Date", &TGtjaDate::Date)
        .def_property_readonly("Day", [](const TGtjaDate* p) { return (uint8_t)(p->Date & 0xFF); })
        .def_property_readonly("Month", [](const TGtjaDate* p) { return (uint8_t)((p->Date >> 8) & 0xFF); })
        .def_property_readonly("Year", [](const TGtjaDate* p) { return (uint16_t)((p->Date >> 16) & 0xFFFF); });

    py::class_<TGtjaDateTime>(m, "TGtjaDateTime")
        .def(py::init<>())
        .def_readwrite("DateTime", &TGtjaDateTime::DateTime)
        .def_property_readonly("Time", [](const TGtjaDateTime* p) -> TGtjaTime {
            TGtjaTime t;
            t.Time = (uint32_t)(p->DateTime & 0xFFFFFFFFULL);
            return t;
        })
        .def_property_readonly("Date", [](const TGtjaDateTime* p) -> TGtjaDate {
            TGtjaDate d;
            d.Date = (uint32_t)((p->DateTime >> 32) & 0xFFFFFFFFULL);
            return d;
        });

    // -----------------------------------------------------------------------
    // Request/Response structs
    // -----------------------------------------------------------------------
    py::class_<GtjaMdRspInfoField>(m, "GtjaMdRspInfoField")
        .def(py::init<>())
        .def_readwrite("ErrorID", &GtjaMdRspInfoField::ErrorID)
        BIND_CHAR_ARRAY(GtjaMdRspInfoField, ErrorMsg);

    py::class_<GtjaMdReqUserLoginField>(m, "GtjaMdReqUserLoginField")
        .def(py::init<>())
        BIND_CHAR_ARRAY(GtjaMdReqUserLoginField, UserID)
        BIND_CHAR_ARRAY(GtjaMdReqUserLoginField, Password)
        .def_readwrite("ProtocolVersion", &GtjaMdReqUserLoginField::ProtocolVersion);

    py::class_<GtjaMdRspUserLoginField>(m, "GtjaMdRspUserLoginField")
        .def(py::init<>())
        BIND_CHAR_ARRAY(GtjaMdRspUserLoginField, UserID)
        BIND_CHAR_ARRAY(GtjaMdRspUserLoginField, LoginTime);

    py::class_<GtjaMdSpecificInstrumentField>(m, "GtjaMdSpecificInstrumentField")
        .def(py::init<>())
        .def_readwrite("ProductType", &GtjaMdSpecificInstrumentField::ProductType)
        .def_readwrite("ExchangeType", &GtjaMdSpecificInstrumentField::ExchangeType)
        BIND_CHAR_ARRAY(GtjaMdSpecificInstrumentField, InstrumentID);

    // -----------------------------------------------------------------------
    // V3 realtime structs
    // -----------------------------------------------------------------------
    py::class_<GtjaMdHeaderFieldV3>(m, "GtjaMdHeaderFieldV3")
        .def(py::init<>())
        .def_readwrite("FieldLen", &GtjaMdHeaderFieldV3::FieldLen)
        .def_readwrite("MdType", &GtjaMdHeaderFieldV3::MdType)
        .def_readwrite("Version", &GtjaMdHeaderFieldV3::Version)
        .def_readwrite("SeqNum", &GtjaMdHeaderFieldV3::SeqNum)
        .def_readwrite("UpdateDateTime", &GtjaMdHeaderFieldV3::UpdateDateTime)
        .def_readwrite("InstrumentIdx", &GtjaMdHeaderFieldV3::InstrumentIdx)
        .def_readwrite("TradeInfoIdx", &GtjaMdHeaderFieldV3::TradeInfoIdx)
        .def_readwrite("MBLInfoIdx", &GtjaMdHeaderFieldV3::MBLInfoIdx)
        .def_readwrite("MBLCount", &GtjaMdHeaderFieldV3::MBLCount)
        .def_readwrite("StaticInfoIdx", &GtjaMdHeaderFieldV3::StaticInfoIdx)
        .def_readwrite("BaseInfoIdx", &GtjaMdHeaderFieldV3::BaseInfoIdx)
        .def_readwrite("InstrumentStatusIdx", &GtjaMdHeaderFieldV3::InstrumentStatusIdx);

    py::class_<GtjaMdInstrumentFieldV3>(m, "GtjaMdInstrumentFieldV3")
        .def(py::init<>())
        .def_readwrite("ExchangeType", &GtjaMdInstrumentFieldV3::ExchangeType)
        .def_property_readonly("InstrumentID", [](const GtjaMdInstrumentFieldV3* p) {
            if (!p) return std::string();
            return std::string(p->InstrumentID);
        });

    py::class_<GtjaMdBaseInfoFieldV3>(m, "GtjaMdBaseInfoFieldV3")
        .def(py::init<>())
        BIND_CHAR_ARRAY(GtjaMdBaseInfoFieldV3, TradingDay)
        .def_readwrite("PreSettlementPrice", &GtjaMdBaseInfoFieldV3::PreSettlementPrice)
        .def_readwrite("PreClosePrice", &GtjaMdBaseInfoFieldV3::PreClosePrice)
        .def_readwrite("PreOpenInterest", &GtjaMdBaseInfoFieldV3::PreOpenInterest)
        .def_readwrite("UpperLimitPrice", &GtjaMdBaseInfoFieldV3::UpperLimitPrice)
        .def_readwrite("LowerLimitPrice", &GtjaMdBaseInfoFieldV3::LowerLimitPrice);

    py::class_<GtjaMdStaticInfoFieldV3>(m, "GtjaMdStaticInfoFieldV3")
        .def(py::init<>())
        .def_readwrite("OpenPrice", &GtjaMdStaticInfoFieldV3::OpenPrice)
        .def_readwrite("ClosePrice", &GtjaMdStaticInfoFieldV3::ClosePrice)
        .def_readwrite("SettlementPrice", &GtjaMdStaticInfoFieldV3::SettlementPrice)
        .def_readwrite("HighestPrice", &GtjaMdStaticInfoFieldV3::HighestPrice)
        .def_readwrite("LowestPrice", &GtjaMdStaticInfoFieldV3::LowestPrice);

    py::class_<GtjaMdTradeInfoFieldV3>(m, "GtjaMdTradeInfoFieldV3")
        .def(py::init<>())
        .def_readwrite("LastPrice", &GtjaMdTradeInfoFieldV3::LastPrice)
        .def_readwrite("Turnover", &GtjaMdTradeInfoFieldV3::Turnover)
        .def_readwrite("OpenInterest", &GtjaMdTradeInfoFieldV3::OpenInterest)
        .def_readwrite("Volume", &GtjaMdTradeInfoFieldV3::Volume);

    py::class_<GtjaMdMBLFieldV3>(m, "GtjaMdMBLFieldV3")
        .def(py::init<>())
        .def_readwrite("BidPrice", &GtjaMdMBLFieldV3::BidPrice)
        .def_readwrite("AskPrice", &GtjaMdMBLFieldV3::AskPrice)
        .def_readwrite("BidVolume", &GtjaMdMBLFieldV3::BidVolume)
        .def_readwrite("AskVolume", &GtjaMdMBLFieldV3::AskVolume);

    py::class_<GtjaMdInstrumentStatusV3>(m, "GtjaMdInstrumentStatusV3")
        .def(py::init<>())
        .def_readwrite("InstrumentType", &GtjaMdInstrumentStatusV3::InstrumentType)
        BIND_CHAR_ARRAY(GtjaMdInstrumentStatusV3, MDStreamID)
        BIND_CHAR_ARRAY(GtjaMdInstrumentStatusV3, InstrumentStauts);

    // -----------------------------------------------------------------------
    // Old snapshot struct (used by OnRspLastSnapshot)
    // -----------------------------------------------------------------------
    py::class_<GtjaDepthMarketDataField>(m, "GtjaDepthMarketDataField")
        .def(py::init<>())
        BIND_CHAR_ARRAY(GtjaDepthMarketDataField, TradingDay)
        BIND_CHAR_ARRAY(GtjaDepthMarketDataField, InstrumentID)
        .def_readwrite("LastPrice", &GtjaDepthMarketDataField::LastPrice)
        .def_readwrite("PreSettlementPrice", &GtjaDepthMarketDataField::PreSettlementPrice)
        .def_readwrite("PreClosePrice", &GtjaDepthMarketDataField::PreClosePrice)
        .def_readwrite("PreOpenInterest", &GtjaDepthMarketDataField::PreOpenInterest)
        .def_readwrite("OpenPrice", &GtjaDepthMarketDataField::OpenPrice)
        .def_readwrite("Volume", &GtjaDepthMarketDataField::Volume)
        .def_readwrite("Turnover", &GtjaDepthMarketDataField::Turnover)
        .def_readwrite("OpenInterest", &GtjaDepthMarketDataField::OpenInterest)
        .def_readwrite("ClosePrice", &GtjaDepthMarketDataField::ClosePrice)
        .def_readwrite("SettlementPrice", &GtjaDepthMarketDataField::SettlementPrice)
        .def_readwrite("UpperLimitPrice", &GtjaDepthMarketDataField::UpperLimitPrice)
        .def_readwrite("LowerLimitPrice", &GtjaDepthMarketDataField::LowerLimitPrice)
        BIND_CHAR_ARRAY(GtjaDepthMarketDataField, UpdateTime)
        .def_readwrite("UpdateMillisec", &GtjaDepthMarketDataField::UpdateMillisec)
        .def_readwrite("BidPrice1", &GtjaDepthMarketDataField::BidPrice1)
        .def_readwrite("BidVolume1", &GtjaDepthMarketDataField::BidVolume1)
        .def_readwrite("AskPrice1", &GtjaDepthMarketDataField::AskPrice1)
        .def_readwrite("AskVolume1", &GtjaDepthMarketDataField::AskVolume1)
        .def_readwrite("BidPrice2", &GtjaDepthMarketDataField::BidPrice2)
        .def_readwrite("BidVolume2", &GtjaDepthMarketDataField::BidVolume2)
        .def_readwrite("AskPrice2", &GtjaDepthMarketDataField::AskPrice2)
        .def_readwrite("AskVolume2", &GtjaDepthMarketDataField::AskVolume2)
        .def_readwrite("BidPrice3", &GtjaDepthMarketDataField::BidPrice3)
        .def_readwrite("BidVolume3", &GtjaDepthMarketDataField::BidVolume3)
        .def_readwrite("AskPrice3", &GtjaDepthMarketDataField::AskPrice3)
        .def_readwrite("AskVolume3", &GtjaDepthMarketDataField::AskVolume3)
        .def_readwrite("BidPrice4", &GtjaDepthMarketDataField::BidPrice4)
        .def_readwrite("BidVolume4", &GtjaDepthMarketDataField::BidVolume4)
        .def_readwrite("AskPrice4", &GtjaDepthMarketDataField::AskPrice4)
        .def_readwrite("AskVolume4", &GtjaDepthMarketDataField::AskVolume4)
        .def_readwrite("BidPrice5", &GtjaDepthMarketDataField::BidPrice5)
        .def_readwrite("BidVolume5", &GtjaDepthMarketDataField::BidVolume5)
        .def_readwrite("AskPrice5", &GtjaDepthMarketDataField::AskPrice5)
        .def_readwrite("AskVolume5", &GtjaDepthMarketDataField::AskVolume5)
        BIND_CHAR_ARRAY(GtjaDepthMarketDataField, ActionDay);

    // -----------------------------------------------------------------------
    // API wrapper class
    // -----------------------------------------------------------------------
    py::class_<GtjaMdApiWrapper>(m, "GtjaMdUserApi")
        .def(py::init<const std::string&>(), py::arg("log_path") = "api.log")
        .def("Release", &GtjaMdApiWrapper::release)
        .def("ReleaseWithTimeout", &GtjaMdApiWrapper::ReleaseWithTimeout,
             py::arg("timeout_ms") = 5000,
             "有界释放：超时后中断 SDK 收包线程的 select 等待，返回耗时毫秒数")
        .def_property_readonly("LastReleaseWakeups", &GtjaMdApiWrapper::LastReleaseWakeups)
        .def_property_readonly("LastReleaseAbandoned", &GtjaMdApiWrapper::LastReleaseAbandoned)
        .def("Init", &GtjaMdApiWrapper::Init)
        .def("Join", &GtjaMdApiWrapper::Join)
        .def("RegisterFront", &GtjaMdApiWrapper::RegisterFront)
        .def("RegisterSpi", &GtjaMdApiWrapper::RegisterSpi)
        .def("SetConfig", &GtjaMdApiWrapper::SetConfig)
        .def("ReqUserLogin", static_cast<int (GtjaMdApiWrapper::*)(const GtjaMdReqUserLoginField&, int, int)>(
            &GtjaMdApiWrapper::ReqUserLogin))
        .def("ReqUserLogin", static_cast<int (GtjaMdApiWrapper::*)(const std::string&, const std::string&, int, int)>(
            &GtjaMdApiWrapper::ReqUserLogin))
        .def("QueryFunction", &GtjaMdApiWrapper::QueryFunction)
        .def("ReqSubMarketData", static_cast<int (GtjaMdApiWrapper::*)(const std::vector<GtjaMdSpecificInstrumentField>&, int, int)>(
            &GtjaMdApiWrapper::ReqSubMarketData))
        .def("ReqSubMarketData", static_cast<int (GtjaMdApiWrapper::*)(const std::vector<std::string>&, int, int)>(
            &GtjaMdApiWrapper::ReqSubMarketData))
        .def("ReqUnSubMarketData", static_cast<int (GtjaMdApiWrapper::*)(const std::vector<GtjaMdSpecificInstrumentField>&, int, int)>(
            &GtjaMdApiWrapper::ReqUnSubMarketData))
        .def("ReqUnSubMarketData", static_cast<int (GtjaMdApiWrapper::*)(const std::vector<std::string>&, int, int)>(
            &GtjaMdApiWrapper::ReqUnSubMarketData));

    // -----------------------------------------------------------------------
    // SPI class
    // -----------------------------------------------------------------------
    py::class_<PySpi>(m, "PySpi")
        .def(py::init<>())
        .def_readwrite("on_front_connected", &PySpi::on_front_connected)
        .def_readwrite("on_front_disconnected", &PySpi::on_front_disconnected)
        .def_readwrite("on_rsp_error", &PySpi::on_rsp_error)
        .def_readwrite("on_rsp_user_login", &PySpi::on_rsp_user_login)
        .def_readwrite("on_rtn_depth_snapshot", &PySpi::on_rtn_depth_snapshot)
        .def_readwrite("on_rsp_last_snapshot", &PySpi::on_rsp_last_snapshot)
        .def_readwrite("on_rsp_sub_market_data", &PySpi::on_rsp_sub_market_data)
        .def_readwrite("on_rsp_unsub_market_data", &PySpi::on_rsp_unsub_market_data);
}
