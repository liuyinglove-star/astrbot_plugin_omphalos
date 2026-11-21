"""昔涟音色：通过本地 GPT-SoVITS 合成语音。

设计取舍：
- 只内嵌昔涟一个人的音色（其他角色模型太大）。
- 参考音频目录、模型权重都通过插件配置传入，不写死路径。
  目录结构约定：<参考音频根目录>/<情绪>/ref.wav，转录在同目录 asr.txt。
- 未配置时自动禁用，合成失败时静默降级为纯文字，不阻塞结局流程。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from astrbot.api import logger

# 本地 GPT-SoVITS 服务地址
GSV_BASE = "http://127.0.0.1:9880"

# 以下三项由插件在启动时通过 configure() 注入，默认留空表示未配置。
# 未配置时 reference_for() 返回 None，结局自动降级为纯文字。
REF_ROOT: Path | None = None
GPT_WEIGHTS: str = ""
SOVITS_WEIGHTS: str = ""


def configure(ref_root: str = "", gpt_weights: str = "", sovits_weights: str = "") -> None:
    """由插件启动时调用，注入用户配置的路径。

    Args:
        ref_root: 参考音频根目录，其下按情绪分子目录。
        gpt_weights: GPT 模型权重路径（.ckpt）。
        sovits_weights: SoVITS 模型权重路径（.pth）。
    """
    global REF_ROOT, GPT_WEIGHTS, SOVITS_WEIGHTS
    REF_ROOT = Path(ref_root) if ref_root else None
    GPT_WEIGHTS = gpt_weights or ""
    SOVITS_WEIGHTS = sovits_weights or ""


def is_configured() -> bool:
    """检查语音所需的路径是否都配好了。

    Returns:
        bool: 三项齐全且参考目录存在时为 True。
    """
    return bool(
        REF_ROOT
        and REF_ROOT.is_dir()
        and GPT_WEIGHTS
        and SOVITS_WEIGHTS
        and Path(GPT_WEIGHTS).is_file()
        and Path(SOVITS_WEIGHTS).is_file()
    )


def reference_for(emotion: str = "温柔") -> tuple[Path, str] | None:
    """取某个情绪的参考音频与转录文本。

    Args:
        emotion: 情绪目录名。

    Returns:
        tuple[Path, str] | None: (音频路径, 转录文本)，缺文件时返回 None。
    """
    # 未配置参考音频目录时直接返回，调用方会降级为纯文字
    if REF_ROOT is None or not REF_ROOT.is_dir():
        return None
    folder = REF_ROOT / emotion
    ref = folder / "ref.wav"
    asr = folder / "asr.txt"
    if not ref.is_file() or not asr.is_file():
        # 回退到任意可用情绪
        for alt in REF_ROOT.iterdir():
            r = alt / "ref.wav"
            a = alt / "asr.txt"
            if r.is_file() and a.is_file():
                return r, a.read_text(encoding="utf-8").strip()
        return None
    return ref, asr.read_text(encoding="utf-8").strip()


class CyreneVoice:
    """昔涟的声音。

    Attributes:
        enabled: 是否启用（配置开关）。
        weights_loaded: 是否已把权重推给 GPT-SoVITS。
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.weights_loaded = False

    async def _ensure_weights(self) -> bool:
        """确保 GPT-SoVITS 已载入昔涟的权重。

        Returns:
            bool: 是否就绪。
        """
        if self.weights_loaded:
            return True
        # 权重路径没配就不要去请求本地服务，直接降级为纯文字
        if not is_configured():
            return False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=180) as client:
                for kind, path in (
                    ("gpt", GPT_WEIGHTS),
                    ("sovits", SOVITS_WEIGHTS),
                ):
                    resp = await client.get(
                        f"{GSV_BASE}/set_{kind}_weights",
                        params={"weights_path": path},
                    )
                    resp.raise_for_status()
            self.weights_loaded = True
            logger.info("[omphalos] 昔涟音色权重已载入")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[omphalos] 昔涟权重载入失败: {exc}")
            return False

    async def synth(
        self,
        text: str,
        emotion: str = "温柔",
        speed: float = 0.95,
    ) -> str | None:
        """合成一段语音，返回 base64 编码的 wav。

        Args:
            text: 要念的文本。
            emotion: 情绪，决定用哪条参考音频。
            speed: 语速。

        Returns:
            str | None: base64 wav 数据；失败返回 None。
        """
        if not self.enabled:
            return None
        ref = reference_for(emotion)
        if ref is None:
            logger.warning("[omphalos] 找不到昔涟参考音频")
            return None
        if not await self._ensure_weights():
            return None

        ref_path, prompt_text = ref
        payload = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": str(ref_path).replace("\\", "/"),
            "prompt_text": prompt_text,
            "prompt_lang": "zh",
            "top_k": 5,
            "top_p": 1.0,
            "temperature": 1.0,
            "text_split_method": "cut5",
            "batch_size": 1,
            "speed_factor": speed,
            "fragment_interval": 0.5,
            "media_type": "wav",
        }
        try:
            import httpx

            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post(f"{GSV_BASE}/tts", json=payload)
                resp.raise_for_status()
                data = resp.content
            if len(data) < 2000:
                logger.warning(f"[omphalos] 昔涟语音过短: {len(data)} bytes")
                return None
            return base64.b64encode(data).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[omphalos] 昔涟语音合成失败: {exc}")
            return None
