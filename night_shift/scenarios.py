# -*- coding: utf-8 -*-
"""剧本库：每个剧本包含工单、故障、验收和线索。

原则：故障是真实写进本地服务配置/运行状态的，验收也走真实协议，
不是前端自说自话。剧本只描述「怎么坏」和「怎么算修好」。
"""

SCENARIOS = {
    "dns": {
        "title": "解析失踪",
        "subtitle": "教务系统打不开，浏览器提示找不到服务器",
        "ticket": (
            "21:47 接到教务处报障：教务系统域名打不开，浏览器直接提示「找不到服务器」。\n"
            "同办公室另一台电脑也打不开，但访问 IP 是通的。\n"
            "值班要求：30 分钟内恢复域名访问，并留下可复核的证据。"
        ),
        "brief": [
            "DNS 服务运行在 127.0.0.1:15353，区域文件是 lab/dns/zone.json。",
            "Web 服务正常，只是没人能通过域名找到它。",
            "验收会真的发一次 DNS 查询，不看你怎么说。",
        ],
        "root_cause": "DNS 区域文件把 portal.nightshift.lab 指到了错误地址 10.0.0.99。",
        "fix_action": "dns_ip",
        "fix_label": "修正 A 记录",
        "fix_value": "127.0.0.1",
        "hints": [
            "先别重启服务：先看它到底解析成了什么。",
            "区域文件里只有一条 A 记录，看看它指向哪。",
            "正确地址不是公网 IP，而是本机回环 127.0.0.1。",
        ],
    },
    "web": {
        "title": "上游失联",
        "subtitle": "门户首页 502，应用服务自己活着",
        "ticket": (
            "20:12 监控告警：门户首页返回 502，但应用进程还在。\n"
            "用户说「昨天还好好的，今天一上班就不行」。\n"
            "值班要求：恢复首页 200，并说明是哪一个上游端口配错了。"
        ),
        "brief": [
            "Web 服务运行在 127.0.0.1:18080，配置在 lab/web/config.json。",
            "服务每次请求都会重新读配置，改对后不用重启。",
            "验收会真的请求 /health，看状态码和上游端口。",
        ],
        "root_cause": "Web 配置把 upstream_port 写成了 18082，而实际上游监听在 18080。",
        "fix_action": "web_port",
        "fix_label": "修正上游端口",
        "fix_value": "18080",
        "hints": [
            "502 不是应用挂了，是它连不上上游。",
            "打开 lab/web/config.json，看 upstream_port。",
            "实际端口在工单 brief 里，别去猜。",
        ],
    },
    "disk": {
        "title": "缓存撑爆",
        "subtitle": "磁盘告警 507，报表服务拒绝写入",
        "ticket": (
            "23:05 接到值班告警：报表服务返回 507，磁盘使用率超过阈值。\n"
            "业务说「晚上批量导出之后就成这样了」。\n"
            "值班要求：把占用降下来，恢复 200，并保留证据。"
        ),
        "brief": [
            "磁盘预算 10 MB，服务在 lab/disk 下写缓存。",
            "超过 80% 就会返回 507，不是磁盘真的坏了。",
            "验收会读 lab/disk 的实际占用，不看页面上的数字。",
        ],
        "root_cause": "批量导出生成的 cache.bin 占满了缓存目录，触发 507。",
        "fix_action": "clean_disk",
        "fix_label": "清理缓存文件",
        "fix_value": "",
        "hints": [
            "先看 lab/disk 里哪个文件最大。",
            "不要删配置，只删导出缓存。",
            "清理后让服务重新检查一次占用。",
        ],
    },
}


def get(name):
    if name not in SCENARIOS:
        raise KeyError("未知剧本：%s" % name)
    return dict(SCENARIOS[name])


def names():
    return sorted(SCENARIOS)
