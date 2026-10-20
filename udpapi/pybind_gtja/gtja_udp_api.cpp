// pybind11 wrapper for Guotai Junan UDP Market Data API (V3.7.x)
// Target: Python 3.9 + pybind11

#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl.h>
#include <string.h>
#include <string>
#include <vector>
#include <functional>

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

// Wrapper class to manage lifetime safely. The official API hides the
// destructor and requires calling Release() to destroy the object. We keep a
// raw pointer and null it after Release() to avoid double-free when the Python
// wrapper is garbage collected.
class GtjaMdApiWrapper {
public:
    explicit GtjaMdApiWrapper(const std::string& log_path)
        : api_(GtjaMdUserApi::CreateMdUserApi(log_path.c_str())) {}

    ~GtjaMdApiWrapper() { release(); }

    void release() {
        if (api_) {
            api_->Release();
            api_ = nullptr;
        }
    }

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
    GtjaMdUserApi* api_;
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
