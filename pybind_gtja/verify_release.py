#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 SDK V3.7.1.1 验证 Release() 能否正常返回（Issue: Release 阻塞）。

背景见仓库根目录 Issue.md：V3.7.0.6 的接收线程停在无超时 pselect6，
Release() 写停止标志后 pthread_join 一直等下去。V3.7.1.1 实测会在
Release 时主动唤醒接收线程并打印 "Recv thread stopped."。

三种不需要账号/行情的场景：
    offline  不注册前置、不登录，Init 后直接 Release
    silent   本机起一个只 accept、不发数据的 TCP 服务端，连上后再 Release
    cycles   连续创建/初始化/释放 N 次，检查线程与句柄不残留

外加一个需要交易时段和账号的场景：
    live     真实前置，连接登录、收数、退订后 Release

用法：
    python verify_release.py                 # 依次跑 offline/silent/cycles
    python verify_release.py --mode silent
    python verify_release.py --mode live --front tcp://... --user ... --password ...
    python verify_release.py --stop-at 5     # Release 本身不设超时，只限整体时间

退出码：0 = 全部通过；3 = 有场景未在期限内返回；2 = 环境/参数问题。
"""
import argparse
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtja_udp_api as gtja


def nthreads():
    return len(os.listdir("/proc/self/task"))


def new_api(log_path):
    api = gtja.GtjaMdUserApi(log_path)
    spi = gtja.PySpi()
    spi.on_rsp_user_login = lambda *a: None
    api.RegisterSpi(spi)
    api.SetConfig("cpu", "1")
    api.SetConfig("efvi", "false")
    return api, spi


def timed_release(api, label, limit_s):
    """在独立线程里调用 Release，超时可判定但不会中断它。"""
    print("%s before_Release threads=%d" % (label, nthreads()), flush=True)
    t0 = time.time()
    done = threading.Event()

    def run():
        api.Release()
        done.set()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    ok = done.wait(limit_s)
    if not ok:
        print("%s after_Release MISSING (still blocked after %.1fs)" % (label, limit_s), flush=True)
        return False
    print("%s after_Release %.1f ms threads=%d"
          % (label, (time.time() - t0) * 1000, nthreads()), flush=True)
    return True


def silent_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(4)
    s.settimeout(0.2)
    port = s.getsockname()[1]
    holding = []

    def serve():
        end = time.time() + 120
        while time.time() < end:
            try:
                c, _ = s.accept()
                holding.append(c)  # accept 后保持连接，不发送任何数据
            except socket.timeout:
                pass
            except OSError:
                break

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    return port, s


def run_offline(log_path, limit_s):
    api, _ = new_api(log_path)
    rc = api.Init()
    print("offline Init rc=%s threads=%d" % (rc, nthreads()), flush=True)
    if rc != 0:
        return False
    time.sleep(1.0)
    return timed_release(api, "offline", limit_s)


def run_silent(log_path, limit_s):
    port, srv = silent_server()
    api, _ = new_api(log_path)
    rc = api.RegisterFront("tcp://127.0.0.1:%d" % port)
    print("silent RegisterFront rc=%s port=%d" % (rc, port), flush=True)
    rc = api.Init()
    print("silent Init rc=%s threads=%d" % (rc, nthreads()), flush=True)
    if rc != 0:
        return False
    time.sleep(1.5)  # 让 SDK 完成 connect 并停在 select
    ok = timed_release(api, "silent", limit_s)
    srv.close()
    return ok


def run_cycles(log_path, limit_s, count):
    spi = None
    ok = True
    for i in range(count):
        api = gtja.GtjaMdUserApi(log_path)
        if spi is None:
            spi = gtja.PySpi()
            spi.on_rsp_user_login = lambda *a: None
        api.RegisterSpi(spi)
        api.SetConfig("cpu", "1")
        api.SetConfig("efvi", "false")
        api.Init()
        time.sleep(0.3)
        if not timed_release(api, "cycle%d" % i, limit_s):
            ok = False
            break
    print("cycles done: %d/%d ok, threads=%d" % (count if ok else -1, count, nthreads()), flush=True)
    return ok


def run_live(log_path, limit_s, front, user, password, symbols, exchange, duration):
    api, spi = new_api(log_path)
    connected = threading.Event()
    logged_in = threading.Event()
    tick_count = [0]
    sub_ok = threading.Event()

    spi.on_front_connected = lambda conn_id: connected.set()
    spi.on_rsp_user_login = lambda rsp, info, rid, last, cid: (
        logged_in.set() if not (info and info.ErrorID) else None)
    spi.on_rsp_sub_market_data = lambda inst, info, rid, cid: sub_ok.set()

    def on_tick(instrument, stamp, trade, base, static, mbl_len, mbl, status, extra, cid):
        tick_count[0] += 1
        if tick_count[0] == 1:
            print("first tick: %s ref=%s vmatch=%s iopv=%s"
                  % (instrument.InstrumentID,
                     extra.DynRefPrice if extra else None,
                     extra.VirMatch if extra else None,
                     extra.IOPV if extra else None), flush=True)

    spi.on_rtn_depth_snapshot = on_tick

    conn_id = api.RegisterFront(front)
    print("live RegisterFront rc=%s" % conn_id, flush=True)
    if conn_id < 0:
        return False
    api.Init()

    if not connected.wait(10):
        print("live: 10s 内未连接")
        return False
    print("live: 已连接，发送登录", flush=True)
    api.ReqUserLogin(user, password, 0, conn_id)
    if not logged_in.wait(10):
        print("live: 10s 内未登录成功")
        return False
    print("live: 登录成功", flush=True)

    supports_sub = api.QueryFunction(gtja._FF_SUPPORT_SUB_MD, conn_id)
    syms = [s for s in symbols.split(",") if s]
    if supports_sub and syms:
        insts = []
        for s in syms:
            inst = gtja.GtjaMdSpecificInstrumentField()
            inst.ExchangeType = gtja._et_unset
            inst.ProductType = gtja._pt_unset
            inst.InstrumentID = s
            insts.append(inst)
        print("live: ReqSubMarketData rc=%s" % api.ReqSubMarketData(insts, 0, conn_id), flush=True)

    deadline = time.time() + duration
    while time.time() < deadline and tick_count[0] == 0:
        time.sleep(0.2)
    print("live: 收到 %d 条 tick" % tick_count[0], flush=True)

    if supports_sub and syms:
        insts = []
        for s in syms:
            inst = gtja.GtjaMdSpecificInstrumentField()
            inst.ExchangeType = gtja._et_unset
            inst.ProductType = gtja._pt_unset
            inst.InstrumentID = s
            insts.append(inst)
        print("live: ReqUnSubMarketData rc=%s" % api.ReqUnSubMarketData(insts, 0, conn_id), flush=True)
        time.sleep(0.5)

    return timed_release(api, "live", limit_s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="all",
                   choices=["all", "offline", "silent", "cycles", "live"])
    p.add_argument("--log", default="/tmp/gtja_verify_api.log")
    p.add_argument("--limit", type=float, default=20.0, help="每个场景等待 Release 的上限（秒）")
    p.add_argument("--cycles", type=int, default=5)
    p.add_argument("--front", default=os.getenv("GTJA_FRONT", ""))
    p.add_argument("--user", default=os.getenv("GTJA_USER", ""))
    p.add_argument("--password", default=os.getenv("GTJA_PASSWORD", ""))
    p.add_argument("--symbols", default=os.getenv("GTJA_SYMBOLS", "600000"))
    p.add_argument("--exchange", default=os.getenv("GTJA_EXCHANGE", "sse"))
    p.add_argument("--duration", type=float, default=10.0)
    cfg = p.parse_args()

    results = {}
    if cfg.mode in ("all", "offline"):
        results["offline"] = run_offline(cfg.log, cfg.limit)
    if cfg.mode in ("all", "silent"):
        results["silent"] = run_silent(cfg.log, cfg.limit)
    if cfg.mode in ("all", "cycles"):
        results["cycles"] = run_cycles(cfg.log, cfg.limit, cfg.cycles)
    if cfg.mode == "live" or (cfg.mode == "all" and cfg.front):
        if not (cfg.front and cfg.user):
            print("live 需要 --front 和 --user")
            if cfg.mode == "live":
                return 2
        else:
            results["live"] = run_live(cfg.log, cfg.limit, cfg.front, cfg.user,
                                       cfg.password, cfg.symbols, cfg.exchange, cfg.duration)

    print("\n=== summary ===")
    for k, v in results.items():
        print("%-8s %s" % (k, "PASS" if v else "FAIL"))
    return 0 if all(results.values()) else 3


if __name__ == "__main__":
    sys.exit(main())
