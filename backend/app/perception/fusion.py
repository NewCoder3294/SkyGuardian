"""Fusion: YOLO image-plane detection + SLAM pose -> local-frame Entity.

The core problem: YOLO gives us a pixel box. SLAM gives us the camera's
position and orientation in the local frame (metres, no GPS). We need a
3D position for the detected object in that same frame.

Approach (honest about what monocular gives us):
  1. Unproject the box centre from pixels to a unit ray in camera coordinates
     using the camera intrinsics K.
  2. Rotate that ray into the local world frame using R_wc from the SLAM pose.
  3. Intersect the ray with the ground plane (z=0 in local frame) to get an
     estimated ground-plane position. This assumes detected objects sit on the
     ground — reasonable for poi/hazard/person detections from an aerial view.
  4. If the SLAM pose is not yet available (pipeline not anchored), fall back
     to placing the entity at the camera position with a lower confidence.

This is intentionally simple and honest. A proper depth estimate needs either
stereo, an IMU, or a monocular depth model — none of which we have here.
The ground-plane assumption degrades gracefully for elevated objects (they will
appear at a slightly wrong distance but in approximately the right direction).
"""
from __future__ import annotations

import numpy as np

from ..contracts import Entity, EntitySource, EntityType, Vec3
from .yolo import YoloDetection
from ..perception.slam.types import CameraModel, Pose


# Map YOLO class names to Entity types. Extend as needed for your model's vocab.
# Classes not listed here default to EntityType.OBJECT.
_LABEL_TO_TYPE: dict[str, EntityType] = {
    "person":    EntityType.SOLDIER,
    "soldier":   EntityType.SOLDIER,
    "car":       EntityType.OBJECT,
    "truck":     EntityType.OBJECT,
    "vehicle":   EntityType.OBJECT,
    "hazard":    EntityType.HAZARD,
    "debris":    EntityType.HAZARD,
    "obstacle":  EntityType.HAZARD,
    "door":      EntityType.POI,
    "doorway":   EntityType.POI,
    "entrance":  EntityType.POI,
    "building":  EntityType.POI,
}


def _unproject_ray(cx_px: float, cy_px: float, camera: CameraModel) -> np.ndarray:
    """Return the unit direction vector in camera space for a pixel (cx, cy)."""
    ray = np.array([
        (cx_px - camera.cx) / camera.fx,
        (cy_px - camera.cy) / camera.fy,
        1.0,
    ], dtype=np.float64)
    return ray / np.linalg.norm(ray)


def _ray_ground_intersect(
    ray_world: np.ndarray,
    camera_pos: np.ndarray,
) -> np.ndarray | None:
    """Intersect a ray from camera_pos in direction ray_world with z=0 plane.

    Returns the intersection point (x, y, 0) in the local frame, or None if
    the ray is parallel to or pointing away from the ground plane.
    """
    # ray: P = camera_pos + t * ray_world;  z=0 when camera_pos.z + t*ray_world.z = 0
    dz = ray_world[2]
    if abs(dz) < 1e-6:
        return None  # ray is nearly horizontal, no useful ground intersection
    t = -camera_pos[2] / dz
    if t < 0:
        return None  # intersection is behind the camera
    point = camera_pos + t * ray_world
    return point


def detection_to_entity(
    det: YoloDetection,
    camera: CameraModel,
    slam_pose: Pose | None,
    t: float,
    depth_map: np.ndarray | None = None,
    entity_id_prefix: str = "yolo",
) -> Entity:
    """Convert a single YOLO detection to a world-model Entity.

    If `depth_map` is provided (from a monocular depth model), the entity is
    placed at the camera's pixel ray scaled by the per-pixel depth — a real 3D
    position. Otherwise it falls back to the ground-plane intersection, which
    is correct only for objects sitting on z=0.

    If slam_pose is None (SLAM not yet running or not anchored), the entity is
    placed at the world origin with confidence halved — clearly flagged as
    unlocated but not silently dropped.
    """
    entity_type = _LABEL_TO_TYPE.get(det.label.lower(), EntityType.OBJECT)

    # Stable ID: hash label + rough pixel position so the same detection in
    # subsequent frames re-uses the same entity slot (world model deduplicates by id).
    bucket_x = int(det.cx_px / 32)
    bucket_y = int(det.cy_px / 32)
    entity_id = f"{entity_id_prefix}_{det.label}_{bucket_x}_{bucket_y}"

    if slam_pose is None:
        # No SLAM pose at all: we have no basis for a world-frame position.
        # Place at origin with halved confidence so the operator sees the
        # detection exists but knows it's unlocalised — not silently dropped.
        position = Vec3(x=0.0, y=0.0, z=0.0)
        confidence = det.confidence * 0.4
    else:
        # Unproject pixel to camera-frame unit ray.
        ray_cam = _unproject_ray(det.cx_px, det.cy_px, camera)
        cam_pos = slam_pose.position

        # Depth-map fusion mixes metric depth (~metres) with the camera-pose
        # position. That only stays self-consistent once SLAM is anchored;
        # before then `cam_pos` is in arbitrary VO units and adding metric
        # depth to it produces a meaningless sum. Until anchored, fall back to
        # the ground-plane intersection — it stays in pose-units throughout,
        # so YOLO entities sit in the same frame as `mavic_cam` and landmarks.
        if depth_map is not None and slam_pose.scale_known:
            # Monocular depth path: scale the ray by the per-pixel depth.
            cy_int = int(np.clip(round(det.cy_px), 0, depth_map.shape[0] - 1))
            cx_int = int(np.clip(round(det.cx_px), 0, depth_map.shape[1] - 1))
            depth = float(depth_map[cy_int, cx_int])
            # P_world = R_wc · (ray_cam * depth) + cam_pos
            p_world = slam_pose.R_wc @ (ray_cam * depth) + cam_pos
            position = Vec3(
                x=float(p_world[0]),
                y=float(p_world[1]),
                z=float(p_world[2]),
            )
            confidence = det.confidence
        else:
            # Ground-plane fallback. Pre-anchor, confidence is reduced to
            # signal the position is in unscaled units, not metres.
            ray_world = slam_pose.R_wc @ ray_cam
            ground_pt = _ray_ground_intersect(ray_world, cam_pos)
            if ground_pt is not None:
                position = Vec3(x=float(ground_pt[0]), y=float(ground_pt[1]), z=0.0)
                confidence = det.confidence if slam_pose.scale_known else det.confidence * 0.6
            else:
                fallback = cam_pos + ray_world * 3.0
                position = Vec3(
                    x=float(fallback[0]),
                    y=float(fallback[1]),
                    z=float(fallback[2]),
                )
                confidence = det.confidence * 0.5

    return Entity(
        id=entity_id,
        type=entity_type,
        position=position,
        confidence=min(1.0, confidence),
        timestamp=t,
        source=EntitySource.YOLO,
        label=det.label,
        ttl_s=3.0,  # detection must be refreshed every 3 s or goes stale
    )


def fuse_detections(
    detections: list[YoloDetection],
    camera: CameraModel,
    slam_pose: Pose | None,
    t: float,
    depth_map: np.ndarray | None = None,
) -> list[Entity]:
    """Convert a list of YOLO detections to world-model entities.
    Returns an empty list if detections is empty — never raises."""
    return [
        detection_to_entity(det, camera, slam_pose, t, depth_map=depth_map)
        for det in detections
    ]
