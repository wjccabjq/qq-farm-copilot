"""SMTP 自定义消息解析器：支持附带异常截图附件。"""

from __future__ import annotations

import mimetypes
import os
from email.message import EmailMessage

from loguru import logger


def smtp_image_parser(
    self,
    subject: str = '',
    title: str = '',
    content: str = '',
    From=None,
    user=None,
    To=None,
    image_path: str | None = None,
    **kwargs,
):
    """构建 SMTP 消息并在存在图片路径时添加附件。"""
    _ = self, kwargs
    msg = EmailMessage()
    msg['Subject'] = str(subject or title or '')
    msg['From'] = str(From or user or '')
    msg['To'] = str(To or user or '')
    msg.set_content(str(content or ''))

    image_file = str(image_path or '').strip()
    if not image_file or not os.path.exists(image_file):
        return msg

    ctype, encoding = mimetypes.guess_type(image_file)
    if ctype is None or encoding is not None:
        ctype = 'application/octet-stream'
    maintype, subtype = ctype.split('/', 1)

    try:
        with open(image_file, 'rb') as file_obj:
            file_data = file_obj.read()
        filename = os.path.basename(image_file)
        msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=filename)
    except Exception as exc:
        logger.warning(f'异常通知: SMTP 图片附件添加失败: {exc}')
    return msg
