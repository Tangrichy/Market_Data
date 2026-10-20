#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demo: 使用 pybind11 封装的国泰君安 UDP 行情 API 快速拉取实时 tick 数据。

运行前请先编译扩展模块：
    source /opt/conda/etc/profile.d/conda.sh && conda activate py39
    cd /root/private_data/trading/udpapi/pybind_gtja
    python setup.py build_ext --inplace

用法：
    python pull_data.py --front tcp://127.0.0.1:42116 --user 00000001 --password 88888888 --symbols cu2501 rb2501

运行中可在控制台输入命令：
    sub 合约1 合约2 ...    # 动态订阅
    unsub 合约1 合约2 ...  # 动态取消订阅
    exit / quit / q        # 退出程序
    help / h / ?           # 显示帮助

环境变量（与命令行等价）：
    GTJA_FRONT, GTJA_USER, GTJA_PASSWORD, GTJA_SYMBOLS, GTJA_CPU, GTJA_NO_EFVI, GTJA_LEVELS
"""
import argparse
import csv
import os
import queue
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

import gtja_udp_api


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------
def get_config():
    parser = argparse.ArgumentParser(description="拉取国泰君安 UDP 行情")
    parser.add_argument("--front", default=os.getenv("GTJA_FRONT", "tcp://114.94.154.60:21002"), help="行情前置地址") #"tcp://127.0.0.1:42116" 183.63.193.58:42116 tcp://114.94.154.60:21002
    parser.add_argument("--user", default=os.getenv("GTJA_USER", "83607651"), help="资金账号")
    parser.add_argument("--password", default=os.getenv("GTJA_PASSWORD", "88888888"), help="登录密码")
    parser.add_argument("--symbols", default=os.getenv("GTJA_SYMBOLS", "000001"), help="订阅合约，逗号分隔")
    parser.add_argument("--exchange", default=os.getenv("GTJA_EXCHANGE", ""),
                        help="指定交易所: sse/szse/shfe/dce/czce/cffex/ine/sge，空表示不指定")
    parser.add_argument("--cpu", default=os.getenv("GTJA_CPU", "1"), help="绑定 CPU 核")
    parser.add_argument("--no-efvi", action="store_true", default=os.getenv("GTJA_NO_EFVI", "").lower() == "true",
                        help="关闭 efvi 加速")
    parser.add_argument("--output", default=os.getenv("GTJA_OUTPUT", ""), help="输出 csv 文件路径，为空则只打印")
    parser.add_argument("--duration", type=int, default=int(os.getenv("GTJA_DURATION", "0")),
                        help="运行时长（秒），0 表示一直运行")
    parser.add_argument("--levels", type=int, default=int(os.getenv("GTJA_LEVELS", "5")),
                        help="CSV 中保存的盘口档位数，默认 5")
    parser.add_argument("--multi", action="store_true", help="打印时输出全部档位（默认只输出第 1 档）")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 交易所代码 → 可读前缀
# ---------------------------------------------------------------------------
EXCHANGE_NAMES = {
    gtja_udp_api._et_czce: "CZCE",
    gtja_udp_api._et_dce: "DCE",
    gtja_udp_api._et_shfe: "SHFE",
    gtja_udp_api._et_cffex: "CFFEX",
    gtja_udp_api._et_ine: "INE",
    gtja_udp_api._et_sse: "SSE",
    gtja_udp_api._et_szse: "SZSE",
    gtja_udp_api._et_sge: "SGE",
}

RTN_CODE_NAMES = {
    gtja_udp_api._rc_succ: "成功",
    gtja_udp_api._rc_invalid_connid: "非法 ConnectID",
    gtja_udp_api._rc_not_connected: "尚未连接",
    gtja_udp_api._rc_send_request_error: "发送请求失败",
    gtja_udp_api._rc_wrong_param: "参数错误",
    gtja_udp_api._rc_not_login: "尚未登录",
    gtja_udp_api._rc_not_support: "不支持此功能",
}

EXCHANGE_NAME_TO_TYPE = {
    "sse": gtja_udp_api._et_sse,
    "szse": gtja_udp_api._et_szse,
    "shfe": gtja_udp_api._et_shfe,
    "dce": gtja_udp_api._et_dce,
    "czce": gtja_udp_api._et_czce,
    "cffex": gtja_udp_api._et_cffex,
    "ine": gtja_udp_api._et_ine,
    "sge": gtja_udp_api._et_sge,
}


def build_instruments(symbols: List[str], exchange: str = ""):
    """根据合约代码和交易所构建订阅结构体数组。"""
    exch_type = EXCHANGE_NAME_TO_TYPE.get(exchange.lower(), gtja_udp_api._et_unset) if exchange else gtja_udp_api._et_unset
    insts = []
    for s in symbols:
        inst = gtja_udp_api.GtjaMdSpecificInstrumentField()
        inst.ProductType = gtja_udp_api._pt_unset
        inst.ExchangeType = exch_type
        inst.InstrumentID = s
        insts.append(inst)
    return insts


# ---------------------------------------------------------------------------
# SPI 实现
# ---------------------------------------------------------------------------
class DataSpi(gtja_udp_api.PySpi):
    def __init__(self, api: gtja_udp_api.GtjaMdUserApi, cfg):
        super().__init__()
        self.api = api
        self.cfg = cfg
        self.connected_event = threading.Event()
        self.logged_in_event = threading.Event()
        self.tick_queue: queue.Queue[dict] = queue.Queue()
        self.csv_writer = None
        self.csv_file = None
        self._csv_lock = threading.Lock()
        self._init_csv()

        # 绑定回调
        self.on_front_connected = self._on_front_connected
        self.on_front_disconnected = self._on_front_disconnected
        self.on_rsp_error = self._on_rsp_error
        self.on_rsp_user_login = self._on_rsp_user_login
        self.on_rtn_depth_snapshot = self._on_rtn_depth_snapshot
        self.on_rsp_last_snapshot = self._on_rsp_last_snapshot
        self.on_rsp_sub_market_data = self._on_rsp_sub_market_data
        self.on_rsp_unsub_market_data = self._on_rsp_unsub_market_data

    def _init_csv(self):
        if not self.cfg.output:
            return
        self.csv_file = open(self.cfg.output, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        headers = [
            "recv_time", "conn_id", "exchange", "symbol", "date", "time", "milli",
            "last_price", "volume", "turnover", "open_interest",
        ]
        for i in range(1, self.cfg.levels + 1):
            headers.extend([f"bid_price_{i}", f"bid_volume_{i}", f"ask_price_{i}", f"ask_volume_{i}"])
        headers.append("status")
        self.csv_writer.writerow(headers)
        self.csv_file.flush()

    def _on_front_connected(self, conn_id: int):
        print(f"[{conn_id}] 连接建立，发送登录请求...")
        self.connected_event.set()
        self.api.ReqUserLogin(self.cfg.user, self.cfg.password, 0, conn_id)

    def _on_front_disconnected(self, reason: int, conn_id: int):
        print(f"[{conn_id}] 连接断开，原因: 0x{reason:04X}")
        self.connected_event.clear()
        self.logged_in_event.clear()

    def _on_rsp_error(self, rsp_info, request_id: int, is_last: bool, conn_id: int):
        if rsp_info:
            print(f"[{conn_id}] 错误响应 ErrorID={rsp_info.ErrorID}, Msg={rsp_info.ErrorMsg}")
        else:
            print(f"[{conn_id}] 错误响应 (NULL)")

    def _on_rsp_user_login(self, rsp_user_login, rsp_info, request_id: int, is_last: bool, conn_id: int):
        if rsp_info and rsp_info.ErrorID:
            print(f"[{conn_id}] 登录失败: {rsp_info.ErrorID} - {rsp_info.ErrorMsg}")
            return
        print(f"[{conn_id}] 登录成功")
        self.logged_in_event.set()

    def _on_rtn_depth_snapshot(self, instrument, stamp, trade_info, base_info,
                               static_info, mbl_length: int, mbl, status, conn_id: int):
        if not instrument:
            return

        symbol = instrument.InstrumentID
        exchange_code = instrument.ExchangeType
        exchange = EXCHANGE_NAMES.get(exchange_code, f"ET{exchange_code}")

        # 时间戳解析
        dt_str = ""
        time_str = ""
        milli = ""
        if stamp:
            d = stamp.Date
            t = stamp.Time
            dt_str = f"{d.Year:04d}{d.Month:02d}{d.Day:02d}"
            time_str = f"{t.Hour:02d}:{t.Minite:02d}:{t.Seccond:02d}"
            milli = f"{t.MilliSec:03d}"

        # 成交信息
        last_price = trade_info.LastPrice if trade_info else None
        volume = trade_info.Volume if trade_info else None
        turnover = trade_info.Turnover if trade_info else None
        open_interest = trade_info.OpenInterest if trade_info else None

        # 盘口信息
        bids = []
        if mbl and mbl_length > 0:
            for i in range(mbl_length):
                bids.append({
                    "bid_price": mbl[i].BidPrice,
                    "bid_volume": mbl[i].BidVolume,
                    "ask_price": mbl[i].AskPrice,
                    "ask_volume": mbl[i].AskVolume,
                })

        # 合约状态
        status_str = ""
        if status:
            status_str = "".join(status.InstrumentStauts)

        tick = {
            "recv_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "conn_id": conn_id,
            "exchange": exchange,
            "symbol": symbol,
            "date": dt_str,
            "time": time_str,
            "milli": milli,
            "last_price": last_price,
            "volume": volume,
            "turnover": turnover,
            "open_interest": open_interest,
            "bids": bids,
            "status": status_str.strip(),
        }

        self.tick_queue.put(tick)

        # 打印
        line = (
            f"{tick['recv_time']} [{conn_id}] {exchange}.{symbol} {dt_str} {time_str}.{milli} "
            f"last={last_price} vol={volume}"
        )
        if bids:
            if self.cfg.multi:
                for i, b in enumerate(bids[:self.cfg.levels], 1):
                    line += (
                        f" L{i}:bid={b['bid_price']}/{b['bid_volume']} "
                        f"ask={b['ask_price']}/{b['ask_volume']}"
                    )
            else:
                b = bids[0]
                line += f" bid={b['bid_price']}/{b['bid_volume']} ask={b['ask_price']}/{b['ask_volume']}"
        if status_str.strip():
            line += f" status={status_str.strip()}"
        print(line)

        # 写入 CSV（写入全部 levels 档）
        if self.csv_writer:
            row = [
                tick["recv_time"], conn_id, exchange, symbol, dt_str, time_str, milli,
                last_price, volume, turnover, open_interest,
            ]
            for i in range(self.cfg.levels):
                if i < len(bids):
                    b = bids[i]
                    row.extend([b['bid_price'], b['bid_volume'], b['ask_price'], b['ask_volume']])
                else:
                    row.extend([None, None, None, None])
            row.append(status_str.strip())
            with self._csv_lock:
                self.csv_writer.writerow(row)
                self.csv_file.flush()

    def _on_rsp_last_snapshot(self, snapshot, conn_id: int):
        if snapshot:
            print(f"[{conn_id}] 快照 {snapshot.InstrumentID}: last={snapshot.LastPrice} vol={snapshot.Volume}")

    def _on_rsp_sub_market_data(self, instrument, rsp_info, request_id: int, conn_id: int):
        if instrument:
            if rsp_info and rsp_info.ErrorID:
                print(f"[{conn_id}] 订阅 {instrument.InstrumentID} 失败: {rsp_info.ErrorMsg}")
            else:
                print(f"[{conn_id}] 订阅 {instrument.InstrumentID} 成功")

    def _on_rsp_unsub_market_data(self, instrument, rsp_info, request_id: int, conn_id: int):
        if instrument:
            if rsp_info and rsp_info.ErrorID:
                print(f"[{conn_id}] 取消订阅 {instrument.InstrumentID} 失败: {rsp_info.ErrorMsg}")
            else:
                print(f"[{conn_id}] 取消订阅 {instrument.InstrumentID} 成功")

    def close(self):
        if self.csv_file:
            self.csv_file.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    cfg = get_config()
    if not cfg.user or not cfg.password:
        print("错误: 必须提供 --user 和 --password")
        sys.exit(1)

    symbols = [s.strip() for s in cfg.symbols.split(",") if s.strip()]
    if not symbols:
        print("警告: 未指定订阅合约，登录后不会收到行情。使用 --symbols 指定，逗号分隔。")

    print(f"前置地址: {cfg.front}")
    print(f"账号: {cfg.user}")
    print(f"订阅合约: {symbols}")
    print(f"CPU 绑定: {cfg.cpu}, 关闭 efvi: {cfg.no_efvi}")

    # 创建 API
    api = gtja_udp_api.GtjaMdUserApi("gtja_udp.log")
    spi = DataSpi(api, cfg)
    api.RegisterSpi(spi)

    # 配置
    api.SetConfig("cpu", cfg.cpu)
    if cfg.no_efvi:
        api.SetConfig("efvi", "false")

    # 注册行情源并启动
    conn_id = api.RegisterFront(cfg.front)
    print(f"RegisterFront 返回 ConnectID={conn_id}")
    if conn_id < 0:
        print("RegisterFront 失败")
        sys.exit(1)

    api.Init()

    # 等待连接+登录（带超时）
    if not spi.connected_event.wait(timeout=10):
        print("错误: 10 秒内未连接上行情前置")
        sys.exit(1)
    if not spi.logged_in_event.wait(timeout=10):
        print("错误: 10 秒内未完成登录")
        sys.exit(1)

    # 查询是否支持订阅
    supports_sub = api.QueryFunction(gtja_udp_api._FF_SUPPORT_SUB_MD, conn_id)
    print(f"前置是否支持订阅: {supports_sub}")

    # 订阅合约
    subscribed_symbols = set(symbols)
    if symbols:
        if supports_sub:
            insts = build_instruments(symbols, cfg.exchange)
            ret = api.ReqSubMarketData(insts, 0, conn_id)
            if ret != gtja_udp_api._rc_succ:
                print(f"ReqSubMarketData 返回错误码: {ret} ({RTN_CODE_NAMES.get(ret, '未知')})")
        else:
            print("当前模式（组播/广播）不支持订阅，行情将自动推送")

    # -----------------------------------------------------------------------
    # 交互式命令线程：支持 sub / unsub / exit
    # -----------------------------------------------------------------------
    stop_event = threading.Event()
    api_call_lock = threading.Lock()

    def _send_sub(syms: list):
        if not syms:
            return
        insts = build_instruments(syms, cfg.exchange)
        with api_call_lock:
            ret = api.ReqSubMarketData(insts, 0, conn_id)
        if ret != gtja_udp_api._rc_succ:
            print(f"ReqSubMarketData 返回错误码: {ret} ({RTN_CODE_NAMES.get(ret, '未知')})")
        else:
            subscribed_symbols.update(syms)
            print(f"已发送订阅: {syms}")

    def _send_unsub(syms: list):
        if not syms:
            return
        insts = build_instruments(syms, cfg.exchange)
        with api_call_lock:
            ret = api.ReqUnSubMarketData(insts, 0, conn_id)
        if ret != gtja_udp_api._rc_succ:
            print(f"ReqUnSubMarketData 返回错误码: {ret} ({RTN_CODE_NAMES.get(ret, '未知')})")
        else:
            subscribed_symbols.difference_update(syms)
            print(f"已发送取消订阅: {syms}")

    def command_loop():
        print("命令行已就绪。输入: sub 合约1 合约2 | unsub 合约1 合约2 | exit")
        while not stop_event.is_set():
            try:
                line = input().strip()
            except EOFError:
                # 非交互式环境或输入关闭，直接退出命令线程
                break
            except Exception as e:
                print(f"读取命令出错: {e}")
                break
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]
            if cmd in ("exit", "quit", "q"):
                print("收到退出命令...")
                stop_event.set()
                break
            elif cmd in ("sub", "subscribe"):
                _send_sub(args)
            elif cmd in ("unsub", "unsubscribe"):
                _send_unsub(args)
            elif cmd in ("help", "h", "?"):
                print("命令: sub 合约1 合约2 | unsub 合约1 合约2 | exit | help")
            else:
                print(f"未知命令: {cmd}。输入 help 查看支持命令。")

    if sys.stdin.isatty():
        cmd_thread = threading.Thread(target=command_loop, daemon=True)
        cmd_thread.start()
    else:
        print("非交互式环境，命令行功能已禁用（可用 Ctrl+C 或 --duration 退出）")

    # 运行主循环
    start = time.time()
    tick_count = 0
    try:
        while not stop_event.is_set():
            try:
                tick = spi.tick_queue.get(timeout=1)
                tick_count += 1
            except queue.Empty:
                pass

            if cfg.duration > 0 and (time.time() - start) >= cfg.duration:
                print(f"运行达到 {cfg.duration} 秒，退出。共收到 {tick_count} 条 tick。")
                break
    except KeyboardInterrupt:
        print(f"\n用户中断。共收到 {tick_count} 条 tick。")
    finally:
        stop_event.set()
        if subscribed_symbols and supports_sub:
            _send_unsub(list(subscribed_symbols))
            time.sleep(0.5)
        api.Release()
        spi.close()


if __name__ == "__main__":
    main()
