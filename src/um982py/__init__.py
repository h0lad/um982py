"""Connect to a UM982 receiver, decode its messages, and work with GNSS data."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from um982py import commands
    from um982py.adapters import geojson_feature, navsatfix
    from um982py.antenna import swap_antenna
    from um982py.assessment import PositionAssessment, PositionLimits, assess_position
    from um982py.async_ppp import AsyncPppSession
    from um982py.async_receiver import AsyncReceiver
    from um982py.augmentation import (
        HIGH_ACCURACY_SIGNAL_GROUP,
        AugmentationState,
        enable_augmentation,
    )
    from um982py.capture import (
        InterruptedCapture,
        capture_live,
        decode_records,
        iter_frames,
        load_records,
        read_frames,
    )
    from um982py.commands import Log
    from um982py.corrections import stale_correction
    from um982py.crs import CoordinateTransform, transform_coordinate
    from um982py.decode import decode_message
    from um982py.geodesy import (
        dms_to_degrees,
        ecef_from_geodetic,
        enu_from_ecef,
        geodetic_from_ecef,
        haversine_distance,
        wavelength,
    )
    from um982py.live import (
        LiveHealth,
        PositionSession,
        PositionSubscription,
        PositionUpdate,
    )
    from um982py.measurement import (
        RangeSample,
        SignalKey,
        bdt_week_to_gps_seconds,
        gps_epoch,
        gps_to_utc,
        message_utc,
        range_samples,
        sample_series,
    )
    from um982py.messages.enums import PositionType, SatelliteSystem, SolutionStatus
    from um982py.messages.navigation import BestNavigation, Fix, Heading
    from um982py.ntrip import (
        Mountpoint,
        NtripClient,
        NtripClientPool,
        NtripDisconnected,
        NtripError,
        ReconnectPolicy,
        fetch_sourcetable,
        parse_sourcetable,
    )
    from um982py.ppk import PostProcessingError, PpkResult, run_ppk
    from um982py.ppp import PppService, PppSession, PppSolution
    from um982py.pps import (
        PpsDevice,
        PpsEdge,
        PpsSnapshot,
        missed_pps_edges,
        pps_clock_offset_ns,
    )
    from um982py.precise import PrecisePoint, Sp3Product, interpolate_sp3, parse_sp3
    from um982py.quality import (
        EpochSolution,
        FixClass,
        QualitySummary,
        solution_from_record,
    )
    from um982py.receiver import Receiver
    from um982py.receiver_models import (
        PerformanceStatus,
        ReceiverConfig,
        ReceiverSystemStatus,
        TaskPerformance,
        parse_configuration,
    )
    from um982py.rinex import RinexExport, RinexMetadata, export_rinex
    from um982py.rinex_merge import MergeResult, merge_gps_observations
    from um982py.rinex_nav import RinexNavigationExport, export_rinex_navigation
    from um982py.rover import Rover, RoverPosition
    from um982py.rtcm import decode_rtcm
    from um982py.rtk_session import (
        CorrectionWriteError,
        GgaProviderError,
        RtkHealth,
        RtkSession,
    )
    from um982py.satellites import Satellite, SatelliteSignal
    from um982py.session import (
        SessionGap,
        SessionRecorder,
        iter_session_bytes,
        iter_session_events,
        iter_session_frames,
    )
    from um982py.signals import TrackingSignal, tracking_signal
    from um982py.streaming import (
        ReceiverStream,
        StreamEvent,
        StreamHealth,
        Subscription,
    )
    from um982py.survey import SurveyPoint, survey_point, wait_for_fix
    from um982py.track import TrackWriter
    from um982py.waypoint import WaypointDirection, waypoint_direction

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "AsyncPppSession": ("um982py.async_ppp", "AsyncPppSession"),
    "AsyncReceiver": ("um982py.async_receiver", "AsyncReceiver"),
    "AugmentationState": ("um982py.augmentation", "AugmentationState"),
    "BestNavigation": ("um982py.messages.navigation", "BestNavigation"),
    "CoordinateTransform": ("um982py.crs", "CoordinateTransform"),
    "CorrectionWriteError": ("um982py.rtk_session", "CorrectionWriteError"),
    "EpochSolution": ("um982py.quality", "EpochSolution"),
    "Fix": ("um982py.messages.navigation", "Fix"),
    "FixClass": ("um982py.quality", "FixClass"),
    "GgaProviderError": ("um982py.rtk_session", "GgaProviderError"),
    "HIGH_ACCURACY_SIGNAL_GROUP": (
        "um982py.augmentation",
        "HIGH_ACCURACY_SIGNAL_GROUP",
    ),
    "Heading": ("um982py.messages.navigation", "Heading"),
    "InterruptedCapture": ("um982py.capture", "InterruptedCapture"),
    "LiveHealth": ("um982py.live", "LiveHealth"),
    "Log": ("um982py.commands", "Log"),
    "MergeResult": ("um982py.rinex_merge", "MergeResult"),
    "Mountpoint": ("um982py.ntrip", "Mountpoint"),
    "NtripClient": ("um982py.ntrip", "NtripClient"),
    "NtripClientPool": ("um982py.ntrip", "NtripClientPool"),
    "NtripDisconnected": ("um982py.ntrip", "NtripDisconnected"),
    "NtripError": ("um982py.ntrip", "NtripError"),
    "PerformanceStatus": ("um982py.receiver_models", "PerformanceStatus"),
    "PositionAssessment": ("um982py.assessment", "PositionAssessment"),
    "PositionLimits": ("um982py.assessment", "PositionLimits"),
    "PositionSession": ("um982py.live", "PositionSession"),
    "PositionSubscription": ("um982py.live", "PositionSubscription"),
    "PositionType": ("um982py.messages.enums", "PositionType"),
    "PositionUpdate": ("um982py.live", "PositionUpdate"),
    "PostProcessingError": ("um982py.ppk", "PostProcessingError"),
    "PpkResult": ("um982py.ppk", "PpkResult"),
    "PppService": ("um982py.ppp", "PppService"),
    "PppSession": ("um982py.ppp", "PppSession"),
    "PppSolution": ("um982py.ppp", "PppSolution"),
    "PpsDevice": ("um982py.pps", "PpsDevice"),
    "PpsEdge": ("um982py.pps", "PpsEdge"),
    "PpsSnapshot": ("um982py.pps", "PpsSnapshot"),
    "PrecisePoint": ("um982py.precise", "PrecisePoint"),
    "QualitySummary": ("um982py.quality", "QualitySummary"),
    "RangeSample": ("um982py.measurement", "RangeSample"),
    "Receiver": ("um982py.receiver", "Receiver"),
    "ReceiverConfig": ("um982py.receiver_models", "ReceiverConfig"),
    "ReceiverStream": ("um982py.streaming", "ReceiverStream"),
    "ReceiverSystemStatus": ("um982py.receiver_models", "ReceiverSystemStatus"),
    "ReconnectPolicy": ("um982py.ntrip", "ReconnectPolicy"),
    "RinexExport": ("um982py.rinex", "RinexExport"),
    "RinexMetadata": ("um982py.rinex", "RinexMetadata"),
    "RinexNavigationExport": ("um982py.rinex_nav", "RinexNavigationExport"),
    "RtkHealth": ("um982py.rtk_session", "RtkHealth"),
    "RtkSession": ("um982py.rtk_session", "RtkSession"),
    "Rover": ("um982py.rover", "Rover"),
    "RoverPosition": ("um982py.rover", "RoverPosition"),
    "Satellite": ("um982py.satellites", "Satellite"),
    "SatelliteSignal": ("um982py.satellites", "SatelliteSignal"),
    "SatelliteSystem": ("um982py.messages.enums", "SatelliteSystem"),
    "SessionGap": ("um982py.session", "SessionGap"),
    "SessionRecorder": ("um982py.session", "SessionRecorder"),
    "SignalKey": ("um982py.measurement", "SignalKey"),
    "SolutionStatus": ("um982py.messages.enums", "SolutionStatus"),
    "Sp3Product": ("um982py.precise", "Sp3Product"),
    "StreamEvent": ("um982py.streaming", "StreamEvent"),
    "StreamHealth": ("um982py.streaming", "StreamHealth"),
    "Subscription": ("um982py.streaming", "Subscription"),
    "SurveyPoint": ("um982py.survey", "SurveyPoint"),
    "TaskPerformance": ("um982py.receiver_models", "TaskPerformance"),
    "TrackingSignal": ("um982py.signals", "TrackingSignal"),
    "TrackWriter": ("um982py.track", "TrackWriter"),
    "WaypointDirection": ("um982py.waypoint", "WaypointDirection"),
    "assess_position": ("um982py.assessment", "assess_position"),
    "bdt_week_to_gps_seconds": ("um982py.measurement", "bdt_week_to_gps_seconds"),
    "capture_live": ("um982py.capture", "capture_live"),
    "commands": ("um982py.commands", None),
    "decode_message": ("um982py.decode", "decode_message"),
    "decode_rtcm": ("um982py.rtcm", "decode_rtcm"),
    "decode_records": ("um982py.capture", "decode_records"),
    "dms_to_degrees": ("um982py.geodesy", "dms_to_degrees"),
    "ecef_from_geodetic": ("um982py.geodesy", "ecef_from_geodetic"),
    "enable_augmentation": ("um982py.augmentation", "enable_augmentation"),
    "enu_from_ecef": ("um982py.geodesy", "enu_from_ecef"),
    "export_rinex": ("um982py.rinex", "export_rinex"),
    "export_rinex_navigation": ("um982py.rinex_nav", "export_rinex_navigation"),
    "fetch_sourcetable": ("um982py.ntrip", "fetch_sourcetable"),
    "geodetic_from_ecef": ("um982py.geodesy", "geodetic_from_ecef"),
    "geojson_feature": ("um982py.adapters", "geojson_feature"),
    "gps_epoch": ("um982py.measurement", "gps_epoch"),
    "gps_to_utc": ("um982py.measurement", "gps_to_utc"),
    "haversine_distance": ("um982py.geodesy", "haversine_distance"),
    "interpolate_sp3": ("um982py.precise", "interpolate_sp3"),
    "iter_frames": ("um982py.capture", "iter_frames"),
    "iter_session_bytes": ("um982py.session", "iter_session_bytes"),
    "iter_session_events": ("um982py.session", "iter_session_events"),
    "iter_session_frames": ("um982py.session", "iter_session_frames"),
    "load_records": ("um982py.capture", "load_records"),
    "merge_gps_observations": ("um982py.rinex_merge", "merge_gps_observations"),
    "message_utc": ("um982py.measurement", "message_utc"),
    "missed_pps_edges": ("um982py.pps", "missed_pps_edges"),
    "navsatfix": ("um982py.adapters", "navsatfix"),
    "parse_configuration": ("um982py.receiver_models", "parse_configuration"),
    "parse_sourcetable": ("um982py.ntrip", "parse_sourcetable"),
    "parse_sp3": ("um982py.precise", "parse_sp3"),
    "pps_clock_offset_ns": ("um982py.pps", "pps_clock_offset_ns"),
    "range_samples": ("um982py.measurement", "range_samples"),
    "read_frames": ("um982py.capture", "read_frames"),
    "run_ppk": ("um982py.ppk", "run_ppk"),
    "sample_series": ("um982py.measurement", "sample_series"),
    "solution_from_record": ("um982py.quality", "solution_from_record"),
    "stale_correction": ("um982py.corrections", "stale_correction"),
    "swap_antenna": ("um982py.antenna", "swap_antenna"),
    "survey_point": ("um982py.survey", "survey_point"),
    "tracking_signal": ("um982py.signals", "tracking_signal"),
    "transform_coordinate": ("um982py.crs", "transform_coordinate"),
    "wavelength": ("um982py.geodesy", "wavelength"),
    "wait_for_fix": ("um982py.survey", "wait_for_fix"),
    "waypoint_direction": ("um982py.waypoint", "waypoint_direction"),
}

__all__ = [
    "HIGH_ACCURACY_SIGNAL_GROUP",
    "AsyncPppSession",
    "AsyncReceiver",
    "AugmentationState",
    "BestNavigation",
    "CoordinateTransform",
    "CorrectionWriteError",
    "EpochSolution",
    "Fix",
    "FixClass",
    "GgaProviderError",
    "Heading",
    "InterruptedCapture",
    "LiveHealth",
    "Log",
    "MergeResult",
    "Mountpoint",
    "NtripClient",
    "NtripClientPool",
    "NtripDisconnected",
    "NtripError",
    "PerformanceStatus",
    "PositionAssessment",
    "PositionLimits",
    "PositionSession",
    "PositionSubscription",
    "PositionType",
    "PositionUpdate",
    "PostProcessingError",
    "PpkResult",
    "PppService",
    "PppSession",
    "PppSolution",
    "PpsDevice",
    "PpsEdge",
    "PpsSnapshot",
    "PrecisePoint",
    "QualitySummary",
    "RangeSample",
    "Receiver",
    "ReceiverConfig",
    "ReceiverStream",
    "ReceiverSystemStatus",
    "ReconnectPolicy",
    "RinexExport",
    "RinexMetadata",
    "RinexNavigationExport",
    "Rover",
    "RoverPosition",
    "RtkHealth",
    "RtkSession",
    "Satellite",
    "SatelliteSignal",
    "SatelliteSystem",
    "SessionGap",
    "SessionRecorder",
    "SignalKey",
    "SolutionStatus",
    "Sp3Product",
    "StreamEvent",
    "StreamHealth",
    "Subscription",
    "SurveyPoint",
    "TaskPerformance",
    "TrackWriter",
    "TrackingSignal",
    "WaypointDirection",
    "assess_position",
    "bdt_week_to_gps_seconds",
    "capture_live",
    "commands",
    "decode_message",
    "decode_records",
    "decode_rtcm",
    "dms_to_degrees",
    "ecef_from_geodetic",
    "enable_augmentation",
    "enu_from_ecef",
    "export_rinex",
    "export_rinex_navigation",
    "fetch_sourcetable",
    "geodetic_from_ecef",
    "geojson_feature",
    "gps_epoch",
    "gps_to_utc",
    "haversine_distance",
    "interpolate_sp3",
    "iter_frames",
    "iter_session_bytes",
    "iter_session_events",
    "iter_session_frames",
    "load_records",
    "merge_gps_observations",
    "message_utc",
    "missed_pps_edges",
    "navsatfix",
    "parse_configuration",
    "parse_sourcetable",
    "parse_sp3",
    "pps_clock_offset_ns",
    "range_samples",
    "read_frames",
    "run_ppk",
    "sample_series",
    "solution_from_record",
    "stale_correction",
    "survey_point",
    "swap_antenna",
    "tracking_signal",
    "transform_coordinate",
    "wait_for_fix",
    "wavelength",
    "waypoint_direction",
]


def __getattr__(name: str) -> object:
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    target = import_module(module)
    value = target if attribute is None else getattr(target, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
