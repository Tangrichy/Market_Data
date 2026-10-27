#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demo: 使用 pybind11 封装的国泰君安 UDP 行情 API 快速拉取沪深股票实时 tick 数据。

本工具仅用于股票行情（上交所/深交所），不支持期货合约。

运行前请先编译扩展模块：
    source /opt/conda/etc/profile.d/conda.sh && conda activate py39
    cd /root/private_data/Market_Data/pybind_gtja
    python setup.py build_ext --inplace

用法：
    python pull_data.py --front tcp://183.193.54.200:21002 --user 00000001 --password 88888888 --symbols 600000,688027 --exchange sse

运行中可在控制台输入命令：
    sub 代码1 代码2 ...    # 动态订阅（仅股票）
    unsub 代码1 代码2 ...  # 动态取消订阅
    exit / quit / q        # 退出程序
    help / h / ?           # 显示帮助

环境变量（与命令行等价）：
    GTJA_FRONT, GTJA_USER, GTJA_PASSWORD, GTJA_SYMBOLS, GTJA_EXCHANGE,
    GTJA_CPU, GTJA_NO_EFVI, GTJA_OUTPUT, GTJA_DURATION, GTJA_LEVELS,
    GTJA_RELEASE_TIMEOUT
"""
import argparse
import csv
import glob
import os
import queue
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

try:
    import gtja_udp_api
except ImportError as _exc:
    # 扩展的 ABI 标签必须是 cpython-<版本>，与解释器不一致时 Python 会直接
    # 忽略该 .so 并报 ModuleNotFoundError。这里扫描同目录找出实际编译版本，
    # 给出明确指引（3.9 / 3.12 等任意版本通用）。
    _here = os.path.dirname(os.path.abspath(__file__))
    _built = sorted(
        os.path.basename(_p)[len("gtja_udp_api."):-len(".so")]
        for _p in glob.glob(os.path.join(_here, "gtja_udp_api*.so"))
    )
    _want = "cpython-%d%d" % sys.version_info[:2]

    _lines = [
        "导入 gtja_udp_api 失败：%s" % _exc,
        "当前解释器：Python %s（%s）" % (sys.version.split()[0], sys.executable),
    ]
    if _built:
        _lines.append("目录中已有扩展：%s" % "、".join(_built))
        if not any(_want in _tag for _tag in _built):
            _lines.append(
                "→ ABI 不匹配：已有扩展是为 %s 编译的，当前解释器需要 %s。\n"
                "  方案一：改用匹配的解释器运行（如 /opt/conda/envs/py39/bin/python）；\n"
                "  方案二：在当前解释器下重新编译（推荐，见下）。" % (_built[0], _want)
            )
        else:
            _lines.append(
                "→ ABI 匹配但加载失败，通常是找不到动态库 libGtjaMdUserApi.so，"
                "或编译用的 Python 与当前解释器不是同一个。"
            )
    else:
        _lines.append("→ 未找到任何 gtja_udp_api*.so，需要先编译。")

    _lines.append(
        "在当前解释器下重新编译：\n"
        "  cd pybind_gtja && rm -rf build\n"
        "  pip install 'pybind11>=2.11.1'\n"
        "  python setup.py build_ext --inplace\n"
        "若仍报找不到 libGtjaMdUserApi.so：\n"
        "  export LD_LIBRARY_PATH=<仓库根目录>/udpapi/Linux64/gcc9.3.1:$LD_LIBRARY_PATH"
    )
    sys.exit("\n".join(_lines))


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------
def get_config():
    parser = argparse.ArgumentParser(description="拉取国泰君安 UDP 行情")
    parser.add_argument("--front", default=os.getenv("GTJA_FRONT", "tcp://114.94.154.60:21002"), help="行情前置地址") #"tcp://127.0.0.1:42116" 183.63.193.58:42116 tcp://114.94.154.60:21002
    parser.add_argument("--user", default=os.getenv("GTJA_USER", "83607651"), help="资金账号")
    parser.add_argument("--password", default=os.getenv("GTJA_PASSWORD", "88888888"), help="登录密码")
    parser.add_argument("--symbols", default=os.getenv("GTJA_SYMBOLS", "000001"),
                        help="订阅股票代码（6 位数字），逗号分隔")
    parser.add_argument("--exchange", default=os.getenv("GTJA_EXCHANGE", ""),
                        help="指定交易所: sse/szse（本工具仅支持股票），空表示不指定")
    parser.add_argument("--cpu", default=os.getenv("GTJA_CPU", "1"), help="绑定 CPU 核")
    parser.add_argument("--no-efvi", action="store_true", default=os.getenv("GTJA_NO_EFVI", "").lower() == "true",
                        help="关闭 efvi 加速")
    parser.add_argument("--output", default=os.getenv("GTJA_OUTPUT", ""), help="输出 csv 文件路径，为空则只打印")
    parser.add_argument("--duration", type=int, default=int(os.getenv("GTJA_DURATION", "0")),
                        help="运行时长（秒），0 表示一直运行")
    parser.add_argument("--levels", type=int, default=int(os.getenv("GTJA_LEVELS", "5")),
                        help="CSV 中保存的盘口档位数，默认 5")
    parser.add_argument("--multi", action="store_true", help="打印时输出全部档位（默认只输出第 1 档）")
    parser.add_argument("--release-timeout", type=int,
                        default=int(os.getenv("GTJA_RELEASE_TIMEOUT", "5000")),
                        help="Release 的有界等待（毫秒）：超时后中断 SDK 收包线程的 select 等待；"
                             "<=0 表示沿用原始的无限等待")
    parser.add_argument("--shutdown", choices=("vendor", "worker", "concurrent", "legacy"),
                        default=os.getenv("GTJA_SHUTDOWN", "vendor"),
                        help="停止顺序：vendor=独立线程退订→主线程Join→Release（厂商建议字面顺序）；"
                             "worker=独立线程内退订+Release、主线程Join等待；"
                             "concurrent=独立线程退订并立即 Release；"
                             "legacy=主线程退订→等待0.5s→Release（原始演示顺序）")
    parser.add_argument("--join-timeout", type=int,
                        default=int(os.getenv("GTJA_JOIN_TIMEOUT", "5000")),
                        help="vendor 顺序中 Join 的有界等待（毫秒），超时后转用有界 Release 收尾；"
                             "<=0 表示无限等待（用于复现原生阻塞）")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 交易所代码 → 可读前缀（仅股票：上交所/深交所）
# ---------------------------------------------------------------------------
EXCHANGE_NAMES = {
    gtja_udp_api._et_sse: "SSE",
    gtja_udp_api._et_szse: "SZSE",
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
}


def validate_stock_symbols(symbols: List[str]) -> List[str]:
    """返回不符合沪深股票代码规则（6 位数字）的合约。"""
    return [s for s in symbols if not (len(s) == 6 and s.isdigit())]


def build_instruments(symbols: List[str], exchange: str = ""):
    """根据股票代码和交易所构建订阅结构体数组（仅上交所/深交所）。"""
    exch_type = EXCHANGE_NAME_TO_TYPE.get(exchange.lower(), gtja_udp_api._et_unset) if exchange else gtja_udp_api._et_unset
    insts = []
    for s in symbols:
        inst = gtja_udp_api.GtjaMdSpecificInstrumentField()
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
# 停止顺序
#
# SDK 的停止标志只有 Release() 会写；收包线程在循环开头检查该标志，因此它
# 必须先从一个无超时的 select() 返回才能观察到停止。Join() 本身不设标志，
# 只是等待收包线程结束，所以 Join 能否返回取决于当时是否有报文/信号唤醒。
#
# 本工具提供三种顺序，均以有界调用收尾，保证进程总能退出：
#   vendor      独立线程发退订 → 主线程 Join → Release（厂商反馈建议）
#   concurrent  独立线程发退订 → 立即 Release（不为退订应答留等待窗口）
#   legacy      主线程发退订 → 等待 0.5s → Release（Issue.md 描述的演示顺序）
# ---------------------------------------------------------------------------
def _release(api, cfg, tick_count: int):
    print(f"[stage] before_Release ticks={tick_count}", flush=True)
    timeout_ms = cfg.release_timeout
    if timeout_ms > 0 and hasattr(api, "ReleaseWithTimeout"):
        elapsed = api.ReleaseWithTimeout(timeout_ms)
        print(f"[stage] after_Release elapsed_ms={elapsed} "
              f"wakeups={api.LastReleaseWakeups} abandoned={api.LastReleaseAbandoned}",
              flush=True)
        return not api.LastReleaseAbandoned
    if not hasattr(api, "ReleaseWithTimeout"):
        print("警告: 当前扩展不支持 ReleaseWithTimeout（可能是旧版本），"
              "Release 可能不返回；请按 README 重新编译扩展。", flush=True)
    api.Release()
    print("[stage] after_Release", flush=True)
    return True


def _join_with_timeout(api, timeout_ms: int) -> bool:
    """在独立线程里调用 Join()，最多等待 timeout_ms；返回 Join 是否已返回。

    Join 不会写停止标志，所以除非收包线程已经结束，它不会返回。超时后这个
    守护线程会一直等在 pthread_join 里，随后的 Release 会另设标志并再次
    Join 同一个线程对象，两条等待在收包线程退出时一起返回。
    """
    done = threading.Event()

    def _join():
        try:
            api.Join()
        except Exception as exc:  # 记录后继续，不改变后续 Release 的行为
            print(f"Join 异常: {exc}", flush=True)
        finally:
            done.set()

    threading.Thread(target=_join, name="sdk-join", daemon=True).start()
    return done.wait(timeout_ms / 1000.0) if timeout_ms > 0 else (api.Join() is not None)


def _unsub_in_thread(send_unsub, symbols: List[str]):
    print("[stage] before_ReqUnSubMarketData", flush=True)
    thread = threading.Thread(target=send_unsub, args=(list(symbols),),
                              name="unsub", daemon=True)
    thread.start()
    print(f"[stage] after_ReqUnSubMarketData (thread started, alive={thread.is_alive()})",
          flush=True)
    return thread


def shutdown(cfg, api, symbols, supports_sub: bool, tick_count: int, send_unsub) -> None:
    order = cfg.shutdown
    print(f"[stage] shutdown_order={order}", flush=True)
    can_unsub = bool(symbols) and supports_sub

    if order == "vendor":
        if can_unsub:
            unsub_thread = _unsub_in_thread(send_unsub, symbols)
        else:
            unsub_thread = None
        print(f"[stage] before_Join timeout_ms={cfg.join_timeout}", flush=True)
        joined = _join_with_timeout(api, cfg.join_timeout)
        if joined:
            print("[stage] after_Join ok", flush=True)
        else:
            print(f"[stage] after_Join TIMEOUT after {cfg.join_timeout}ms "
                  f"(unsub_alive={unsub_thread.is_alive() if unsub_thread else None})", flush=True)
        _release(api, cfg, tick_count)
        return

    if order == "concurrent":
        if can_unsub:
            _unsub_in_thread(send_unsub, symbols)
        _release(api, cfg, tick_count)
        return

    if order == "worker":
        # 另一种读法：退订和 Release 都在工作线程里背靠背执行，主线程只负责
        # Join 等待 SDK 收包线程结束。
        def _worker():
            if can_unsub:
                send_unsub(list(symbols))
            _release(api, cfg, tick_count)

        worker = threading.Thread(target=_worker, name="shutdown", daemon=True)
        print("[stage] before_shutdown_worker", flush=True)
        worker.start()
        print(f"[stage] before_Join timeout_ms={cfg.join_timeout}", flush=True)
        if _join_with_timeout(api, cfg.join_timeout):
            print("[stage] after_Join ok", flush=True)
        else:
            print(f"[stage] after_Join TIMEOUT after {cfg.join_timeout}ms", flush=True)
        return

    # legacy：主线程退订并等待 0.5 秒后再 Release
    if can_unsub:
        print("[stage] before_ReqUnSubMarketData", flush=True)
        send_unsub(list(symbols))
        print("[stage] after_ReqUnSubMarketData", flush=True)
        time.sleep(0.5)
    _release(api, cfg, tick_count)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    cfg = get_config()
    print("[stage] before_main", flush=True)
    cfg.exchange = cfg.exchange.strip().lower()
    if cfg.exchange and cfg.exchange not in EXCHANGE_NAME_TO_TYPE:
        print("错误: 本工具仅支持股票，--exchange 只能为 sse 或 szse")
        sys.exit(2)

    if not cfg.user or not cfg.password:
        print("错误: 必须提供 --user 和 --password")
        sys.exit(1)

    symbols = [s.strip() for s in cfg.symbols.split(",") if s.strip()]
    invalid = validate_stock_symbols(symbols)
    if invalid:
        print(f"错误: 本工具仅支持沪深股票代码（6 位数字），不支持: {', '.join(invalid)}")
        sys.exit(2)
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
        invalid = validate_stock_symbols(syms)
        if invalid:
            print(f"仅支持沪深股票代码（6 位数字），已忽略: {', '.join(invalid)}")
            syms = [s for s in syms if s not in invalid]
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
        print("命令行已就绪。输入: sub 股票代码... | unsub 股票代码... | exit")
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
                print("命令: sub 股票代码... | unsub 股票代码... | exit | help（仅支持沪深股票）")
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
        # The SDK's Release() joins a receive thread parked in an untimed
        # select(), so it only returns once that select() returns. The chosen
        # shutdown order decides what is expected to wake it; every path is
        # bounded so the process still exits.
        shutdown(cfg, api, subscribed_symbols, supports_sub, tick_count, _send_unsub)
        spi.close()
        print("[stage] after_spi_close", flush=True)


if __name__ == "__main__":
    main()
