# -*- coding: utf-8 -*-
"""命令行入口：起一个值班台，修完点提交。"""

import argparse
import time
import webbrowser

from .console import ConsoleServer
from .engine import Lab


def main(argv=None):
    parser = argparse.ArgumentParser(prog="night-shift", description="夜班 · 故障剧本杀")
    parser.add_argument("--scenario", default="dns", choices=["dns", "web", "disk"], help="剧本名")
    parser.add_argument("--root", default="lab", help="实验目录，默认 ./lab")
    parser.add_argument("--time", type=int, default=1800, help="处置时限（秒），默认 1800")
    parser.add_argument("--port", type=int, default=18081, help="值班台端口，默认 18081")
    parser.add_argument("--dns-port", type=int, default=15353, help="DNS 服务端口，默认 15353")
    parser.add_argument("--web-port", type=int, default=18080, help="Web 服务端口，默认 18080")
    parser.add_argument("--no-open", action="store_true", help="不要自动打开浏览器")
    args = parser.parse_args(argv)

    lab = Lab(
        root=args.root,
        scenario=args.scenario,
        time_limit=args.time,
        dns_port=args.dns_port,
        web_port=args.web_port,
    ).setup()
    console = ConsoleServer(lab, port=args.port).start()
    url = "http://127.0.0.1:%d" % console.port
    print("夜班值班台已启动：%s" % url)
    print("剧本：%s / 时限：%d 秒 / 实验目录：%s" % (args.scenario, args.time, lab.root))
    print("结束请按 Ctrl-C。")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收班。")
    finally:
        console.stop()
        lab.close()


if __name__ == "__main__":
    main()
