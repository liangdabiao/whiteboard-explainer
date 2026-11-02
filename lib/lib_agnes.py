"""lib_agnes.py — Agnes Image 2.1 Flash HTTP 客户端

直连 https://api.agnes-ai.cn/v1/images/generations，绕开 apiz CLI。
当前免费（$0/张），高信息密度，适合手绘日记风插画。

设计要点：
- 文生图：传 model/prompt/size 即可，response URL 直接下载
- 图生图（character_reference 锁身份）：把 reference 转 data URI 塞进 extra_body.image
- agnes 没有上传端点，所有图生图用 data:image/png;base64,... 形式
- 顶层不能放 response_format，必须放 extra_body.response_format
- 上游偶发 503 "Service busy"，自带指数退避重试（最多 4 次）
"""
from __future__ import annotations
import base64
import json
import os
import time
import http.client
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "agnes-image-2.1-flash"
DEFAULT_BASE_URL = "https://api.agnes-ai.cn"
DEFAULT_TIMEOUT = 300  # 单张图片最多等 5 分钟
MAX_RETRIES = 4  # 503/网络错重试上限


ENV_CANDIDATES = (
    # 公开 skill 的稳定回退路径（用户 ~/.workbuddy/ 下集中放配置也兼容）
    Path.home() / ".env",
    Path.home() / ".workbuddy" / ".env",
    # skill 内置（极少用，但 fallback 一下）
    Path(__file__).resolve().parents[1] / ".env",
)


def _find_env_file() -> Path | None:
    """从 cwd 向上找 .env（dotenv 标准做法），找不到再退到 ENV_CANDIDATES。

    这样 skill 在任意项目目录里跑都能找到用户的 .env。
    """
    start = Path.cwd()
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    for candidate in ENV_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _load_env_file() -> None:
    """从 .env 读 AGNES_API_KEY/AGNES_BASE_URL。

    os.environ 已经有的话优先用；否则从 .env 文件加载。
    找不到 .env 也不报错，调用 _resolve_api_key 时再明确报错。
    """
    if os.environ.get("AGNES_API_KEY"):
        return
    env_path = _find_env_file()
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k.startswith(("AGNES_",)):
            os.environ.setdefault(k, v)


_load_env_file()


def _resolve_api_key() -> str:
    key = os.environ.get("AGNES_API_KEY")
    if not key:
        raise RuntimeError(
            "AGNES_API_KEY 未设置。请在以下任一位置设置：\n"
            "  export AGNES_API_KEY=sk-...                  # 直接 export 进环境变量\n"
            "  在 cwd 或父目录的 .env 文件里写：AGNES_API_KEY=sk-...\n"
            "  或放在 ~/.env / ~/.workbuddy/.env\n"
            "（Agnes API key 申请见 README.md「依赖与凭证」）"
        )
    return key


def _resolve_base_url() -> str:
    return os.environ.get("AGNES_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _file_to_data_uri(path: Path) -> str:
    """本地 png 转 data:image/png;base64,... 形式给 agnes extra_body.image 用。"""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _post(payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST + 指数退避重试。503/网络错才重试，4xx 立即抛。"""
    key = _resolve_api_key()
    base = _resolve_base_url()
    url = f"{base}/v1/images/generations"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s, 40s
                print(f"  ⚠️ agnes HTTP {e.code}（attempt {attempt+1}/{MAX_RETRIES}），{wait}s 后重试")
                time.sleep(wait)
                last_err = RuntimeError(f"agnes HTTP {e.code}: {err_body[:200]}")
                continue
            raise RuntimeError(f"agnes HTTP {e.code}: {err_body[:500]}") from None
        except (urllib.error.URLError, TimeoutError,
                http.client.RemoteDisconnected, http.client.BadStatusLine,
                ConnectionResetError, ConnectionAbortedError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)
                print(f"  ⚠️ agnes 网络错 ({type(e).__name__}: {e})，{wait}s 后重试")
                time.sleep(wait)
                last_err = e
                continue
            raise RuntimeError(f"agnes 网络超时: {type(e).__name__}: {e}") from None
    raise RuntimeError(f"agnes 重试 {MAX_RETRIES} 次仍失败: {last_err}")


def _download(url: str, out_path: Path) -> None:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "story-handdrawn-skill"})
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                out_path.write_bytes(resp.read())
            return
        except (http.client.IncompleteRead, http.client.RemoteDisconnected,
                ConnectionResetError, ConnectionAbortedError,
                urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)
                print(f"  ⚠️ 下载断流 ({type(e).__name__})，{wait}s 后重试")
                time.sleep(wait)
                continue
            raise RuntimeError(f"下载失败 {MAX_RETRIES} 次: {type(e).__name__}: {e}") from None
    raise RuntimeError(f"下载失败: {last_err}")


def generate_image(
    prompt: str,
    out_path: str | Path,
    model: str = DEFAULT_MODEL,
    size: str = "2K",
    ratio: str = "2:3",
    image_ref: str | Path | None = None,
) -> Path:
    """调 agnes 生成图片，下载到 out_path。

    Args:
        prompt: 提示词
        out_path: 本地保存路径
        model: agnes 模型名（默认 agnes-image-2.1-flash）
        size: 1K/2K/3K/4K（默认 2K，对应 2:3 = 1664×2496，downscale 到 master 1024×1536）
        ratio: 1:1/3:4/4:3/16:9/9:16/2:3/3:2/21:9（默认 2:3，与 master 1024×1536 比例一致）
        image_ref: 若提供，走图生图模式锁角色身份（character_reference 路径）

    Returns:
        下载后的本地 Path
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "ratio": ratio,
    }

    if image_ref is not None:
        ref_path = Path(image_ref)
        if not ref_path.exists():
            raise RuntimeError(f"image_ref 不存在: {ref_path}")
        data_uri = _file_to_data_uri(ref_path)
        payload["extra_body"] = {
            "image": [data_uri],
            "response_format": "url",
        }
    else:
        payload["extra_body"] = {"response_format": "url"}

    data = _post(payload)

    if not data.get("data") or not isinstance(data["data"], list):
        raise RuntimeError(f"agnes 返回缺 data 字段: {json.dumps(data)[:500]}")
    first = data["data"][0] or {}
    img_url = first.get("url")
    if not img_url:
        raise RuntimeError(f"agnes 返回缺 url: {json.dumps(data)[:500]}")

    _download(img_url, out_path)
    return out_path


if __name__ == "__main__":
    # 自检：只确认 key 已设置，不打印它的任何片段
    key = _resolve_api_key()
    print(f"AGNES_API_KEY: set (length {len(key)})")
    print(f"BASE_URL: {_resolve_base_url()}")
    print("OK（未发测试请求，节省配额）")
