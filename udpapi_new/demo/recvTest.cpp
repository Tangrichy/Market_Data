#include "GtjaMdUserApi.h"
#include <stdio.h>
#include <string.h>
#include <fstream>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <vector>
#include <stdlib.h>
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
		return " ɹ ";
		break;
	case _rc_invalid_connid:
		return " Ƿ   ConnectID";
		break;
	case _rc_not_connected:
		return "  δ    ";
		break;
	case _rc_send_request_error:
		return "      ʧ  ";
		break;
	case _rc_wrong_param:
		return "    Ĳ   ";
		break;
	case _rc_not_login:
		return "  δ  ¼";
		break;
	case _rc_not_support:
		return "  ֧ ִ˹   ";
		break;
	default:
		return "δ֪    ";
	}
}

class MySpi: public GtjaMdUserSpi
{
public:
	///   ͻ    뽻 ׺ ̨      ͨ      ʱ    δ  ¼ǰ     ÷        á 
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

	///   ͻ    뽻 ׺ ̨ͨ     ӶϿ ʱ   ÷        á               API   Զ        ӣ  ͻ  ˿ɲ        
	///@param nReason     ԭ  
	///        0x1001      ʧ  
	///        0x1002     дʧ  
	///        0x2001           ʱ
	///        0x2002         ʧ  
	///        0x2003  յ       
	virtual void GTJAMDAPI OnFrontDisconnected(int nReason, int nConnectID) override {
		std::stringstream str;
		str << nConnectID << " OnFrontDisconnected: nReason:" << nReason;
		std::cout << str.str() << std::endl;
	}
	///    Ӧ  
	virtual void GTJAMDAPI OnRspError(const GtjaMdRspInfoField* pRspInfo, int nRequestID, bool bIsLast, int nConnectID) override {
		std::stringstream str;
		str << nConnectID << " ";
		if (pRspInfo)
			str << "ErrorID:" << pRspInfo->ErrorID << ", ErrorMsg : " << pRspInfo->ErrorMsg;
		else
			str << "NULL";
		std::cout << str.str() << std::endl;
	}
	///  ¼      Ӧ
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
			std::cout << "ǰ  " << nConnectID << "֧ ֶ  Ĺ   " << std::endl;
		}
		else {
			std::cout << "ǰ  " << nConnectID << "  ֧ ֶ  Ĺ   " << std::endl;
		}
	}
	///       ֪ͨ
	virtual void GTJAMDAPI OnRtnDepthSnapshot(
		const GtjaMdV3::GtjaMdInstrumentFieldV3* pInstrument,
		const GtjaMdV3::TGtjaDateTime* pStamp,
		const GtjaMdV3::GtjaMdTradeInfoFieldV3* pTradeInfo,
		const GtjaMdV3::GtjaMdBaseInfoFieldV3* pBaseInfo,
		const GtjaMdV3::GtjaMdStaticInfoFieldV3* pStaticInfo,
		int MBLLength,
		const GtjaMdV3::GtjaMdMBLFieldV3* pMBL,
		const GtjaMdV3::GtjaMdInstrumentStatusV3* pStatus,
		const GtjaMdV3::SecurityExtraInfo* pExtra,
		int nConnectID) override
	{
		std::stringstream str;
		str<<nConnectID<<" OnRtnDepthMarketData: "<<DspExch(pInstrument->ExchangeType)<<pInstrument->InstrumentID<<"," << std::setfill('0') << std::setw(2) <<(int)pStamp->Time.Hour<<":"<<(int)pStamp->Time.Minite<<":"<<pStamp->Time.Seccond<<"." << std::setw(3) <<pStamp->Time.MilliSec;
		if (pTradeInfo){
			str<<",LastPrice:"<<pTradeInfo->LastPrice \
			<<",Volume:"<<pTradeInfo->Volume;
		}
		if (pMBL && MBLLength>0){
			str << ",Bid1:" << pMBL[0].BidPrice << "/" << pMBL[0].BidVolume << ",Ask1:" << pMBL[0].AskPrice << "/" << pMBL[0].AskVolume;
		}
		if (pBaseInfo) {
			str << ",PreClose:" << pBaseInfo->PreClosePrice << ",PreSett:" << pBaseInfo->PreSettlementPrice << ",LimitUp:" << pBaseInfo->UpperLimitPrice << ",LimitLow:" << pBaseInfo->LowerLimitPrice;
		}
		if (pStaticInfo) {
			str << ",Open:" << pStaticInfo->OpenPrice << ",High:" << pStaticInfo->HighestPrice << ",Low:" << pStaticInfo->LowestPrice << ",Close:" << pStaticInfo->ClosePrice;
		}
		if (pStatus) {
			str << ",Status:";
			for (unsigned i = 0; i < 8; ++i) str << pStatus->InstrumentStauts[i];
		}
		if (pExtra) {
			str << ",RefPrice:" << pExtra->DynRefPrice << ",VirMatch:" << pExtra->VirMatch << ",IOPV:" << pExtra->IOPV;
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
	///   ĺ Լ ص 
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

	///ȡ     ĺ Լ ص 
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
	//pApi->SetConfig("efvi", "false");//   ò ʹ  efvi(      )
	pApi->SetConfig("cpu", "1");//  cpu ں 1  
	if (bNoEfvi) {
		pApi->SetConfig("efvi", "false");
	}
	pApi->Init();
	char buf[8192];
	do {
		std::cin.getline(buf, sizeof(buf)-1);
		std::vector<std::string> vec;
		SplitColumns(buf, vec, " ");
		if(vec.size()>1){
			if (0 == strcmp("sub", vec[0].c_str())) {
				GtjaMdV3::GtjaMdSpecificInstrumentField* instr = (GtjaMdV3::GtjaMdSpecificInstrumentField*)malloc(sizeof(GtjaMdV3::GtjaMdSpecificInstrumentField) * (vec.size() - 1));
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
				free(instr);
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
	pApi->Release();
	return 0;
}

