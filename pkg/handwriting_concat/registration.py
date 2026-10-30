"""Identify the sheet's ArUco markers and rectify its perspective."""

from __future__ import annotations

import cv2
import numpy as np

from .types import RegisteredPage, TemplateLayout


class RegistrationError(ValueError):
    """The collection sheet cannot be aligned automatically."""


def _marker_target_corners(bbox: tuple[float, float, float, float],
                           width_px: int, height_px: int,
                           layout: TemplateLayout) -> np.ndarray:
    left, top, right, bottom = bbox
    return np.asarray([
        [left * width_px / layout.width_mm, top * height_px / layout.height_mm],
        [right * width_px / layout.width_mm, top * height_px / layout.height_mm],
        [right * width_px / layout.width_mm, bottom * height_px / layout.height_mm],
        [left * width_px / layout.width_mm, bottom * height_px / layout.height_mm],
    ], dtype=np.float32)


def register_page(image_rgb: np.ndarray, layout: TemplateLayout, *,
                  output_dpi: int | None = None) -> RegisteredPage:
    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
        raise RegistrationError("Expected an RGB image")
    source_height, source_width = image_rgb.shape[:2]
    if min(source_width, source_height) < 500:
        raise RegistrationError("Image is too small to read the 9 mm markers")

    detection_scale = min(1.0, 3200 / max(source_width, source_height))
    detection_image = (cv2.resize(image_rgb, None, fx=detection_scale,
                                  fy=detection_scale, interpolation=cv2.INTER_AREA)
                       if detection_scale < 1.0 else image_rgb)
    grayscale = cv2.cvtColor(detection_image, cv2.COLOR_RGB2GRAY)
    dictionary = cv2.aruco.getPredefinedDictionary(
        getattr(cv2.aruco, layout.dictionary_name)
    )
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detected_corners, detected_ids, _ = cv2.aruco.ArucoDetector(
        dictionary, parameters
    ).detectMarkers(grayscale)
    found: dict[int, np.ndarray] = {}
    if detected_ids is not None:
        for marker_id, corners in zip(detected_ids.flatten(), detected_corners):
            identifier = int(marker_id)
            if identifier in found:
                raise RegistrationError(f"Marker ID {identifier} was detected twice")
            found[identifier] = corners.reshape(4, 2) / detection_scale

    expected = {marker.id for marker in layout.markers}
    missing = sorted(expected - set(found))
    if missing:
        raise RegistrationError(
            f"Missing ArUco markers {missing}; keep all four page corners in view"
        )

    marker_sizes = []
    for marker in layout.markers:
        corners = found[marker.id]
        lengths = np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1)
        physical_size = marker.bbox_mm[2] - marker.bbox_mm[0]
        marker_sizes.extend(lengths * 25.4 / physical_size)
    estimated_dpi = float(np.median(marker_sizes))
    dpi = int(output_dpi) if output_dpi is not None else int(round(
        min(600, max(150, estimated_dpi))
    ))
    if not 100 <= dpi <= 600:
        raise RegistrationError("Output DPI must be between 100 and 600")
    target_width = round(layout.width_mm / 25.4 * dpi)
    target_height = round(layout.height_mm / 25.4 * dpi)

    source_points = []
    target_points = []
    for marker in layout.markers:
        source_points.extend(found[marker.id])
        target_points.extend(_marker_target_corners(
            marker.bbox_mm, target_width, target_height, layout
        ))
    source_array = np.asarray(source_points, dtype=np.float32)
    target_array = np.asarray(target_points, dtype=np.float32)
    homography, inliers = cv2.findHomography(
        source_array, target_array, cv2.RANSAC,
        ransacReprojThreshold=max(2.0, dpi * 0.015),
    )
    if homography is None or inliers is None or int(inliers.sum()) < 12:
        raise RegistrationError("Marker corners do not describe a reliable flat page")
    projected = cv2.perspectiveTransform(
        source_array.reshape(-1, 1, 2), homography
    ).reshape(-1, 2)
    residuals = np.linalg.norm(projected - target_array, axis=1)
    rms = float(np.sqrt(np.mean(np.square(residuals[inliers.flatten() != 0]))))
    if rms > max(3.0, dpi * 0.03):
        raise RegistrationError("Page alignment error is too large; flatten and rescan")

    corrected = cv2.warpPerspective(
        image_rgb, homography, (target_width, target_height),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return RegisteredPage(
        rgb=corrected,
        homography=homography,
        detected_ids=tuple(sorted(expected)),
        reprojection_rms_px=rms,
        output_dpi=float(dpi),
        input_size_px=(source_width, source_height),
    )
