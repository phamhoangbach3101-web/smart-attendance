"""AdaFace IR101 WebFace12M Model Service.

Official Checkpoint: minchul/cvlface_adaface_ir101_webface12m
Reference: https://github.com/mk-minchul/CVLface
Paper: AdaFace: Quality Adaptive Margin for Face Recognition (CVPR 2022)

Pipeline requirements:
1. Face alignment: 5 facial landmarks -> 112x112 similarity transform.
2. Color space: OpenCV BGR -> RGB (converted exactly once).
3. Normalization: pixel values scaled to [0, 1], then normalized with
   mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5].
4. Output embedding: 512-dim float32 vector, checked for finite values,
   and L2-normalized for cosine similarity matching.
5. Execution: eval mode, torch.inference_mode(), auto-selects CUDA or CPU.
"""
import hashlib
import os
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import torch
import yaml
from insightface.utils import face_align
from omegaconf import OmegaConf

MODEL_ID = 'cvlface_adaface_ir101_webface12m'
MODEL_NAME = 'AdaFace IR101 WebFace12M'
REVISION = '54f602a0737bd1ee4a4e7e9fd089a485f397fefd'
WEIGHTS_FILE = 'pretrained_model/model.pt'
WEIGHTS_SHA256 = 'e312d79222d28027f146ed495e182e48fe0dddf404cdbbdabcccdbdd07cc3758'
SAFETENSORS_SHA256 = '2ea535a43877bd3de8091903935c783ce335be66a9f8917fae9a7a18ae4bbf56'
EMBEDDING_DIM = 512
PREPROCESSING_VERSION = 'v1.0-norm_crop_112x112_rgb_norm0.5'
DEFAULT_COSINE_THRESHOLD = 0.45
DEFAULT_MIN_MARGIN = 0.08

_instance: Optional['AdaFaceService'] = None
_instance_lock = threading.Lock()


def get_adaface_service(model_dir: Optional[str] = None) -> 'AdaFaceService':
    """Retrieve or initialize the global AdaFaceService singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AdaFaceService(model_dir=model_dir)
            _instance.load_model()
        return _instance


def embed_detected_face(service, frame: np.ndarray, raw) -> np.ndarray:
    """AdaFace embedding of one face found by the SCRFD detector.

    InsightFace buffalo_sc also attaches its own ArcFace vector (raw.embedding)
    to every detected face. That vector lives in a different embedding space
    from the AdaFace gallery, so it must never be used for matching here.
    The 5 landmarks are required for the 112x112 alignment AdaFace expects.
    """
    kps = getattr(raw, 'kps', None)
    if kps is None or len(kps) < 5:
        raise ValueError('Thiếu 5 điểm mốc khuôn mặt để căn chỉnh cho AdaFace.')
    return service.extract_embedding(frame, kps=np.asarray(kps, dtype=np.float32))


class AdaFaceService:
    """Manages AdaFace IR101 model loading, landmark alignment, and embedding extraction."""

    def __init__(self, model_dir: Optional[str] = None, device: Optional[str] = None):
        if model_dir is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_dir = os.path.join(base, 'models', 'cvlface_adaface_ir101_webface12m')
        self.model_dir = os.path.abspath(model_dir)
        self.requested_device = device
        self.device = None
        self.model = None
        self.state = 'idle'  # 'idle', 'loading', 'ready', 'error'
        self.error: Optional[str] = None
        self.load_seconds: Optional[float] = None
        self.loaded_at: Optional[str] = None
        self._lock = threading.RLock()

    def load_model(self) -> None:
        """Load the IR101 model architecture and pretrained WebFace12M weights."""
        with self._lock:
            if self.state == 'ready':
                return
            self.state = 'loading'
            self.error = None
            t0 = time.time()
            try:
                # 1. Determine device
                if self.requested_device:
                    self.device = torch.device(self.requested_device)
                else:
                    self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

                # 2. Verify model directory
                if not os.path.exists(self.model_dir):
                    raise FileNotFoundError(
                        f"Thư mục model không tồn tại: {self.model_dir}. Vui lòng tải model từ Hugging Face."
                    )

                # 3. Import model definition from local repo
                if self.model_dir not in sys.path:
                    sys.path.insert(0, self.model_dir)
                try:
                    from models import get_model
                except ImportError as exc:
                    raise ImportError(
                        f"Không import được kiến trúc CVLFace từ {self.model_dir}: {exc}"
                    )

                # 4. Load config and weights
                yaml_path = os.path.join(self.model_dir, 'pretrained_model', 'model.yaml')
                weights_path = os.path.join(self.model_dir, 'pretrained_model', 'model.pt')
                if not os.path.exists(yaml_path):
                    raise FileNotFoundError(f"Thiếu file config model: {yaml_path}")
                if not os.path.exists(weights_path):
                    raise FileNotFoundError(f"Thiếu file weights model: {weights_path}")

                conf_dict = yaml.safe_load(open(yaml_path, 'r', encoding='utf-8'))
                model_conf = OmegaConf.create(conf_dict)

                # Instantiate IR101
                model = get_model(model_conf)
                model.load_state_dict_from_path(weights_path)
                model.eval()
                model.to(self.device)

                self.model = model
                self.load_seconds = round(time.time() - t0, 2)
                self.loaded_at = time.strftime('%Y-%m-%d %H:%M:%S')
                self.state = 'ready'

                device_name = self.get_device_name()
                print(
                    f"[INFO] {MODEL_NAME} loaded on {device_name} in {self.load_seconds}s "
                    f"(eval mode, revision {REVISION[:7]})"
                )
            except Exception as exc:
                self.state = 'error'
                self.error = f"{type(exc).__name__}: {exc}"
                print(f"[ERROR] Failed to load {MODEL_NAME}: {self.error}")
                raise

    def get_device_name(self) -> str:
        """Human-readable device description for logs and status UI."""
        if self.device is None:
            return 'Chưa khởi tạo'
        if self.device.type == 'cuda':
            gpu_name = torch.cuda.get_device_name(self.device)
            return f"CUDA ({gpu_name})"
        return 'CPU'

    def align_and_crop(self, img_bgr: np.ndarray, kps: Optional[np.ndarray] = None) -> np.ndarray:
        """Align face using 5 facial landmarks to a 112x112 BGR image crop."""
        if img_bgr is None or img_bgr.size == 0:
            raise ValueError("Input image is empty")

        if kps is not None and len(kps) >= 5:
            try:
                aligned = face_align.norm_crop(img_bgr, landmark=kps, image_size=112)
                if aligned is not None and aligned.shape[:2] == (112, 112):
                    return aligned
            except Exception as exc:
                print(f"[DEBUG] Landmark alignment failed, falling back to resize: {exc}")

        # Fallback if landmarks missing or alignment threw an error
        if img_bgr.shape[:2] == (112, 112):
            return img_bgr.copy()
        return cv2.resize(img_bgr, (112, 112), interpolation=cv2.INTER_AREA)

    def preprocess_tensor(self, aligned_bgr: np.ndarray) -> torch.Tensor:
        """Convert 112x112 BGR to normalized RGB PyTorch tensor.

        Rules:
        - Convert BGR to RGB exactly once.
        - Scale to [0, 1].
        - Normalize: mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5] (range [-1, 1]).
        - Output tensor shape: (3, 112, 112) float32.
        """
        if aligned_bgr.shape[:2] != (112, 112):
            aligned_bgr = cv2.resize(aligned_bgr, (112, 112), interpolation=cv2.INTER_AREA)

        aligned_rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(aligned_rgb).permute(2, 0, 1).float() / 255.0
        tensor = (tensor - 0.5) / 0.5
        return tensor

    def extract_embedding(
        self, img_bgr: np.ndarray, kps: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """Extract a 512-dim L2-normalized feature embedding from an image.

        Args:
            img_bgr: Full image or face crop in BGR format (numpy uint8).
            kps: 5 facial landmarks (x, y) if available from detector.

        Returns:
            np.ndarray of shape (512,), float32, with L2-norm == 1.0.
        """
        if self.state != 'ready':
            self.load_model()

        aligned_bgr = self.align_and_crop(img_bgr, kps=kps)
        tensor = self.preprocess_tensor(aligned_bgr).unsqueeze(0).to(self.device)

        with self._lock:
            with torch.inference_mode():
                out = self.model(tensor)

        emb = out.cpu().numpy().flatten().astype(np.float32)

        if not np.isfinite(emb).all():
            raise ValueError("AdaFace model produced non-finite values in embedding")

        norm = float(np.linalg.norm(emb))
        if norm < 1e-12:
            raise ValueError("AdaFace embedding norm is zero")

        return (emb / norm).astype(np.float32)

    def extract_embeddings_batch(
        self, samples: List[Tuple[np.ndarray, Optional[np.ndarray]]]
    ) -> List[np.ndarray]:
        """Batch extraction of embeddings for multiple images to maximize inference throughput."""
        if not samples:
            return []
        if self.state != 'ready':
            self.load_model()

        tensors = []
        for img_bgr, kps in samples:
            aligned_bgr = self.align_and_crop(img_bgr, kps=kps)
            tensors.append(self.preprocess_tensor(aligned_bgr))

        batch_tensor = torch.stack(tensors).to(self.device)

        with self._lock:
            with torch.inference_mode():
                out = self.model(batch_tensor)

        embs = out.cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1e-12, norms)
        unit_embs = (embs / norms).astype(np.float32)

        for i, vec in enumerate(unit_embs):
            if not np.isfinite(vec).all():
                raise ValueError(f"AdaFace batch item {i} produced non-finite values")

        return [unit_embs[i] for i in range(len(unit_embs))]

    def calibrate_thresholds(self, dataset_dir: str) -> Dict[str, Union[float, int, bool, str]]:
        """Calibrate threshold using empirical genuine & impostor similarity distributions."""
        if not os.path.exists(dataset_dir):
            return {
                'validated': False,
                'message': 'Thư mục dataset chưa tồn tại.',
                'recommended_threshold': DEFAULT_COSINE_THRESHOLD,
                'default_threshold': DEFAULT_COSINE_THRESHOLD,
                'genuine_count': 0,
                'impostor_count': 0,
            }

        import collections
        from functions.identity import parse_student_folder

        student_embs: Dict[str, List[np.ndarray]] = collections.defaultdict(list)
        for root, dirs, files in os.walk(dataset_dir):
            parts = root.replace('\\', '/').split('/')
            if any(p.startswith('.') for p in parts):
                continue
            if 'embeddings.npy' in files:
                folder_name = os.path.basename(root)
                parsed = parse_student_folder(folder_name)
                sid = parsed.get('id') or folder_name
                emb_path = os.path.join(root, 'embeddings.npy')
                try:
                    arr = np.load(emb_path)
                    if arr.size and np.isfinite(arr).all():
                        arr_2d = np.atleast_2d(arr)
                        if arr_2d.shape[1] == EMBEDDING_DIM:
                            norms = np.linalg.norm(arr_2d, axis=1, keepdims=True)
                            norms = np.where(norms < 1e-12, 1e-12, norms)
                            normed_arr = (arr_2d / norms).astype(np.float32)
                            for i in range(len(normed_arr)):
                                student_embs[sid].append(normed_arr[i])
                except Exception as exc:
                    print(f"[DEBUG] calibrate_thresholds error reading {emb_path}: {exc}")

        genuine_scores: List[float] = []
        impostor_scores: List[float] = []

        # Genuine pairs (same student ID, across samples or classes)
        for sid, embs_list in student_embs.items():
            if len(embs_list) >= 2:
                for i in range(len(embs_list)):
                    for j in range(i + 1, len(embs_list)):
                        score = float(embs_list[i] @ embs_list[j])
                        genuine_scores.append(score)

        # Impostor pairs (different student IDs)
        sids = list(student_embs.keys())
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                sid1, sid2 = sids[i], sids[j]
                # Compare first sample of each student
                score = float(student_embs[sid1][0] @ student_embs[sid2][0])
                impostor_scores.append(score)

        has_genuine = len(genuine_scores) >= 3
        has_impostor = len(impostor_scores) >= 5

        imp_mean = float(np.mean(impostor_scores)) if impostor_scores else 0.0
        imp_max = float(np.max(impostor_scores)) if impostor_scores else 0.0

        if has_genuine and has_impostor:
            gen_mean = float(np.mean(genuine_scores))
            gen_min = float(np.min(genuine_scores))

            # Optimal threshold placed between maximum impostor and mean genuine
            optimal = (imp_max + gen_mean) / 2.0
            optimal = float(np.clip(optimal, 0.35, 0.65))

            return {
                'validated': True,
                'message': 'Đã hiệu chuẩn thành công dựa trên phân phối thực tế trong dataset.',
                'recommended_threshold': round(optimal, 2),
                'default_threshold': DEFAULT_COSINE_THRESHOLD,
                'genuine_count': len(genuine_scores),
                'genuine_mean': round(gen_mean, 4),
                'genuine_min': round(gen_min, 4),
                'impostor_count': len(impostor_scores),
                'impostor_mean': round(imp_mean, 4),
                'impostor_max': round(imp_max, 4),
            }

        return {
            'validated': False,
            'message': (
                f"Chưa đủ dữ liệu ảnh cặp cùng người ({len(genuine_scores)} cặp cùng người, "
                f"{len(impostor_scores)} cặp khác người) để hiệu chuẩn thực nghiệm đầy đủ. "
                f"Ngưỡng chưa được xác thực hoàn toàn trên tập đa ảnh. "
                f"Sử dụng ngưỡng tiêu chuẩn {DEFAULT_COSINE_THRESHOLD}."
            ),
            'recommended_threshold': DEFAULT_COSINE_THRESHOLD,
            'default_threshold': DEFAULT_COSINE_THRESHOLD,
            'genuine_count': len(genuine_scores),
            'impostor_count': len(impostor_scores),
            'impostor_mean': round(imp_mean, 4),
            'impostor_max': round(imp_max, 4),
        }

    def info(self) -> dict:
        """Model status dictionary for API and settings UI."""
        return {
            'model_id': MODEL_ID,
            'model_name': MODEL_NAME,
            'revision': REVISION,
            'weights_sha256': WEIGHTS_SHA256,
            'embedding_dim': EMBEDDING_DIM,
            'preprocessing_version': PREPROCESSING_VERSION,
            'state': self.state,
            'error': self.error,
            'device': self.get_device_name(),
            'loaded_at': self.loaded_at,
            'load_seconds': self.load_seconds,
            'model_dir': self.model_dir,
            'default_threshold': DEFAULT_COSINE_THRESHOLD,
            'default_min_margin': DEFAULT_MIN_MARGIN,
        }
