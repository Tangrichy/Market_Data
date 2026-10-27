#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Offline reproduction / verification for the GtjaMdUserApi Release hang.

This script needs no front address, no account and no market data. After
Init() the SDK starts its receive thread and parks it in an untimed
select()/pselect6(); Release() sets an internal stop flag and joins that
thread, so it returns only once select() returns. With no traffic arriving
it never does.

Modes:
    bounded   (default) call ReleaseWithTimeout() and check it returns
    blocking  call the plain Release() and watch it stay blocked
    cycles    two create -> Init -> release cycles in one process

Exit codes: 0 = resolved, 3 = still blocked, 2 = bad environment/argument.
"""
import argparse
import os
import sys
import threading
import time

import gtja_udp_api as gtja


def make_api(log_path):
    api = gtja.GtjaMdUserApi(log_path)
    api.SetConfig("cpu", "1")
    rc = api.Init()
    if rc != 0:
        sys.exit("Init() returned %s" % rc)
    # Let the receive thread reach its select() before we tear down.
    time.sleep(0.8)
    return api


def mode_bounded(log_path, timeout_ms, watch_s):
    if not hasattr(gtja.GtjaMdUserApi, "ReleaseWithTimeout"):
        sys.exit("this build has no ReleaseWithTimeout(); rebuild the extension")
    api = make_api(log_path)
    print("before_Release", flush=True)
    elapsed = api.ReleaseWithTimeout(timeout_ms)
    abandoned = api.LastReleaseAbandoned
    print("after_Release %d ms, wakeups=%d, abandoned=%s"
          % (elapsed, api.LastReleaseWakeups, abandoned), flush=True)
    if abandoned:
        print("RESULT: FAIL - SDK never returned; object was abandoned")
        return 3
    print("RESULT: PASS - Release returned within the bounded wait")
    return 0


def mode_blocking(log_path, watch_s):
    api = make_api(log_path)
    thread = threading.Thread(target=api.Release, daemon=True)
    print("before_Release", flush=True)
    thread.start()
    deadline = time.time() + watch_s
    ticks = 0
    while time.time() < deadline and thread.is_alive():
        time.sleep(0.25)
        ticks += 1
        # Reaching this line at all proves Release() no longer pins the GIL.
        print("  main thread alive, Release still blocked (%d)" % ticks, flush=True)
    if thread.is_alive():
        print("after_Release: never   (still blocked after %ds)" % watch_s, flush=True)
        print("RESULT: FAIL - plain Release() does not return; use ReleaseWithTimeout()")
        return 3
    print("RESULT: PASS - plain Release() returned")
    return 0


def mode_cycles(log_path, timeout_ms, count):
    for i in range(1, count + 1):
        api = make_api("%s.%d" % (log_path, i))
        elapsed = api.ReleaseWithTimeout(timeout_ms)
        print("cycle%d: released in %d ms, wakeups=%d, abandoned=%s"
              % (i, elapsed, api.LastReleaseWakeups, api.LastReleaseAbandoned),
              flush=True)
        if api.LastReleaseAbandoned:
            print("RESULT: FAIL - cycle %d abandoned the SDK object" % i)
            return 3
    print("RESULT: PASS - %d create/Init/release cycles completed" % count)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("bounded", "blocking", "cycles"),
                    default="bounded")
    ap.add_argument("--log", default="/tmp/gtja_repro.log")
    ap.add_argument("--timeout-ms", type=int, default=3000)
    ap.add_argument("--watch", type=int, default=8, help="blocking-mode watch seconds")
    ap.add_argument("--count", type=int, default=2, help="cycles-mode iterations")
    args = ap.parse_args()

    print("mode=%s log=%s" % (args.mode, args.log), flush=True)
    if args.mode == "bounded":
        return mode_bounded(args.log, args.timeout_ms, 1)
    if args.mode == "blocking":
        return mode_blocking(args.log, args.watch)
    return mode_cycles(args.log, args.timeout_ms, args.count)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # The SDK object is intentionally never freed on the failing path; exit
    # directly so a stuck receive thread cannot block interpreter shutdown.
    os._exit(code)
