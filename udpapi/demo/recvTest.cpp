#include "../Common/GtjaMdUserApi.h"
#include <stdio.h>
#include <string.h>
#include <fstream>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <vector>
#ifdef __linux__
#include <alloca.h>
#endif

#if __cplusplus < 201103L
#define override
#endif

std::ofstream f("out.txt");

GtjaMdUserApi* pApi = NULL;
using namespace GtjaMdV3;

struct LinkInfo {
	int ConnectID;
	std::string front;
	std::string userID;
	std::string pass;
};

std::vector<LinkInfo> g_loginInfos;

static const char* DspExch(uint8_t t) {
	switch (t) {
	case _et_czce:
		return "CZCE.";
		break;
	case _et_dce:
		return "DCE.";
		break;
	case _et_shfe:
		return "SHFE.";
		break;
	case _et_cffex:
		return "CFFEX.";
		break;
	case _et_ine:
		return "INE.";
		break;
	case _et_sse:
		return "SSE.";
		break;
	case _et_szse:
		return "SZSE.";
		break;
	case _et_sge:
		return "SGE.";
		break;
	default:
		return "";
	}
}

static const char* DspRtnCode(int rtnCode) {
	switch (rtnCode) {
	case _rc_succ:
		return "成功";
		break;
	case _rc_invalid_connid:
		return "非法的ConnectID";
		break;
	case _rc_not_connected:
		return "尚未连接";
		break;
	case _rc_send_request_error:
		return "发请求失败";
		break;
	case _rc_wrong_param:
		return "错误的参数";
		break;
	case _rc_not_login:
		return "尚未登录";
		break;
	case _rc_not_support:
		return "不支持此功能";
		break;
	default:
		return "未知错误";
	}
}

class MySpi: public GtjaMdUserSpi
{
public:
	///当客户端与交易后台建立起通信连接时（还未登录前），该方法被调用。
	virtual void GTJAMDAPI OnFrontConnected(int nConnectID) override {
		std::cout << nConnectID << " OnFrontConnected\n";
		if (nConnectID < g_loginInfos.size()) {
			GtjaMdReqUserLoginField req;
			memset(&req, 0, sizeof(req));
			strncpy(req.UserID, g_loginInfos[nConnectID].userID.c_str(), sizeof(req.UserID));
			strncpy(req.Password, g_loginInfos[nConnectID].pass.c_str(), sizeof(req.Password));
			int re = pApi->ReqUserLogin(&req, 0, nConnectID);
			if (re) {
				std::cerr << "ReqUserLogin error:" << re << "," << DspRtnCode(re) << std::endl;
			}
		}
	}

	///当客户端与交易后台通信连接断开时，该方法被调用。当发生这个情况后，API会自动重新连接，客户端可不做处理。
	///@param nReason 错误原因
	///        0x1001 网络读失败
	///        0x1002 网络写失败
	///        0x2001 接收心跳超时
	///        0x2002 发送心跳失败
	///        0x2003 收到错误报文
	virtual void GTJAMDAPI OnFrontDisconnected(int nReason, int nConnectID) override {
		std::stringstream str;
		str << nConnectID << " OnFrontDisconnected: nReason:" << nReason;
		std::cout << str.str() << std::endl;
	}
	///错误应答
	virtual void GTJAMDAPI OnRspError(const GtjaMdRspInfoField* pRspInfo, int nRequestID, bool bIsLast, int nConnectID) override {
		std::stringstream str;
		str << nConnectID << " ";
		if (pRspInfo)
			str << "ErrorID:" << pRspInfo->ErrorID << ", ErrorMsg : " << pRspInfo->ErrorMsg;
		else
			str << "NULL";
		std::cout << str.str() << std::endl;
	}
	///登录请求响应
	virtual void GTJAMDAPI OnRspUserLogin(const GtjaMdRspUserLoginField* pRspUserLogin, const GtjaMdRspInfoField* pRspInfo, int nRequestID, bool bIsLast, int nConnectID) override {
		std::stringstream str;
		str << nConnectID << " OnRspUserLogin:";
		if (pRspInfo && pRspInfo->ErrorID){
			str << "ErrorID:" << pRspInfo->ErrorID << ",ErrorMsg:" << pRspInfo->ErrorMsg;
		}
		else if (pRspUserLogin){
			str << "Succ.";
		}
		std::cout << str.str() << std::endl;
		if (pApi->QueryFunction(_FF_SUPPORT_SUB_MD, nConnectID)) {
			std::cout << "前置" << nConnectID << "支持订阅功能" << std::endl;
		}
		else {
			std::cout << "前置" << nConnectID << "不支持订阅功能" << std::endl;
		}
	}
	///深度行情通知
	virtual void GTJAMDAPI OnRtnDepthSnapshot(
		const GtjaMdV3::GtjaMdInstrumentFieldV3* pInstrument,
		const GtjaMdV3::TGtjaDateTime* pStamp,
		const GtjaMdV3::GtjaMdTradeInfoFieldV3* pTradeInfo,
		const GtjaMdV3::GtjaMdBaseInfoFieldV3* pBaseInfo,
		const GtjaMdV3::GtjaMdStaticInfoFieldV3* pStaticInfo,
		int MBLLength,
		const GtjaMdV3::GtjaMdMBLFieldV3* pMBL,
		const GtjaMdV3::GtjaMdInstrumentStatusV3* pInstrumentStatus,
		int nConnectID)
	{
		std::stringstream str;
		str<<nConnectID<<" OnRtnDepthMarketData: "<<DspExch(pInstrument->ExchangeType)<<pInstrument->InstrumentID<<"\t" << std::setfill('0') << std::setw(2) <<(int)pStamp->Time.Hour<<":"<<(int)pStamp->Time.Minite<<":"<<pStamp->Time.Seccond<<"." << std::setw(3) <<pStamp->Time.MilliSec;
		if (pTradeInfo){
			str<<"\t"<<pTradeInfo->LastPrice \
			<<"\t"<<pTradeInfo->Volume;
		}
		if (pMBL && MBLLength>0){
			str<<"\t"<<pMBL[0].BidPrice<<"\t"<<pMBL[0].BidVolume<<"\t"<<pMBL[0].AskPrice \
			<<"\t"<<pMBL[0].AskVolume;
		}
		if (pInstrumentStatus) {
			str << "\t";
			for (unsigned i = 0; i < 8; ++i) str << pInstrumentStatus->InstrumentStauts[i];
		}
		std::cout<<str.str()<<std::endl;
		f<<str.str()<<std::endl;
	}
	virtual void GTJAMDAPI OnRspLastSnapshot(const GtjaDepthMarketDataField* pDepthMarketData, int nConnectID) override {
		std::stringstream str;
		str<<nConnectID<<" OnRspLastSnapshot:"<<pDepthMarketData->InstrumentID<<"\t"<<pDepthMarketData->UpdateTime<<"."<<pDepthMarketData->UpdateMillisec;
		str<<"\t"<<pDepthMarketData->LastPrice \
			<<"\t"<<pDepthMarketData->Volume;
		str<<"\t"<<pDepthMarketData->BidPrice1<<"\t"<<pDepthMarketData->BidVolume1<<"\t"<<pDepthMarketData->AskPrice1 \
			<<"\t"<<pDepthMarketData->AskVolume1;
		std::cout<<str.str()<<std::endl;
		f<<str.str()<<std::endl;
	}
	///订阅合约回调
	virtual void GTJAMDAPI OnRspSubMarketData(const GtjaMdV3::GtjaMdSpecificInstrumentField* pInstrument, const GtjaMdV3::GtjaMdRspInfoField* pRspInfo, int nRequestID, int nConnectID) override {
		std::stringstream str;
		str <<nConnectID<< " OnRspSubMarketData:" << pInstrument->InstrumentID << " ";
		if (pRspInfo && pRspInfo->ErrorID) {
			str << "ErrorID:" << pRspInfo->ErrorID << ",ErrorMsg:" << pRspInfo->ErrorMsg;
		}
		else {
			str << "Succ.";
		}
		std::cout << str.str() << std::endl;
	}

	///取消订阅合约回调
	virtual void GTJAMDAPI OnRspUnSubMarketData(const GtjaMdV3::GtjaMdSpecificInstrumentField* pInstrument, const GtjaMdV3::GtjaMdRspInfoField* pRspInfo, int nRequestID, int nConnectID) override {
		std::stringstream str;
		str <<nConnectID << " OnRspUnSubMarketData:" << pInstrument->InstrumentID << " ";
		if (pRspInfo && pRspInfo->ErrorID) {
			str << "ErrorID:" << pRspInfo->ErrorID << ",ErrorMsg:" << pRspInfo->ErrorMsg;
		}
		else {
			str << "Succ.";
		}
		std::cout << str.str() << std::endl;
	}
};

template<typename listType> bool SplitColumns(const std::string& str, listType& lst, const std::string& delim) {
	lst.clear();
	size_t last = 0;
	size_t index = str.find_first_of(delim, last);
	while (index != std::string::npos)
	{
		lst.push_back(str.substr(last, index - last));
		last = index + 1;
		index = str.find_first_of(delim, last);
	}
	index = str.length();
	if (index - last >= 0 && index > 0) {
		lst.push_back(str.substr(last, index - last));
	}
	return true;
}

int main(int argc, char* argv[])
{
	if (argc<4){
		std::cout<<"usage:"<<argv[0]<<" front username password [noefvi].\neg. "<<argv[0]<<" tcp://127.0.0.1:42116 00000001 00000000"<<std::endl;
		return 0;
	}
	pApi = GtjaMdUserApi::CreateMdUserApi("api.log");
	MySpi spi;
	pApi->RegisterSpi(&spi);
	bool bNoEfvi = false;

	int i = 1;
	int stat = 0;
	LinkInfo info;
	while (i < argc) {
		if (std::string("noefvi") == argv[i]) {
			bNoEfvi = true;
		}
		else {
			if (0 == stat % 3) {
				info.front = argv[i];
			}
			else if (1 == stat % 3) {
				info.userID = argv[i];
			}
			else {
				info.pass = argv[i];
				info.ConnectID = pApi->RegisterFront(info.front.c_str());
				g_loginInfos.push_back(info);
			}
			++stat;
		}
		++i;
	}
	//pApi->SetConfig("efvi", "false");//设置不使用efvi(不建议)
	pApi->SetConfig("cpu", "1");//绑定cpu在核1上
	if (bNoEfvi) {
		pApi->SetConfig("efvi", "false");
	}
	pApi->Init();
	char buf[1024];
	do {
		std::cin.getline(buf, 1024);
		std::vector<std::string> vec;
		SplitColumns(buf, vec, " ");
		if(vec.size()>1){
			if (0 == strcmp("sub", vec[0].c_str())) {
				GtjaMdV3::GtjaMdSpecificInstrumentField* instr = (GtjaMdV3::GtjaMdSpecificInstrumentField*)alloca(sizeof(GtjaMdV3::GtjaMdSpecificInstrumentField) * (vec.size() - 1));
				for (unsigned i = 0; i < vec.size() - 1; ++i) {
					instr[i].ExchangeType = GtjaMdV3::_et_unset;
					instr[i].ProductType = GtjaMdV3::_pt_unset;
					strncpy(instr[i].InstrumentID, vec[i + 1].c_str(), sizeof(instr[i].InstrumentID));
				}
				for (unsigned i = 0; i < g_loginInfos.size(); ++i) {
					LinkInfo& info = g_loginInfos[i];
					int re = pApi->ReqSubMarketData(instr, vec.size() - 1, 0, info.ConnectID);
					if (re) {
						std::cerr << info.ConnectID << " ReqSubMarketData error:" << re << "," << DspRtnCode(re) << std::endl;
					}
				}
			}
			else if (0 == strcmp("unsub", vec[0].c_str())) {
				GtjaMdV3::GtjaMdSpecificInstrumentField* instr = (GtjaMdV3::GtjaMdSpecificInstrumentField*)alloca(sizeof(GtjaMdV3::GtjaMdSpecificInstrumentField) * vec.size() - 1);
				for (unsigned i = 0; i < vec.size() - 1; ++i) {
					instr[i].ExchangeType = GtjaMdV3::_et_unset;
					instr[i].ProductType = GtjaMdV3::_pt_unset;
					strncpy(instr[i].InstrumentID, vec[i + 1].c_str(), sizeof(instr[i].InstrumentID));
				}
				for (unsigned i = 0; i < g_loginInfos.size(); ++i) {
					LinkInfo& info = g_loginInfos[i];
					int re = pApi->ReqUnSubMarketData(instr, vec.size() - 1, 0, info.ConnectID);
					if (re) {
						std::cerr << info.ConnectID << " ReqUnSubMarketData error:" << re << "," << DspRtnCode(re) << std::endl;
					}
				}
			}
		}
	} while (strcmp("exit",buf));
	return 0;
}

