# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""
SSE 工具模块 - Server-Sent Events 通用辅助函数
"""

import json
import logging
from typing import Dict, Any


def serialize_event(event_data: Dict[str, Any]) -> str:
    """将事件数据序列化为 JSON 字符串，用于 SSE 输出"""
    def json_serializer(obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, Exception):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")

    try:
        return json.dumps(event_data, default=json_serializer, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to serialize event: {e}")
        return json.dumps({"type": "error", "content": f"Serialization error: {e}"})
