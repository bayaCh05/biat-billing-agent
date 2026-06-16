from __future__ import annotations

import numpy as np
from PIL import Image

# Minimum width (pixels) below which we upscale before OCR.
# Screenshots captured at 72–96 dpi often land around 800–1200 px wide;
# Tesseract accuracy drops sharply below ~150 dpi equivalent.
_MIN_OCR_WIDTH = 1800


class OCRPreprocessor:
    """Cleans scanned images before OCR.

    Pipeline (in order):
      1. grayscale
      2. upscale   — screenshots are often too small for accurate OCR
      3. deskew
      4. denoise
      5. contrast  — CLAHE boosts local contrast on washed-out scans
      6. binarize  — Sauvola adaptive threshold

    Each step is defensive: on any failure it returns the input unchanged.
    """

    def process(self, image: Image.Image) -> Image.Image:
        image = self._to_grayscale(image)
        image = self._upscale(image)
        image = self._deskew(image)
        image = self._denoise(image)
        image = self._enhance_contrast(image)
        image = self._binarize(image)
        return image

    # ── Steps ─────────────────────────────────────────────────────────────────

    def _to_grayscale(self, image: Image.Image) -> Image.Image:
        return image.convert("L")

    def _upscale(self, image: Image.Image) -> Image.Image:
        """Scale up images narrower than _MIN_OCR_WIDTH.

        Screenshots printed to PDF typically arrive at 72–96 dpi.
        Upscaling to a minimum width before deskew/denoise/binarize
        gives Tesseract enough resolution to distinguish similar glyphs
        (e.g. R vs E, ct vs f).
        """
        w, h = image.size
        if w >= _MIN_OCR_WIDTH:
            return image
        scale = _MIN_OCR_WIDTH / w
        new_size = (int(w * scale), int(h * scale))
        try:
            return image.resize(new_size, Image.LANCZOS)
        except Exception:
            return image

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
            return image

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

    def _enhance_contrast(self, image: Image.Image) -> Image.Image:
        """CLAHE — Contrast Limited Adaptive Histogram Equalization.

        Applied after denoising and before binarization.  CLAHE boosts
        local contrast independently per tile, which recovers faint ink
        on washed-out screenshots and uneven scans without over-brightening
        already-clear areas.
        """
        try:
            import cv2
            arr = np.array(image, dtype=np.uint8)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(arr)
            return Image.fromarray(enhanced)
        except Exception:
            return image

    def _binarize(self, image: Image.Image) -> Image.Image:
        from skimage.filters import threshold_sauvola
        arr = np.array(image, dtype=np.uint8)
        thresh = threshold_sauvola(arr, window_size=25)
        binary = ((arr > thresh) * 255).astype(np.uint8)
        return Image.fromarray(binary)
