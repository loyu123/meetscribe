import sys, time
import torch
from funasr import AutoModel

MODEL_ID = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_ID  = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_ID = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

# 优先使用 GPU（CUDA），无 GPU 时自动回退 CPU
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
print(">> 推理设备: %s" % DEVICE, flush=True)

print(">> 正在加载 FunASR 模型 (paraformer + fsmn-vad + ct-punc) ...", flush=True)
t0 = time.time()
model = AutoModel(
    model=MODEL_ID,
    vad_model=VAD_ID,
    punc_model=PUNC_ID,
    device=DEVICE,
    disable_update=True,
    hub="modelscope",
)
print(">> 模型加载完成, 耗时 %.1fs" % (time.time() - t0), flush=True)


def transcribe(path, hotword=""):
    kwargs = {"input": path, "batch_size_s": 300}
    if hotword:
        kwargs["hotword"] = hotword
    res = model.generate(**kwargs)
    item = res[0] if res else {}
    text = item.get("text", "")
    sentences = []
    if "sentence_info" in item:
        for s in item["sentence_info"]:
            sentences.append({
                "text": s.get("text", ""),
                "start": s.get("start"),
                "end": s.get("end"),
            })
    elif "timestamp" in item:
        for t in item["timestamp"]:
            sentences.append({"text": "", "start": t[0], "end": t[1]})
    return text, sentences


if __name__ == "__main__":
    paths = sys.argv[1:]
    for p in paths:
        print("\n" + "=" * 60)
        print("FILE:", p)
        print("=" * 60, flush=True)
        t0 = time.time()
        text, sentences = transcribe(p)
        dt = time.time() - t0
        segs = len(sentences)
        print("语音段数(VAD):", segs, "| 转写字符数:", len(text), "| 耗时 %.1fs" % dt)
        print("---- 转写文本 ----")
        print(text if text else "(空：VAD 未检到有效语音，符合 FR-10/11 静音/噪声不产文本)")
        if sentences and sentences[0].get("text"):
            print("---- 带时间戳分句(前20) ----")
            for i, s in enumerate(sentences[:20]):
                print("[%s -> %s] %s" % (s.get("start"), s.get("end"), s.get("text")))
