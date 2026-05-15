"""通知工具：用于异常停机通知。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from loguru import logger

from models.config import AppConfig
from utils.onebot11_provider import OneBot11
from utils.smtp_image_parser import smtp_image_parser

_WIN_NOTIFY_APP_ID = 'QQFarmCopilot'
_WIN_NOTIFY_TITLE = '[QQ农场通知]'


@dataclass
class NotifySendResult:
    """通知发送结果。"""

    win_status: str = 'skipped'
    onepush_status: str = 'skipped'

    @property
    def sent(self) -> bool:
        return self.win_status == 'success' or self.onepush_status == 'success'


def _send_windows_toast(*, title: str, content: str, image_path: str | None = None) -> bool:
    """发送 Windows Toast 通知。"""
    try:
        from winotify import Notification
    except Exception:
        logger.warning('异常通知: 未安装 winotify，跳过 Windows Toast 推送')
        return False

    icon = str(image_path or '').strip()
    if icon and not os.path.exists(icon):
        icon = ''

    kwargs: dict[str, Any] = {
        'app_id': _WIN_NOTIFY_APP_ID,
        'title': str(title or _WIN_NOTIFY_TITLE),
        'msg': str(content or ''),
        'duration': 'long',
    }
    if icon:
        kwargs['icon'] = icon

    try:
        toast = Notification(**kwargs)
        toast.show()
        logger.info('异常通知: Windows Toast 推送成功')
        return True
    except Exception as exc:
        logger.warning(f'异常通知: Windows Toast 发送失败: {exc}')
        return False


def _parse_onepush_config(config_text: str) -> dict[str, Any]:
    """解析 OnePush 配置（仅支持 YAML）。"""
    raw = str(config_text or '').strip()
    if not raw:
        return {}

    try:
        import yaml  # type: ignore
    except Exception:
        logger.warning('异常通知: 未安装 pyyaml，无法解析 OnePush YAML 配置')
        return {}

    try:
        merged: dict[str, Any] = {}
        for item in yaml.safe_load_all(raw):
            if isinstance(item, dict):
                merged.update(item)
        return merged
    except Exception as exc:
        logger.warning(f'异常通知: OnePush YAML 解析失败: {exc}')
        return {}


def _send_onepush(*, config_text: str, title: str, content: str, image_path: str | None = None) -> bool:
    """发送 OnePush 通知。"""
    raw = str(config_text or '').strip()
    if not raw:
        return False

    cfg = _parse_onepush_config(raw)
    if not cfg:
        logger.warning('异常通知: OnePush 配置解析失败，跳过推送')
        return False

    provider_name = str(cfg.pop('provider', '') or '').strip()
    if not provider_name:
        logger.warning('异常通知: OnePush 未配置提供方，跳过推送')
        return False

    try:
        import onepush.core  # type: ignore
        from onepush import get_notifier  # type: ignore
        from onepush.exceptions import OnePushException  # type: ignore
        from onepush.providers.custom import Custom  # type: ignore
    except Exception:
        logger.warning('异常通知: 未安装 onepush，跳过 OnePush 推送')
        return False

    try:
        onepush.core._all_providers['onebot11'] = OneBot11
        onepush.core.log = logger
        notifier = get_notifier(provider_name)
        payload: dict[str, Any] = dict(cfg)
        payload['title'] = str(title or _WIN_NOTIFY_TITLE)
        payload['content'] = str(content or '')

        if image_path and os.path.exists(image_path):
            payload['image_path'] = str(image_path)

        if isinstance(notifier, Custom):
            if 'method' not in payload or str(payload.get('method') or '').lower() == 'post':
                payload['datatype'] = 'json'
            data = payload.get('data')
            if not isinstance(data, dict):
                data = {}
            data['title'] = payload['title']
            data['content'] = payload['content']
            payload['data'] = data
        elif provider_name.lower() == 'smtp' and image_path and os.path.exists(image_path):
            notifier.set_message_parser(smtp_image_parser)

        response = notifier.notify(**payload)
        try:
            status_code = int(response.status_code)  # type: ignore[attr-defined]
        except Exception:
            status_code = 200
        if isinstance(status_code, int) and status_code != 200:
            logger.warning(f'异常通知: OnePush 推送失败，状态码={status_code}')
            return False
        logger.info('异常通知: OnePush 推送成功')
        return True
    except OnePushException as exc:
        detail = str(exc).strip() or repr(exc)
        logger.warning(
            f'异常通知: OnePush 推送失败 | 提供方={provider_name} | 异常类型={type(exc).__name__} | 异常信息={detail}'
        )
        return False
    except Exception as exc:
        detail = str(exc).strip() or repr(exc)
        logger.warning(
            f'异常通知: OnePush 推送失败 | 提供方={provider_name} | 异常类型={type(exc).__name__} | 异常信息={detail}'
        )
        return False


def send_exception_notification(
    *,
    config: AppConfig,
    instance_id: str,
    reason: str,
    image_path: str | None = None,
) -> bool:
    """按实例配置发送异常通知。"""
    result = send_exception_notification_detailed(
        config=config,
        instance_id=instance_id,
        reason=reason,
        image_path=image_path,
    )
    if result.sent:
        logger.info('异常通知: 推送成功')
    if not result.sent:
        logger.warning('异常通知: 推送未发送（可能未安装依赖或未配置 OnePush）')
    return result.sent


def send_exception_notification_detailed(
    *,
    config: AppConfig,
    instance_id: str,
    reason: str,
    image_path: str | None = None,
) -> NotifySendResult:
    """按实例配置发送异常通知，并返回分渠道结果。"""
    notify_cfg = config.notification
    if not bool(notify_cfg.exception_notify_enabled):
        return NotifySendResult(win_status='disabled', onepush_status='disabled')

    title = f'{_WIN_NOTIFY_TITLE} 实例 {str(instance_id or "default")} 出现异常'
    content = str(reason or '检测到异常，任务已停止')
    onepush_config_text = str(notify_cfg.onepush_config or '')

    result = NotifySendResult(win_status='skipped', onepush_status='skipped')
    if bool(notify_cfg.win_toast_enabled) and sys.platform.startswith('win'):
        result.win_status = (
            'success' if _send_windows_toast(title=title, content=content, image_path=image_path) else 'failed'
        )
    elif bool(notify_cfg.win_toast_enabled):
        result.win_status = 'not_windows'
    else:
        result.win_status = 'disabled'

    if onepush_config_text.strip():
        result.onepush_status = (
            'success'
            if _send_onepush(
                config_text=onepush_config_text,
                title=title,
                content=content,
                image_path=image_path,
            )
            else 'failed'
        )
    else:
        result.onepush_status = 'unconfigured'
    return result
