/////////////////////////////////////////////////////////////////////////
///@system UDP快速行情二期
///@company 国泰君安期货有限公司
///@file GtjaMdUserApi.h
///@history 
///20060621	高伟男   创建该文件
///20201215 高伟男   支持多个udp连接(内部仍旧一个线程，轮询各行情);
///                  增加订阅支持(目前仅tcp单播支持订阅，同时须后台支持订阅功能)
///20210202 高伟男   增加上证、深证合约状态推送功能
/////////////////////////////////////////////////////////////////////////

#if !defined(__GTJAMDUSERAPI_H__)
#define __GTJAMDUSERAPI_H__

#if _MSC_VER > 1000
#pragma once
#endif // _MSC_VER > 1000

#include "GtjaMdStructV3.h"

#if defined(_WINDOWS_) || defined(WIN32)
#ifdef GTJAMDUSERAPI_EXPORTS
#define GTJAMD_API_EXPORT __declspec(dllexport)
#else
#define GTJAMD_API_EXPORT __declspec(dllimport)
#endif
#define GTJAMDAPI __stdcall
#else
#define GTJAMD_API_EXPORT
#define GTJAMDAPI
#endif

class GtjaMdUserSpi
{
public:
	///当客户端与交易后台建立起通信连接时（还未登录前），该方法被调用。
	virtual void GTJAMDAPI OnFrontConnected(int /*nConnectID*/){};

	///当客户端与交易后台通信连接断开时，该方法被调用。当发生这个情况后，API会自动重新连接，客户端可不做处理。
	///@param nReason 错误原因
	///        0x1001 网络读失败
	///        0x1002 网络写失败
	///        0x2001 接收心跳超时
	///        0x2002 发送心跳失败
	///        0x2003 收到错误报文
	virtual void GTJAMDAPI OnFrontDisconnected(int /*nReason*/, int /*nConnectID*/){};
	///错误应答
	virtual void GTJAMDAPI OnRspError(const GtjaMdV3::GtjaMdRspInfoField* /*pRspInfo*/, int /*nRequestID*/, bool /*bIsLast*/, int /*nConnectID*/){};
	///登录请求响应
	virtual void GTJAMDAPI OnRspUserLogin(const GtjaMdV3::GtjaMdRspUserLoginField* /*pRspUserLogin*/, const GtjaMdV3::GtjaMdRspInfoField* /*pRspInfo*/, int /*nRequestID*/, bool /*bIsLast*/, int /*nConnectID*/) = 0;
	///深度行情通知
	virtual void GTJAMDAPI OnRtnDepthSnapshot(
		const GtjaMdV3::GtjaMdInstrumentFieldV3* /*pInstrument*/,
		const GtjaMdV3::TGtjaDateTime* /*pStamp*/,
		const GtjaMdV3::GtjaMdTradeInfoFieldV3* /*pTradeInfo*/,
		const GtjaMdV3::GtjaMdBaseInfoFieldV3* /*pBaseInfo*/,
		const GtjaMdV3::GtjaMdStaticInfoFieldV3* /*pStaticInfo*/,
		int /*MBLLength*/,
		const  GtjaMdV3::GtjaMdMBLFieldV3* /*pMBL*/,
		const GtjaMdV3::GtjaMdInstrumentStatusV3* /*pInstrumentStatus*/,
		int /*nConnectID*/) = 0;
	//登录后返回最近一次的快照信息（可选调用，不一定有会有返回，比如认证服务无缓存的情况下，无返回；支持订阅的行情，无快照信息返回）
	virtual void GTJAMDAPI OnRspLastSnapshot(const GtjaMdV3::GtjaDepthMarketDataField* /*pDepthMarketData*/, int /*nConnectID*/){};

	///订阅合约回调
	virtual void GTJAMDAPI OnRspSubMarketData(const GtjaMdV3::GtjaMdSpecificInstrumentField* /*pInstrument*/, const GtjaMdV3::GtjaMdRspInfoField* /*pRspInfo*/, int /*nRequestID*/, int /*nConnectID*/) {};

	///取消订阅合约回调
	virtual void GTJAMDAPI OnRspUnSubMarketData(const GtjaMdV3::GtjaMdSpecificInstrumentField* /*pInstrument*/, const GtjaMdV3::GtjaMdRspInfoField* /*pRspInfo*/, int /*nRequestID*/, int /*nConnectID*/) {};
};

class GTJAMD_API_EXPORT GtjaMdUserApi{
protected:
	virtual GTJAMDAPI ~GtjaMdUserApi(){}
public:
	//创建实例
	static GtjaMdUserApi* GTJAMDAPI CreateMdUserApi(const char* logPath);

	//删除接口对象本身
	///@remark 不再使用本接口对象时,调用该函数删除接口对象
	virtual void GTJAMDAPI Release() = 0;

	///初始化
	///@remark 初始化运行环境,只有调用后,接口才开始工作
	virtual int GTJAMDAPI Init() = 0;

	///等待接口线程结束运行
	///@return 线程退出代码
	virtual int GTJAMDAPI Join() = 0;

	///注册前置机网络地址
	///@param pszFrontAddress：前置机网络地址。
	///@remark 网络地址的格式为：“protocol://ipaddress:port”，如：”tcp://127.0.0.1:17001”。 
	///@remark “tcp”代表传输协议，“127.0.0.1”代表服务器地址。”17001”代表服务器端口号。
	///@return 当前注册的前置的ConnectID，后续可用于Spi中的回调，及后续请求。返回值应该>=0,如<0表示注册失败.
	virtual int GTJAMDAPI RegisterFront(const char *pszFrontAddress) = 0;

	///注册回调接口
	///@param pSpi 派生自回调接口类的实例
	virtual void GTJAMDAPI RegisterSpi(GtjaMdUserSpi *pSpi) = 0;

	///设置其它参数
	///@param key:参数的key。
	///@param val:参数的value。
	///@remark 该函数须在Init函数之前调用，Init之后调用无效
	virtual void GTJAMDAPI SetConfig(const char* key, const char* val) = 0;

	///用户登录请求
	///@param nConnectID:RegisterFront注册前置时返回的连接ID
	///@param pReqUserLoginField:请求登录参数，其中UserID及Password为必填写，ProtocolVersion不必填写。
	///@remark 该函数须在Init函数之前调用，Init之后调用无效
	virtual int GTJAMDAPI ReqUserLogin(const GtjaMdV3::GtjaMdReqUserLoginField *pReqUserLoginField, int nRequestID, int nConnectID) = 0;

	///检查支持功能
	///@param nConnectID:RegisterFront注册前置时返回的连接ID
	///@param pInstrument:合约代码字段。
	///@remark 该函数须登录成功响应后调用，即在收到OnRspUserLogin响应后调用，否则一定会订阅失败
	virtual bool GTJAMDAPI QueryFunction(uint64_t function, int nConnectID) = 0;

	///订阅合约
	///@param nConnectID:RegisterFront注册前置时返回的连接ID
	///@param pInstrument:合约代码字段。
	///@remark 该函数须在登录完成后调用，否则会失败
	///@remark 仅针对单播的行情(tcp发送)才有可能支持订阅，组播行情不支持订阅
	virtual int GTJAMDAPI ReqSubMarketData(const GtjaMdV3::GtjaMdSpecificInstrumentField* pInstrumentArray, uint32_t nInstrumentCount, int nRequestID, int nConnectID) = 0;

	///取消订阅合约
	///@param nConnectID:RegisterFront注册前置时返回的连接ID
	///@param pInstrument:合约代码字段。
	///@remark 该函数须在登录完成后调用，否则会失败
	///@remark 仅针对单播的行情(tcp发送)才有可能支持取消订阅，组播行情不支持取消订阅
	virtual int GTJAMDAPI ReqUnSubMarketData(const GtjaMdV3::GtjaMdSpecificInstrumentField* pInstrumentArray, uint32_t nInstrumentCount, int nRequestID, int nConnectID) = 0;
};

#endif //__GTJAMDUSERAPI_H__
