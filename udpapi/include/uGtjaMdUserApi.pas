unit uGtjaMdUserApi;

interface
const
GTJAMD_TRADE	=	$00000001;//成交行情信息
GTJAMD_MBL	=	$00000002;//盘口量价信息
GTJAMD_STATIC	=	$00000004;//静态行情信息

type
GtjaMdRspInfoField = packed record
	ErrorID: Integer;
	ErrorMsg: array[0..43] of ansichar;
end;
PGtjaMdRspInfoField = ^GtjaMdRspInfoField;

GtjaMdReqUserLoginField = packed record
	UserID: array[0..15] of ansichar;
	Password: array[0..23] of ansichar;
	ProtocolVersion: Integer;
end;
PGtjaMdReqUserLoginField = ^GtjaMdReqUserLoginField;

GtjaMdRspUserLoginField = packed record
	UserID: array[0..15] of ansichar;
	LoginTime: array[0..7] of ansichar;//登录时间：服务端时间，仅供参考，不一定准
end;
PGtjaMdRspUserLoginField = ^GtjaMdRspUserLoginField;

GtjaMdReqUserPasswordUpdateField = packed record
	UserID: array[0..15] of ansichar;
	OldPassword: array[0..23] of ansichar;
	NewPassword: array[0..23] of ansichar;
end;
PGtjaMdReqUserPasswordUpdateField = ^GtjaMdReqUserPasswordUpdateField;

GtjaMdInstrumentIDField = packed record
	///本结构体长度（包含本字节)
	FieldLen: byte;
	///合约信息，长度由FieldLen决定，比如FieldLen为8时，则InstrumentID长度为7; 如果FieldLen为16，则InstrumentID长度为15
	InstrumentID: array[0..31] of ansichar;
end;
PGtjaMdInstrumentIDField = ^GtjaMdInstrumentIDField;

GtjaMdReqQryDepthMarketDataField = packed record
	UserID: array[0..15] of ansichar;
end;
PGtjaMdReqQryDepthMarketDataField = ^GtjaMdReqQryDepthMarketDataField;

GtjaMdHeaderField = packed record
	///业务日期
	ActionDay: array[0..7] of ansichar; //该字段取决于交易所，有些交易所不提供此字段，可能为空
	///更新时间
	UpdateTime: array[0..7] of ansichar;
	///更新时间（毫秒数)
	UpdateMillisec: integer;
	FieldType: cardinal;///行情类型GtjaMdFieldType进行标识位组合
end;
PGtjaMdHeaderField = ^GtjaMdHeaderField;

//静态行情结构体
GtjaMdStaticInfoField = packed record
	///交易日
	TradingDay: array[0..7] of ansichar;
	///上次结算价
	PreSettlementPrice: Double;
	///昨收盘
	PreClosePrice: Double;
	///昨持仓量
	PreOpenInterest: Double;
	///今开盘
	OpenPrice: Double;
	///今收盘
	ClosePrice: Double;
	///本次结算价
	SettlementPrice: Double;
	///涨停板价
	UpperLimitPrice: Double;
	///跌停板价
	LowerLimitPrice: Double;
end;
PGtjaMdStaticInfoField = ^GtjaMdStaticInfoField;

//成交信息结构体
GtjaMdTradeInfoField = packed record
	///最新价
	LastPrice: Double;
	///成交金额
	Turnover: Double;
	///持仓量
	OpenInterest: Double;
	///成交数量
	Volume: UInt64;
end;
PGtjaMdTradeInfoField = ^GtjaMdTradeInfoField;

//最优价结构体
GtjaMdMBLField = packed record
	///申买价
	BidPrice: Double;
	///申卖价
	AskPrice: Double;
	///申买量
	BidVolume: integer;
	///申卖量
	AskVolume: integer;
end;
PGtjaMdMBLField = ^GtjaMdMBLField;

GtjaDepthMarketDataField = packed record
	///交易日
	TradingDay: array[0..8] of ansichar;
	///合约代码
	InstrumentID: array[0..30] of ansichar;
	///最新价
	LastPrice: Double;
	///上次结算价
	PreSettlementPrice: Double;
	///昨收盘
	PreClosePrice: Double;
	///昨持仓量
	PreOpenInterest: Double;
	///今开盘
	OpenPrice: Double;
	///数量
	Volume: Int64;
	///成交金额
	Turnover: Double;
	///持仓量
	OpenInterest: Double;
	///今收盘
	ClosePrice: Double;
	///本次结算价
	SettlementPrice: Double;
	///涨停板价
	UpperLimitPrice: Double;
	///跌停板价
	LowerLimitPrice: Double;
	///最后修改时间
	UpdateTime: array[0..8] of ansichar;
	///最后修改毫秒
	UpdateMillisec: integer;
	///申买价一
	BidPrice1: Double;
	///申买量一
	BidVolume1: integer;
	///申卖价一
	AskPrice1: Double;
	///申卖量一
	AskVolume1: integer;
	///申买价二
	BidPrice2: Double;
	///申买量二
	BidVolume2: integer;
	///申卖价二
	AskPrice2: Double;
	///申卖量二
	AskVolume2: integer;
	///申买价三
	BidPrice3: Double;
	///申买量三
	BidVolume3: integer;
	///申卖价三
	AskPrice3: Double;
	///申卖量三
	AskVolume3: integer;
	///申买价四
	BidPrice4: Double;
	///申买量四
	BidVolume4: integer;
	///申卖价四
	AskPrice4: Double;
	///申卖量四
	AskVolume4: integer;
	///申买价五
	BidPrice5: Double;
	///申买量五
	BidVolume5: integer;
	///申卖价五
	AskPrice5: Double;
	///申卖量五
	AskVolume5: integer;
	///业务日期
	ActionDay: array[0..8] of ansichar;
end;
PGtjaDepthMarketDataField = ^GtjaDepthMarketDataField;

IGtjaMdAbsSpi = class
    procedure OnFrontConnected; virtual; stdcall; abstract;
    procedure OnFrontDisconnected(nReason: Integer); virtual; stdcall; abstract;
    procedure OnRspError(const pRspInfo: PGtjaMdRspInfoField; nRequestID: Integer; bIsLast: Boolean); virtual; stdcall; abstract;
    procedure OnRspUserLogin(const pRspUserLogin: PGtjaMdRspUserLoginField; const pRspInfo: PGtjaMdRspInfoField; nRequestID: Integer; bIsLast: Boolean);virtual; stdcall; abstract;
    procedure OnRtnDepthMarketData_inner(
    	const pInstrumentId: PGtjaMdInstrumentIDField;
    	const pHeader: PGtjaMdHeaderField;
    	const pTradeInfo: PGtjaMdTradeInfoField;
        const pStatic: PGtjaMdStaticInfoField;
        MBLLength: integer;
    	const pMBL: PGtjaMdMBLField);virtual; stdcall;
    procedure OnRtnSnapshotData(const pDepthMarketData: PGtjaDepthMarketDataField);virtual; stdcall; abstract;
    //此函数为另加的函数，方便使用
    procedure OnRtnDepthMarketData(
		const pInstrumentId: PGtjaMdInstrumentIDField;
		const pHeader: PGtjaMdHeaderField;
		const pTradeInfo: PGtjaMdTradeInfoField;
                const pStatic: PGtjaMdStaticInfoField;
                MBL: array of PGtjaMdMBLField); virtual; abstract;
end;

GtjaMdUserSpi = class(IGtjaMdAbsSpi)
public
  ///当客户端与交易后台建立起通信连接时（还未登录前），该方法被调用。
  procedure OnFrontConnected; override;

	///当客户端与交易后台通信连接断开时，该方法被调用。当发生这个情况后，API会自动重新连接，客户端可不做处理。
	///@param nReason 错误原因
	///        0x1001 网络读失败
	///        0x1002 网络写失败
	///        0x2001 接收心跳超时
	///        0x2002 发送心跳失败
	///        0x2003 收到错误报文
	procedure OnFrontDisconnected(nReason: Integer); override;
	///错误应答
	procedure OnRspError(const pRspInfo: PGtjaMdRspInfoField; nRequestID: Integer; bIsLast: Boolean); override;
	///登录请求响应
	procedure OnRspUserLogin(const pRspUserLogin: PGtjaMdRspUserLoginField; const pRspInfo: PGtjaMdRspInfoField; nRequestID: Integer; bIsLast: Boolean);override;
	///深度行情通知
	procedure OnRtnDepthMarketData(
		const pInstrumentId: PGtjaMdInstrumentIDField;
		const pHeader: PGtjaMdHeaderField;
		const pTradeInfo: PGtjaMdTradeInfoField;
                const pStatic: PGtjaMdStaticInfoField;
                MBL: array of PGtjaMdMBLField);override;
	procedure OnRtnSnapshotData(const pDepthMarketData: PGtjaDepthMarketDataField);override;
end;

GtjaMdUserApi = class
protected
        destructor destroy; virtual;
public
	//删除接口对象本身
	///@remark 不再使用本接口对象时,调用该函数删除接口对象
	procedure Release; virtual; stdcall; abstract;

	///初始化
	///@remark 初始化运行环境,只有调用后,接口才开始工作
	function Init: Integer; virtual; stdcall; abstract;

	///等待接口线程结束运行
	///@return 线程退出代码
	function Join: Integer; virtual; stdcall; abstract;

	///注册前置机网络地址
	///@param pszFrontAddress：前置机网络地址。
	///@remark 网络地址的格式为：“protocol://ipaddress:port”，如：”tcp://127.0.0.1:17001”。
	///@remark “tcp”代表传输协议，“127.0.0.1”代表服务器地址。”17001”代表服务器端口号。
	procedure RegisterFront(const pszFrontAddress: pansichar); virtual; stdcall; abstract;

	///注册回调接口
	///@param pSpi 派生自回调接口类的实例
	procedure RegisterSpi(pSpi: GtjaMdUserSpi); virtual; stdcall; abstract;

	///设置其它参数(预留接口)
	///@param key:参数的key。
	///@param val:参数的value。
	///@remark 该函数须在Init函数之前调用，Init之后调用无效
	procedure SetConfig(const key: pansichar; const val: pansichar); virtual; stdcall; abstract;

	///用户登录请求
	function ReqUserLogin(const pReqUserLoginField: PGtjaMdReqUserLoginField; nRequestID: Integer): Integer; virtual; stdcall; abstract;

end;
PGtjaMdUserApi = ^GtjaMdUserApi;

//创建实例
function CreateMdUserApi(const logPath: pansichar): GtjaMdUserApi; stdcall; external 'GtjaMdUserApi.dll' name 'CreateMdUserApi';

implementation
destructor GtjaMdUserApi.destroy;
begin
end;

procedure GtjaMdUserSpi.OnFrontConnected;
begin
end;

procedure GtjaMdUserSpi.OnFrontDisconnected(nReason: Integer);
begin
end;

procedure GtjaMdUserSpi.OnRspError(const pRspInfo: PGtjaMdRspInfoField; nRequestID: Integer; bIsLast: Boolean);
begin
end;

procedure GtjaMdUserSpi.OnRspUserLogin(const pRspUserLogin: PGtjaMdRspUserLoginField; const pRspInfo: PGtjaMdRspInfoField; nRequestID: Integer; bIsLast: Boolean);
begin
end;
procedure GtjaMdUserSpi.OnRtnDepthMarketData(
	const pInstrumentId: PGtjaMdInstrumentIDField;
	const pHeader: PGtjaMdHeaderField;
	const pTradeInfo: PGtjaMdTradeInfoField;
        const pStatic: PGtjaMdStaticInfoField;
        MBL: array of PGtjaMdMBLField);
begin
end;
procedure IGtjaMdAbsSpi.OnRtnDepthMarketData_inner(
	const pInstrumentId: PGtjaMdInstrumentIDField;
	const pHeader: PGtjaMdHeaderField;
	const pTradeInfo: PGtjaMdTradeInfoField;
        const pStatic: PGtjaMdStaticInfoField;
        MBLLength: integer;
	const pMBL: PGtjaMdMBLField);
var
mbl: array of PGtjaMdMBLField;
i: integer;
begin
  if (MBLLength > 0) and (pMBL <> nil) then
  begin
    SetLength(mbl,MBLLength);
    for i := 0 to MBLLength-1 do
    begin
        mbl[i] := PGtjaMdMBLField(integer(pMBL)+sizeof(GtjaMdMBLField)*i);
    end;
  end;
  OnRtnDepthMarketData(pInstrumentId,pHeader,pTradeInfo,pStatic,mbl);
  SetLength(mbl,0);
end;

procedure GtjaMdUserSpi.OnRtnSnapshotData(const pDepthMarketData: PGtjaDepthMarketDataField);
begin
end;

end.
