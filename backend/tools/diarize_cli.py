"""说话人分离命令行工具（FunASR + CAM++）。

用法:
    python diarize_cli.py audio.wav [more.wav ...] [--num-spk N]

技术路线:
    fsmn-vad (静音切分) -> paraformer (转写) -> ct-punc (标点)
    -> CAM++ (说话人嵌入) -> 聚类 (会话内说话人标签)
注意: 仅做"会话内"说话人分离，不提取/不落库声纹，符合合规要求。
"""
import sys
import time

import torch
from funasr import AutoModel

ASR_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
SPK_MODEL = "cam++"  # 别名 -> iic/speech_campplus_sv_zh-cn_16k-common

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"


def fmt_ms(ms):
    if ms is None:
        return ""
    s = int(ms) / 1000.0
    return "%02d:%02d:%06.3f" % (int(s) // 3600, int(s) % 3600 // 60, s % 60)


def build_model():
    print(">> 推理设备: %s" % DEVICE, flush=True)
    print(">> 加载模型 (paraformer + fsmn-vad + ct-punc + cam++) ...", flush=True)
    t0 = time.time()
    model = AutoModel(
        model=ASR_MODEL,
        vad_model=VAD_MODEL,
        punc_model=PUNC_MODEL,
        spk_model=SPK_MODEL,
        device=DEVICE,
        disable_update=True,
        hub="modelscope",
    )
    print(">> 模型加载完成, 耗时 %.1fs" % (time.time() - t0), flush=True)
    return model


def diarize(model, path, num_spk=None):
    kwargs = {
        "input": path,
        "batch_size_s": 300,
        "sentence_timestamp": True,
        "return_spk_center": True,  # 返回每位说话人的质心向量
    }
    if num_spk:
        kwargs["preset_spk_num"] = int(num_spk)
    t0 = time.time()
    res = model.generate(**kwargs)
    cost = time.time() - t0
    return (res[0] if res else {}), cost


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    num_spk = None
    for i, a in enumerate(sys.argv):
        if a == "--num-spk" and i + 1 < len(sys.argv):
            num_spk = sys.argv[i + 1]
    if not args:
        print(__doc__)
        return

    model = build_model()
    for path in args:
        print("\n" + "=" * 64)
        print("FILE:", path)
        print("=" * 64, flush=True)
        item, cost = diarize(model, path, num_spk)
        si = item.get("sentence_info") or []
        speakers = sorted({s.get("spk") for s in si if s.get("spk") is not None})
        print("sentence 数:", len(si), "| 检出说话人:", speakers, "| 耗时 %.2fs" % cost)
        for s in si:
            print("[%s - %s] SPK%s  %s" % (
                fmt_ms(s.get("start")), fmt_ms(s.get("end")), s.get("spk"), s.get("text")))
        c = item.get("spk_embedding_center")
        if c is not None:
            try:
                print("spk 质心 shape:", tuple(c.shape))
            except Exception:
                pass


if __name__ == "__main__":
    main()
