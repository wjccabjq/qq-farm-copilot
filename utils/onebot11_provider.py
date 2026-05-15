"""OnePush onebot11 provider（移植自 NIKKE，支持文本+图片发送）。"""

from __future__ import annotations

import base64
import os
from typing import Any

import requests
from loguru import logger
from onepush.core import Provider
from requests import Response


class OneBot11(Provider):
    """OneBot11 通知提供方。"""

    name = 'onebot11'

    def __init__(self) -> None:
        super().__init__()
        self._params = {
            'required': ['endpoint', 'message_type'],
            'optional': ['token', 'user_id', 'group_id', 'title', 'content', 'image_path'],
        }

    def _mock_response(self, status_code: int) -> Response:
        resp = Response()
        resp.status_code = int(status_code)
        return resp

    def _post_message(
        self,
        *,
        api_url: str,
        headers: dict[str, str],
        payload_base: dict[str, Any],
        message: list[dict[str, Any]],
    ) -> bool:
        payload = dict(payload_base)
        payload['message'] = message
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if int(response.status_code) != 200:
            logger.warning(f'异常通知: OneBot11 推送失败，状态码={response.status_code}')
            return False
        return True

    def notify(self, **kwargs) -> Response:
        endpoint = str(kwargs.get('endpoint', '') or '').strip().rstrip('/')
        token = str(kwargs.get('token', '') or '').strip()
        message_type = str(kwargs.get('message_type', '') or '').strip().lower()
        user_id = kwargs.get('user_id')
        group_id = kwargs.get('group_id')

        if not endpoint:
            logger.warning("异常通知: OneBot11 缺少必填参数 'endpoint'")
            return self._mock_response(400)
        if message_type == 'private' and not user_id:
            logger.warning("异常通知: OneBot11 私聊模式缺少必填参数 'user_id'")
            return self._mock_response(400)
        if message_type == 'group' and not group_id:
            logger.warning("异常通知: OneBot11 群聊模式缺少必填参数 'group_id'")
            return self._mock_response(400)
        if message_type not in {'private', 'group'}:
            logger.warning("异常通知: OneBot11 参数 'message_type' 仅支持 private/group")
            return self._mock_response(400)

        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        payload_base: dict[str, Any] = {}
        if message_type == 'group':
            api_url = f'{endpoint}/send_group_msg'
            payload_base['group_id'] = int(group_id)
        else:
            api_url = f'{endpoint}/send_private_msg'
            payload_base['user_id'] = int(user_id)

        title = str(kwargs.get('title', '') or '')
        content = str(kwargs.get('content', '') or '')
        text_msg = f'{title}\n{content}'.strip()
        success = True

        try:
            if text_msg:
                ok = self._post_message(
                    api_url=api_url,
                    headers=headers,
                    payload_base=payload_base,
                    message=[{'type': 'text', 'data': {'text': text_msg}}],
                )
                success = success and ok

            image_path = str(kwargs.get('image_path', '') or '').strip()
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as file_obj:
                    b64_data = base64.b64encode(file_obj.read()).decode('utf-8')
                ok = self._post_message(
                    api_url=api_url,
                    headers=headers,
                    payload_base=payload_base,
                    message=[{'type': 'image', 'data': {'file': f'base64://{b64_data}'}}],
                )
                success = success and ok
        except Exception as exc:
            logger.warning(f'异常通知: OneBot11 推送异常: {exc}')
            success = False

        return self._mock_response(200 if success else 500)
