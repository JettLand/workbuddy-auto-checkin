"""签到结果推送通知（接口预留，默认禁用）。

仅当 config.notify.webhook_url 非空时才实际推送；否则所有调用静默跳过，
不影响主流程与退出码。默认适配企业微信群机器人 webhook（markdown 消息）。

依赖：仅标准库（urllib）。企业微信 markdown 仅支持标题/加粗/引用/列表，
不支持表格与代码块。如需其他通道（Server 酱 / 飞书 / 钉钉），可在此扩展。
"""

import json
import urllib.request
import urllib.error

_DEFAULT_ON = {"success": True, "already": False, "error": True}

# write_result 的 status -> 通知事件类别
_STATUS_EVENT = {
    "success": "success",
    "already_checked": "already",
    "skipped": "already",
}


def _event_for(status):
    """把运行结果 status 映射为通知事件类别。"""
    return _STATUS_EVENT.get(status, "error")


def _build_markdown(event, result):
    """构造企业微信 markdown 消息体（仅基础语法）。"""
    title = {"success": "✅ 签到成功", "already": "ℹ️ 今日已签到",
             "error": "⚠️ 签到异常"}.get(event, "签到通知")
    lines = [f"## {title}"]
    if result:
        if result.get("status"):
            lines.append(f"> **状态**: {result.get('status')}")
        if result.get("exit_code") is not None:
            lines.append(f"> **退出码**: {result.get('exit_code')}")
        msg = result.get("message")
        if msg:
            lines.append(f"> **详情**: {msg}")
    return "\n".join(lines)


def send_notify(event, result=None, cfg=None, log=None):
    """推送签到结果通知。

    event: 'success' | 'already' | 'error'
    cfg:    config 字典（含 notify.webhook_url / notify.on）
    未配置 webhook 或事件被 on 掩码关闭时静默跳过。任何异常均被吞掉，
    绝不阻断主流程、不影响退出码。返回是否成功发送（未发送返回 False）。
    """
    notify_cfg = (cfg or {}).get("notify") or {}
    webhook = (notify_cfg.get("webhook_url") or "").strip()
    if not webhook:
        return False  # 接口预留：未配置即不推送
    on = notify_cfg.get("on") or _DEFAULT_ON
    if not on.get(event, False):
        return False
    try:
        content = _build_markdown(event, result)
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {"content": content},
        }).encode("utf-8")
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if log:
            log.log(f"推送通知已发送（{event}）：errcode={data.get('errcode')}")
        return data.get("errcode") == 0
    except Exception as e:
        if log:
            log.log(f"推送通知失败（已忽略，不影响主流程）：{e}", "WARN")
        return False
