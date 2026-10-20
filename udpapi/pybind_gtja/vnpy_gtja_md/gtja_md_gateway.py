#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
国泰君安 UDP 行情接口的 vn.py 3.x Gateway 封装。

仅封装行情（MdApi），不含交易接口。

用法示例:
    from vnpy.event import EventEngine
    from vnpy.trader.engine import MainEngine
    from vnpy_gtja_md import GtjaMdGateway

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(GtjaMdGateway)

    setting = {
        "front": "tcp://114.94.154.60:21002",
        "user": "00000001",
        "password": "88888888",
        "cpu": "1",
        "efvi": "true",
        "exchange": "",
    }
    main_engine.connect(setting, "GTJA_UDP_MD")

    # 订阅
    from vnpy.trader.object import SubscribeRequest
    from vnpy.trader.constant import Exchange
    req = SubscribeRequest(symbol="cu2501", exchange=Exchange.SHFE)
    main_engine.subscribe(req, "GTJA_UDP_MD")
"""
import threading
from datetime import datetime
from typing import Dict, List, Optional, Set

from vnpy.event import EventEngine
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    SubscribeRequest,
    TickData,
    LogData,
)
from vnpy.trader.constant import Exchange

import gtja_udp_api


# ---------------------------------------------------------------------------
# 交易所映射
# ---------------------------------------------------------------------------
EXCHANGE_GTJA2VN: Dict[int, Exchange] = {
    gtja_udp_api._et_czce: Exchange.CZCE,
    gtja_udp_api._et_dce: Exchange.DCE,
    gtja_udp_api._et_shfe: Exchange.SHFE,
    gtja_udp_api._et_cffex: Exchange.CFFEX,
    gtja_udp_api._et_ine: Exchange.INE,
    gtja_udp_api._et_sse: Exchange.SSE,
    gtja_udp_api._et_szse: Exchange.SZSE,
    gtja_udp_api._et_sge: Exchange.SGE,
}

EXCHANGE_VN2GTJA: Dict[Exchange, int] = {v: k for k, v in EXCHANGE_GTJA2VN.items()}

RTN_CODE_NAMES: Dict[int, str] = {
    gtja_udp_api._rc_succ: "成功",
    gtja_udp_api._rc_invalid_connid: "非法 ConnectID",
    gtja_udp_api._rc_not_connected: "尚未连接",
    gtja_udp_api._rc_send_request_error: "发送请求失败",
    gtja_udp_api._rc_wrong_param: "参数错误",
    gtja_udp_api._rc_not_login: "尚未登录",
    gtja_udp_api._rc_not_support: "不支持此功能",
}


def _format_rtn_code(code: int) -> str:
    """格式化返回码。"""
    return f"{code} ({RTN_CODE_NAMES.get(code, '未知')})"


def _parse_datetime(stamp) -> Optional[datetime]:
    """将 GTJA 时间戳解析为 Python datetime。"""
    if not stamp:
        return None
    d = stamp.Date
    t = stamp.Time
    # 注意：t.Minite / t.Seccond 是底层 API 的字段拼写
    return datetime(
        year=d.Year,
        month=d.Month,
        day=d.Day,
        hour=t.Hour,
        minute=t.Minite,
        second=t.Seccond,
        microsecond=t.MilliSec * 1000,
    )


# ---------------------------------------------------------------------------
# SPI 实现
# ---------------------------------------------------------------------------
class GtjaMdSpi(gtja_udp_api.PySpi):
    """国泰君安 UDP 行情 SPI。"""

    def __init__(self, gateway: "GtjaMdGateway"):
        super().__init__()
        self.gateway: GtjaMdGateway = gateway

        self.connected: bool = False
        self.logged_in: bool = False
        self.tick_count: int = 0
        self._connect_event: threading.Event = threading.Event()
        self._login_event: threading.Event = threading.Event()

        # 绑定回调
        self.on_front_connected = self._on_front_connected
        self.on_front_disconnected = self._on_front_disconnected
        self.on_rsp_error = self._on_rsp_error
        self.on_rsp_user_login = self._on_rsp_user_login
        self.on_rtn_depth_snapshot = self._on_rtn_depth_snapshot
        self.on_rsp_last_snapshot = self._on_rsp_last_snapshot
        self.on_rsp_sub_market_data = self._on_rsp_sub_market_data
        self.on_rsp_unsub_market_data = self._on_rsp_unsub_market_data

    # ------------------------------------------------------------------
    def _on_front_connected(self, conn_id: int):
        self.connected = True
        self._connect_event.set()
        self.gateway.write_log(f"[{conn_id}] 行情前置已连接，发送登录请求")
        self.gateway.api.ReqUserLogin(
            self.gateway.user,
            self.gateway.password,
            0,
            conn_id,
        )

    def _on_front_disconnected(self, reason: int, conn_id: int):
        self.connected = False
        self.logged_in = False
        self._connect_event.clear()
        self._login_event.clear()
        self.gateway.write_log(f"[{conn_id}] 行情前置已断开，原因: 0x{reason:04X}")

    def _on_rsp_error(self, rsp_info, request_id: int, is_last: bool, conn_id: int):
        if rsp_info:
            self.gateway.write_log(
                f"[{conn_id}] 错误响应 ErrorID={rsp_info.ErrorID}, Msg={rsp_info.ErrorMsg}"
            )
        else:
            self.gateway.write_log(f"[{conn_id}] 错误响应 (NULL)")

    def _on_rsp_user_login(self, rsp_user_login, rsp_info, request_id: int, is_last: bool, conn_id: int):
        if rsp_info and rsp_info.ErrorID:
            self.gateway.write_log(
                f"[{conn_id}] 登录失败: {rsp_info.ErrorID} - {rsp_info.ErrorMsg}"
            )
            return
        self.logged_in = True
        self._login_event.set()
        self.gateway.write_log(f"[{conn_id}] 登录成功")

    def _on_rtn_depth_snapshot(self, instrument, stamp, trade_info, base_info,
                               static_info, mbl_length: int, mbl, status, conn_id: int):
        try:
            self.tick_count += 1
            # 每 100 条以及第一条 tick 写日志，便于排查
            if self.tick_count == 1 or self.tick_count % 100 == 0:
                self.gateway.write_log(
                    f"[{conn_id}] 累计收到 {self.tick_count} 条深度快照"
                )

            if not instrument:
                self.gateway.write_log(f"[{conn_id}] 深度快照 instrument 为空，忽略")
                return

            exchange: Exchange = EXCHANGE_GTJA2VN.get(instrument.ExchangeType, Exchange.LOCAL)
            symbol: str = instrument.InstrumentID

            dt: datetime = _parse_datetime(stamp) or datetime.now()

            tick: TickData = TickData(
                symbol=symbol,
                exchange=exchange,
                datetime=dt,
                gateway_name=self.gateway.gateway_name,
            )

            if trade_info:
                tick.last_price = trade_info.LastPrice
                tick.volume = trade_info.Volume
                tick.turnover = trade_info.Turnover
                tick.open_interest = trade_info.OpenInterest

            # 盘口：vn.py 标准支持 5 档
            if mbl and mbl_length > 0:
                depth: int = min(mbl_length, 5)
                for i in range(depth):
                    entry = mbl[i]
                    setattr(tick, f"bid_price_{i + 1}", entry.BidPrice)
                    setattr(tick, f"bid_volume_{i + 1}", entry.BidVolume)
                    setattr(tick, f"ask_price_{i + 1}", entry.AskPrice)
                    setattr(tick, f"ask_volume_{i + 1}", entry.AskVolume)

            self.gateway.on_tick(tick)
        except Exception as e:
            self.gateway.write_log(f"[{conn_id}] tick 处理异常: {e}")

    def _on_rsp_last_snapshot(self, snapshot, conn_id: int):
        if snapshot:
            self.gateway.write_log(
                f"[{conn_id}] 收到快照 {snapshot.InstrumentID}: last={snapshot.LastPrice} vol={snapshot.Volume}"
            )

    def _on_rsp_sub_market_data(self, instrument, rsp_info, request_id: int, conn_id: int):
        if not instrument:
            return
        symbol: str = instrument.InstrumentID
        if rsp_info and rsp_info.ErrorID:
            self.gateway.write_log(f"[{conn_id}] 订阅 {symbol} 失败: {rsp_info.ErrorMsg}")
        else:
            self.gateway.write_log(f"[{conn_id}] 订阅 {symbol} 成功")

    def _on_rsp_unsub_market_data(self, instrument, rsp_info, request_id: int, conn_id: int):
        if not instrument:
            return
        symbol: str = instrument.InstrumentID
        if rsp_info and rsp_info.ErrorID:
            self.gateway.write_log(f"[{conn_id}] 取消订阅 {symbol} 失败: {rsp_info.ErrorMsg}")
        else:
            self.gateway.write_log(f"[{conn_id}] 取消订阅 {symbol} 成功")

    # ------------------------------------------------------------------
    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self._connect_event.wait(timeout)

    def wait_logged_in(self, timeout: float = 10.0) -> bool:
        return self._login_event.wait(timeout)


# ---------------------------------------------------------------------------
# Gateway 实现
# ---------------------------------------------------------------------------
class GtjaMdGateway(BaseGateway):
    """
    国泰君安 UDP 行情 Gateway。
    """

    default_name: str = "GTJA_UDP_MD"

    default_setting: Dict[str, str] = {
        "front": "",
        "user": "",
        "password": "",
        "cpu": "1",
        "efvi": "true",
        "exchange": "",
    }

    exchanges: List[Exchange] = list(EXCHANGE_GTJA2VN.values())

    def __init__(self, event_engine: EventEngine, gateway_name: str):
        """"""
        super().__init__(event_engine, gateway_name)

        self.api: Optional[gtja_udp_api.GtjaMdUserApi] = None
        self.spi: Optional[GtjaMdSpi] = None
        self.conn_id: int = -1

        self.user: str = ""
        self.password: str = ""
        self.default_exchange: str = ""
        self.cpu: str = "1"
        self.efvi: bool = True

        self._subscribed: Set[str] = set()
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    def connect(self, setting: dict) -> None:
        """连接行情前置。"""
        front: str = setting.get("front", "").strip()
        self.user = setting.get("user", "").strip()
        self.password = setting.get("password", "").strip()
        self.default_exchange = setting.get("exchange", "").strip()
        self.cpu = setting.get("cpu", "1").strip() or "1"
        self.efvi = str(setting.get("efvi", "true")).lower() == "true"

        if not front:
            self.write_log("连接失败: 行情前置地址(front)不能为空")
            return

        self.api = gtja_udp_api.GtjaMdUserApi("gtja_udp.log")
        self.spi = GtjaMdSpi(self)
        self.api.RegisterSpi(self.spi)

        self.api.SetConfig("cpu", self.cpu)
        if not self.efvi:
            self.api.SetConfig("efvi", "false")

        self.conn_id = self.api.RegisterFront(front)
        if self.conn_id < 0:
            self.write_log(f"RegisterFront 失败，返回: {self.conn_id}")
            return

        self.write_log(f"正在连接 {front} ...")
        self.api.Init()

        if not self.spi.wait_connected(10):
            self.write_log("连接行情前置超时")
            return
        if not self.spi.wait_logged_in(10):
            self.write_log("登录行情前置超时")
            return

        self.write_log("行情网关连接并登录成功")

    def close(self) -> None:
        """关闭行情网关。"""
        if not self.api:
            return

        # 取消已订阅合约
        with self._lock:
            for vt_symbol in list(self._subscribed):
                symbol = vt_symbol.split(".")[0]
                insts = self._build_instruments([symbol])
                self.api.ReqUnSubMarketData(insts, 0, self.conn_id)
            self._subscribed.clear()

        self.api.Release()
        self.api = None
        self.spi = None
        self.conn_id = -1
        self.write_log("行情网关已关闭")

    def subscribe(self, req: SubscribeRequest) -> None:
        """订阅合约行情。"""
        if not self.spi or not self.spi.logged_in:
            self.write_log("订阅失败: 行情网关尚未登录")
            return

        insts = self._build_instruments([req.symbol], req.exchange)
        with self._lock:
            ret = self.api.ReqSubMarketData(insts, 0, self.conn_id)
        if ret != gtja_udp_api._rc_succ:
            self.write_log(f"订阅 {req.vt_symbol} 失败，返回值: {_format_rtn_code(ret)}")
        else:
            self._subscribed.add(req.vt_symbol)

    # ------------------------------------------------------------------
    # 以下接口为纯行情网关保留空实现 / 安全返回
    # ------------------------------------------------------------------
    def send_order(self, req) -> str:
        """本网关不支持交易。"""
        self.write_log("GTJA_UDP_MD 为纯行情网关，不支持下单")
        return ""

    def cancel_order(self, req) -> None:
        """本网关不支持交易。"""
        self.write_log("GTJA_UDP_MD 为纯行情网关，不支持撤单")

    def query_account(self) -> None:
        """本网关不查询账户。"""
        pass

    def query_position(self) -> None:
        """本网关不查询持仓。"""
        pass

    # ------------------------------------------------------------------
    def _build_instruments(self, symbols: List[str], exchange: Optional[Exchange] = None):
        """根据合约代码和交易所构建订阅结构体数组。"""
        exch_type = gtja_udp_api._et_unset

        # 优先使用请求中指定的交易所
        if exchange and exchange in EXCHANGE_VN2GTJA:
            exch_type = EXCHANGE_VN2GTJA[exchange]
        # 否则使用默认交易所配置
        elif self.default_exchange:
            default_ex = Exchange(self.default_exchange.upper())
            exch_type = EXCHANGE_VN2GTJA.get(default_ex, gtja_udp_api._et_unset)

        insts = []
        for s in symbols:
            inst = gtja_udp_api.GtjaMdSpecificInstrumentField()
            inst.ProductType = gtja_udp_api._pt_unset
            inst.ExchangeType = exch_type
            inst.InstrumentID = s
            insts.append(inst)
        return insts
