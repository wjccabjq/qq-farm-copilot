"""主界面头部信息 OCR 识别。"""

from __future__ import annotations

import re
from typing import Any

import cv2
import numpy as np

from utils.ocr_provider import get_ocr_tool
from utils.ocr_utils import OCRItem, OCRTool

# 固定等级徽章 ROI（基于 540x960 预览坐标系），按平台区分。
# QQ 示例：x≈124~158, y≈102~128；微信示例：x≈60~94, y≈102~128。
_LEVEL_BADGE_ROIS_BASE = {
    'qq': [
        (128, 100, 164, 126),
    ],
    'wechat': [
        (64, 100, 100, 126),
    ],
}


class HeadInfoOCR:
    """封装主界面头部信息识别逻辑，支持传入 ROI。"""

    def __init__(
        self,
        ocr_tool: OCRTool | None = None,
        *,
        scope: str = 'engine',
        key: str | None = None,
    ):
        """初始化 OCR 实例，优先使用注入对象。"""
        self.ocr = ocr_tool or get_ocr_tool(scope=scope, key=key)

    @staticmethod
    def _normalize_text(text: str) -> str:
        """标准化 OCR 文本用于提取。"""
        raw = str(text or '')
        raw = raw.replace('：', ':').replace('（', '(').replace('）', ')')
        return ''.join(raw.split())

    @staticmethod
    def _sort_items(items: list[OCRItem]) -> list[OCRItem]:
        """按视觉阅读顺序排序 OCR item。"""
        return sorted(
            items,
            key=lambda item: (
                min(point[1] for point in item.box),
                min(point[0] for point in item.box),
            ),
        )

    @staticmethod
    def _item_center(item: OCRItem) -> tuple[float, float]:
        """计算 OCR item 的中心点。"""
        xs = [point[0] for point in item.box]
        ys = [point[1] for point in item.box]
        return float(sum(xs) / len(xs)), float(sum(ys) / len(ys))

    @staticmethod
    def _item_bbox(item: OCRItem) -> tuple[float, float, float, float]:
        """返回 OCR item 包围框 `(x1, y1, x2, y2)`。"""
        xs = [point[0] for point in item.box]
        ys = [point[1] for point in item.box]
        return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))

    @staticmethod
    def _normalize_platform(platform: str | None) -> str:
        text = str(platform or '').strip().lower()
        if text in {'qq', 'wechat'}:
            return text
        return ''

    @staticmethod
    def _clip_region(region: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int] | None:
        """裁剪 ROI 到图像范围。"""
        x1, y1, x2, y2 = region
        x1 = max(0, min(int(x1), int(width) - 1))
        y1 = max(0, min(int(y1), int(height) - 1))
        x2 = max(0, min(int(x2), int(width)))
        y2 = max(0, min(int(y2), int(height)))
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2

    @staticmethod
    def _is_nickname_candidate(text: str) -> bool:
        """判断文本是否可作为昵称候选。"""
        normalized = HeadInfoOCR._normalize_text(text)
        if not normalized:
            return False
        if re.search(r'(?i)\b(?:id|version)[:：]?', normalized):
            return False
        if re.search(r'\d+(?:\.\d+)?(?:万|亿)', normalized):
            return False
        if not re.search(r'[\u4e00-\u9fff]', normalized):
            return False
        return 1 <= len(normalized) <= 16

    def _collect_level_text_candidates(
        self,
        ordered: list[OCRItem],
        *,
        min_level: int,
        max_level: int,
        img_bgr: np.ndarray,
        platform: str | None = None,
    ) -> list[tuple[int, float, str]]:
        """等级 OCR 候选（仅固定等级徽章 ROI 的 rec-only 多参数）。"""
        _ = ordered
        out = self._collect_level_badge_rec_only_candidates(
            img_bgr,
            min_level=min_level,
            max_level=max_level,
            platform=platform,
        )

        # 同等级去重：保留最高分。
        best_by_level: dict[int, tuple[int, float, str]] = {}
        for cand in out:
            old = best_by_level.get(int(cand[0]))
            if old is None or float(cand[1]) > float(old[1]):
                best_by_level[int(cand[0])] = cand
        merged = list(best_by_level.values())
        merged.sort(key=lambda item: item[1], reverse=True)
        return merged

    def _collect_level_badge_rec_only_candidates(
        self,
        img_bgr: np.ndarray,
        *,
        min_level: int,
        max_level: int,
        platform: str | None = None,
    ) -> list[tuple[int, float, str]]:
        """参考种子数字框：在等级徽章区域执行 rec-only 多参数识别。"""
        rapid_ocr = getattr(self.ocr, '_ocr', None)
        if rapid_ocr is None:
            return []

        h, w = img_bgr.shape[:2]
        platform_key = self._normalize_platform(platform)
        if platform_key not in _LEVEL_BADGE_ROIS_BASE:
            return []

        sx = float(w) / 540.0
        sy = float(h) / 960.0
        roi_candidates = []
        for x1b, y1b, x2b, y2b in _LEVEL_BADGE_ROIS_BASE[platform_key]:
            roi_candidates.append(
                (
                    int(round(x1b * sx)),
                    int(round(y1b * sy)),
                    int(round(x2b * sx)),
                    int(round(y2b * sy)),
                )
            )

        rois: list[tuple[int, int, int, int]] = []
        for roi in roi_candidates:
            clipped = self._clip_region(roi, w, h)
            if clipped is not None:
                rois.append(clipped)
        if not rois:
            return []

        prev_use_det = getattr(rapid_ocr, 'use_det', True)
        prev_use_cls = getattr(rapid_ocr, 'use_cls', True)
        prev_use_rec = getattr(rapid_ocr, 'use_rec', True)
        prev_text_score = getattr(rapid_ocr, 'text_score', 0.5)

        out: list[tuple[int, float, str]] = []
        try:
            for x1, y1, x2, y2 in rois:
                patch = img_bgr[y1:y2, x1:x2]
                if patch.size == 0:
                    continue
                up = cv2.resize(patch, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
                gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
                rec_input = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                res = rapid_ocr(
                    rec_input,
                    use_det=False,
                    use_cls=False,
                    use_rec=True,
                    text_score=0.0,
                )
                txts = list(getattr(res, 'txts', []) or [])
                scores = list(getattr(res, 'scores', []) or [])
                raw = str(txts[0]).strip() if txts else ''
                score = float(scores[0]) if scores else 0.0
                normalized = self._normalize_text(raw)
                matched = re.search(r'\d{1,3}', normalized)
                if matched is None:
                    continue
                num = int(matched.group(0))
                if num < min_level or num > max_level:
                    continue
                fused = 0.72 + score * 0.36
                out.append((int(num), float(fused), str(raw)))
        finally:
            try:
                rapid_ocr.update_params(
                    use_det=bool(prev_use_det),
                    use_cls=bool(prev_use_cls),
                    use_rec=bool(prev_use_rec),
                    text_score=float(prev_text_score),
                )
            except Exception:
                pass

        return out

    def _extract_structured_head_info(
        self,
        ordered: list[OCRItem],
        *,
        level: int | None,
        nickname_text: str,
        level_raw_text: str = '',
    ) -> dict[str, Any]:
        """从 OCR token 提取头部结构化信息。"""
        money_pattern = re.compile(r'\d+(?:\.\d+)?(?:万|亿)')
        coupon_token_pattern = re.compile(r'^\d+(?:\.\d+)?(?:万|亿)?$')
        exp_slash_pattern = re.compile(r'(\d+(?:\.\d+)?(?:万|亿)?)/(\d+(?:\.\d+)?(?:万|亿)?)')
        exp_concat_pattern = re.compile(r'^(\d+(?:\.\d+)?(?:万|亿))(\d+(?:\.\d+)?(?:万|亿))$')

        gold = ''
        exp = ''
        coupon = ''
        nickname_pos: tuple[float, float] | None = None
        level_pos: tuple[float, float] | None = None
        normalized_level_raw = self._normalize_text(level_raw_text)
        money_candidates: list[tuple[float, float, str, str, float]] = []
        coupon_tokens: list[tuple[float, float, str]] = []

        if level is not None:
            for item in ordered:
                normalized = self._normalize_text(item.text)
                if re.fullmatch(r'\d{1,3}', normalized) is None:
                    continue
                try:
                    if int(normalized) != int(level):
                        continue
                except Exception:
                    continue
                cx, cy = self._item_center(item)
                if normalized_level_raw and normalized == normalized_level_raw:
                    level_pos = (cx, cy)
                    break
                if level_pos is None:
                    level_pos = (cx, cy)

        for item in ordered:
            text = str(item.text or '').strip()
            normalized = self._normalize_text(text)
            if not normalized:
                continue
            cx, cy = self._item_center(item)
            x1, _y1, x2, _y2 = self._item_bbox(item)
            if not nickname_pos and text == str(nickname_text or ''):
                nickname_pos = (cx, cy)

            if not exp and level_pos is not None:
                lx, _ly = level_pos
                if cx > lx:
                    slash_matched = exp_slash_pattern.search(normalized)
                    if slash_matched is not None:
                        exp = f'{slash_matched.group(1)}/{slash_matched.group(2)}'

            if money_pattern.search(normalized):
                money_candidates.append((cx, cy, text, normalized, float(x2 - x1)))
            if '/' not in normalized and coupon_token_pattern.fullmatch(normalized):
                coupon_tokens.append((cx, cy, text))

        if not exp:
            level_x = level_pos[0] if level_pos is not None else None
            for item in ordered:
                normalized = self._normalize_text(item.text)
                if not normalized:
                    continue
                if level_x is not None:
                    cx, _cy = self._item_center(item)
                    if cx <= level_x:
                        continue
                concat_matched = exp_concat_pattern.fullmatch(normalized)
                if concat_matched is None:
                    continue
                exp = f'{concat_matched.group(1)}/{concat_matched.group(2)}'
                break

        gold_pos: tuple[float, float, float] | None = None
        if money_candidates:
            if nickname_pos is not None:
                _nx, ny = nickname_pos
                money_candidates.sort(key=lambda item: (abs(item[1] - ny), item[0]))
            else:
                money_candidates.sort(key=lambda item: (item[1], item[0]))
            gold = money_candidates[0][2]
            gold_pos = (money_candidates[0][0], money_candidates[0][1], money_candidates[0][4])

        # 最简规则：点券=金币正下方同列范围内最近 token。
        if gold_pos is not None:
            gx, gy, gw = gold_pos
            below_candidates = []
            col_tolerance = max(22.0, float(gw) * 1.2)
            for cx, cy, text in coupon_tokens:
                if text == gold:
                    continue
                if cy <= gy:
                    continue
                if abs(cx - gx) > col_tolerance:
                    continue
                below_candidates.append((cx, cy, text))
            if below_candidates:
                below_candidates.sort(key=lambda item: (abs(item[0] - gx), item[1] - gy))
                coupon = below_candidates[0][2]

        return {
            'gold': gold,
            'nickname': str(nickname_text or ''),
            'exp': exp,
            'level': int(level) if level is not None else None,
            'coupon': coupon,
        }

    def detect_head_info(
        self,
        img_bgr: np.ndarray,
        *,
        region: tuple[int, int, int, int] | None = None,
        min_level: int = 1,
        max_level: int = 999,
        platform: str | None = None,
    ) -> tuple[int | None, float, str, dict[str, Any]]:
        """识别等级并返回 `(level, score, raw_text, extra_info)`。"""
        if img_bgr is None:
            return None, 0.0, '', {}

        lower = max(1, int(min_level))
        upper = max(lower, int(max_level))
        items = self.ocr.detect(img_bgr, region=region, scale=1.5, alpha=1.15, beta=0.0)
        if not items:
            return (
                None,
                0.0,
                '',
                {
                    'tokens': [],
                    'gold': '',
                    'nickname': '',
                    'exp': '',
                    'level': None,
                    'coupon': '',
                },
            )

        ordered = self._sort_items(items)
        raw_texts = [str(item.text) for item in ordered]
        merged_text = ''.join(self._normalize_text(text) for text in raw_texts)

        nickname_item: OCRItem | None = None
        nickname_score = -1.0
        nickname_y = float('inf')
        for item in ordered:
            if not self._is_nickname_candidate(item.text):
                continue
            _nx1, ny1, _nx2, _ny2 = self._item_bbox(item)
            score = float(item.score)
            if ny1 < nickname_y - 1e-6 or (abs(ny1 - nickname_y) <= 1e-6 and score > nickname_score):
                nickname_item = item
                nickname_y = ny1
                nickname_score = score

        level_ocr_candidates = self._collect_level_text_candidates(
            ordered,
            min_level=lower,
            max_level=upper,
            img_bgr=img_bgr,
            platform=platform,
        )
        level_ocr_best = level_ocr_candidates[0] if level_ocr_candidates else None

        selected_level: int | None = None
        selected_score = 0.0
        selected_raw = ''

        if level_ocr_best is not None:
            ocr_level, ocr_score, ocr_raw = level_ocr_best
            selected_level = int(ocr_level)
            selected_score = float(ocr_score)
            selected_raw = str(ocr_raw)

        nickname_text = str(nickname_item.text) if nickname_item is not None else ''
        structured = self._extract_structured_head_info(
            ordered,
            level=selected_level,
            nickname_text=nickname_text,
            level_raw_text=selected_raw,
        )

        extra_info: dict[str, Any] = {
            'tokens': raw_texts,
            'nickname_candidate': nickname_text,
            'platform_hint': self._normalize_platform(platform),
            **structured,
        }
        if level_ocr_best is not None:
            extra_info['ocr_level_match'] = {
                'level': int(level_ocr_best[0]),
                'score': round(float(level_ocr_best[1]), 4),
                'raw': str(level_ocr_best[2]),
            }

        if selected_level is None:
            return None, 0.0, merged_text, extra_info
        return int(selected_level), float(selected_score), str(selected_raw), extra_info
