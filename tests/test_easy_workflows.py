"""Exercise the common receiver APIs through recorded wire responses."""

import asyncio
from dataclasses import replace
from threading import Event

import pytest

from conftest import FIXTURES, ReplayTransport, SubscriptionTransport, sentence
from test_bodies import manual_message
from um982py import AsyncReceiver, Log, Receiver, RoverPosition
from um982py.commands.types import Port
from um982py.messages import AsciiHeader, BestNavigation, Fix, Position, decode_log
from um982py.messages.enums import PositionType
from um982py.ppp import PppSolution
from um982py.protocol.ascii import parse_ascii

GGA = sentence(b"GNGGA,145842.00,5232.0000,N,01322.0000,E,4,17,1.3,38.0,M,36.0,M,0.5,")
GGAH = sentence(
    b"GNGGAH,145842.00,5232.0000,N,01322.0000,E,4,17,1.3,38.0,M,36.0,M,0.5,"
)


class PositionTransport(SubscriptionTransport):
    def read(self, size: int, timeout: float) -> bytes:
        if not self.pending:
            if ("GPGGA", Port.COM1) in self.subscriptions:
                self.pending.extend(GGA)
            elif ("GPGGAH", Port.COM1) in self.subscriptions:
                self.pending.extend(GGAH)
        return super().read(size, timeout)


def test_receiver_stream_restores_existing_output_after_early_exit() -> None:
    transport = PositionTransport()
    transport.subscriptions[("GPGGAH", Port.COM1)] = 5
    with Receiver(transport) as receiver:
        with receiver.stream_positions(duration=5, rate_hz=2, antenna=2) as positions:
            fix = next(positions)
            assert fix.valid and fix.rtk_fixed and fix.correction_age_s == 0.5
            assert transport.subscriptions[("GPGGAH", Port.COM1)] == 0.5
        assert transport.subscriptions[("GPGGAH", Port.COM1)] == 5
    assert b"GPGGAH 0.5\r\n" in transport.writes


def test_async_stream_restores_output_on_cancellation() -> None:
    async def run() -> None:
        transport = PositionTransport()
        receiver = AsyncReceiver(Receiver(transport))
        started = asyncio.Event()

        async def consume() -> None:
            async with receiver.stream_positions(duration=5) as positions:
                assert (await anext(positions)).valid
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.subscriptions == {}
        await receiver.close()

    asyncio.run(run())


def test_async_stream_waits_for_cancelled_read_before_restoring() -> None:
    async def run() -> None:
        started, release = Event(), Event()

        class BlockingTransport(PositionTransport):
            block_next = False

            def read(self, size: int, timeout: float) -> bytes:
                if self.block_next and not self.pending:
                    self.block_next = False
                    started.set()
                    assert release.wait(2)
                return super().read(size, timeout)

        transport = BlockingTransport()
        receiver = AsyncReceiver(Receiver(transport))

        async def consume() -> None:
            async with receiver.stream_positions(duration=5) as positions:
                assert (await anext(positions)).valid
                transport.block_next = True
                await anext(positions)

        task = asyncio.create_task(consume())
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert transport.subscriptions == {}
        await receiver.close()

    asyncio.run(run())


def test_antenna_selection_and_typed_diagnostics() -> None:
    pps = (FIXTURES / "captures/PPSSTATUSB.bin").read_bytes()
    spoof = (FIXTURES / "captures/SPOOFINFOB.bin").read_bytes()
    transport = ReplayTransport(
        {b"GPGGAH\r\n": GGAH, b"PPSSTATUSB\r\n": pps, b"SPOOFINFOB\r\n": spoof}
    )
    with Receiver(transport) as receiver:
        assert receiver.fix(antenna=2).valid
        assert receiver.read_log(Log.GPGGA, antenna=2).name == "GNGGAH"
        assert receiver.pps_status().gps_week >= 0
        assert receiver.spoof_info().indicator == 0
        with pytest.raises(ValueError, match="antenna"):
            receiver.read_log(Log.GPGGA, antenna=3)
        with pytest.raises(ValueError, match="antenna"):
            receiver.fix(antenna=True)


def test_async_typed_diagnostics_and_antenna_selection() -> None:
    async def run() -> None:
        pps = (FIXTURES / "captures/PPSSTATUSB.bin").read_bytes()
        spoof = (FIXTURES / "captures/SPOOFINFOB.bin").read_bytes()
        transport = ReplayTransport(
            {
                b"GPGGAH\r\n": GGAH,
                b"PPSSTATUSB\r\n": pps,
                b"SPOOFINFOB\r\n": spoof,
            }
        )
        async with AsyncReceiver(Receiver(transport)) as receiver:
            assert (await receiver.fix(antenna=2)).valid
            assert (await receiver.read_log(Log.GPGGA, antenna=2)).name == "GNGGAH"
            assert (await receiver.pps_status()).gps_week >= 0
            assert (await receiver.spoof_info()).indicator == 0

    asyncio.run(run())


def test_position_models_share_common_fields_without_inventing_a_gga_date() -> None:
    fix = Fix.from_message(parse_ascii(GGA))
    nav = BestNavigation.from_record(decode_log(manual_message("BESTNAVA")))
    ppp = PppSolution.from_record(decode_log(manual_message("PPPNAVA")))
    rover = RoverPosition(nav, None, None, None, None, nav.correction_age_s)
    positions: tuple[Position, ...] = (fix, nav, ppp, rover)
    for position in positions:
        assert isinstance(position, Position)
        assert isinstance(position.valid, bool)
        assert isinstance(position.rtk_fixed, bool)
        assert position.latitude is None or -90 <= position.latitude <= 90
        assert position.correction_age_s is None or position.correction_age_s >= 0
    assert fix.rtk_fixed and fix.epoch_gps_seconds is None
    assert fix.correction_age_s == 0.5 and fix.satellites_used == 17
    assert not ppp.rtk_fixed
    assert (
        rover.latitude == nav.latitude and rover.satellites_used == nav.satellites_used
    )
    fixed = replace(nav, position_type=PositionType.NARROW_INT)
    assert fixed.rtk_fixed
    assert not replace(fixed, position_type=PositionType.SINGLE).rtk_fixed


def test_position_correction_age_and_epoch_preserve_source_semantics() -> None:
    invalid_age = GGA.replace(b",0.5,", b",-1,")
    invalid_age = sentence(invalid_age[1 : invalid_age.index(b"*")])
    assert Fix.from_message(parse_ascii(invalid_age)).correction_age_s is None

    frame = replace(
        manual_message("BESTNAVA"),
        header=AsciiHeader("BESTNAVA", 0, "GPS", "FINE", 2400, 123000, 0, 0, 18, 0),
    )
    record = decode_log(frame)
    entries = tuple(
        (
            name,
            "NARROW_INT"
            if name == "pos_type"
            else 2.5
            if name == "diff_age"
            else value,
        )
        for name, value in record.entries
    )
    position = BestNavigation.from_record(replace(record, entries=entries))
    assert position.rtk_fixed and position.correction_age_s == 2.5
    assert position.epoch_gps_seconds == 2400 * 604800 + 123
    bds_frame = replace(frame, header=replace(frame.header, time_reference="BDS"))
    assert (
        BestNavigation.from_record(
            replace(record, entries=entries, message=bds_frame)
        ).epoch_gps_seconds
        is None
    )
