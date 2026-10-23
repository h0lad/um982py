"""Correction and PPP body layouts."""

from um982py.messages.schema import Field, Group, Layout

PPP_HEADER = (
    Field("prn", "u", 0, 2),
    Field("iodssr", "u", 2, 1),
    Field("iodp", "u", 3, 1),
    Field("seconds_of_day", "u", 4, 4),
)
ORBIT = (
    Field("prn", "u", 0, 2),
    Field("iodn", "u", 2, 2),
    Field("radial", "i", 4, 2),
    Field("in_track", "i", 6, 2),
    Field("cross_track", "i", 8, 2),
    Field("iod_corr", "u", 10, 1),
    Field("urai", "u", 11, 1),
)
CLOCK = (Field("iod_corr", "u", 0, 2), Field("c0", "i", 2, 2))
CODE_CORRECTION = (Field("mode", "u", 0, 2), Field("code_correction", "i", 2, 2))
CODE_BIAS = (
    Field("satellite_slot", "u", 0, 2),
    Field("bias_count", "u", 2, 2),
    Group("corrections", 4, CODE_CORRECTION, 15, 4),
)
COMBINED_HEADER = (
    Field("prn", "u", 0, 2),
    Field("num_clock", "u", 2, 1),
    Field("num_orbit", "u", 3, 1),
)
ORBIT_BLOCK = (
    Field("seconds_of_day", "u", 0, 4),
    Field("iodssr", "u", 4, 1),
    Field("reserved", "u", 5, 1, 3),
    Group("corrections", 8, ORBIT, 6, 12, "num_orbit"),
)
CLOCK_BLOCK = (
    Field("seconds_of_day", "u", 0, 4),
    Field("iodssr", "u", 4, 1),
    Field("iodp", "u", 5, 1),
    Field("satellite_start_index", "u", 6, 2),
    Group("corrections", 8, CLOCK, 22, 4, "num_clock"),
)
CLOCK_BLOCK7 = (
    Field("seconds_of_day", "u", 0, 4),
    Field("iodssr", "u", 4, 1),
    Field("iodp", "u", 5, 1),
    Field("reserved", "u", 6, 1, 2),
    Group(
        "corrections",
        8,
        (Field("prn", "i", 0, 4), Field("iod_corr", "u", 4, 2), Field("c0", "i", 6, 2)),
        15,
        8,
        "num_clock",
    ),
)
HAS_HEADER = (
    Field("toh", "u", 0, 4),
    Field("block_flags", "u", 4, 1),
    Field("reserved", "u", 5, 1),
    Field("mask_id", "u", 6, 1),
    Field("iod_set_id", "u", 7, 1),
)
HAS_CORRECTION_HEADER = (
    *HAS_HEADER,
    Field("validity_interval", "i", 8, 2),
    Field("reserved_2", "i", 10, 2),
)
MASK = (
    Field("gnss_id", "u", 0, 2),
    Field("satellite_mask", "b", 2, 5),
    Field("signal_mask", "X", 7, 2),
    Field("cell_mask_available", "u", 9, 1),
    Field("cell_mask", "b", 10, 40),
    Field("navigation_message_index", "u", 50, 1),
    Field("reserved", "u", 51, 1, 3),
)
SUBCLOCK = (
    Field("gnss_id", "u", 0, 2),
    Field("delta_clock_multiplier", "u", 2, 2),
    Field("satellite_mask", "b", 4, 5),
    Field("reserved", "u", 9, 1, 3),
    Field("delta_clock_corrections", "i", 12, 2, 36),
)
LAYOUTS: tuple[Layout, ...] = (
    Layout("PPPB2BINFO1", "7-136", (*PPP_HEADER, Field("mask", "b", 8, 32)), 40),
    Layout(
        "PPPB2BINFO2",
        "7-137",
        (
            *PPP_HEADER[:2],
            Field("reserved", "u", 3, 1),
            PPP_HEADER[3],
            Group("orbit", 8, ORBIT, 6, 12),
        ),
        80,
    ),
    Layout(
        "PPPB2BINFO3",
        "7-138",
        (
            Field("prn", "u", 0, 2),
            Field("iodssr", "u", 2, 1),
            Field("satellite_count", "u", 3, 1),
            Field("seconds_of_day", "u", 4, 4),
            Group("code_biases", 8, CODE_BIAS, "satellite_count", 64),
        ),
        None,
    ),
    Layout(
        "PPPB2BINFO4",
        "7-139",
        (
            *PPP_HEADER,
            Field("subtype", "u", 8, 1),
            Field("reserved", "u", 9, 1, 3),
            Group("clock", 12, CLOCK, 23, 4),
        ),
        104,
    ),
    Layout(
        "PPPB2BINFO5",
        "7-140",
        (
            Field("prn", "u", 0, 2),
            Field("iodssr", "u", 2, 1),
            Field("iodp", "u", 3, 1),
            Field("subtype", "u", 4, 1),
            Field("reserved", "u", 5, 1, 3),
            Field("seconds_of_day", "u", 8, 4),
            Group(
                "urai",
                12,
                (Field("class", "u", 0, 1), Field("value", "u", 1, 1)),
                70,
                2,
            ),
        ),
        152,
    ),
    Layout(
        "PPPB2BINFO6",
        "7-141",
        (
            *COMBINED_HEADER,
            Group("clock", 4, CLOCK_BLOCK, 1, 96),
            Group("orbit", 100, ORBIT_BLOCK, 1, 80),
        ),
        180,
    ),
    Layout(
        "PPPB2BINFO7",
        "7-142",
        (
            *COMBINED_HEADER,
            Group("clock", 4, CLOCK_BLOCK7, 1, 128),
            Group("orbit", 132, ORBIT_BLOCK, 1, 80),
        ),
        212,
    ),
    Layout(
        "E6MASKBLOCK",
        "7-143",
        (
            *HAS_HEADER,
            Field("system_count", "u", 8, 2),
            Field("reserved_2", "u", 10, 2),
            Group("systems", 12, MASK, "system_count", 54),
        ),
        None,
    ),
    Layout(
        "E6ORBITBLOCK",
        "7-147",
        (
            *HAS_CORRECTION_HEADER,
            Group(
                "corrections",
                12,
                (
                    Field("iod_ref", "u", 0, 2),
                    Field("radial", "i", 2, 2),
                    Field("in_track", "i", 4, 2),
                    Field("cross_track", "i", 6, 2),
                ),
                68,
                8,
            ),
        ),
        556,
    ),
    Layout(
        "E6CLOCKFULLBLOCK",
        "7-149",
        (
            *HAS_CORRECTION_HEADER,
            Field("delta_clock_multipliers", "u", 12, 1, 4),
            Field("delta_clock_corrections", "i", 16, 2, 68),
        ),
        152,
    ),
    Layout(
        "E6CLOCKSUBBLOCK",
        "7-151",
        (
            *HAS_HEADER,
            Field("validity_interval", "i", 8, 2),
            Field("system_count", "i", 10, 2),
            Group("systems", 12, SUBCLOCK, "system_count", 84),
        ),
        None,
    ),
    Layout(
        "E6CBIASBLOCK",
        "7-152",
        (*HAS_CORRECTION_HEADER, Field("code_biases", "i", 12, 2, 256)),
        524,
    ),
    Layout(
        "E6PBIASBLOCK",
        "7-153",
        (
            *HAS_CORRECTION_HEADER,
            Group(
                "phase_biases",
                12,
                (Field("bias", "i", 0, 2), Field("discontinuity", "u", 2, 2)),
                256,
                4,
            ),
        ),
        1036,
    ),
)

# R1.15 sections 7.5.58-63 and table 7-185. Values retain native integer
# units and mask bytes, while applying corrections requires the service's SSR rules.
L6_HEADER = (
    Field("prn", "u", 0, 4),
    Field("message_number", "u", 4, 2),
    Field("subtype", "u", 6, 2),
    Field("epoch_time", "u", 8, 4),
    Field("interval", "u", 12, 2),
    Field("indicator", "u", 14, 1),
    Field("iod_ssr", "u", 15, 1),
    Field("gnss_count", "u", 16, 1),
    Field("reserved", "u", 17, 1),
    Field("hourly_time", "u", 18, 2),
    Field("correction_count", "u", 20, 2),
    Field("validity", "u", 22, 2),
)
L6_MASK = (
    Field("gnss_id", "u", 0, 1),
    Field("satellite_mask", "b", 1, 5),
    Field("signal_mask", "b", 6, 2),
    Field("cell_mask_available", "u", 8, 1),
    Field("reserved", "u", 9, 1, 3),
    Field("cell_mask", "b", 12, 40),
)
L6_ORBIT = (
    Field("iode", "u", 0, 2),
    Field("radial", "i", 2, 2),
    Field("along_track", "i", 4, 2),
    Field("cross_track", "i", 6, 2),
)
LAYOUTS = (
    *LAYOUTS,
    Layout(
        "L6MDCTYPE1",
        "7-116",
        (*L6_HEADER, Group("masks", 24, L6_MASK, "gnss_count", 52)),
        None,
    ),
    Layout(
        "L6MDCTYPE2",
        "7-119",
        (*L6_HEADER, Group("orbit", 24, L6_ORBIT, "correction_count", 8)),
        None,
    ),
    Layout(
        "L6MDCTYPE3",
        "7-121",
        (*L6_HEADER, Field("clock", "i", 24, 2, "correction_count")),
        None,
    ),
    Layout(
        "L6MDCTYPE4",
        "7-122",
        (
            *L6_HEADER,
            Group(
                "code_bias",
                24,
                (Field("values", "i", 0, 2, 7),),
                "correction_count",
                14,
            ),
        ),
        None,
    ),
    Layout(
        "L6MDCTYPE5",
        "7-124",
        (
            *L6_HEADER,
            Group(
                "phase_bias",
                24,
                (Field("values", "i", 0, 2, 7), Field("indicators", "u", 14, 2, 7)),
                "correction_count",
                28,
            ),
        ),
        None,
    ),
    Layout("L6MDCTYPE7", "7-126", (*L6_HEADER, Field("ura", "u", 24, 2, 80)), 184),
)

# QZSS L1S SLAS messages (7.5.54-57, tables 7-112 to 7-115). Binary offsets are
# documented. The manual's ASCII examples carry an extra leading message-code
# token and print the BDS mask truncated to five bytes. The ascii_count and
# prefix fields accommodate those examples without changing binary decoding.
LAYOUTS = (
    *LAYOUTS,
    Layout(
        "L1SMT47",
        "7-112",
        (
            # Binary has eight bytes. ASCII prints a code and five station codes.
            Field("gms_code", "u", 0, 1, count=8, ascii_count=6),
            Field("gms_lat1", "d", 8, 8),
            Field("gms_lon1", "d", 16, 8),
            Field("gms_hgt1", "d", 24, 8),
            Field("gms_lat2", "d", 32, 8),
            Field("gms_lon2", "d", 40, 8),
            Field("gms_hgt2", "d", 48, 8),
            Field("gms_lat3", "d", 56, 8),
            Field("gms_lon3", "d", 64, 8),
            Field("gms_hgt3", "d", 72, 8),
            Field("gms_lat4", "d", 80, 8),
            Field("gms_lon4", "d", 88, 8),
            Field("gms_hgt4", "d", 96, 8),
            Field("gms_lat5", "d", 104, 8),
            Field("gms_lon5", "d", 112, 8),
            Field("gms_hgt5", "d", 120, 8),
            Field("reserved", "d", 128, 8, count=6),
        ),
        176,
    ),
    Layout(
        "L1SMT48",
        "7-113",
        (
            Field("prefix", "u", 0, 1, count=0, ascii_count=2),
            Field("gps_mask", "b", 0, 8),
            Field("qzss_mask", "b", 8, 2),
            Field("glo_mask", "b", 10, 5),
            Field("gal_mask", "b", 15, 5),
            Field("reserved", "u", 20, 1, count=4),
            # The ASCII example prints five bytes, while binary contains eight.
            Field("bds_mask", "b", 24, 8),
            Field("reserved_2", "u", 32, 1, count=4),
        ),
        36,
    ),
    Layout(
        "L1SMT49",
        "7-114",
        (
            Field("prefix", "u", 0, 1, count=0, ascii_count=1),
            Field("iodi", "u", 0, 4),
            Field("mask_sv", "b", 4, 4),
            Field("iod", "u", 8, 1, count=24),
            Field("iodp", "u", 32, 4),
            Field("reserved", "u", 36, 4),
            Field("reserved_2", "u", 40, 4),
            Field("reserved_3", "u", 44, 4),
        ),
        48,
    ),
    Layout(
        "L1SMT50",
        "7-115",
        (
            Field("prefix", "u", 0, 1, count=0, ascii_count=1),
            Field("iodp", "u", 0, 4),
            Field("iodi", "u", 4, 4),
            Field("gms_code", "u", 8, 1),
            Field("gms_health", "u", 9, 1),
            Field("reserved", "u", 10, 1),
            Field("reserved_2", "u", 11, 1),
            Field("mask_sv", "b", 12, 3),
            Field("reserved_3", "u", 15, 1),
            Field("prc", "f", 16, 4, count=14),
            Field("reserved_4", "f", 72, 4),
            Field("reserved_5", "f", 76, 4),
            Field("reserved_6", "f", 80, 4),
        ),
        84,
    ),
)
