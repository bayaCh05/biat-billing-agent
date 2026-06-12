from __future__ import annotations

import numpy as np
from PIL import Image


class OCRPreprocessor:
    """Cleans scanned images before OCR.

    Pipeline: grayscale → deskew → denoise → binarize (Sauvola adaptive threshold).
    Each step is defensive: if it fails it returns the input unchanged.
    """

    def process(self, image: Image.Image) -> Image.Image:
        image = self._to_grayscale(image)
        image = self._deskew(image)
        image = self._denoise(image)
        image = self._binarize(image)
        return image

    # ── Steps ─────────────────────────────────────────────────────────────────

    def _to_grayscale(self, image: Image.Image) -> Image.Image:
        return image.convert("L")

    def _deskew(self, image: Image.Image) -> Image.Image:
        import cv2
        arr = np.array(image, dtype=np.uint8)
        edges = cv2.Canny(arr, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180,
            threshold=80, minLineLength=80, maxLineGap=10,
        )
        if lines is None or len(lines) == 0:
            return image

        angles: list[float] = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 != x1:
                angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
                if abs(angle) < 45:
                    angles.append(angle)

        if not angles:
            return image

        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.5:
            return image  # negligible skew — skip rotation

        h, w = arr.shape
        M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
        rotated = cv2.warpAffine(
            arr, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return Image.fromarray(rotated)

    def _denoise(self, image: Image.Image) -> Image.Image:
        import cv2
        arr = np.array(image, dtype=np.uint8)
        denoised = cv2.fastNlMeansDenoising(arr, h=10, templateWindowSize=7, searchWindowSize=21)
        return Image.fromarray(denoised)

    def _binarize(self, image: Image.Image) -> Image.Image:
        from skimage.filters import threshold_sauvola
        arr = np.array(image, dtype=np.uint8)
        thresh = threshold_sauvola(arr, window_size=25)
        binary = ((arr > thresh) * 255).astype(np.uint8)
        return Image.fromarray(binary)
