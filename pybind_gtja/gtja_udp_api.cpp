// pybind11 wrapper for Guotai Junan UDP Market Data API (V3.7.x)
// Target: Python 3.9 + pybind11

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h>
#include <string.h>
#include <string>
#include <vector>
#include <functional>
#include <mutex>
#include <condition_variable>
#include <exception>

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
                       const std::vector<GtjaMdMBLFieldV3>&, const GtjaMdInstrumentStatusV3*,
                       const SecurityExtraInfo*, int)> on_rtn_depth_snapshot;
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
                                      const SecurityExtraInfo* pSecurityExtra, int nConnectID) override {
        std::vector<GtjaMdMBLFieldV3> mbl_vec;
        if (pMBL && MBLLength > 0) {
            mbl_vec.assign(pMBL, pMBL + MBLLength);
        }
        if (on_rtn_depth_snapshot) on_rtn_depth_snapshot(pInstrument, pStamp, pTradeInfo, pBaseInfo, pStaticInfo,
                                                          MBLLength, mbl_vec, pInstrumentStatus, pSecurityExtra,
                                                          nConnectID);
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

// Wrapper class to manage lifetime safely. The official API hides the
// destructor and requires calling Release() to destroy the object. Every SDK
// call runs under a CallToken that pins the object for the duration:
//
//   * Release() rejects new calls from the moment it starts, then waits for
//     the tokens already handed out. No request can therefore overlap the
//     SDK teardown, and a concurrent second Release() cannot re-enter the
//     SDK on a destroyed object.
//   * The mutex is never held across an SDK call. The SDK's receive thread
//     may enter Python and call back into this object; holding the lock
//     across Release() (which joins that thread) would deadlock.
class GtjaMdApiWrapper {
public:
    explicit GtjaMdApiWrapper(const std::string& log_path)
        : api_(GtjaMdUserApi::CreateMdUserApi(log_path.c_str())) {}

    // Release blocks until the SDK has joined its receive thread, and that
    // thread needs the GIL to deliver callbacks into Python, so drop it here
    // too (PyGILState_Check covers interpreter finalisation, where no thread
    // state is available).
    ~GtjaMdApiWrapper() {
        try {
            if (PyGILState_Check()) {
                py::gil_scoped_release no_gil;
                release();
            } else {
                release();
            }
        } catch (...) {
            // A throwing destructor would call std::terminate; the SDK is gone
            // either way, so there is nothing left to report.
        }
    }

    // Idempotent and safe to call from several threads at once: the first
    // caller releases the SDK after draining in-flight calls, the others wait
    // for it and then return as no-ops.
    void release() {
        GtjaMdUserApi* api = nullptr;
        {
            std::unique_lock<std::mutex> lock(mu_);
            if (releasing_) {
                // A second caller must not enter the SDK again: wait for the
                // first release to finish, then observe api_ == nullptr.
                release_done_.wait(lock, [this] { return !releasing_; });
                return;
            }
            if (!api_) return;
            releasing_ = true;
            api = api_;
            api_ = nullptr;  // further calls fail fast instead of entering the SDK
            // Let calls that were already handed a token finish first.
            idle_.wait(lock, [this] { return active_calls_ == 0; });
        }
        std::exception_ptr error;
        try {
            api->Release();
        } catch (...) {
            error = std::current_exception();
        }
        {
            std::lock_guard<std::mutex> lock(mu_);
            releasing_ = false;
        }
        release_done_.notify_all();
        if (error) std::rethrow_exception(error);
    }

    void RegisterSpi(PySpi* spi) {
        if (!spi) throw std::runtime_error("SPI must not be null");
        api_alive()->RegisterSpi(spi);
    }

    int RegisterFront(const std::string& addr) {
        return api_alive()->RegisterFront(addr.c_str());
    }

    void SetConfig(const std::string& key, const std::string& val) {
        api_alive()->SetConfig(key.c_str(), val.c_str());
    }

    int Init() {
        return api_alive()->Init();
    }

    int Join() {
        return api_alive()->Join();
    }

    int ReqUserLogin(const GtjaMdReqUserLoginField& req, int request_id, int conn_id) {
        return api_alive()->ReqUserLogin(&req, request_id, conn_id);
    }

    int ReqUserLogin(const std::string& user, const std::string& pwd, int request_id, int conn_id) {
        GtjaMdReqUserLoginField req{};
        strncpy(req.UserID, user.c_str(), sizeof(req.UserID) - 1);
        strncpy(req.Password, pwd.c_str(), sizeof(req.Password) - 1);
        return api_alive()->ReqUserLogin(&req, request_id, conn_id);
    }

    bool QueryFunction(uint64_t function, int conn_id) {
        return api_alive()->QueryFunction(function, conn_id);
    }

    int ReqSubMarketData(const std::vector<GtjaMdSpecificInstrumentField>& insts, int request_id, int conn_id) {
        return api_alive()->ReqSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

    int ReqSubMarketData(const std::vector<std::string>& symbols, int request_id, int conn_id) {
        std::vector<GtjaMdSpecificInstrumentField> insts(symbols.size());
        for (size_t i = 0; i < symbols.size(); ++i) {
            memset(&insts[i], 0, sizeof(insts[i]));
            insts[i].ExchangeType = _et_unset;
            insts[i].ProductType = _pt_unset;
            strncpy(insts[i].InstrumentID, symbols[i].c_str(), sizeof(insts[i].InstrumentID) - 1);
        }
        return api_alive()->ReqSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

    int ReqUnSubMarketData(const std::vector<GtjaMdSpecificInstrumentField>& insts, int request_id, int conn_id) {
        return api_alive()->ReqUnSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

    int ReqUnSubMarketData(const std::vector<std::string>& symbols, int request_id, int conn_id) {
        std::vector<GtjaMdSpecificInstrumentField> insts(symbols.size());
        for (size_t i = 0; i < symbols.size(); ++i) {
            memset(&insts[i], 0, sizeof(insts[i]));
            insts[i].ExchangeType = _et_unset;
            insts[i].ProductType = _pt_unset;
            strncpy(insts[i].InstrumentID, symbols[i].c_str(), sizeof(insts[i].InstrumentID) - 1);
        }
        return api_alive()->ReqUnSubMarketData(insts.data(), (uint32_t)insts.size(), request_id, conn_id);
    }

private:
    // Held for the duration of one SDK call. The owning wrapper cannot start
    // Release() while a token is alive, which is what makes handing out the
    // raw api_ pointer safe. Not copyable; movable only so it can be returned.
    class CallToken {
    public:
        CallToken(GtjaMdApiWrapper* owner, GtjaMdUserApi* api) : owner_(owner), api_(api) {}
        CallToken(CallToken&& other) noexcept : owner_(other.owner_), api_(other.api_) {
            other.owner_ = nullptr;
        }
        CallToken(const CallToken&) = delete;
        CallToken& operator=(const CallToken&) = delete;
        CallToken& operator=(CallToken&&) = delete;
        ~CallToken() {
            if (owner_) owner_->end_call();
        }
        GtjaMdUserApi* operator->() const { return api_; }

    private:
        GtjaMdApiWrapper* owner_;
        GtjaMdUserApi* api_;
    };

    // Never hold the lock across the SDK call, and never hand the pointer out
    // without a token: the token is what stops Release() from tearing the
    // object down mid-request.
    CallToken api_alive() {
        std::lock_guard<std::mutex> lock(mu_);
        if (!api_) throw std::runtime_error("API already released");
        ++active_calls_;
        return CallToken(this, api_);
    }

    void end_call() {
        std::lock_guard<std::mutex> lock(mu_);
        --active_calls_;
        if (active_calls_ == 0) idle_.notify_all();
    }

    std::mutex mu_;
    std::condition_variable release_done_;
    std::condition_variable idle_;
    GtjaMdUserApi* api_;
    bool releasing_ = false;
    int active_calls_ = 0;
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
        .def_readwrite("InstrumentStatusIdx", &GtjaMdHeaderFieldV3::InstrumentStatusIdx)
        .def_readwrite("SecurityExtraInfoIdx", &GtjaMdHeaderFieldV3::SecurityExtraInfoIdx);

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

    // Added in SDK V3.7.1.1 (20250624). OnRtnDepthSnapshot gained a trailing
    // const SecurityExtraInfo* argument; the struct itself is absent from
    // V3.7.0.6, so this binding only compiles against the newer headers.
    py::class_<SecurityExtraInfo>(m, "SecurityExtraInfo")
        .def(py::init<>())
        .def_readwrite("DynRefPrice", &SecurityExtraInfo::DynRefPrice)   // 动态参考价(上交期权有效)
        .def_readwrite("VirMatch", &SecurityExtraInfo::VirMatch)         // 虚拟匹配量(上交所期权有效)
        .def_readwrite("IOPV", &SecurityExtraInfo::IOPV);                // 基金类产品有效

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
        // Release/Join hand control to the SDK's own threads, so drop the GIL
        // for the duration: a stuck SDK can then never wedge the interpreter.
        .def("Release", &GtjaMdApiWrapper::release, py::call_guard<py::gil_scoped_release>())
        .def("Init", &GtjaMdApiWrapper::Init)
        .def("Join", &GtjaMdApiWrapper::Join, py::call_guard<py::gil_scoped_release>())
        .def("RegisterFront", &GtjaMdApiWrapper::RegisterFront)
        // The SDK keeps the SPI pointer for the whole session, so pin the
        // Python object to the API's lifetime: dropping the last Python
        // reference would otherwise free it while callbacks still arrive.
        .def("RegisterSpi", &GtjaMdApiWrapper::RegisterSpi, py::keep_alive<1, 2>())
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
