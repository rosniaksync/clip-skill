"""Acha o centro horizontal do rosto do streamer dentro da caixa da webcam (para o zoom dos compilados).

Usa o detector YuNet do OpenCV (assets/face_yunet.onnx). Precisa de opencv-python-headless < 5.
Uso no código: face_cx(src, t0, t1, cam_px) -> x em pixels da fonte (ou None se não achar rosto).
Linha de comando: python face_center.py source.mp4 ini fim x,y,w,h(frações)
"""
import os
import subprocess
import sys

import numpy as np

try:
    import cv2
except ImportError:   # sem OpenCV: o zoom volta a centrar na caixa da webcam
    cv2 = None

MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "face_yunet.onnx")


def face_cx(src, t0, t1, cam_px, step=0.2):
    """cam_px = (x, y, w, h) em pixels. Retorna a mediana do centro x do rosto entre t0 e t1."""
    if cv2 is None or not os.path.exists(MODEL):
        return None
    x, y, w, h = cam_px
    n = max(1, int((t1 - t0) / step))
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", src,
           "-vf", f"crop={w}:{h}:{x}:{y},fps={1 / step:.3f}", "-frames:v", str(n),
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    sz = w * h * 3
    frames = np.frombuffer(raw, np.uint8)[: (len(raw) // sz) * sz].reshape(-1, h, w, 3)
    det = cv2.FaceDetectorYN.create(MODEL, "", (w, h), 0.6)
    xs = []
    for fr in frames:
        _, faces = det.detect(np.ascontiguousarray(fr))
        if faces is not None and len(faces):
            best = max(faces, key=lambda f: f[14])   # maior confiança
            xs.append(best[0] + best[2] / 2)
    if not xs:
        return None
    return x + float(np.median(xs))


if __name__ == "__main__":
    src, a, b, box = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    W, H = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", src],
                                   capture_output=True, text=True).stdout.split(",")[:2])
    fx, fy, fw, fh = map(float, box.split(","))
    print(face_cx(src, a, b, (int(fx * W), int(fy * H), int(fw * W) // 2 * 2, int(fh * H) // 2 * 2)))
